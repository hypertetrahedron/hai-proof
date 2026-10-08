"""summary.json + self-contained report.html (DESIGN §8)."""

from __future__ import annotations

import html
import json
import math
import statistics
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence

from . import stats
from .models import TrialResult, trial_from_json

METRIC_LABELS = {"cost_usd": "Cost", "tokens_total": "Tokens", "wall_s": "Wall time"}
BAND = 0.15

e = html.escape


# --------------------------------------------------------------------------- summary


def _med(vals: Sequence[float]) -> float | None:
    return statistics.median(vals) if vals else None


def _val(t: TrialResult, name: str) -> float:
    m = t.metrics
    if m is None:
        return 0.0
    return float(getattr(m, name))


def _asdict(x: Any) -> Any:
    return asdict(x) if is_dataclass(x) and not isinstance(x, type) else x


def build_summary(run: dict, trials: Sequence[TrialResult], *, n_boot: int = 5000, seed: int = 0) -> dict:
    labels = [a["label"] for a in run.get("arms", [])]
    shape = run.get("shape", "comparative")
    single = shape == "single" or len(labels) < 2
    scored = [t for t in trials if t.scored]

    verdict = None
    ratios: dict[str, Any] = {}
    if not single:
        v = stats.verdict(scored, shape=shape, reps=run.get("reps", 1), n_boot=n_boot, seed=seed)
        verdict = _asdict(v) if v is not None else None
        for metric in stats.METRICS:
            r = stats.ratio_ci(scored, metric, ref=labels[0], cand=labels[1], n_boot=n_boot, seed=seed)
            ratios[metric] = _asdict(r) if r is not None else None

    pass_k = {lab: stats.pass_k(scored, lab) for lab in labels}

    per_task = []
    for task in run.get("tasks", []):
        tid = task["id"]
        arms_out: dict[str, Any] = {}
        for lab in labels:
            ts = [t for t in scored if t.arm == lab and t.task_id == tid and t.metrics]
            if not ts:
                continue
            deps: dict[str, int] = {}
            for t in ts:
                for tool, used in t.dependency_used.items():
                    deps[tool] = deps.get(tool, 0) + (1 if used else 0)
            cats = sorted({c for t in ts for c in t.diff_breakdown})
            arms_out[lab] = {
                "runs": len(ts),
                "passes": sum(1 for t in ts if t.success),
                "median_cost_usd": _med([_val(t, "cost_usd") for t in ts]),
                "median_tokens_total": _med([_val(t, "tokens_total") for t in ts]),
                "median_wall_s": _med([_val(t, "wall_s") for t in ts]),
                "median_turns": _med([_val(t, "turns") for t in ts]),
                "median_tool_calls": _med([_val(t, "tool_calls") for t in ts]),
                "subagent_calls_total": int(sum(_val(t, "subagent_calls") for t in ts)),
                "skills_fired": sorted({s for t in ts for s in t.metrics.skills_fired}),
                "dependency_used": {k: f"{v}/{len(ts)} runs" for k, v in sorted(deps.items())},
                "diff_breakdown_median_lines": {
                    c: _med([t.diff_breakdown.get(c, {}).get("lines", 0) for t in ts]) for c in cats
                },
            }
        ratio = None
        if ratios:
            ratio = {m: (r["per_task"].get(tid) if r else None) for m, r in ratios.items()}
            if all(v is None for v in ratio.values()):
                ratio = None
        per_task.append(
            {
                "task_id": tid,
                "kind": task.get("kind"),
                "level": task.get("level"),
                "origin": task.get("origin"),
                "arms": arms_out,
                "ratio": ratio,
            }
        )

    probe_trials = [t for t in trials if t.rep == -2 and t.status == "ok" and t.metrics]
    probe: dict[str, Any] | None = None
    if probe_trials:
        probe = {}
        for lab in labels:
            ts = [t for t in probe_trials if t.arm == lab]
            if ts:
                probe[lab] = {
                    "runs": len(ts),
                    "median_first_request_input_tokens": _med([t.metrics.first_request_input_tokens for t in ts]),
                    "median_cost_usd": _med([t.metrics.cost_usd for t in ts]),
                }

    excluded = [
        {
            "arm": t.arm,
            "task_id": t.task_id,
            "rep": t.rep,
            "status": t.status,
            "error": t.error,
            "isolation_problems": list(t.isolation_problems),
            "leakage_flags": list(t.leakage_flags),
            "rate_limited": t.rate_limited,
        }
        for t in trials
        if t.status != "ok" and (t.rep >= 0 or t.rep == -2)
    ]

    analysis_cost: dict[str, Any] = {}
    trial_analyses = []
    for t in trials:
        for a in t.analyses:
            c = analysis_cost.setdefault(t.arm, {"cost_usd": 0.0, "sessions": 0})
            c["cost_usd"] += a.cost_usd
            c["sessions"] += 1
            trial_analyses.append(
                {"arm": t.arm, "task_id": t.task_id, "rep": t.rep, "name": a.name, "ok": a.ok,
                 "report_path": a.report_path, "error": a.error}
            )

    trials_table = [
        {
            "arm": t.arm, "task": t.task_id, "rep": t.rep, "success": t.success,
            "wall_s": _val(t, "wall_s"), "cost_usd": _val(t, "cost_usd"),
            "tokens_total": int(_val(t, "tokens_total")), "turns": int(_val(t, "turns")),
            "status": t.status, "artifacts_dir": t.artifacts_dir,
        }
        for t in trials
        if t.rep >= 0
    ]

    first_init: dict[str, Any] = {}
    for lab in labels:
        for t in scored:
            if t.arm == lab and t.init_snapshot:
                first_init[lab] = t.init_snapshot
                break

    return {
        "schema": 1,
        "run": run,
        "verdict": verdict,
        "ratios": ratios,
        "pass_k": pass_k,
        "per_task": per_task,
        "probe": probe,
        "excluded": excluded,
        "analysis_cost": analysis_cost,
        "trials_table": trials_table,
        # additive extras
        "warmup_trials": sum(1 for t in trials if t.rep == -1),
        "trial_analyses": trial_analyses,
        "init_snapshots": first_init,
    }


# --------------------------------------------------------------------------- IO


def write_report(results_dir: Path, run: dict, trials: Sequence[TrialResult]) -> tuple[Path, Path]:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(run, trials)
    texts: dict[str, dict[str, str]] = {}
    for lab, d in (run.get("arm_analyses") or {}).items():
        for name, rel in d.items():
            p = results_dir / rel
            try:
                texts.setdefault(lab, {})[name] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts.setdefault(lab, {})[name] = f"(report not found: {rel})"
    sp = results_dir / "summary.json"
    hp = results_dir / "report.html"
    sp.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    html_summary = dict(summary)
    html_summary["arm_analysis_text"] = texts
    hp.write_text(render_html(html_summary), encoding="utf-8")
    return sp, hp


def load_run(results_dir: Path) -> tuple[dict, list[TrialResult]]:
    results_dir = Path(results_dir)
    run = json.loads((results_dir / "run.json").read_text(encoding="utf-8"))
    latest: dict[tuple, TrialResult] = {}
    tp = results_dir / "trials.jsonl"
    if tp.exists():
        for line in tp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            t = trial_from_json(json.loads(line))
            key = (t.arm, t.task_id, t.rep, t.pair_id)
            latest.pop(key, None)
            latest[key] = t
    return run, list(latest.values())


# --------------------------------------------------------------------------- HTML helpers


def _fx(v: float | None, nd: int = 2) -> str:
    return "—" if v is None else f"×{v:.{nd}f}"


def _num(v: float | None, nd: int = 2) -> str:
    return "—" if v is None else f"{v:,.{nd}f}"


def _usd(v: float | None) -> str:
    return "—" if v is None else f"${v:,.3f}"


def _link(path: str, text: str) -> str:
    return f'<a href="{e(path, quote=True)}">{e(text)}</a>'


def _arm_name(run: dict, lab: str) -> str:
    for a in run.get("arms", []):
        if a["label"] == lab:
            return str(a.get("treatment", lab))
    return lab


CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--surface:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;
--line:#e3e2dd;--series:#2a78d6;--band:rgba(42,120,214,.10);--ref:#52514e;
--good:#0b6b3a;--bad:#a8261b;--warn:#8a5a00;--hl:rgba(237,161,0,.22)}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#1a1a19;--surface:#222221;
--ink:#ffffff;--ink2:#c3c2b7;--muted:#8d8c84;--line:#3a3a38;--series:#3987e5;--band:rgba(57,135,229,.16);--ref:#c3c2b7;
--good:#5fd18f;--bad:#ff8a7a;--warn:#f0b84a;--hl:rgba(201,133,0,.30)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--surface:#222221;--ink:#ffffff;--ink2:#c3c2b7;--muted:#8d8c84;
--line:#3a3a38;--series:#3987e5;--band:rgba(57,135,229,.16);--ref:#c3c2b7;--good:#5fd18f;--bad:#ff8a7a;--warn:#f0b84a;--hl:rgba(201,133,0,.30)}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:36px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.stamp{display:inline-block;border:2px solid var(--ink2);padding:2px 10px;font-weight:700;letter-spacing:.04em;font-size:13px}
.note{color:var(--ink2);font-size:13px}.meta{color:var(--ink2);font-size:13px;margin:2px 0}
.verdict{font-size:22px;font-weight:700;margin:20px 0 6px;line-height:1.3}
.badge{font-size:12px;border:1px solid var(--warn);color:var(--warn);padding:1px 8px;border-radius:10px;vertical-align:middle;margin-left:6px}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--surface)}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right;vertical-align:top}
th:first-child,td:first-child,td.l,th.l{text-align:left}th{color:var(--ink2);font-weight:600}
td.hl{background:var(--hl)}.bad{color:var(--bad)}.good{color:var(--good)}
.tablewrap{overflow-x:auto}.panels{display:flex;flex-wrap:wrap;gap:16px}.panels svg{flex:1 1 320px;max-width:100%;height:auto}
svg text{fill:var(--ink2);font:11px system-ui,sans-serif}svg .lbl{fill:var(--ink)}
pre{background:var(--surface);border:1px solid var(--line);padding:10px;overflow-x:auto;white-space:pre-wrap;font-size:12px}
a{color:var(--series)}details{margin:8px 0}summary{cursor:pointer;color:var(--ink2)}
footer{margin-top:40px;color:var(--ink2);font-size:13px;border-top:1px solid var(--line);padding-top:8px}
"""


def _stamp(run: dict) -> str:
    shape = run.get("shape")
    if shape == "single":
        return '<span class="stamp">SINGLE-ARM — NO COMPARATIVE VERDICT</span>'
    if shape == "ab":
        return ('<span class="stamp">A/B COMPARISON</span> <span class="note">Plain Claude Code was not an arm: '
                "this result says nothing about either bundle versus vanilla Claude Code.</span>")
    return '<span class="stamp">COMPARATIVE (treatment vs plain)</span>'


def _success_totals(summary: dict, lab: str) -> str:
    pk = summary["pass_k"].get(lab, {})
    return f"{sum(v['passes'] for v in pk.values())}/{sum(v['runs'] for v in pk.values())}"


def _verdict_html(summary: dict) -> str:
    run = summary["run"]
    labels = [a["label"] for a in run.get("arms", [])]
    if summary["verdict"] is None:
        if run.get("shape") == "single" and labels:
            lab = labels[0]
            return (f'<div class="verdict">Treatment {e(_arm_name(run, lab))}: no verdict (single arm) — '
                    f"success {e(_success_totals(summary, lab))}</div>")
        return '<div class="verdict">No verdict could be computed (insufficient paired data).</div>'
    v = summary["verdict"]
    a, b = labels[0], labels[1]
    parts = [f"success {_success_totals(summary, b)} vs {_success_totals(summary, a)}"]
    for m, short in (("cost_usd", "cost"), ("wall_s", "wall")):
        r = summary["ratios"].get(m)
        if r:
            if r.get("ci_low") is not None and r.get("ci_high") is not None:
                parts.append(f"{short} {_fx(r['gm_ratio'])} [{r['ci_low']:.2f}, {r['ci_high']:.2f}]")
            else:
                parts.append(f"{short} {_fx(r['gm_ratio'])}")
    name = _arm_name(run, b)
    if run.get("shape") == "ab":
        name = f"{name} vs {_arm_name(run, a)}"
    badge = '<span class="badge">INDICATIVE</span>' if v.get("indicative") else ""
    reasons = "".join(f"<li>{e(r)}</li>" for r in v.get("reasons", []))
    return (f'<div class="verdict">Treatment {e(name)}: {e(v["label"])} — {e(", ".join(parts))}{badge}</div>'
            f'<ul class="note">{reasons}</ul>')


def _probe_html(summary: dict) -> str:
    p = summary.get("probe")
    if not p:
        return '<p class="note">No context-tax probe in this run.</p>'
    run = summary["run"]
    rows = "".join(
        f'<tr><td>{e(lab)} ({e(_arm_name(run, lab))})</td><td>{v["runs"]}</td>'
        f'<td>{_num(v["median_first_request_input_tokens"], 0)}</td><td>{_usd(v["median_cost_usd"])}</td></tr>'
        for lab, v in p.items()
    )
    delta = ""
    labs = list(p)
    if len(labs) == 2:
        d = p[labs[1]]["median_first_request_input_tokens"] - p[labs[0]]["median_first_request_input_tokens"]
        delta = (f"<p><b>Fixed context added per session ({e(labs[1])} − {e(labs[0])}): "
                 f"{d:+,.0f} input tokens.</b></p>")
    return (f'{delta}<div class="tablewrap"><table><tr><th>Arm</th><th>Runs</th><th>Median first-request input tokens</th>'
            f"<th>Median cost</th></tr>{rows}</table></div>")


def _forest_svg(summary: dict, metric: str) -> str:
    r = summary["ratios"].get(metric)
    rows: list[tuple[str, float, float | None, float | None, bool]] = []
    for pt in summary["per_task"]:
        v = (pt.get("ratio") or {}).get(metric)
        if v is not None:
            rows.append((pt["task_id"], v, None, None, False))
    if r:
        rows.append(("OVERALL", r["gm_ratio"], r.get("ci_low"), r.get("ci_high"), True))
    if not rows:
        return ""
    logs = [abs(math.log(max(x[1], 1e-6))) for x in rows]
    for x in rows:
        for b in (x[2], x[3]):
            if b:
                logs.append(abs(math.log(b)))
    ext = max(max(logs) * 1.1, math.log(1.5))
    left, right, top, rh = 110, 20, 26, 22
    w = 440
    h = top + rh * len(rows) + 30
    plot_w = w - left - right

    def X(v: float) -> float:
        return left + (math.log(max(v, 1e-6)) + ext) / (2 * ext) * plot_w

    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Forest plot of {e(METRIC_LABELS[metric])} ratios">',
           f'<text class="lbl" x="{left}" y="14" font-weight="600">{e(METRIC_LABELS[metric])} ratio</text>',
           f'<rect x="{X(1 - BAND):.1f}" y="{top - 4}" width="{X(1 + BAND) - X(1 - BAND):.1f}" '
           f'height="{rh * len(rows) + 4}" fill="var(--band)"/>',
           f'<line x1="{X(1):.1f}" x2="{X(1):.1f}" y1="{top - 4}" y2="{top + rh * len(rows)}" '
           'stroke="var(--ref)" stroke-width="1" stroke-dasharray="3 3"/>']
    ticks = [t for t in (0.25, 0.5, 0.67, 1, 1.5, 2, 4) if math.exp(-ext) <= t <= math.exp(ext)]
    ay = top + rh * len(rows) + 4
    out.append(f'<line x1="{left}" x2="{w - right}" y1="{ay}" y2="{ay}" stroke="var(--line)"/>')
    for t in ticks:
        out.append(f'<text x="{X(t):.1f}" y="{ay + 14}" text-anchor="middle">×{t:g}</text>')
    for i, (name, v, lo, hi, overall) in enumerate(rows):
        cy = top + rh * i + rh / 2
        lbl = name if len(name) <= 16 else name[:15] + "…"
        weight = ' font-weight="700"' if overall else ""
        out.append(f'<text class="lbl" x="{left - 8}" y="{cy + 4:.1f}" text-anchor="end"{weight}>{e(lbl)}</text>')
        tip = f"{name}: ×{v:.3f}" + (f" [{lo:.3f}, {hi:.3f}]" if lo and hi else "")
        if lo and hi:
            out.append(f'<line x1="{X(lo):.1f}" x2="{X(hi):.1f}" y1="{cy:.1f}" y2="{cy:.1f}" '
                       'stroke="var(--series)" stroke-width="2"/>')
        if overall:
            x = X(v)
            out.append(f'<path d="M{x - 6:.1f},{cy:.1f} L{x:.1f},{cy - 6:.1f} L{x + 6:.1f},{cy:.1f} '
                       f'L{x:.1f},{cy + 6:.1f} Z" fill="var(--series)" stroke="var(--surface)" stroke-width="2">'
                       f"<title>{e(tip)}</title></path>")
        else:
            out.append(f'<circle cx="{X(v):.1f}" cy="{cy:.1f}" r="4.5" fill="var(--series)" '
                       f'stroke="var(--surface)" stroke-width="2"><title>{e(tip)}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def _per_task_table(summary: dict) -> str:
    run = summary["run"]
    labels = [a["label"] for a in run.get("arms", [])]
    single = not summary["ratios"]
    head = '<tr><th class="l">Task</th>'
    for lab in labels:
        head += f"<th>{e(lab)} pass</th><th>{e(lab)} cost</th><th>{e(lab)} tokens</th><th>{e(lab)} wall s</th>"
    if not single:
        head += "<th>cost ×</th><th>tokens ×</th><th>wall ×</th>"
    head += "</tr>"
    body = ""
    for pt in summary["per_task"]:
        meta = f'({e(str(pt["kind"]))} L{e(str(pt["level"]))}, {e(str(pt["origin"]))})'
        body += f'<tr><td class="l">{e(str(pt["task_id"]))} <span class="note">{meta}</span></td>'
        for lab in labels:
            a = pt["arms"].get(lab)
            if a:
                body += (f'<td>{a["passes"]}/{a["runs"]}</td><td>{_usd(a["median_cost_usd"])}</td>'
                         f'<td>{_num(a["median_tokens_total"], 0)}</td><td>{_num(a["median_wall_s"], 1)}</td>')
            else:
                body += "<td>—</td>" * 4
        if not single:
            rr = pt.get("ratio") or {}
            body += "".join(f"<td>{_fx(rr.get(m))}</td>" for m in stats.METRICS)
        body += "</tr>"
    return f'<div class="tablewrap"><table>{head}{body}</table></div>'


def _disagreements(summary: dict) -> str:
    labels = [a["label"] for a in summary["run"].get("arms", [])]
    if len(labels) < 2:
        return '<p class="note">Single arm: no disagreements to compare.</p>'
    rows = ""
    for pt in summary["per_task"]:
        a, b = pt["arms"].get(labels[0]), pt["arms"].get(labels[1])
        if a and b and a["passes"] != b["passes"]:
            links = []
            for tr in summary["trials_table"]:
                if tr["task"] == pt["task_id"] and tr["artifacts_dir"] and tr["status"] == "ok":
                    links.append(_link(tr["artifacts_dir"], f'{tr["arm"]}/rep{tr["rep"]}'))
            rows += (f'<tr><td class="l">{e(str(pt["task_id"]))}</td><td>{e(labels[0])}: {a["passes"]}/{a["runs"]}</td>'
                     f'<td>{e(labels[1])}: {b["passes"]}/{b["runs"]}</td><td class="l">{" ".join(links)}</td></tr>')
    if not rows:
        return '<p class="note">No task where the arms disagree on success.</p>'
    return ('<div class="tablewrap"><table><tr><th class="l">Task</th><th>Arm A</th><th>Arm B</th>'
            f'<th class="l">Trial artifacts</th></tr>{rows}</table></div>')


def _behavior(summary: dict) -> str:
    labels = [a["label"] for a in summary["run"].get("arms", [])]
    head = '<tr><th class="l">Task</th>'
    for lab in labels:
        head += (f'<th>{e(lab)} turns</th><th>{e(lab)} tool calls</th><th>{e(lab)} subagents</th>'
                 f'<th class="l">{e(lab)} skills / deps</th>')
    body = ""
    for pt in summary["per_task"]:
        body += f'<tr><td class="l">{e(str(pt["task_id"]))}</td>'
        for lab in labels:
            a = pt["arms"].get(lab)
            if not a:
                body += "<td>—</td>" * 3 + "<td></td>"
                continue
            deps = ", ".join(f"{k}: {v}" for k, v in a["dependency_used"].items())
            extra = e(", ".join(a["skills_fired"]) or "no skills")
            if deps:
                extra += f"<br>{e(deps)}"
            body += (f'<td>{_num(a["median_turns"], 1)}</td><td>{_num(a["median_tool_calls"], 1)}</td>'
                     f'<td>{a["subagent_calls_total"]}</td><td class="l">{extra}</td>')
        body += "</tr>"
    return f'<div class="tablewrap"><table>{head}</tr>{body}</table></div>'


def _breakdown(summary: dict) -> str:
    labels = [a["label"] for a in summary["run"].get("arms", [])]
    cats: list[str] = []
    totals: dict[str, dict[str, float]] = {lab: {} for lab in labels}
    for pt in summary["per_task"]:
        for lab, a in pt["arms"].items():
            for c, v in a["diff_breakdown_median_lines"].items():
                if c not in cats:
                    cats.append(c)
                totals[lab][c] = totals[lab].get(c, 0) + (v or 0)
    if not cats:
        return '<p class="note">No diff breakdown recorded.</p>'
    cats.sort(key=lambda c: (c != "product_code", c))
    head = ('<tr><th class="l">Category (sum of per-task median changed lines)</th>'
            + "".join(f"<th>{e(lab)}</th>" for lab in labels) + "</tr>")
    body = ""
    for c in cats:
        vals = [totals[lab].get(c, 0) for lab in labels]
        differ = len(labels) > 1 and c != "product_code" and len(set(vals)) > 1
        cls = ' class="hl"' if differ else ""
        body += f'<tr><td class="l hl">{e(c)}</td>' if differ else f'<tr><td class="l">{e(c)}</td>'
        body += "".join(f"<td{cls}>{v:g}</td>" for v in vals) + "</tr>"
    return (f'<div class="tablewrap"><table>{head}{body}</table></div>'
            '<p class="note">Highlighted: non-code categories where the arms differ.</p>')


def _analyses(summary: dict) -> str:
    run = summary["run"]
    if not run.get("analyses") and not summary.get("trial_analyses"):
        return '<p class="note">No analyses in this run.</p>'
    out = []
    texts = summary.get("arm_analysis_text", {})
    for lab, d in (run.get("arm_analyses") or {}).items():
        for name, rel in d.items():
            out.append(f"<h3>{e(name)} — arm {e(lab)} (arm scope) {_link(rel, 'file')}</h3>")
            out.append(f"<pre>{e(texts.get(lab, {}).get(name, ''))}</pre>")
    ta = summary.get("trial_analyses", [])
    if ta:
        items = ""
        for a in ta:
            who = f'{e(a["arm"])} / {e(a["task_id"])} / rep{a["rep"]}'
            if a["ok"] and a["report_path"]:
                items += f'<li>{who}: {_link(a["report_path"], a["name"])}</li>'
            else:
                items += f'<li>{who}: {e(a["name"])} failed ({e(str(a["error"]))})</li>'
        out.append(f"<h3>Per-trial reports</h3><ul>{items}</ul>")
    return "".join(out)


def _excluded(summary: dict) -> str:
    ex = summary["excluded"]
    wu = summary.get("warmup_trials", 0)
    note = f'<p class="note">{wu} warm-up trial(s) ignored.</p>' if wu else ""
    if not ex:
        return note + '<p class="note">No excluded or discarded trials.</p>'
    rows = "".join(
        f'<tr><td class="l">{e(x["arm"])}</td><td class="l">{e(x["task_id"])}</td><td>{x["rep"]}</td>'
        f'<td class="l">{e(x["status"])}{" (rate limited)" if x["rate_limited"] else ""}</td>'
        f'<td class="l">{e(str(x["error"] or ""))}</td>'
        f'<td class="l">{e("; ".join(x["isolation_problems"] + x["leakage_flags"]))}</td></tr>'
        for x in ex
    )
    return (note + '<div class="tablewrap"><table><tr><th class="l">Arm</th><th class="l">Task</th><th>Rep</th>'
            f'<th class="l">Status</th><th class="l">Error</th><th class="l">Isolation / leakage</th></tr>{rows}</table></div>')


def _isolation(summary: dict) -> str:
    snaps = summary.get("init_snapshots") or {}
    if not snaps:
        return '<p class="note">No init snapshots recorded.</p>'
    run = summary["run"]
    out = ""
    for lab, snap in snaps.items():
        out += (f"<details><summary>Arm {e(lab)} ({e(_arm_name(run, lab))}) init snapshot</summary>"
                f"<pre>{e(json.dumps(snap, indent=2, sort_keys=True))}</pre></details>")
    return out


def _header(summary: dict) -> str:
    run = summary["run"]
    hi = run.get("host_info") or {}
    arms = "".join(
        f'<tr><td class="l">{e(a["label"])}</td><td class="l">{e(str(a.get("treatment")))}</td>'
        f'<td class="l">{e(str(a.get("treatment_hash") or ""))}</td>'
        f'<td class="l">{e(str(a.get("image_digest") or a.get("image") or ""))}</td></tr>'
        for a in run.get("arms", [])
    )
    mem = hi.get("mem_bytes")
    host = str(run.get("host", ""))
    if isinstance(mem, (int, float)):
        host += (f" — {hi.get('ncpu', '?')} CPU, {mem / 2**30:.0f} GiB, {hi.get('arch', '?')}, "
                 f"engine {hi.get('engine_version', '?')}")
    return (f'<h1>hai-proof report — {e(str(run.get("run_id", "")))}</h1><p>{_stamp(run)}</p>'
            f'<p class="meta">Mode {e(str(run.get("mode")))}, {e(str(run.get("reps")))} rep(s). '
            f'Started {e(str(run.get("started_at", "")))}, finished {e(str(run.get("finished_at", "")))}.</p>'
            f'<p class="meta">Host: {e(host)}</p>'
            f'<p class="meta">Model: {e(str(run.get("model")))} (effort {e(str(run.get("effort")))}), '
            f'Claude Code CLI {e(str(run.get("cli_version")))}</p>'
            '<div class="tablewrap"><table><tr><th class="l">Arm</th><th class="l">Treatment</th><th class="l">Hash</th>'
            f'<th class="l">Image</th></tr>{arms}</table></div>')


def render_html(summary: dict) -> str:
    run = summary["run"]
    single = not summary["ratios"]
    parts = [f"<section>{_header(summary)}</section>", f"<section>{_verdict_html(summary)}</section>",
             f"<h2>Context-tax probe</h2>{_probe_html(summary)}"]
    if single:
        parts.append("<h2>Absolute metrics per task</h2>" + _per_task_table(summary))
        for lab, d in summary["pass_k"].items():
            n = sum(1 for v in d.values() if v["all_pass"])
            parts.append(f'<p class="note">Arm {e(lab)}: pass^k on {n}/{len(d)} tasks.</p>')
    else:
        panels = "".join(_forest_svg(summary, m) for m in stats.METRICS)
        parts.append("<h2>Forest plot</h2>"
                     '<p class="note">Geometric-mean ratio (candidate ÷ reference); log scale centred at ×1; '
                     "shaded band is ±15%. Dots are tasks, diamond with whiskers is overall (95% CI).</p>"
                     f'<div class="panels">{panels}</div>')
        parts.append("<h2>Per-task table</h2>" + _per_task_table(summary))
        parts.append("<h2>Success disagreements</h2>" + _disagreements(summary))
    parts += ["<h2>Behavior differences</h2>" + _behavior(summary),
              "<h2>Change breakdown</h2>" + _breakdown(summary),
              "<h2>Analyses</h2>" + _analyses(summary),
              "<h2>Excluded / discarded trials</h2>" + _excluded(summary),
              "<h2>Isolation audit</h2>" + _isolation(summary)]
    ac = summary.get("analysis_cost") or {}
    cost = ", ".join(f"{e(a)}: ${v['cost_usd']:.2f} over {v['sessions']} session(s)" for a, v in ac.items()) or "none"
    parts.append(f"<footer>Analysis cost (excluded from all verdicts and metrics): {cost}.</footer>")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>hai-proof {e(str(run.get('run_id', '')))}</title><style>{CSS}</style></head>"
            f"<body><main>{''.join(parts)}</main></body></html>")
