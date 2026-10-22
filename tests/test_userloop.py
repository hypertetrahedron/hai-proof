"""User-in-the-loop turn loop (DESIGN §3.8): scripted turns, stand-in decisions and replies, limits."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hai_proof import cli
from hai_proof.config import ConfigError
from hai_proof.models import PLAIN, ArmSpec, TreatmentSpec
from hai_proof.tasks import load_task
from hai_proof.treatments import load_treatment
from hai_proof.userloop import (CLASSIFIER_SYSTEM, NO_INFO_REPLY, RESPONDER_SYSTEM, RETICENT_RESPONDER_SYSTEM,
                                RETICENT_RESPONDER_SYSTEM_STRICT, STRICT_FILTER_SYSTEM, UNINFORMATIVE_REPLY, AgentTurn, ContainerStandIn, LoopLog, StandInCall, ToolAnswerer,
                                classifier_prompt, parse_decision, parse_tool_answers, responder_prompt, run_loop,
                                tool_responder_prompt)

ROOT = Path(__file__).resolve().parents[1]


class FakeAgent:
    """Answers each call with the next scripted final message."""

    def __init__(self, finals: list[str], *, cost_step: float = 0.1, wall: float = 10.0, turns: int = 2,
                 fail_at: int | None = None):
        self.finals, self.cost_step, self.wall, self.turns, self.fail_at = finals, cost_step, wall, turns, fail_at
        self.calls: list[tuple[str, int, object]] = []

    def __call__(self, message, n, lim):
        self.calls.append((message, n, lim))
        if n == self.fail_at:
            return AgentTurn(final_text="", num_turns=1, cost_usd=self.cost_step * (n + 1), wall_s=self.wall,
                             ok=False, end="error_max_turns")
        text = self.finals[n] if n < len(self.finals) else "Done."
        return AgentTurn(final_text=text, num_turns=self.turns, cost_usd=self.cost_step * (n + 1), wall_s=self.wall,
                         ok=True, end="success")


class FakeStandIn:
    """WAITING when the agent's message ends with '?'; replies from a canned answer."""

    def __init__(self, answer: str = "B. The brief says so.", *, classify_output: str | None = None,
                 reply_error: bool = False):
        self.answer, self.classify_output, self.reply_error = answer, classify_output, reply_error
        self.classified: list[tuple[str, str]] = []
        self.replied: list[tuple[list, str]] = []

    def classify(self, user_message, agent_message):
        self.classified.append((user_message, agent_message))
        out = self.classify_output if self.classify_output is not None else (
            "WAITING" if agent_message.rstrip().endswith("?") else "DONE")
        return StandInCall(kind="classify", output=out, cost_usd=0.001)

    def answer_tool(self, history, questions):
        self.replied.append((list(history), questions))
        return StandInCall(kind="tool-answer", output="1: B\n2: x, y", cost_usd=0.003)

    def reply(self, history, agent_message):
        self.replied.append((list(history), agent_message))
        if self.reply_error:
            return StandInCall(kind="reply", error="boom")
        return StandInCall(kind="reply", output=self.answer, cost_usd=0.002)


def _loop(mode, turns, agent, stand_in=None, **kw):
    args = dict(timeout_s=1800, max_turns=60, budget_usd=5.0, max_replies=5)
    args.update(kw)
    return run_loop(mode=mode, turns=turns, agent=agent, stand_in=stand_in, **args)


def test_conventional_sends_each_scripted_turn_without_a_stand_in():
    agent = FakeAgent(["Which one?", "Implemented."])
    log = _loop("conventional", ["/plan fix it", "/apply"], agent)
    assert [c[0] for c in agent.calls] == ["/plan fix it", "/apply"]
    s = log.summary()
    assert s["agent_calls"] == 2 and s["user_replies"] == 0 and s["stand_in_calls"] == 0
    assert log.stop_reason == "completed" and all(t.decision is None for t in log.turns)


def test_informative_answers_questions_and_script_moves_phases():
    agent = FakeAgent(["Should I use A) a list or B) a dict?", "Plan saved.", "Implemented."])
    si = FakeStandIn()
    log = _loop("informative", ["/plan fix it", "/apply"], agent, si)
    assert [c[0] for c in agent.calls] == ["/plan fix it", "B. The brief says so.", "/apply"]
    assert [t.source for t in log.turns] == ["script", "stand-in", "script"]
    assert [t.phase for t in log.turns] == [0, 0, 1]
    assert [t.decision for t in log.turns] == ["waiting", "done", "done"]
    s = log.summary()
    assert (s["agent_calls"], s["scripted_turns"], s["user_replies"]) == (3, 2, 1)
    assert s["stand_in_calls"] == 4 and s["stand_in_cost_usd"] == pytest.approx(0.005)
    assert log.stop_reason == "completed" and not s["ended_waiting"]
    # the responder saw the conversation up to and including the question
    history, msg = si.replied[0]
    assert history == [("user", "/plan fix it"), ("agent", "Should I use A) a list or B) a dict?")]
    assert msg.endswith("dict?")


def test_uninformative_uses_the_same_decision_but_a_fixed_reply():
    agent = FakeAgent(["Which one?", "Done."])
    si = FakeStandIn()
    log = _loop("uninformative", ["fix it"], agent, si)
    assert [c[0] for c in agent.calls] == ["fix it", UNINFORMATIVE_REPLY]
    assert si.replied == [] and len(si.classified) == 2
    assert log.summary()["user_replies"] == 1


def test_reply_limit_moves_the_script_on_or_ends_the_trial():
    agent = FakeAgent(["Q1?", "Q2?", "Q3?", "Q4?"])
    log = _loop("uninformative", ["/plan x", "/apply"], agent, FakeStandIn(), max_replies=1)
    # plan asks, gets one reply, asks again (cap) -> /apply; apply asks (cap, script empty) -> stop
    assert [c[0] for c in agent.calls] == ["/plan x", UNINFORMATIVE_REPLY, "/apply"]
    assert log.stop_reason == "user-reply limit"
    s = log.summary()
    assert s["reply_cap_hits"] == 2 and s["ended_waiting"]


def test_agent_error_stops_the_loop():
    agent = FakeAgent(["Q?"], fail_at=1)
    log = _loop("informative", ["/plan x", "/apply"], agent, FakeStandIn())
    assert len(agent.calls) == 2 and log.stop_reason == "agent ended: error_max_turns"


def test_limits_are_shared_across_calls():
    agent = FakeAgent(["Q?"] * 9, cost_step=1.0, wall=100.0, turns=10)
    _loop("uninformative", ["x"], agent, FakeStandIn(), timeout_s=1000, max_turns=60, budget_usd=5.0,
          max_replies=9)
    lims = [c[2] for c in agent.calls]
    assert [lim.timeout_s for lim in lims] == [1000, 900, 800, 700, 600]
    assert [lim.max_turns for lim in lims] == [60, 50, 40, 30, 20]
    assert [lim.budget_usd for lim in lims] == [5.0, 4.0, 3.0, 2.0, 1.0]
    # the 6th call would start with $0 left
    agent2 = FakeAgent(["Q?"] * 9, cost_step=1.0)
    log = _loop("uninformative", ["x"], agent2, FakeStandIn(), budget_usd=5.0, max_replies=9)
    assert log.stop_reason == "budget" and len(agent2.calls) == 5


def test_unparseable_decision_counts_as_done_and_is_recorded():
    agent = FakeAgent(["Q?"])
    log = _loop("informative", ["x"], agent, FakeStandIn(classify_output="maybe"))
    assert len(agent.calls) == 1 and log.turns[0].decision == "done"
    assert log.summary()["stand_in_errors"] == 1


def test_failed_reply_falls_back_to_no_information():
    agent = FakeAgent(["Q?", "Done."])
    log = _loop("informative", ["x"], agent, FakeStandIn(reply_error=True))
    assert agent.calls[1][0] == NO_INFO_REPLY and log.summary()["stand_in_errors"] == 1


def test_stand_in_modes_need_a_stand_in():
    with pytest.raises(ValueError):
        _loop("informative", ["x"], FakeAgent([]))


def test_parse_decision_and_prompts():
    assert parse_decision("WAITING") == "waiting" and parse_decision("done.") == "done"
    assert parse_decision("I think DONE") == "done" and parse_decision("") is None
    p = classifier_prompt("/plan x", "Which one?")
    assert "/plan x" in p and "Which one?" in p
    r = responder_prompt("fix the bug", "Wants a dict.", [("user", "/plan"), ("agent", "Plan?")], "Which one?")
    assert "fix the bug" in r and "Wants a dict." in r and "[agent]\nPlan?" in r and r.endswith("Which one?\n>>>")
    assert "(empty)" in classifier_prompt("x", "")


# --------------------------------------------------------------------------- manifests, tasks, CLI


def test_workflow_turns_in_manifest(tmp_path):
    d = tmp_path / "wf"
    d.mkdir()
    (d / "manifest.toml").write_text('[workflow]\nturns = ["/plan {task_prompt}", "/apply"]\n')
    t = load_treatment(d)
    assert t.workflow == ("/plan {task_prompt}", "/apply")
    assert t.turns("fix {it}") == ["/plan fix {it}", "/apply"]
    assert ArmSpec("B", t).multi_turn and not ArmSpec("A", PLAIN).multi_turn
    assert ArmSpec("A", PLAIN, "uninformative").multi_turn
    assert PLAIN.turns("p") == ["p"]
    (d / "manifest.toml").write_text('[workflow]\nturns = ["/plan", "/apply"]\n')
    with pytest.raises(ConfigError, match="task_prompt"):
        load_treatment(d)
    (d / "manifest.toml").write_text('[workflow]\nsteps = ["x"]\n')
    with pytest.raises(ConfigError, match="unknown keys"):
        load_treatment(d)


def test_workflow_does_not_change_existing_treatment_hashes(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "manifest.toml").write_text('name = "t"\n')
    t = load_treatment(d)
    assert "workflow" not in t.manifest_dict()
    assert TreatmentSpec(name="t", path=d, workflow=("{task_prompt}",)).content_hash() != t.content_hash()


def _task_copy(tmp_path) -> Path:
    dst = tmp_path / "tasks" / "example-bug"
    shutil.copytree(ROOT / "examples" / "tasks" / "example-bug", dst)
    return dst


def test_user_brief_is_loaded_and_checked(tmp_path):
    d = _task_copy(tmp_path)
    before = load_task(d).content_hash()
    assert load_task(d).user_brief == ""
    (d / "user.md").write_text("I want totals in cents.\n")
    t = load_task(d)
    # the brief only reaches the stand-in: the task hash (baselines, regrade) is unchanged
    assert t.user_brief == "I want totals in cents." and t.content_hash() == before
    assert t.brief_hash() and load_task(_task_copy(tmp_path / "other")).brief_hash() is None
    (d / "user.md").write_text("The hidden tests check cents.\n")
    with pytest.raises(ConfigError, match="hidden tests"):
        load_task(d)


def test_cli_user_modes(tmp_path, capsys):
    _task_copy(tmp_path)
    (tmp_path / "hai-proof.toml").write_text('model = "claude-test-model"\nstand_in_model = "claude-si"\n')
    base = ["--root", str(tmp_path), "run", "--no-control", "--reps", "1", "--dry-run"]
    assert cli.main(base) == 0
    assert "user in the loop" not in capsys.readouterr().out
    assert cli.main(base + ["--user", "uninformative"]) == 0
    out = capsys.readouterr().out
    assert "A=plain (uninformative)" in out and "stand-in claude-si" in out
    # the informative stand-in needs a user brief for every task
    assert cli.main(base + ["--user", "informative"]) == 2
    assert "user.md" in capsys.readouterr().err
    (tmp_path / "tasks" / "example-bug" / "user.md").write_text("Totals in cents.\n")
    assert cli.main(base + ["--user", "informative", "--stand-in-model", "m2"]) == 0
    assert "stand-in m2" in capsys.readouterr().out
    assert cli.main(base + ["--user-b", "informative"]) == 2  # single arm


# --------------------------------------------------------------------------- the ask tool (AskUserQuestion)

QS = [{"question": "Which store?", "options": [{"label": "A", "description": "list"}, {"label": "B"}]},
      {"question": "Which flags?", "multiSelect": True, "options": [{"label": "x"}, {"label": "y"}]}]


def test_tool_answers_are_parsed_per_question():
    assert parse_tool_answers("1: B\n2: x, y", QS) == {"Which store?": "B", "Which flags?": "x, y"}
    # answers run onto following lines; a numbered list inside an answer stays in it
    out = "1: B. Also:\n1. register_encoder(fn) returns fn\n2. unregister is a no-op\n2: x"
    assert parse_tool_answers(out, QS) == {
        "Which store?": "B. Also:\n1. register_encoder(fn) returns fn\n2. unregister is a no-op", "Which flags?": "x"}
    assert parse_tool_answers("1: B", QS) == {"Which store?": "B", "Which flags?": NO_INFO_REPLY}
    p = tool_responder_prompt("fix it", "Wants B.", [("user", "fix it")], QS)
    assert "Wants B." in p and "1. Which store?" in p and "   - A - list" in p and "(several may be chosen)" in p
    assert "conversation so far" not in p  # only the request itself so far


def test_answerer_modes_and_cap():
    si = FakeStandIn()
    inf = ToolAnswerer("informative", si, max_answers=1)
    inf.history = [("user", "fix it")]
    assert inf({"questions": QS}) == {"Which store?": "B", "Which flags?": "x, y"}
    assert si.replied == [([("user", "fix it")], QS)]
    # past the cap: the fixed reply, no stand-in call
    assert inf({"questions": QS[:1]}) == {"Which store?": UNINFORMATIVE_REPLY}
    assert [r["source"] for r in inf.records] == ["stand-in", "cap"]
    for mode in ("conventional", "uninformative"):
        a = ToolAnswerer(mode, FakeStandIn(), max_answers=5)
        assert a({"questions": QS}) == {q["question"]: UNINFORMATIVE_REPLY for q in QS}
        assert a.records[0]["source"] == "fixed" and a.records[0]["stand_in"] is None
    # reticent answers from the brief like informative
    si = FakeStandIn()
    assert ToolAnswerer("reticent", si, max_answers=5)({"questions": QS}) == {"Which store?": "B", "Which flags?": "x, y"}
    assert len(si.replied) == 1


class _RecordingStandIn(ContainerStandIn):
    def _call(self, kind, system, prompt):
        self.calls.append((kind, system, prompt))
        return StandInCall(kind=kind, output="ok")


def test_reticent_stand_in_uses_its_own_prompts():
    kw = dict(image="i", model="m", run_id="r", name="n", auth_env={}, network=None, proxy=None,
              task_prompt="fix it", brief="Wants B.")
    for reticent, system, fmt in ((False, RESPONDER_SYSTEM, "as fully as you would"),
                                  (True, RETICENT_RESPONDER_SYSTEM, "say nothing about other points")):
        si = _RecordingStandIn(None, reticent=reticent, **kw)
        si.calls = []
        si.reply([("user", "fix it"), ("agent", "A or B?")], "A or B?")
        si.answer_tool([("user", "fix it")], QS)
        si.classify("fix it", "A or B?")
        (k1, s1, _), (k2, s2, p2), (k3, s3, _) = si.calls
        assert s1 == s2 == system and fmt in p2 and "Wants B." in p2
        assert s3 == CLASSIFIER_SYSTEM  # the WAITING / DONE decision is the same in every mode
    assert "Do not bring up" in RETICENT_RESPONDER_SYSTEM and "Do not bring up" not in RESPONDER_SYSTEM


def test_reticent_full_tool_answers():
    kw = dict(image="i", model="m", run_id="r", name="n", auth_env={}, network=None, proxy=None,
              task_prompt="fix it", brief="Wants B.")
    for reticent, tool_answers, want, unwanted in (
            (True, "brief", "add in a sentence", "add everything the brief says"),
            (True, "full", "add everything the brief says", "add in a sentence"),
            (False, "full", "in a sentence or two", "add everything the brief says")):  # reticent only
        si = _RecordingStandIn(None, reticent=reticent, tool_answers=tool_answers, **kw)
        si.calls = []
        si.answer_tool([("user", "fix it")], QS)
        (_, _, prompt), = si.calls
        assert want in prompt and unwanted not in prompt


def test_strict_reticence_filters_text_replies():
    kw = dict(image="i", model="m", run_id="r", name="n", auth_env={}, network=None, proxy=None,
              task_prompt="fix it", brief="Wants B.")
    si = _RecordingStandIn(None, reticent=True, reticence="strict", **kw)
    si.calls = []
    call = si.reply([("user", "fix it"), ("agent", "Plan: B. OK?")], "Plan: B. OK?")
    (k1, s1, _), (k2, s2, p2) = si.calls
    assert k1 == "reply" and s1 == RETICENT_RESPONDER_SYSTEM_STRICT and "not an open question" in s1
    assert k2 == "filter" and s2 == STRICT_FILTER_SYSTEM and "Plan: B. OK?" in p2
    assert call.draft is not None and call.output  # the filter's output is what gets sent
    si.calls = []
    si.answer_tool([("user", "fix it")], QS)  # tool answers are not filtered
    assert len(si.calls) == 1
    for reticent, reticence in ((True, "standard"), (False, "strict")):  # strict applies to reticent only
        si = _RecordingStandIn(None, reticent=reticent, reticence=reticence, **kw)
        si.calls = []
        si.reply([("user", "fix it"), ("agent", "A or B?")], "A or B?")
        assert len(si.calls) == 1 and si.calls[0][1] != RETICENT_RESPONDER_SYSTEM_STRICT


def test_cli_tool_answers(tmp_path, capsys):
    _task_copy(tmp_path)
    (tmp_path / "hai-proof.toml").write_text('model = "claude-test-model"\n')
    base = ["--root", str(tmp_path), "run", "--reps", "1", "--dry-run", "--arm-a", "plain", "--arm-b", "plain",
            "--ask-tool", "on", "--user", "uninformative"]
    assert cli.main(base) == 0
    assert "tool answers" not in capsys.readouterr().out
    assert cli.main(base + ["--tool-answers", "full"]) == 0
    assert "full tool answers" in capsys.readouterr().out
    assert cli.main(base + ["--reticence", "strict"]) == 0
    assert "strict reticence" in capsys.readouterr().out


def test_run_loop_records_tool_questions_per_call():
    si = FakeStandIn()
    ans = ToolAnswerer("informative", si, max_answers=5)
    seen = []

    def agent(message, n, lim):
        seen.append(list(ans.history))
        if n == 0:
            ans({"questions": QS})
        return AgentTurn(final_text="Done.", num_turns=2, cost_usd=0.1 * (n + 1), wall_s=1.0)

    log = _loop("informative", ["/plan x", "/apply"], agent, si, answerer=ans)
    assert seen[0] == [("user", "/plan x")] and seen[1][-1] == ("user", "/apply")
    assert [len(t.tool_questions) for t in log.turns] == [1, 0]
    s = log.summary()
    assert (s["tool_question_calls"], s["tool_questions"]) == (1, 2)
    assert s["stand_in_calls"] == 3 and s["stand_in_cost_usd"] == pytest.approx(0.005)


def test_cli_ask_tool(tmp_path, capsys):
    _task_copy(tmp_path)
    (tmp_path / "hai-proof.toml").write_text('model = "claude-test-model"\n')
    base = ["--root", str(tmp_path), "run", "--reps", "1", "--dry-run", "--arm-a", "plain", "--arm-b", "plain"]
    assert cli.main(base + ["--ask-tool-b", "on"]) == 0
    out = capsys.readouterr().out
    assert "B=plain (ask tool)" in out and "B=conventional + ask tool" in out and "A=conventional" not in out
    assert cli.main(["--root", str(tmp_path), "run", "--no-control", "--reps", "1", "--dry-run",
                     "--ask-tool-b", "on"]) == 2
    assert ArmSpec("A", PLAIN, ask_tool="on").multi_turn and ArmSpec("A", PLAIN, ask_tool="hidden").multi_turn
    assert not ArmSpec("A", PLAIN, ask_tool="off").multi_turn
    assert cli.main(base + ["--ask-tool-a", "hidden", "--ask-tool-b", "on"]) == 0
    out = capsys.readouterr().out
    assert "A=plain (ask tool hidden)" in out and "B=plain (ask tool)" in out


def test_cli_task_stand_in(tmp_path, capsys):
    d = _task_copy(tmp_path)
    (d / "user.md").write_text("I want totals in cents.\n")
    toml = (d / "task.toml").read_text()
    (d / "task.toml").write_text(toml.replace('kind = "bug"', 'kind = "bug"\nuser = "reticent"\nask_tool = "on"\n'
                                                               'reticence = "strict"\ntool_answers = "full"', 1))
    (tmp_path / "hai-proof.toml").write_text('model = "claude-test-model"\n')
    base = ["--root", str(tmp_path), "run", "--reps", "1", "--dry-run", "--arm-a", "plain", "--arm-b", "plain",
            "--ask-tool", "on", "--user", "reticent"]
    assert cli.main(base) == 0
    assert "stand-in set by the task: EX1 = full tool answers, strict reticence" in capsys.readouterr().out
    assert cli.main(base + ["--reticence", "standard"]) != 0
    assert "define their stand-in with strict" in capsys.readouterr().err


def test_loop_log_records_stand_in():
    assert "reticence" not in LoopLog(mode="informative").to_json()
    j = LoopLog(mode="reticent", tool_answers="full", reticence="strict").to_json()
    assert (j["tool_answers"], j["reticence"]) == ("full", "strict")
