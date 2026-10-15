"""Long-run plain-arm aggregates per task: tasks/<ID>/baseline.json (docs/task-authoring.md).

Every scored plain-arm trial is kept as a small sample, grouped by (model, CLI version, effort,
task hash), and the summary (counts, pass rate, mean/variance/median/range per metric) is
recomputed from the samples on each update. Keeping the samples, not just running sums, means
medians and any later statistic can be computed, and re-importing a run never double counts:
samples are keyed by (run_id, rep).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import TaskSpec, ask_tool_mode

FILE = "baseline.json"
SCHEMA = 1
METRICS = (
    "cost_usd", "tokens_total", "tokens_output", "wall_s", "turns", "tool_calls",
    "first_request_input_tokens",  # fixed context per session: grows with CLI system prompt/tool changes
    "cache_read_share", "cache_misses",  # main cost drivers
    "first_edit_s", "test_runs", "code_runs",  # diagnosis vs verification time
    "diff_files", "diff_lines",  # solution size (git diff of the trial)
)
_AGENT = ("cost_usd", "tokens_total", "tokens_output", "wall_s", "turns", "tool_calls", "first_request_input_tokens")
_SESSION = ("cache_misses", "first_edit_s", "test_runs", "code_runs")


def end_reason(m: Any) -> str:
    """Why the session ended: "timeout", the CLI's non-success subtype ("error_max_turns",
    "error_max_budget_usd", ...), "error:<terminal_reason>", or the terminal reason ("completed")."""
    if m is None:
        return "no_metrics"
    if m.timed_out:
        return "timeout"
    if m.subtype and m.subtype != "success":
        return str(m.subtype)
    if m.is_error:
        return f"error:{m.terminal_reason or '?'}"
    return str(m.terminal_reason or m.subtype or "unknown")


def _session_stats(t: Any, results_dir: Path | None) -> dict:
    """Session stats from the trial's claude_data.json (regenerated with current parsing) or, failing that,
    the copy stored on the trial record at run time."""
    if results_dir is not None and t.artifacts_dir:
        p = Path(results_dir) / t.artifacts_dir / "claude_data.json"
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("stats") or {}
            except (OSError, ValueError):
                pass
    return t.session or {}


def plain_labels(run: dict) -> set[str]:
    # A plain arm with a user stand-in or the ask tool ran differently from a conventional trial: not a
    # baseline sample.
    return {a["label"] for a in run.get("arms", [])
            if a.get("treatment") == "plain" and a.get("user", "conventional") == "conventional"
            and ask_tool_mode(a.get("ask_tool")) == "off"}


def _entry_key(e: dict) -> tuple:
    return (e["model"], e["cli_version"], e["effort"], e["task_hash"])


def samples_from_run(
    run: dict, trials: Sequence[Any], *, legacy_hashes: dict[str, str] | None = None,
    skip: Iterable[tuple[str, str]] = (), results_dir: Path | None = None,
) -> tuple[dict[str, list[tuple[dict, dict]]], list[str]]:
    """Per task id: [(entry key fields, sample)] for the run's plain-arm trials (rep >= 0).

    The task hash comes from run.json. Runs recorded before task hashes existed are skipped unless
    `legacy_hashes` (task id -> hash to assume) is given. `skip` holds (task id, run id) pairs to leave
    out, e.g. runs graded before a task fix.
    """
    plain = plain_labels(run)
    run_id = str(run.get("run_id", ""))
    hashes = {t["id"]: t.get("hash") for t in run.get("tasks", [])}
    skip = set(skip)
    notes: list[str] = []
    out: dict[str, list[tuple[dict, dict]]] = {}
    for t in trials:
        if t.arm not in plain or t.rep < 0 or (t.task_id, run_id) in skip:
            continue
        h, assumed = hashes.get(t.task_id), False
        if not h:
            if legacy_hashes is None or t.task_id not in legacy_hashes:
                notes.append(f"{run_id} {t.task_id}: no task hash recorded, skipped")
                continue
            h, assumed = legacy_hashes[t.task_id], True
        key = {"model": str(run.get("model")), "cli_version": str(run.get("cli_version")),
               "effort": str(run.get("effort") or "default"), "task_hash": h}
        m = t.metrics
        ok = t.status == "ok"
        sample: dict[str, Any] = {
            "run_id": run_id, "rep": t.rep, "date": str(run.get("started_at") or "")[:10],
            "harness": (run.get("harness") or {}).get("code_hash"),
            "status": t.status, "pass": bool(t.success) if ok else None,
            "timed_out": bool(m.timed_out) if m else False, "end_reason": end_reason(m),
        }
        if assumed:
            sample["hash_assumed"] = True
        for name in METRICS:
            sample[name] = None
        if ok and m is not None:
            for name in _AGENT:
                sample[name] = getattr(m, name)
            sample["cache_read_share"] = m.tokens_cache_read / m.tokens_total if m.tokens_total else None
            st = _session_stats(t, results_dir)
            for name in _SESSION:
                v = st.get(name)
                sample[name] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
            if t.diff_breakdown:
                sample["diff_files"] = sum(int(v.get("files", 0)) for v in t.diff_breakdown.values())
                sample["diff_lines"] = sum(int(v.get("lines", 0)) for v in t.diff_breakdown.values())
        out.setdefault(t.task_id, []).append((key, sample))
    return out, sorted(set(notes))


def wilson(passes: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = passes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - hw), min(1.0, c + hw)


def _metric_summary(vals: list[float]) -> dict:
    n = len(vals)
    mean = sum(vals) / n
    var = statistics.variance(vals) if n > 1 else None
    sd = math.sqrt(var) if var is not None else None
    return {"n": n, "mean": mean, "var": var, "sd": sd, "cv": (sd / mean) if sd is not None and mean else None,
            "min": min(vals), "median": statistics.median(vals), "max": max(vals)}


def summarize(samples: Sequence[dict]) -> dict:
    scored = [s for s in samples if s["status"] == "ok"]
    passes = sum(1 for s in scored if s["pass"])
    runs: dict[str, dict] = {}
    for s in samples:
        r = runs.setdefault(s["run_id"], {"run_id": s["run_id"], "date": s["date"], "trials": 0, "passes": 0,
                                          "excluded": 0})
        if s["status"] == "ok":
            r["trials"] += 1
            r["passes"] += 1 if s["pass"] else 0
        else:
            r["excluded"] += 1
    ci = wilson(passes, len(scored))
    ends: dict[str, int] = {}
    for s in scored:
        r = s.get("end_reason") or "unknown"
        ends[r] = ends.get(r, 0) + 1
    metrics = {}
    for name in METRICS:
        vals = [float(s[name]) for s in scored if isinstance(s.get(name), (int, float))]
        if vals:
            metrics[name] = _metric_summary(vals)
    return {
        "trials": len(scored), "passes": passes, "pass_rate": passes / len(scored) if scored else None,
        "pass_rate_wilson95": list(ci) if ci else None,
        "timeouts": sum(1 for s in scored if s["timed_out"]),
        "end_reasons": dict(sorted(ends.items())),
        "harness_versions": sorted({s.get("harness") or "unrecorded" for s in samples}),
        "excluded": len(samples) - len(scored),
        "first_date": min((s["date"] for s in samples), default=None),
        "last_date": max((s["date"] for s in samples), default=None),
        "runs": sorted(runs.values(), key=lambda r: r["run_id"]),
        "metrics": metrics,
    }


def load(task_dir: Path) -> dict:
    p = Path(task_dir) / FILE
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"schema": SCHEMA, "entries": []}


def merge(doc: dict, task: TaskSpec, new: Sequence[tuple[dict, dict]]) -> int:
    """Add new samples and refresh ones already present; recompute summaries. Returns how many were new."""
    entries = {_entry_key(e): e for e in doc.get("entries", [])}
    added = 0
    for key, sample in new:
        k = _entry_key(key)
        e = entries.setdefault(k, {**key, "samples": []})
        same = [i for i, s in enumerate(e["samples"]) if (s["run_id"], s["rep"]) == (sample["run_id"], sample["rep"])]
        if same:  # re-import: refresh the sample (new fields, re-parsed session data), never duplicate it
            e["samples"][same[0]] = sample
            continue
        e["samples"].append(sample)
        added += 1
    for e in entries.values():
        e["samples"].sort(key=lambda s: (s["run_id"], s["rep"]))
        e["summary"] = summarize(e["samples"])
    doc.update({
        "schema": SCHEMA, "task": task.id,
        "about": "Generated by `hai-proof baseline update`: plain-arm (unmodified Claude Code) trials only, "
                 "one entry per model / CLI version / effort / task hash. Do not edit by hand.",
        "current_task_hash": task.content_hash(),
        "entries": [entries[k] for k in sorted(entries)],
    })
    return added


def update(tasks: Sequence[TaskSpec], runs: Iterable[tuple], *, legacy: bool = False,
           skip: Iterable[tuple[str, str]] = ()) -> tuple[dict[str, int], list[str]]:
    """Fold runs into each task's baseline.json. Returns (new samples per task id, notes).

    `runs` yields (run, trials) or (run, trials, results_dir); with a results dir, session stats are read
    from each trial's claude_data.json."""
    by_id = {t.id: t for t in tasks}
    legacy_hashes = {t.id: t.content_hash() for t in tasks} if legacy else None
    pending: dict[str, list[tuple[dict, dict]]] = {}
    notes: list[str] = []
    skip = list(skip)
    for item in runs:
        run, trials = item[0], item[1]
        got, n = samples_from_run(run, trials, legacy_hashes=legacy_hashes, skip=skip,
                                  results_dir=item[2] if len(item) > 2 else None)
        notes += n
        for tid, items in got.items():
            if tid in by_id:
                pending.setdefault(tid, []).extend(items)
            else:
                notes.append(f"{run.get('run_id')} {tid}: task not in the library, skipped")
    added: dict[str, int] = {}
    for tid, items in sorted(pending.items()):
        task = by_id[tid]
        doc = load(task.path)
        before = json.dumps(doc, sort_keys=True)
        n = merge(doc, task, items)
        if json.dumps(doc, sort_keys=True) != before:
            (task.path / FILE).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
        added[tid] = n
    return added, notes


def current_entries(task: TaskSpec) -> list[dict]:
    """Entries recorded against the task as it is now (same task hash)."""
    h = task.content_hash()
    return [e for e in load(task.path).get("entries", []) if e.get("task_hash") == h]
