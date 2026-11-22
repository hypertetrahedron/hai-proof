"""User-in-the-loop trials (DESIGN §3.8): scripted user turns, and a stand-in that answers the agent.

A conventional trial is one `claude -p` session. A user-in-the-loop trial is a series of `claude -p` calls on
one session (`--session-id`, then `--resume`). The treatment's script decides which phase comes next (e.g. a
planning skill, then an execution skill). Between scripted turns, a stand-in user reads the agent's final
message: if the agent is waiting for the user (a question, an approval) it replies, otherwise the script
moves on. The stand-in never moves the workflow forward itself.

Modes (per arm):
- conventional: no stand-in; each scripted turn is sent when the agent stops.
- uninformative: the stand-in decides WAITING / DONE and always replies with UNINFORMATIVE_REPLY.
- informative: same decision, but the reply comes from the task's user brief (tasks/<ID>/user.md).
- reticent: like informative, but the stand-in only answers what the agent asks or states: it corrects
  choices a plan makes explicitly and never volunteers brief points the agent did not raise, so the
  agent has to ask to find them out (a user with tacit requirements).

The WAITING / DONE decision uses the same prompt in both stand-in modes and never sees the brief, so the
modes differ only in what the replies contain. The stand-in runs in its own plain container: the agent's
container never holds the brief.

With the ask tool (ArmSpec.ask_tool) the agent can also call AskUserQuestion during a call. The wrapper
hands each call's questions to a ToolAnswerer: the informative and reticent stand-ins answer from the brief,
every other mode answers each question with UNINFORMATIVE_REPLY (nobody else is there to ask).
"""

from __future__ import annotations

import json
import re
import shlex
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Callable, Protocol

from .models import BRIEF_MODES
from .tarutil import tar_files

if TYPE_CHECKING:
    from .executor import Executor

UNINFORMATIVE_REPLY = "I don't have anything to add. Use your best judgement and continue."
NO_INFO_REPLY = "I don't have a preference on that. Make a reasonable assumption and continue."
AGENT_TEXT_CAP = 8000  # characters of an agent message shown to the stand-in
HISTORY_TURNS = 8  # most recent exchanges shown to the responder
MIN_TURN_S = 30.0  # don't start an agent call with less time than this left
MIN_BUDGET_USD = 0.05

CLASSIFIER_SYSTEM = """\
You watch a coding agent that is working on a request from a user. The agent has just stopped and \
handed control back to the user. Decide whether the agent is waiting for the user's input before it \
can continue the work it was asked to do.

WAITING: the agent's final message asks the user a question, asks the user to choose between options, \
asks for approval or confirmation of a plan or design, or asks permission before continuing with the \
requested work.
DONE: the agent reports the requested step as finished (or as impossible) and needs nothing from the \
user. An optional offer of further work after the requested work is finished ("Want me to also add \
...?", "Let me know if you need anything else") is DONE. So is a finished step that only tells the user \
what they can run or do next ("The plan is ready for review. When you are ready, run /apply."): the \
agent is not asking anything.

Answer with exactly one word: WAITING or DONE."""

RESPONDER_SYSTEM = """\
You are the user who asked a coding agent for some work. The agent has stopped to ask you something. \
Reply as that user, briefly and in plain text.

Rules:
- Answer only from the user brief and the original request below. They are everything you know and want.
- If the brief does not settle the question, say you have no preference and tell the agent to make a \
reasonable assumption and continue. Do not invent requirements.
- If the agent asks you to approve a plan or design, approve it when it agrees with the brief; otherwise \
say what to change, in the brief's terms. Judge only whether it does what you want, never whether the \
code is correct.
- If the agent offers numbered or lettered options, start your reply with the label of the option that \
matches the brief (for example "B."), then one short reason. If none fits, say so and say what you want.
- Never tell the agent which command, skill or phase to run next, and never tell it to start or skip \
implementing. Just answer what it asked.
- Do not write code. Keep the reply to a few sentences.

Output only your reply to the agent."""

TOOL_ANSWER_FORMAT = """\
The agent asked these questions with its question tool:

{questions}

Answer every question as the user, following the rules, as fully as you would if the agent had asked in \
plain text. Start with the label of the matching option (several labels separated by ", " where several \
may be chosen), or say that none fits. Then add, in a sentence or two, anything in the brief that bears \
on the question and that the option leaves out or gets wrong (names, signatures, behaviour). If the \
brief does not settle it, say you have no preference. Start each answer on a new line with \
"<number>: ", in order; an answer may continue onto the following lines. Output only the answers."""


RETICENT_RESPONDER_SYSTEM = """\
You are the user who asked a coding agent for some work. The agent has stopped to ask you something. \
Reply as that user, briefly and in plain text.

You know what you want: the user brief below. Like most people, though, you only think of a detail when \
the agent's message brings it up. You never go through the brief looking for things the agent missed.

Rules:
- Answer only from the user brief and the original request below. They are everything you know and want.
- Answer exactly what the agent's latest message asks. For a specific question, give what the brief says \
about that point, and nothing about other points.
- If the agent proposes a plan or design, look only at the choices it states explicitly. Approve the ones \
that agree with the brief, and correct the ones that contradict it, in the brief's terms. Do not bring up \
anything the plan leaves out or does not mention, even if the brief covers it.
- If the agent asks an open question (for example "anything else I should know?", "which edge cases \
matter to you?", "how should errors behave?"), answer it fully from the brief on the topic it asks about.
- If the brief does not settle what was asked, say you have no preference and tell the agent to make a \
reasonable assumption and continue. Do not invent requirements.
- Judge only whether it does what you want, never whether the code is correct.
- If the agent offers numbered or lettered options, start your reply with the label of the option that \
matches the brief (for example "B."), then one short reason. If none fits, say so and say what you want.
- Never tell the agent which command, skill or phase to run next, and never tell it to start or skip \
implementing. Just answer what it asked.
- Do not write code. Keep the reply to a few sentences.

Output only your reply to the agent."""

RETICENT_TOOL_ANSWER_FORMAT = """\
The agent asked these questions with its question tool:

{questions}

Answer every question as the user, following the rules. Start with the label of the matching option \
(several labels separated by ", " where several may be chosen), or say that none fits. If the chosen option \
gets this question's point wrong or leaves out part of it, add in a sentence what the brief says about \
exactly this point; say nothing about other points. If the brief does not settle it, say you have no \
preference. Start each answer on a new line with "<number>: ", in order; an answer may continue onto the \
following lines. Output only the answers."""

# --tool-answers full: a tool answer carries as much as a plain-text reply on the same point would, so the
# question channel (tool menu vs text) does not decide how much of the brief the agent hears.
RETICENT_TOOL_ANSWER_FORMAT_FULL = """\
The agent asked these questions with its question tool:

{questions}

Answer every question as the user, following the rules, as fully as you would if the agent had asked \
about the same point in plain text. Start with the label of the matching option (several labels separated \
by ", " where several may be chosen), or say that none fits. If the chosen option gets this question's \
point wrong or leaves out part of it, add everything the brief says about exactly this point; say nothing \
about other points. If the brief does not settle it, say you have no preference. Start each answer on a \
new line with "<number>: ", in order; an answer may continue onto the following lines. Output only the \
answers."""

# --reticence strict (2026-10-21): the reticent stand-in volunteered facts a proposed plan left out, framed as
# corrections ("the plan doesn't say X"), in about 17% of its answers to superpowers' plan-approval turns
# (audit of run 20261021-114732-027d). Strict mode tightens the plan rule and passes every text reply through
# a second call that deletes what the agent's message did not raise. In an offline replay of 027d's 23
# plan-approval replies, leaking replies fell from 21 to 5 while answers to open questions kept their content.
RETICENCE_LEVELS: tuple[str, ...] = ("standard", "strict")

_STRICT_PLAN_RULE = """- If the agent proposes a plan or design, look only at the choices it states explicitly. Approve the ones \
that agree with the brief, and correct the ones that contradict it, in the brief's terms. Do not bring up \
anything the plan leaves out or does not mention, even if the brief covers it: no "also", "one more thing", \
"you haven't mentioned" or "don't forget". Asking whether the plan looks right, or whether to proceed, is \
not an open question; it asks only about the choices the plan states. Before you reply, check each \
sentence against the agent's message and delete any that concerns a point the message does not mention.
"""

RETICENT_RESPONDER_SYSTEM_STRICT = RETICENT_RESPONDER_SYSTEM.replace(
    RETICENT_RESPONDER_SYSTEM[RETICENT_RESPONDER_SYSTEM.index("- If the agent proposes"):
                              RETICENT_RESPONDER_SYSTEM.index("- If the agent asks an open question")],
    _STRICT_PLAN_RULE)

STRICT_FILTER_SYSTEM = """\
You edit a simulated user's reply before it is sent to a coding agent. The user is RETICENT: they reply only \
about what the agent's latest message explicitly asks, or explicitly states as a choice or plan item. They \
never raise points the agent's message does not mention, even as "corrections", "one more thing", or "the \
plan doesn't say X".

Remove only sentences or clauses that introduce a separate point: a topic, input, option, case or \
requirement the agent's message neither asks about nor states. Keep every sentence that answers a question, \
approves, rejects or corrects a choice the agent stated (saying what the brief wants instead on that same \
point), or gives a direct consequence, condition, exception, example or error behaviour of a point the agent \
asked about or stated. Keep the reply's answer to each option the agent offered, its opening "Yes"/"No", and \
any "no preference" answer. When unsure whether a sentence is part of an answer or a new point, keep it. If \
the agent asks an open question (for example "anything else?", "any other requirements?", "which edge cases \
matter to you?"), keep everything the reply says about the user's requirements, including documentation and \
tests.

Do not add anything, do not rephrase what you keep beyond what grammar needs. If nothing is left but an \
approval, output a short approval. Output only the edited reply."""


# --------------------------------------------------------------------------- data


@dataclass
class TurnLimits:
    timeout_s: float
    max_turns: int
    budget_usd: float


@dataclass
class AgentTurn:
    """Outcome of one `claude -p` call."""

    final_text: str = ""
    num_turns: int = 0
    cost_usd: float = 0.0  # session total after this call (Claude Code restores the cost on --resume)
    wall_s: float = 0.0
    ok: bool = True  # ended normally: a result event, no error, not timed out
    end: str = ""  # result subtype, "timed_out" or "no_result"


@dataclass
class StandInCall:
    kind: str  # "classify" | "reply"
    output: str = ""
    cost_usd: float = 0.0
    wall_s: float = 0.0
    error: str | None = None
    draft: str | None = None  # --reticence strict: the reply before the filter pass removed unraised points
    filter_error: str | None = None  # the filter pass failed; the draft was sent


@dataclass
class LoopTurn:
    n: int
    source: str  # "script" | "stand-in"
    phase: int  # index of the scripted turn this exchange belongs to
    message: str
    agent: AgentTurn | None = None
    decision: str | None = None  # "waiting" | "done" | None (no stand-in)
    stand_in: list[StandInCall] = field(default_factory=list)
    tool_questions: list[dict] = field(default_factory=list)  # AskUserQuestion calls answered in this call


@dataclass
class LoopLog:
    mode: str
    turns: list[LoopTurn] = field(default_factory=list)
    stop_reason: str = ""
    reply_cap_hits: int = 0  # times the agent was waiting but the reply limit was reached
    tool_answers: str = ""  # reticent stand-in settings this trial ran with (task's own or the run's); "" otherwise
    reticence: str = ""

    def summary(self) -> dict:
        calls = [c for t in self.turns for c in t.stand_in]
        calls += [StandInCall(**q["stand_in"]) for t in self.turns for q in t.tool_questions if q.get("stand_in")]
        last = self.turns[-1] if self.turns else None
        return {
            "mode": self.mode,
            "agent_calls": sum(1 for t in self.turns if t.agent is not None),
            "scripted_turns": sum(1 for t in self.turns if t.source == "script"),
            "user_replies": sum(1 for t in self.turns if t.source == "stand-in"),
            "tool_question_calls": sum(len(t.tool_questions) for t in self.turns),
            "tool_questions": sum(len(q.get("questions") or []) for t in self.turns for q in t.tool_questions),
            "stop_reason": self.stop_reason,
            "ended_waiting": bool(last and last.decision == "waiting"),
            "reply_cap_hits": self.reply_cap_hits,
            "stand_in_calls": len(calls),
            "stand_in_errors": sum(1 for c in calls if c.error),
            "stand_in_cost_usd": round(sum(c.cost_usd for c in calls), 6),
            "stand_in_wall_s": round(sum(c.wall_s for c in calls), 1),
        }

    def to_json(self) -> dict:
        stand_in = {k: v for k, v in (("tool_answers", self.tool_answers), ("reticence", self.reticence)) if v}
        return {"mode": self.mode, **stand_in, "stop_reason": self.stop_reason, "summary": self.summary(),
                "turns": [asdict(t) for t in self.turns]}


class StandIn(Protocol):
    def classify(self, user_message: str, agent_message: str) -> StandInCall: ...

    def reply(self, history: list[tuple[str, str]], agent_message: str) -> StandInCall: ...

    def answer_tool(self, history: list[tuple[str, str]], questions: list[dict]) -> StandInCall: ...


# --------------------------------------------------------------------------- prompts and parsing


def _cap(text: str, n: int = AGENT_TEXT_CAP) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n // 2] + "\n[...]\n" + text[-n // 2:]


def classifier_prompt(user_message: str, agent_message: str) -> str:
    return ("The user's last message to the agent:\n<<<\n" + _cap(user_message) + "\n>>>\n\n"
            "The agent's final message:\n<<<\n" + (_cap(agent_message) or "(empty)") + "\n>>>\n\n"
            "Is the agent WAITING for the user, or DONE? Answer with one word.")


def responder_prompt(task_prompt: str, brief: str, history: list[tuple[str, str]], agent_message: str) -> str:
    lines = ["Your original request to the agent:\n<<<\n" + task_prompt + "\n>>>",
             "User brief (what you want and know):\n<<<\n" + brief + "\n>>>"]
    recent = history[-2 * HISTORY_TURNS:]
    if recent:
        conv = "\n\n".join(f"[{who}]\n{_cap(text, 3000)}" for who, text in recent)
        lines.append("The conversation so far:\n<<<\n" + conv + "\n>>>")
    lines.append("The agent's latest message, which you are replying to:\n<<<\n" + _cap(agent_message) + "\n>>>")
    return "\n\n".join(lines)


def strict_filter_prompt(agent_message: str, reply: str) -> str:
    return ("The agent's latest message:\n<<<\n" + _cap(agent_message) + "\n>>>\n\n"
            "Reply to edit:\n<<<\n" + reply + "\n>>>")


def tool_responder_prompt(task_prompt: str, brief: str, history: list[tuple[str, str]],
                          questions: list[dict], answer_format: str = TOOL_ANSWER_FORMAT) -> str:
    """The questions come mid-call: history ends with the user's message the agent is working on."""
    lines = ["Your original request to the agent:\n<<<\n" + task_prompt + "\n>>>",
             "User brief (what you want and know):\n<<<\n" + brief + "\n>>>"]
    recent = history[-2 * HISTORY_TURNS:]
    if len(recent) > 1:
        conv = "\n\n".join(f"[{who}]\n{_cap(text, 3000)}" for who, text in recent)
        lines.append("The conversation so far:\n<<<\n" + conv + "\n>>>")
    lines.append(answer_format.format(questions=format_tool_questions(questions)))
    return "\n\n".join(lines)


def format_tool_questions(questions: list[dict]) -> str:
    out = []
    for i, q in enumerate(questions, 1):
        lines = [f"{i}. {q.get('question', '')}" + (" (several may be chosen)" if q.get("multiSelect") else "")]
        for o in q.get("options") or []:
            desc = f" - {o.get('description')}" if o.get("description") else ""
            lines.append(f"   - {o.get('label', '')}{desc}")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def parse_tool_answers(output: str, questions: list[dict]) -> dict[str, str]:
    """{question: answer} from answers that start with "<n>: " (and may run onto following lines).

    Only "<next number>:" starts a new answer, so a numbered list ("2. ...") inside an answer stays in it. A
    question without an answer gets NO_INFO_REPLY.
    """
    got: dict[int, list[str]] = {}
    current = 0
    for line in (output or "").splitlines():
        m = re.match(r"\s*(\d+)\s*:\s*(.*)", line)
        if m and int(m.group(1)) == current + 1 and current < len(questions):
            current += 1
            got[current] = [m.group(2)]
        elif current:
            got[current].append(line)
    answers = {i: "\n".join(lines).strip() for i, lines in got.items()}
    return {str(q.get("question", "")): answers.get(i) or NO_INFO_REPLY for i, q in enumerate(questions, 1)}


class ToolAnswerer:
    """Answers AskUserQuestion calls made during an agent call (the arm's ask tool).

    run_loop sets `history` before each call and collects `records` after it. Outside the brief modes
    (informative, reticent), and after `max_answers` stand-in answers in a trial, every question gets
    UNINFORMATIVE_REPLY.
    """

    def __init__(self, mode: str, stand_in: StandIn | None, max_answers: int):
        self.mode, self.stand_in, self.max_answers = mode, stand_in, max_answers
        self.history: list[tuple[str, str]] = []
        self.records: list[dict] = []
        self.answered = 0

    def __call__(self, tool_input: dict) -> dict[str, str]:
        questions = [q for q in tool_input.get("questions") or [] if isinstance(q, dict)]
        rec: dict = {"questions": questions, "source": "fixed", "stand_in": None}
        if self.mode in BRIEF_MODES and self.stand_in is not None and self.answered < self.max_answers:
            call = self.stand_in.answer_tool(self.history, questions)
            if call.error or not call.output.strip():
                call.error = call.error or "empty reply"
            answers = parse_tool_answers(call.output, questions)
            rec.update(source="stand-in", stand_in=asdict(call))
            self.answered += 1
        else:
            answers = {str(q.get("question", "")): UNINFORMATIVE_REPLY for q in questions}
            if self.mode in BRIEF_MODES:
                rec["source"] = "cap"
        rec["answers"] = answers
        self.records.append(rec)
        return answers


def parse_decision(output: str) -> str | None:
    """'waiting' / 'done' from the classifier's answer, or None if it gave neither."""
    m = re.search(r"\b(WAITING|DONE)\b", (output or "").upper())
    return m.group(1).lower() if m else None


# --------------------------------------------------------------------------- the loop


def run_loop(*, mode: str, turns: list[str], agent: Callable[[str, int, TurnLimits], AgentTurn],
             stand_in: StandIn | None, timeout_s: float, max_turns: int, budget_usd: float,
             max_replies: int, log: LoopLog | None = None, answerer: ToolAnswerer | None = None) -> LoopLog:
    """Drive one trial's agent calls. `agent(message, n, limits)` runs call n (0 = the new session)."""
    log = log or LoopLog(mode=mode)
    if mode != "conventional" and stand_in is None:
        raise ValueError(f"user mode {mode!r} needs a stand-in")
    queue = list(turns)
    message, source, phase = queue.pop(0), "script", 0
    history: list[tuple[str, str]] = []
    replies = 0
    used_wall, used_turns, cost = 0.0, 0, 0.0
    while True:
        lim = TurnLimits(timeout_s=timeout_s - used_wall, max_turns=max_turns - used_turns,
                         budget_usd=budget_usd - cost)
        stop = _limit_reached(lim)
        if stop:
            log.stop_reason = stop
            return log
        entry = LoopTurn(n=len(log.turns), source=source, phase=phase, message=message)
        log.turns.append(entry)
        if answerer is not None:
            answerer.history = history + [("user", message)]
        out = agent(message, entry.n, lim)
        entry.agent = out
        if answerer is not None:
            entry.tool_questions, answerer.records = answerer.records, []
        used_wall += out.wall_s
        used_turns += out.num_turns
        cost = max(cost, out.cost_usd)
        history += [("user", message), ("agent", out.final_text)]
        if not out.ok:
            log.stop_reason = f"agent ended: {out.end or 'error'}"
            return log

        if mode == "conventional":
            entry.decision = None
        else:
            call = stand_in.classify(message, out.final_text)
            entry.stand_in.append(call)
            decision = parse_decision(call.output)
            if decision is None:  # the stand-in failed: behave as if nobody answered
                call.error = call.error or f"no WAITING/DONE in {call.output[:200]!r}"
                decision = "done"
            entry.decision = decision
            if decision == "waiting" and replies < max_replies:
                if mode == "uninformative":
                    reply = StandInCall(kind="reply", output=UNINFORMATIVE_REPLY)
                else:
                    reply = stand_in.reply(history, out.final_text)
                    if reply.error or not reply.output.strip():
                        reply.error = reply.error or "empty reply"
                        reply.output = NO_INFO_REPLY
                entry.stand_in.append(reply)
                replies += 1
                message, source = reply.output.strip(), "stand-in"
                continue
            if decision == "waiting":
                log.reply_cap_hits += 1
                if not queue:
                    log.stop_reason = "user-reply limit"
                    return log

        if not queue:
            log.stop_reason = "completed"
            return log
        message, source, phase = queue.pop(0), "script", phase + 1


def _limit_reached(lim: TurnLimits) -> str:
    if lim.timeout_s < MIN_TURN_S:
        return "time limit"
    if lim.max_turns < 1:
        return "max turns"
    if lim.budget_usd < MIN_BUDGET_USD:
        return "budget"
    return ""


# --------------------------------------------------------------------------- the stand-in container


class ContainerStandIn:
    """The stand-in user: one `claude -p` call per decision or reply, with no tools, in its own container.

    The container starts on first use from the plain base image (no treatment config), on the arm's
    egress network, and is removed by close().
    """

    def __init__(self, ex: "Executor", *, image: str, model: str, run_id: str, name: str, auth_env: dict[str, str],
                 network: str | None, proxy: str | None, task_prompt: str, brief: str, timeout_s: float = 300,
                 reticent: bool = False, tool_answers: str = "brief", reticence: str = "standard"):
        self.ex, self.image, self.model, self.run_id, self.name = ex, image, model, run_id, name
        self.auth_env, self.network, self.proxy = auth_env, network, proxy
        self.task_prompt, self.brief, self.timeout_s = task_prompt, brief, timeout_s
        self.container: str | None = None
        self._n = 0
        self.responder_system = RETICENT_RESPONDER_SYSTEM if reticent else RESPONDER_SYSTEM
        self.tool_answer_format = RETICENT_TOOL_ANSWER_FORMAT if reticent else TOOL_ANSWER_FORMAT
        if reticent and tool_answers == "full":
            self.tool_answer_format = RETICENT_TOOL_ANSWER_FORMAT_FULL
        self.strict = reticent and reticence == "strict"
        if self.strict:
            self.responder_system = RETICENT_RESPONDER_SYSTEM_STRICT

    def classify(self, user_message: str, agent_message: str) -> StandInCall:
        return self._call("classify", CLASSIFIER_SYSTEM, classifier_prompt(user_message, agent_message))

    def reply(self, history: list[tuple[str, str]], agent_message: str) -> StandInCall:
        # The last history pair is the exchange being answered; it is shown separately.
        call = self._call("reply", self.responder_system,
                          responder_prompt(self.task_prompt, self.brief, history[:-1], agent_message))
        if not self.strict or call.error or not call.output.strip():
            return call
        f = self._call("filter", STRICT_FILTER_SYSTEM, strict_filter_prompt(agent_message, call.output))
        call.cost_usd += f.cost_usd
        call.wall_s += f.wall_s
        call.draft = call.output
        if f.error or not f.output.strip():
            call.filter_error = f.error or "empty filter output"
        else:
            call.output = f.output
        return call

    def answer_tool(self, history: list[tuple[str, str]], questions: list[dict]) -> StandInCall:
        return self._call("tool-answer", self.responder_system,
                          tool_responder_prompt(self.task_prompt, self.brief, history, questions,
                                                self.tool_answer_format))

    def close(self) -> None:
        if self.container:
            self.ex.remove(self.container)
            self.container = None

    def _start(self) -> str:
        args = ["--name", self.name, "--label", f"hai-proof.run={self.run_id}", "--cpus", "1", "--memory", "2g"]
        if self.network and self.proxy:
            args += ["--network", self.network, "-e", f"HTTPS_PROXY={self.proxy}", "-e", f"https_proxy={self.proxy}"]
        self.container = self.ex.run_detached(args + [self.image, "sleep", "infinity"], secret_env=self.auth_env)
        self.ex.exec(self.container, ["mkdir", "-p", "/si"], user="root")
        return self.container

    def _call(self, kind: str, system: str, prompt: str) -> StandInCall:
        t0 = time.monotonic()
        call = StandInCall(kind=kind)
        try:
            container = self.container or self._start()
            d = f"/si/{self._n:03d}"
            self._n += 1
            self.ex.put_tar(container, "/si", tar_files({f"{d[4:]}/system.txt": system, f"{d[4:]}/prompt.txt": prompt}))
            self.ex.exec(container, ["chown", "-R", "agent:agent", "/si"], user="root")
            script = (f"mkdir -p /tmp/si/config /tmp/si/home && cd {d} && claude -p --safe-mode "
                      f"--model {shlex.quote(self.model)} --system-prompt \"$(cat system.txt)\" "
                      "--tools '' --max-turns 1 --no-session-persistence --output-format json < prompt.txt")
            r = self.ex.exec(container, ["bash", "-c", script], check=False, timeout=self.timeout_s,
                             env={"CLAUDE_CONFIG_DIR": "/tmp/si/config", "HOME": "/tmp/si/home"})
            text = r.stdout.decode(errors="replace").strip()
            try:
                res = json.loads(text.splitlines()[-1]) if text else {}
            except json.JSONDecodeError:
                res = {}
            call.cost_usd = float(res.get("total_cost_usd") or 0.0)
            call.output = str(res.get("result") or "").strip()
            if r.returncode != 0 or res.get("is_error") or not res:
                call.error = (f"stand-in exited {r.returncode}: "
                              + (str(res.get("result") or "") or r.stderr.decode(errors="replace"))[-500:])
        except Exception as e:  # noqa: BLE001 - a stand-in failure is recorded, never fails the trial
            call.error = f"{type(e).__name__}: {e}"[:500]
        call.wall_s = time.monotonic() - t0
        return call
