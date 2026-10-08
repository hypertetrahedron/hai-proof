"""One trial = one arm × one task × one repetition, run in a fresh container (DESIGN §3.1)."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import diffbreakdown, streamjson
from .executor import Executor
from .models import AnalysisSpec, ArmSpec, RunConfig, TaskSpec, TrialResult, to_json
from .tarutil import extract_tar, tar_directory, tar_files

PYTHON = "/usr/local/bin/python3"  # system python in the image, independent of the task venv
WRAP = "/usr/local/bin/hai_proof_wrap.py"
GRADE = "/usr/local/bin/hai_proof_grade.py"
PROBE_PROMPT = "Reply with the single word OK."
POLL_S = 5.0
AUTH_FAILED = "authentication failed"
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
        "--no-session-persistence",
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
    rel_dir = Path("trials") / arm.label / task.id / rep_name
    trial_dir = ctx.run_dir / rel_dir
    trial_dir.mkdir(parents=True, exist_ok=True)
    result.artifacts_dir = rel_dir.as_posix()

    name = f"tp-{run.run_id}-{arm.label}-{_slug(task.id)}-{rep_name}-{uuid.uuid4().hex[:6]}".lower()
    container: str | None = None
    try:
        container = _start_container(ctx, arm, task, name)
        _prepare_workspace(ctx, container, arm, task, probe=probe)

        prompt = PROBE_PROMPT if probe else (t.prompt_prefix + task.prompt)
        timeout_s = 300 if probe else task.timeout_s
        argv = claude_argv(run, max_turns=5 if probe else task.max_turns,
                           budget_usd=1.0 if probe else task.budget_usd)
        env = {**t.env, "CLAUDE_CODE_SUBAGENT_MODEL": run.model}
        spec = {"argv": argv, "prompt_arg_index": 2, "prompt_file": "/tp/prompt.md", "cwd": "/work",
                "env": env, "timeout_s": timeout_s, "out_dir": "/out/agent"}
        ex.put_tar(container, "/tp", tar_files({"prompt.md": prompt, "agent.json": json.dumps(spec)}))

        ex.exec(container, [PYTHON, WRAP, "/tp/agent.json"], detach=True)
        _wait_for(ctx, container, "/out/agent/done", deadline_s=timeout_s + 180)

        agent_dir = trial_dir / "agent"
        extract_tar(ex.get_tar(container, "/out/agent"), trial_dir)
        transcript_text = _read(agent_dir / "transcript.jsonl")
        timing = json.loads(_read(agent_dir / "timing.json") or "{}")
        stderr = _read(agent_dir / "stderr.log")

        tr = streamjson.parse_transcript(transcript_text)
        result.metrics = streamjson.metrics_from_transcript(
            tr, wall_s=float(timing.get("wall_s", 0.0)), exit_code=timing.get("exit_code"),
            timed_out=bool(timing.get("timed_out", False)))
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
        numstat = _sh(ctx, container, "git add -A && git diff --cached --numstat baseline").stdout.decode()
        patch = _sh(ctx, container, "git diff --cached baseline", check=False).stdout
        (trial_dir / "session.patch").write_bytes(patch)
        result.diff_breakdown = diffbreakdown.diff_breakdown(
            numstat, artifacts=t.artifacts, overrides=task.diff_categories or None)
        (trial_dir / "diff_breakdown.json").write_text(json.dumps(result.diff_breakdown, indent=2))
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


# --------------------------------------------------------------------------- steps


def _start_container(ctx: TrialContext, arm: ArmSpec, task: TaskSpec, name: str) -> str:
    run = ctx.run
    image = ctx.trial_images[(arm.label, task.id)]
    args = ["--name", name, "--label", f"hai-proof.run={run.run_id}",
            "--cpus", str(run.limits.cpus), "--memory", run.limits.memory]
    net = ctx.arm_networks.get(arm.label)
    if net:
        proxy = ctx.arm_proxies[arm.label]
        args += ["--network", net,
                 "-e", f"HTTPS_PROXY={proxy}", "-e", f"HTTP_PROXY={proxy}",
                 "-e", f"https_proxy={proxy}", "-e", f"http_proxy={proxy}",
                 "-e", "NO_PROXY=localhost,127.0.0.1"]
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
    # Build byproducts (e.g. .pyc from the agent running pytest) are not session changes. Excluding
    # them via .git/info/exclude keeps them out of diff_breakdown without touching the workspace.
    excludes = "\\n".join(DIFF_EXCLUDES)
    _sh(ctx, container,
        "git init -q && printf '%b\\n' '" + excludes + "' >> .git/info/exclude && "
        "git add -A && git commit -q --allow-empty -m baseline && git tag baseline")


def _wait_for(ctx: TrialContext, container: str, path: str, *, deadline_s: float) -> None:
    """Poll for a file. Survives transient SSH failures; the trial keeps running on the host."""
    end = time.monotonic() + deadline_s
    misses = 0
    while time.monotonic() < end:
        try:
            r = ctx.ex.exec(container, ["test", "-f", path], check=False, timeout=60)
            misses = 0
            if r.returncode == 0:
                return
        except Exception as e:  # noqa: BLE001
            misses += 1
            if misses >= 12:
                raise TrialFailure(f"lost contact with execution host while waiting: {e}") from e
        time.sleep(POLL_S)
    raise TrialFailure(f"trial did not finish within {deadline_s:.0f}s")


def _grade(ctx: TrialContext, container: str, arm: ArmSpec, task: TaskSpec) -> dict:
    ex = ctx.ex
    net = ctx.arm_networks.get(arm.label)
    if net:
        ex.network_disconnect(net, container)
    ex.exec(container, ["pkill", "-KILL", "-u", "agent", "-f", "claude"], user="root", check=False)
    return run_grader(ex, container, task)


def run_grader(ex: Executor, container: str, task: TaskSpec) -> dict:
    """Copy the hidden tests onto /work and run the in-container grader. Shared with validate-task."""
    if task.hidden_tests_dir.is_dir():
        ex.put_tar(container, "/work", tar_directory(task.hidden_tests_dir))
    files: dict[str, bytes | str] = {}
    custom = None
    if task.custom_grader:
        files["grade.sh"] = task.custom_grader.read_bytes()
        custom = "/tp/grade.sh"
    spec = {"cwd": "/work", "acceptance": list(task.acceptance), "regression": task.regression,
            "custom_grader": custom, "timeout_s": 900}
    files["grade.json"] = json.dumps(spec)
    ex.put_tar(container, "/tp", tar_files(files))
    ex.exec(container, ["chown", "-R", "agent:agent", "/work", "/tp"], user="root")
    r = ex.exec(container, [PYTHON, GRADE, "/tp/grade.json"], workdir="/work", check=False, timeout=1200)
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
