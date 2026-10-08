"""Post-run analyses (DESIGN §3.7): a neutral, blinded, read-only Claude session per trial or per arm.

Analyses run after grading and their cost is recorded separately; they can never change a trial's result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from . import streamjson
from .models import AnalysisResult, AnalysisSpec, ArmSpec, TaskSpec
from .tarutil import extract_tar, tar_files

if TYPE_CHECKING:
    from .trial import TrialContext

PYTHON = "/usr/local/bin/python3"
WRAP = "/usr/local/bin/hai_proof_wrap.py"

# Read-only toolset. The report comes back as the session's final message, so no write access is needed.
ANALYZER_TOOLS = ",".join([
    "Read", "Grep", "Glob",
    "Bash(git diff:*)", "Bash(git log:*)", "Bash(git status:*)", "Bash(git show:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(wc:*)", "Bash(head:*)", "Bash(tail:*)",
])

OUTPUT_CONTRACT = (
    "\n\n---\nReturn the complete report as Markdown in your final response. "
    "Do not modify any files. You are not told which configuration produced this session; "
    "do not speculate about it."
)


def analyzer_spec(ctx: "TrialContext", a: AnalysisSpec, *, cwd: str, out_dir: str) -> dict:
    argv = ["claude", "-p", "<prompt>", "--safe-mode", "--model", ctx.run.model,
            "--permission-mode", "dontAsk", "--allowedTools", ANALYZER_TOOLS,
            "--max-budget-usd", f"{a.budget_usd:.2f}", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose"]
    return {
        "argv": argv, "prompt_arg_index": 2, "prompt_file": f"{out_dir}/prompt.md", "cwd": cwd,
        # Fresh config + home so nothing from the treatment's ~/.claude can load (safe mode also blocks it).
        "env": {"CLAUDE_CONFIG_DIR": "/tmp/analyzer/config", "HOME": "/tmp/analyzer/home",
                "CLAUDE_CODE_SUBAGENT_MODEL": ctx.run.model},
        "timeout_s": 900, "out_dir": out_dir,
    }


def _run_one(ctx: "TrialContext", container: str, a: AnalysisSpec, *, cwd: str,
             local_dir: Path, rel_dir: Path) -> AnalysisResult:
    ex = ctx.ex
    out_dir = f"/analysis/run-{a.name}"
    spec = analyzer_spec(ctx, a, cwd=cwd, out_dir=out_dir)
    ex.exec(container, ["mkdir", "-p", out_dir, "/tmp/analyzer/config", "/tmp/analyzer/home"])
    ex.put_tar(container, out_dir, tar_files({"prompt.md": a.prompt + OUTPUT_CONTRACT,
                                              "spec.json": json.dumps(spec)}))
    ex.exec(container, ["chown", "-R", "agent:agent", "/analysis"], user="root")
    # The wrapper's exit code is informational; timing.json and the transcript are authoritative.
    ex.exec(container, [PYTHON, WRAP, f"{out_dir}/spec.json"], check=False, timeout=1000)
    extract_tar(ex.get_tar(container, out_dir), local_dir)  # lands in local_dir/run-<name>/
    raw = local_dir / f"run-{a.name}"
    transcript = raw / "transcript.jsonl"
    timing_file = raw / "timing.json"
    text = transcript.read_text(encoding="utf-8", errors="replace") if transcript.is_file() else ""
    timing = json.loads(timing_file.read_text()) if timing_file.is_file() else {}
    tr = streamjson.parse_transcript(text)
    m = streamjson.metrics_from_transcript(tr, wall_s=float(timing.get("wall_s", 0.0)))
    report = (tr.result or {}).get("result") or ""
    report_path = local_dir / f"analysis-{a.name}.md"
    report_path.write_text(report, encoding="utf-8")
    ok = bool(report.strip()) and not m.is_error
    return AnalysisResult(name=a.name, ok=ok, report_path=(rel_dir / report_path.name).as_posix(),
                          cost_usd=m.cost_usd, wall_s=m.wall_s, tokens_total=m.tokens_total,
                          error=None if ok else (m.subtype or "empty report"))


def run_trial_analyses(ctx: "TrialContext", container: str, arm: ArmSpec, task: TaskSpec,
                       trial_dir: Path, rel_dir: Path) -> list[AnalysisResult]:
    """Run every trial-scope analysis. /analysis/workspace was snapshotted before grading."""
    ex = ctx.ex
    files: dict[str, bytes | str] = {"task.md": task.prompt}
    for name in ("grade.json", "diff_breakdown.json"):
        p = trial_dir / name
        if p.is_file():
            files[name] = p.read_bytes()
    transcript = trial_dir / "agent" / "transcript.jsonl"
    if transcript.is_file():
        files["transcript.jsonl"] = transcript.read_bytes()
    ex.put_tar(container, "/analysis", tar_files(files))
    results = []
    for a in ctx.trial_analyses:
        try:
            results.append(_run_one(ctx, container, a, cwd="/analysis", local_dir=trial_dir, rel_dir=rel_dir))
        except Exception as e:  # noqa: BLE001 - analyses must never fail a trial
            results.append(AnalysisResult(name=a.name, ok=False, error=f"{type(e).__name__}: {e}"[:500]))
    return results


def run_arm_analyses(ctx: "TrialContext", arm: ArmSpec, specs: list[AnalysisSpec], trials_root: Path,
                     *, image: str) -> dict[str, AnalysisResult]:
    """Run arm-scope analyses over all of an arm's trial artifacts in a fresh plain container."""
    ex = ctx.ex
    files: dict[str, bytes | str] = {}
    arm_root = trials_root / arm.label
    for trial_dir in sorted(p for p in arm_root.glob("*/rep*") if p.is_dir()):
        key = f"trials/{trial_dir.parent.name}-{trial_dir.name}"
        for md in sorted(trial_dir.glob("analysis-*.md")):
            files[f"{key}/{md.name}"] = md.read_bytes()
        reports = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(trial_dir.glob("analysis-*.md"))]
        files[f"{key}/report.md"] = "\n\n".join(reports)
        for name in ("diff_breakdown.json", "grade.json"):
            if (trial_dir / name).is_file():
                files[f"{key}/{name}"] = (trial_dir / name).read_bytes()
        tr = trial_dir / "agent" / "transcript.jsonl"
        if tr.is_file():
            files[f"{key}/transcript.jsonl"] = tr.read_bytes()

    out_local = ctx.run_dir / "arms" / arm.label
    out_local.mkdir(parents=True, exist_ok=True)
    rel = Path("arms") / arm.label
    args = ["--label", f"hai-proof.run={ctx.run.run_id}", "--cpus", "2", "--memory", "4g"]
    net = ctx.arm_networks.get(arm.label)
    if net:
        proxy = ctx.arm_proxies[arm.label]
        args += ["--network", net, "-e", f"HTTPS_PROXY={proxy}", "-e", f"https_proxy={proxy}"]
    container = ex.run_detached(args + [image, "sleep", "infinity"], secret_env=ctx.auth_env)
    results: dict[str, AnalysisResult] = {}
    try:
        ex.exec(container, ["mkdir", "-p", "/analysis"], user="root")
        if files:
            ex.put_tar(container, "/analysis", tar_files(files))
        for a in specs:
            try:
                results[a.name] = _run_one(ctx, container, a, cwd="/analysis", local_dir=out_local, rel_dir=rel)
            except Exception as e:  # noqa: BLE001
                results[a.name] = AnalysisResult(name=a.name, ok=False, error=f"{type(e).__name__}: {e}"[:500])
    finally:
        ex.remove(container)
    return results
