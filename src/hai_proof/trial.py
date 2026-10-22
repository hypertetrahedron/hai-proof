"""One trial = one arm × one task × one repetition, run in a fresh container (DESIGN §3.1)."""

from __future__ import annotations

import json
import re
import shlex
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import claudedata, diffbreakdown, streamjson, userloop
from .executor import Executor
from .models import AnalysisSpec, ArmSpec, RunConfig, TaskSpec, TrialResult, to_json
from .tarutil import extract_tar, tar_directory, tar_files

PYTHON = "/usr/local/bin/python3"  # system python in the image, independent of the task venv
WRAP = "/usr/local/bin/hai_proof_wrap.py"
GRADE = "/usr/local/bin/hai_proof_grade.py"
PROBE_PROMPT = "Reply with the single word OK."
POLL_S = 5.0
OVERRUN_GRACE_S = 180  # past its time limit the wrapper must have stopped claude; else the controller does
ASK_POLL_S = 2.0  # the agent is blocked while a question waits, so look for questions more often
ASK_ANSWER_TIMEOUT_S = 600  # the wrapper denies a question nobody answered in this time
AUTH_FAILED = "authentication failed"
USAGE_LIMIT = "account usage limit reached"
# The start-state commit is marked with a plain ref, not a tag: projects that derive their version from
# `git describe --tags` (setuptools-scm, websockets, ...) break on an unexpected tag such as "baseline".
BASELINE_REF = "refs/hai-proof/baseline"
AGENT_SHELL_ENV = "/tp/agent_shell_env.sh"
AGENT_SHELL_ENV_SCRIPT = ("unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY "
                          "http_proxy https_proxy all_proxy no_proxy\n")
DIFF_EXCLUDES = ("__pycache__/", "*.py[cod]", ".pytest_cache/", "*.egg-info/", ".mypy_cache/", ".ruff_cache/")


@dataclass
class TrialContext:
    """Everything a trial needs that is shared across the run."""

    ex: Executor
    run: RunConfig
    run_dir: Path
    auth_env: dict[str, str]
    trial_images: dict[tuple[str, str], str]  # (arm label, task id) -> image tag
    arm_networks: dict[str, str] = field(default_factory=dict)  # arm label -> internal network
    arm_proxies: dict[str, str] = field(default_factory=dict)  # arm label -> proxy URL
    trial_analyses: list[AnalysisSpec] = field(default_factory=list)
    log: Callable[[str], None] = print
    stand_in_image: str = ""  # plain base image for the user stand-in (userloop.ContainerStandIn)


class TrialFailure(RuntimeError):
    """Infrastructure failure inside a trial (not an agent failure)."""


def claude_argv(run: RunConfig, *, max_turns: int, budget_usd: float) -> list[str]:
    """The identical `claude -p` invocation used for every arm (prompt inserted at index 2)."""
    argv = ["claude", "-p", "<prompt>", "--model", run.model]
    if run.effort:
        argv += ["--effort", run.effort]
    argv += [
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(max_turns),
        "--max-budget-usd", f"{budget_usd:.2f}",
        "--exclude-dynamic-system-prompt-sections",
        "--output-format", "stream-json",
        "--verbose",
    ]
    return argv


def leakage_needles(task: TaskSpec) -> tuple[list[str], list[str]]:
    """(url needles, commit needles) whose appearance means the agent reached the upstream fix.

    URLs only count inside network requests (the repo's own files mention its URL); commit SHAs of the
    upstream fix count anywhere.
    """
    if not task.source:
        return [], []
    url = re.sub(r"^(https?://|git@)", "", task.source.url).removesuffix(".git").replace(":", "/")
    shas = [task.source.fix, task.source.fix[:10]] if task.source.fix else []
    return [url], shas


def run_trial(ctx: TrialContext, arm: ArmSpec, task: TaskSpec, rep: int, pair_id: str,
              *, probe: bool = False) -> TrialResult:
    run, ex = ctx.run, ctx.ex
    t = arm.treatment
    result = TrialResult(
        run_id=run.run_id, arm=arm.label, treatment=t.name, task_id=task.id, rep=rep, pair_id=pair_id,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    rep_name = {-1: "warmup", -2: f"probe-{pair_id.rsplit('-', 1)[-1]}"}.get(rep, f"rep{rep}")
    # A rerun pair (pair id "<task>-r<rep>-retry1", "-ulwait1", ...) gets its own directory, so the discarded
    # attempt's files stay for inspection instead of being overwritten.
    base_id = f"{task.id}-r{rep}"
    if rep >= 0 and pair_id.startswith(base_id + "-"):
        rep_name += pair_id[len(base_id):]
    rel_dir = Path("trials") / arm.label / task.id / rep_name
    trial_dir = ctx.run_dir / rel_dir
    trial_dir.mkdir(parents=True, exist_ok=True)
    result.artifacts_dir = rel_dir.as_posix()

    name = f"tp-{run.run_id}-{arm.label}-{_slug(task.id)}-{rep_name}-{uuid.uuid4().hex[:6]}".lower()
    container: str | None = None
    try:
        container = _start_container(ctx, arm, task, name)
        _prepare_workspace(ctx, container, arm, task, probe=probe)

        task_prompt = t.prompt_prefix + task.prompt_for(t.prompt_variant)
        # The egress proxy is for the claude process only. Commands the agent runs never need the
        # network, and libraries that honour proxy variables (websockets, requests, ...) would route even
        # local test traffic to the proxy, so the agent's shell drops them (CLAUDE_ENV_FILE is sourced
        # before each Bash command).
        env = {**t.env, "CLAUDE_CODE_SUBAGENT_MODEL": run.model, "CLAUDE_ENV_FILE": AGENT_SHELL_ENV}
        agent_dir = trial_dir / "agent"
        last_call_has_result = True
        if probe or not arm.multi_turn:
            prompt = PROBE_PROMPT if probe else t.turns(task_prompt)[0]
            timeout_s, max_turns, budget_usd = (300, 5, 1.0) if probe else run.task_limits(task)
            argv = claude_argv(run, max_turns=max_turns, budget_usd=budget_usd)
            spec = {"argv": argv, "prompt_arg_index": 2, "prompt_file": "/tp/prompt.md", "cwd": "/work",
                    "env": env, "timeout_s": timeout_s, "out_dir": "/out/agent"}
            ex.put_tar(container, "/tp", tar_files({"prompt.md": prompt, "agent.json": json.dumps(spec),
                                                    "agent_shell_env.sh": AGENT_SHELL_ENV_SCRIPT}))

            ex.exec(container, [PYTHON, WRAP, "/tp/agent.json"], detach=True)
            _wait_for(ctx, container, "/out/agent", deadline_s=timeout_s + OVERRUN_GRACE_S)
            extract_tar(ex.get_tar(container, "/out/agent"), trial_dir)
        else:
            loop = _run_turns(ctx, container, arm, task, task_prompt, env, trial_dir, f"{name}-user")
            result.user_loop = loop.summary()
            last = loop.turns[-1].agent if loop.turns else None
            last_call_has_result = bool(last and last.end not in ("no_result", "timed_out"))
        claudedata.scrub_secrets(agent_dir, list(ctx.auth_env.values()))
        if not probe:
            _collect_claude_data(ctx, container, trial_dir, f"{run.run_id} · {arm.label} / {task.id} / {rep_name}",
                                 result)
        transcript_text = _read(agent_dir / "transcript.jsonl")
        timing = json.loads(_read(agent_dir / "timing.json") or "{}")
        stderr = _read(agent_dir / "stderr.log")

        tr = streamjson.parse_transcript(transcript_text)
        result.metrics = streamjson.metrics_from_transcript(
            tr, wall_s=float(timing.get("wall_s", 0.0)), exit_code=timing.get("exit_code"),
            timed_out=bool(timing.get("timed_out", False)))
        if tr.result is None or not last_call_has_result:
            # stopped before its result event (e.g. the time limit): use Claude Code's record
            claudedata.apply_cost_state(result.metrics, claudedata.cost_state(trial_dir / "claude_home"))
        result.init_snapshot = streamjson.init_snapshot(tr)
        result.isolation_problems = streamjson.isolation_problems(result.init_snapshot, t)
        result.rate_limited = streamjson.is_rate_limited(tr, stderr)
        result.dependency_used = streamjson.dependency_usage(tr, [r.name for r in t.requires])
        urls, shas = leakage_needles(task)
        result.leakage_flags = (streamjson.network_leakage_flags(tr, urls)
                                + streamjson.leakage_flags(tr, shas))

        if streamjson.is_auth_failure(tr):
            result.status = "error"
            result.error = AUTH_FAILED + " (API returned 401/403; check ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN)"
            return result
        ul = streamjson.usage_limit(tr)
        if ul:
            result.status = "discarded"
            result.rate_limited = True
            result.usage_limit_resets_at = ul["resets_at"]
            result.error = USAGE_LIMIT + (f" ({ul['type']})" if ul.get("type") else "")
            return result
        if result.rate_limited:
            result.status = "discarded"
            result.error = "rate limited / overloaded API"
        elif result.isolation_problems:
            result.status = "excluded"
            result.error = "isolation check failed"
        elif result.leakage_flags:
            result.status = "excluded"
            result.error = "agent reached the upstream fix"

        if probe:
            return result

        # ---- diff vs baseline (before hidden tests arrive)
        numstat = _sh(ctx, container, f"git add -A && git diff --cached --numstat {BASELINE_REF}").stdout.decode()
        patch = _sh(ctx, container, f"git diff --cached {BASELINE_REF}", check=False).stdout
        (trial_dir / "session.patch").write_bytes(patch)
        result.diff_breakdown = diffbreakdown.diff_breakdown(
            numstat, artifacts=t.artifacts, overrides=task.diff_categories or None)
        (trial_dir / "diff_breakdown.json").write_text(json.dumps(result.diff_breakdown, indent=2))
        if result.session and "error" not in result.session:
            # Re-render now that session.patch exists, so the session page shows the real diff size.
            collected = result.session.get("collected")
            result.session = claudedata.write_trial_data(
                trial_dir, f"{run.run_id} · {arm.label} / {task.id} / {rep_name}")
            result.session["collected"] = collected
        if ctx.trial_analyses:
            _sh(ctx, container, "rm -rf /analysis && mkdir -p /analysis && cp -a /work /analysis/workspace")

        # ---- grade, offline
        grade = _grade(ctx, container, arm, task)
        (trial_dir / "grade.json").write_text(json.dumps(grade, indent=2))
        result.acceptance_pass = grade.get("acceptance_pass")
        result.regression_pass = grade.get("regression_pass")

        # ---- optional analyses (network back on; never touch metrics)
        if ctx.trial_analyses:
            from .analyses import run_trial_analyses

            net = ctx.arm_networks.get(arm.label)
            if net:
                ex.network_connect(net, container)
            result.analyses = run_trial_analyses(ctx, container, arm, task, trial_dir, rel_dir)
        return result
    except Exception as e:  # noqa: BLE001 - every failure must become a recorded trial
        result.status = "error"
        result.error = f"{type(e).__name__}: {e}"[:2000]
        ctx.log(f"  ! {arm.label}/{task.id}/{rep_name}: {result.error}")
        return result
    finally:
        (trial_dir / "trial.json").write_text(json.dumps(_safe_json(result), indent=2))
        if container:
            ex.remove(container)


# --------------------------------------------------------------------------- user-in-the-loop turns


def _run_turns(ctx: TrialContext, container: str, arm: ArmSpec, task: TaskSpec, task_prompt: str,
               env: dict[str, str], trial_dir: Path, stand_in_name: str) -> userloop.LoopLog:
    """Run the scripted turns and stand-in replies as `claude -p` calls on one session (DESIGN §3.8).

    Each call writes to /out/turns/NN and is copied to agent/turns/NN. Afterwards agent/transcript.jsonl,
    timing.json and stderr.log are the concatenation, so the rest of the trial reads them as for a
    single session (cost and token totals in the last result event cover the whole session).
    """
    run, ex = ctx.run, ctx.ex
    session_id = str(uuid.uuid4())
    turns_dir = trial_dir / "agent" / "turns"
    turns_dir.mkdir(parents=True, exist_ok=True)
    ex.put_tar(container, "/tp", tar_files({"agent_shell_env.sh": AGENT_SHELL_ENV_SCRIPT}))

    def agent(message: str, n: int, lim: userloop.TurnLimits) -> userloop.AgentTurn:
        tag = f"{n:02d}"
        argv = claude_argv(run, max_turns=lim.max_turns, budget_usd=lim.budget_usd)
        argv += ["--session-id", session_id] if n == 0 else ["--resume", session_id]
        out_dir = f"/out/turns/{tag}"
        spec = {"argv": argv, "prompt_arg_index": 2, "prompt_file": f"/tp/turn{tag}.md", "cwd": "/work",
                "env": env, "timeout_s": lim.timeout_s, "out_dir": out_dir}
        if arm.sdk_input:
            # AskUserQuestion is only offered with stream-json input and stdio permission prompts; the
            # wrapper sends the prompt on stdin and passes the questions to us through out_dir/ask.
            spec["argv"] = argv[:2] + argv[3:] + ["--input-format", "stream-json", "--permission-prompt-tool", "stdio"]
            if arm.ask_tool == "hidden":
                spec["argv"] += ["--disallowedTools", "AskUserQuestion"]
            spec["prompt_arg_index"] = None
            spec["stdio"] = {"ask_dir": f"{out_dir}/ask", "answer_timeout_s": ASK_ANSWER_TIMEOUT_S}
        ex.put_tar(container, "/tp", tar_files({f"turn{tag}.md": message, f"turn{tag}.json": json.dumps(spec)}))
        ex.exec(container, ["chown", "-R", "agent:agent", "/tp", "/out"], user="root")
        ex.exec(container, [PYTHON, WRAP, f"/tp/turn{tag}.json"], detach=True)
        if arm.sdk_input:
            _serve_questions(ctx, container, out_dir, answerer, deadline_s=lim.timeout_s + OVERRUN_GRACE_S)
        else:
            _wait_for(ctx, container, out_dir, deadline_s=lim.timeout_s + OVERRUN_GRACE_S)
        extract_tar(ex.get_tar(container, out_dir), turns_dir)
        timing = json.loads(_read(turns_dir / tag / "timing.json") or "{}")
        tr = streamjson.parse_transcript(_read(turns_dir / tag / "transcript.jsonl"))
        m = streamjson.metrics_from_transcript(tr, wall_s=float(timing.get("wall_s", 0.0)),
                                               timed_out=bool(timing.get("timed_out", False)))
        end = "timed_out" if m.timed_out else (m.subtype or "")
        return userloop.AgentTurn(final_text=str((tr.result or {}).get("result") or ""), num_turns=m.turns,
                                  cost_usd=m.cost_usd, wall_s=m.wall_s, ok=not (m.is_error or m.timed_out),
                                  end=end)

    stand_in = None
    if arm.user != "conventional":
        stand_in = userloop.ContainerStandIn(
            ex, image=ctx.stand_in_image, model=run.stand_in_model, run_id=run.run_id, name=stand_in_name,
            auth_env=ctx.auth_env, network=ctx.arm_networks.get(arm.label), proxy=ctx.arm_proxies.get(arm.label),
            task_prompt=task_prompt, brief=task.user_brief, reticent=arm.user == "reticent",
            tool_answers=run.tool_answers)
    answerer = userloop.ToolAnswerer(arm.user, stand_in, run.max_user_replies) if arm.sdk_input else None
    log = userloop.LoopLog(mode=arm.user)
    timeout_s, max_turns, budget_usd = run.task_limits(task)
    try:
        userloop.run_loop(mode=arm.user, turns=arm.treatment.turns(task_prompt), agent=agent, stand_in=stand_in,
                          timeout_s=timeout_s, max_turns=max_turns, budget_usd=budget_usd,
                          max_replies=run.max_user_replies, log=log, answerer=answerer)
    finally:
        if stand_in:
            stand_in.close()
        _merge_turns(turns_dir, trial_dir / "agent")
        (trial_dir / "user_loop.json").write_text(json.dumps(log.to_json(), indent=2), encoding="utf-8")
    return log


def _serve_questions(ctx: TrialContext, container: str, out_dir: str, answerer: userloop.ToolAnswerer,
                     *, deadline_s: float) -> None:
    """Wait for out_dir/done, answering each out_dir/ask/NNN.json the wrapper writes meanwhile."""
    ex = ctx.ex
    end = time.monotonic() + deadline_s
    answered: set[str] = set()
    misses = 0
    while time.monotonic() < end:
        try:
            r = ex.exec(container, ["sh", "-c", f"test -f {out_dir}/done && echo DONE; ls {out_dir}/ask 2>/dev/null"],
                        check=False, timeout=60)
            misses = 0
        except Exception as e:  # noqa: BLE001
            misses += 1
            if misses >= 12:
                raise TrialFailure(f"lost contact with execution host while waiting: {e}") from e
            time.sleep(POLL_S)
            continue
        names = r.stdout.decode(errors="replace").split()
        if "DONE" in names:
            return
        for q in sorted(n for n in names if re.fullmatch(r"\d{3}\.json", n) and n not in answered):
            text = ex.exec(container, ["cat", f"{out_dir}/ask/{q}"], timeout=60).stdout.decode(errors="replace")
            try:
                tool_input = json.loads(text)
            except json.JSONDecodeError:
                tool_input = {}
            answers = answerer(tool_input if isinstance(tool_input, dict) else {})
            name = q.removesuffix(".json") + ".answer.json"
            ex.put_tar(container, f"{out_dir}/ask", tar_files({name: json.dumps({"answers": answers})}))
            answered.add(q)
        time.sleep(ASK_POLL_S)
    _stop_overrun(ctx, container, out_dir, deadline_s)


def _merge_turns(turns_dir: Path, agent_dir: Path) -> None:
    """agent/transcript.jsonl, stderr.log and timing.json for the whole session, from the per-call copies."""
    parts = sorted(p for p in turns_dir.iterdir() if p.is_dir()) if turns_dir.is_dir() else []
    transcript, stderr, timings = [], [], []
    for p in parts:
        text = _read(p / "transcript.jsonl")
        transcript.append(text if not text or text.endswith("\n") else text + "\n")
        err = _read(p / "stderr.log")
        if err:
            stderr.append(f"--- call {p.name}\n{err}")
        timings.append(json.loads(_read(p / "timing.json") or "{}"))
    (agent_dir / "transcript.jsonl").write_text("".join(transcript), encoding="utf-8")
    (agent_dir / "stderr.log").write_text("".join(stderr), encoding="utf-8")
    timing = {"wall_s": sum(float(t.get("wall_s", 0.0)) for t in timings),
              "exit_code": timings[-1].get("exit_code") if timings else None,
              "timed_out": any(t.get("timed_out") for t in timings),
              "started_at": timings[0].get("started_at") if timings else None,
              "ended_at": timings[-1].get("ended_at") if timings else None,
              "calls": len(timings)}
    (agent_dir / "timing.json").write_text(json.dumps(timing), encoding="utf-8")


# --------------------------------------------------------------------------- steps


# Docker lets unprivileged users bind any port (ip_unprivileged_port_start=0). Restore the usual Linux
# value: upstream suites assume a low port can't be bound (tornado's test_source_port_fail flaked).
CONTAINER_SYSCTLS = ("--sysctl", "net.ipv4.ip_unprivileged_port_start=1024")


def _start_container(ctx: TrialContext, arm: ArmSpec, task: TaskSpec, name: str) -> str:
    run = ctx.run
    image = ctx.trial_images[(arm.label, task.id)]
    args = ["--name", name, "--label", f"hai-proof.run={run.run_id}",
            "--cpus", str(run.limits.cpus), "--memory", run.limits.memory, *CONTAINER_SYSCTLS]
    net = ctx.arm_networks.get(arm.label)
    if net:
        proxy = ctx.arm_proxies[arm.label]
        args += ["--network", net,
                 "-e", f"HTTPS_PROXY={proxy}", "-e", f"HTTP_PROXY={proxy}",
                 "-e", f"https_proxy={proxy}", "-e", f"http_proxy={proxy}",
                 "-e", "NO_PROXY=localhost,127.0.0.1", "-e", "no_proxy=localhost,127.0.0.1"]
    args += [image, "sleep", "infinity"]
    return ctx.ex.run_detached(args, secret_env=ctx.auth_env)


def _prepare_workspace(ctx: TrialContext, container: str, arm: ArmSpec, task: TaskSpec, *, probe: bool) -> None:
    ex, t = ctx.ex, arm.treatment
    if t.user_dir:
        ex.put_tar(container, "/home/agent/.claude", tar_directory(t.user_dir))
    if t.project_dir:
        ex.put_tar(container, "/work", tar_directory(t.project_dir))
    # docker cp extracts as root; hand everything back to the agent user.
    ex.exec(container, ["chown", "-R", "agent:agent", "/work", "/home/agent", "/tp", "/out"], user="root")
    for cmd in t.setup_commands:
        r = _sh(ctx, container, cmd, check=False, timeout=600)
        if r.returncode != 0:
            raise TrialFailure(f"treatment setup command failed ({r.returncode}): {cmd}\n"
                               f"{r.stderr.decode(errors='replace')[-1500:]}")
    _sh(ctx, container, baseline_script())


def baseline_script() -> str:
    """Shell snippet that makes /work a git repo at the start state.

    Shared with validate-task, so a project that reacts to being inside a git repo fails validation the
    same way it would fail a trial. Build byproducts (e.g. .pyc from the agent running pytest) are not
    session changes; excluding them via .git/info/exclude keeps them out of diff_breakdown without
    touching the workspace.
    """
    excludes = "\\n".join(DIFF_EXCLUDES)
    return ("git init -q && printf '%b\\n' '" + excludes + "' >> .git/info/exclude && "
            "git add -A && git commit -q --allow-empty -m baseline && git update-ref " + BASELINE_REF + " HEAD")


def _collect_claude_data(ctx: TrialContext, container: str, trial_dir: Path, title: str,
                         result: TrialResult) -> None:
    """Save Claude Code's own records (~/.claude) and their parsed summary. Never fails the trial."""
    try:
        manifest = claudedata.collect(ctx.ex, container, trial_dir, list(ctx.auth_env.values()))
        result.session = claudedata.write_trial_data(trial_dir, title)
        result.session["collected"] = manifest
    except Exception as e:  # noqa: BLE001
        ctx.log(f"  ! could not collect Claude Code data: {type(e).__name__}: {e}")
        result.session = {"error": f"{type(e).__name__}: {e}"[:500]}


def _wait_for(ctx: TrialContext, container: str, out_dir: str, *, deadline_s: float) -> None:
    """Poll for out_dir/done. Survives transient SSH failures; the trial keeps running on the host."""
    end = time.monotonic() + deadline_s
    misses = 0
    while time.monotonic() < end:
        try:
            r = ctx.ex.exec(container, ["test", "-f", f"{out_dir}/done"], check=False, timeout=60)
            misses = 0
            if r.returncode == 0:
                return
        except Exception as e:  # noqa: BLE001
            misses += 1
            if misses >= 12:
                raise TrialFailure(f"lost contact with execution host while waiting: {e}") from e
        time.sleep(POLL_S)
    _stop_overrun(ctx, container, out_dir, deadline_s)


def _stop_overrun(ctx: TrialContext, container: str, out_dir: str, deadline_s: float) -> None:
    """The wrapper missed its own time limit by OVERRUN_GRACE_S: kill it and claude, and leave what it wrote
    plus a timing.json saying the call timed out, so the trial is graded as a timed-out failure and its
    cost read from Claude Code's records. Retrying it instead would give a slow failure a second chance.
    """
    ctx.log(f"  ! no result {deadline_s:.0f}s after the call started: stopping it, graded as timed out")
    timing = json.dumps({"wall_s": float(deadline_s), "exit_code": None, "timed_out": True,
                         "controller_stopped": True, "ended_at": datetime.now(timezone.utc).isoformat()})
    script = ("pkill -KILL -f '[h]ai_proof_wrap' ; "
              f"pkill -KILL -u agent -f claude ; mkdir -p {out_dir} && "
              f"touch {out_dir}/transcript.jsonl {out_dir}/stderr.log && "
              f"{{ test -s {out_dir}/timing.json || printf '%s' {shlex.quote(timing)} > {out_dir}/timing.json; }} && "
              f"touch {out_dir}/done && chown -R agent:agent {out_dir}")
    ctx.ex.exec(container, ["sh", "-c", script], user="root", timeout=60)


def _grade(ctx: TrialContext, container: str, arm: ArmSpec, task: TaskSpec) -> dict:
    ex = ctx.ex
    net = ctx.arm_networks.get(arm.label)
    if net:
        ex.network_disconnect(net, container)
    ex.exec(container, ["pkill", "-KILL", "-u", "agent", "-f", "claude"], user="root", check=False)
    return run_grader(ex, container, task)


# Per grading step (acceptance, regression). Suites run in well under 90 s; a step that hangs (a task
# whose start state deadlocks, e.g. B17/B18) is cut off here, and the exec timeout covers both steps.
GRADE_STEP_TIMEOUT_S = 600


def run_grader(ex: Executor, container: str, task: TaskSpec) -> dict:
    """Copy the hidden tests onto /work and run the in-container grader. Shared with validate-task."""
    if task.hidden_tests_dir.is_dir():
        ex.put_tar(container, "/work", tar_directory(task.hidden_tests_dir))
    files: dict[str, bytes | str] = {}
    custom = None
    if task.custom_grader:
        files["grade.sh"] = task.custom_grader.read_bytes()
        custom = "/tp/grade.sh"
    spec = {"cwd": "/work", "acceptance": list(task.acceptance), "acceptance_args": list(task.acceptance_args),
            "acceptance_cmd": task.acceptance_cmd, "regression": task.regression,
            "custom_grader": custom, "timeout_s": GRADE_STEP_TIMEOUT_S}
    files["grade.json"] = json.dumps(spec)
    ex.put_tar(container, "/tp", tar_files(files))
    ex.exec(container, ["chown", "-R", "agent:agent", "/work", "/tp"], user="root")
    r = ex.exec(container, [PYTHON, GRADE, "/tp/grade.json"], workdir="/work", check=False,
                timeout=2 * GRADE_STEP_TIMEOUT_S + 120)
    try:
        return json.loads(r.stdout.decode(errors="replace").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"acceptance_pass": False, "regression_pass": False,
                "error": f"grader produced no JSON (rc={r.returncode}): "
                         f"{r.stderr.decode(errors='replace')[-1500:]}"}


def _sh(ctx: TrialContext, container: str, script: str, *, check: bool = True, timeout: float | None = 300):
    # Not `bash -l`: /etc/profile resets PATH and would drop /opt/venv/bin.
    return ctx.ex.exec(container, ["bash", "-c", script], workdir="/work", check=check, timeout=timeout)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", s.lower())


def _safe_json(result: TrialResult) -> dict:
    return to_json(result)
