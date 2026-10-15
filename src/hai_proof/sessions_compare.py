"""Compare Claude Code sessions across trials and runs (`hai-proof sessions`).

Reads each trial's collected ``claude_home/`` (see claudedata.py), so it works for any run made since
session capture was added. For every trial it shows the outcome next to how the agent worked: time to
first edit, exploration before it, edit/test cycles, whether it re-tested after its last edit, time per
phase, and a phase timeline on a common time scale, so long and short runs of the same task can be
read side by side.
"""

from __future__ import annotations

import json
from html import escape as e
from pathlib import Path
from typing import Any, Iterable

from . import claudedata

PHASE_COLORS = {"explore": "var(--explore)", "edit": "var(--edit)", "test": "var(--test)",
                "run": "var(--run)", "delegate": "var(--delegate)", "other": "var(--other)"}


def find_trials(results_dirs: Iterable[Path], task: str | None = None) -> list[Path]:
    out = []
    for rd in results_dirs:
        for tj in sorted(Path(rd).glob("trials/*/*/rep*/trial.json")):
            tdir = tj.parent
            if (tdir / "claude_home").is_dir() and (task is None or tdir.parent.name == task):
                out.append(tdir)
    return out


def trial_row(tdir: Path, *, refresh: bool = False) -> dict[str, Any]:
    trial = json.loads((tdir / "trial.json").read_text(encoding="utf-8"))
    data = claudedata.summarize(tdir / "claude_home")
    if refresh:
        (tdir / "claude_data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        (tdir / "session.html").write_text(
            claudedata.render_session_html(data, f"{trial['run_id']} · {trial['arm']} / {trial['task_id']} / "
                                                 f"rep{trial['rep']}"), encoding="utf-8")
    m = trial.get("metrics") or {}
    main = data["sessions"][0] if data["sessions"] else None
    timeline = []
    if main and main.get("first_ts") is not None:
        t0 = main["first_ts"]
        calls = [c for c in main["tool_calls"] if c.get("start") is not None]
        for i, c in enumerate(calls):
            end = calls[i + 1]["start"] if i + 1 < len(calls) else main["last_ts"]
            phase = "test" if c.get("runs_tests") else "run" if c.get("runs_code") else c.get("phase") or "other"
            timeline.append([round(c["start"] - t0, 1), round((end or c["start"]) - t0, 1), phase,
                             c.get("name"), c.get("summary", "")[:120]])
    return {
        "run_id": trial["run_id"], "arm": trial["arm"], "treatment": trial.get("treatment"),
        "task": trial["task_id"], "rep": trial["rep"], "status": trial.get("status"),
        "success": bool(trial.get("acceptance_pass")) and bool(trial.get("regression_pass")),
        "wall_s": m.get("wall_s"), "cost_usd": m.get("cost_usd"), "turns": m.get("turns"),
        "session": data["stats"], "timeline": timeline,
        "dir": tdir.as_posix(),
    }


def compare(results_dirs: Iterable[Path], *, task: str | None = None, refresh: bool = False) -> list[dict]:
    rows = [trial_row(t, refresh=refresh) for t in find_trials(results_dirs, task)]
    rows.sort(key=lambda r: (r["task"], r["arm"], r["run_id"], r["rep"]))
    return rows


_CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--surface:#fff;--ink:#0b0b0b;--ink2:#52514e;--line:#e3e2dd;
--good:#0b6b3a;--bad:#a8261b;--explore:#b9b7af;--edit:#2a78d6;--test:#1f9d55;--run:#d6762a;--delegate:#8a4fd6;
--other:#e3e2dd}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#1a1a19;--surface:#222221;
--ink:#fff;--ink2:#c3c2b7;--line:#3a3a38;--good:#5fd18f;--bad:#ff8a7a;--explore:#6b6a64;--edit:#3987e5;
--test:#3cbf74;--run:#e5913a;--delegate:#a77ae8;--other:#3a3a38}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--surface:#222221;--ink:#fff;--ink2:#c3c2b7;--line:#3a3a38;
--good:#5fd18f;--bad:#ff8a7a;--explore:#6b6a64;--edit:#3987e5;--test:#3cbf74;--run:#e5913a;--delegate:#a77ae8;
--other:#3a3a38}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1300px;margin:0 auto;padding:24px 16px 64px}h1{font-size:20px}h2{font-size:16px;margin-top:28px}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:var(--surface)}
th,td{border-bottom:1px solid var(--line);padding:3px 6px;text-align:right;vertical-align:middle;white-space:nowrap}
th.l,td.l{text-align:left}th{color:var(--ink2);font-weight:600}.tablewrap{overflow-x:auto}
.good{color:var(--good)}.bad{color:var(--bad)}.note{color:var(--ink2);font-size:12.5px}
.key span{display:inline-block;width:12px;height:12px;margin:0 4px -2px 12px;border-radius:2px}
svg{display:block}
"""


def _usd(v: float | None) -> str:
    return "—" if v is None else f"${v:.2f}"


def _strip(row: dict, scale: float, width: int = 420) -> str:
    rects = []
    for start, end, phase, name, summary in row["timeline"]:
        x = start / scale * width
        w = max(0.8, (end - start) / scale * width)
        rects.append(f'<rect x="{x:.1f}" y="2" width="{w:.1f}" height="14" fill="{PHASE_COLORS.get(phase)}">'
                     f'<title>{e(f"+{start:.0f}s {phase}: {name} {summary}")}</title></rect>')
    return f'<svg width="{width}" height="18" role="img" aria-label="phase timeline">{"".join(rects)}</svg>'


def render_html(rows: list[dict], title: str = "Session comparison") -> str:
    scale = max((r["timeline"][-1][1] for r in rows if r["timeline"]), default=1.0) or 1.0
    body = ""
    for task in sorted({r["task"] for r in rows}):
        trs = ""
        for r in [x for x in rows if x["task"] == task]:
            s = r["session"] or {}
            pt = s.get("phase_time_s") or {}

            def n(v: Any, nd: int = 0) -> str:
                return "—" if v is None else (f"{v:,.{nd}f}" if isinstance(v, float) else str(v))

            ok = '<span class="good">pass</span>' if r["success"] else '<span class="bad">fail</span>'
            link = Path(r["dir"]) / "session.html"
            trs += (f'<tr><td class="l">{e(r["run_id"])}</td><td class="l">{e(r["arm"])}</td><td>{r["rep"]}</td>'
                    f'<td>{ok if r["status"] == "ok" else e(str(r["status"]))}</td>'
                    f'<td>{n((r["wall_s"] or 0) / 60, 1)}</td><td>{_usd(r["cost_usd"])}</td>'
                    f'<td>{n(s.get("tool_calls"))}</td><td>{n(s.get("first_edit_s"))}</td>'
                    f'<td>{n(s.get("explore_before_first_edit"))}</td><td>{n(s.get("edit_calls"))}</td>'
                    f'<td>{n(s.get("test_runs"))}</td><td>{n(s.get("code_runs"))}</td>'
                    f'<td>{n(s.get("edit_test_cycles"))}</td>'
                    f'<td>{"yes" if s.get("tested_after_last_edit") else "no"}</td>'
                    + "".join(f'<td>{n(pt.get(p))}</td>' for p in ("explore", "edit", "test", "run"))
                    + f'<td>{n(s.get("slow_calls"))}</td><td>{n(s.get("longest_call_s"))}</td>'
                    f'<td>{n(s.get("subagents"))}</td><td>{n(s.get("peak_context"))}</td>'
                    f'<td class="l">{_strip(r, scale)}</td>'
                    f'<td class="l"><a href="{e(link.as_uri() if link.is_absolute() else link.as_posix(), quote=True)}">'
                    f'session</a></td></tr>')
        body += (f"<h2>Task {e(task)}</h2><div class=\"tablewrap\"><table><tr><th class=\"l\">Run</th>"
                 "<th class=\"l\">Arm</th><th>Rep</th><th>Result</th><th>Wall (min)</th><th>Cost</th>"
                 "<th>Tool calls</th><th>First edit (s)</th><th>Explore before edit</th><th>Edits</th>"
                 "<th>Test runs</th><th>Code runs</th><th>Edit→test cycles</th><th>Re-tested after last edit</th>"
                 "<th>Explore s</th><th>Edit s</th><th>Test s</th><th>Run s</th><th>Calls &gt;120 s</th>"
                 "<th>Longest call s</th><th>Subagents</th>"
                 f"<th>Peak context</th><th class=\"l\">Timeline (common scale)</th><th></th></tr>{trs}</table></div>")
    key = "".join(f'<span style="background:{c}"></span>{p}' for p, c in PHASE_COLORS.items())
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{e(title)}</title><style>{_CSS}</style></head><body><main><h1>{e(title)}</h1>"
            "<p class=\"note\">Phases come from each tool call; Bash commands are classified by what they do. "
            "Time after a call (including the model thinking about its result) counts towards that call's "
            "phase; an edit that also runs tests or code counts as test/run time. Timelines share one scale "
            f"({scale / 60:.1f} min full width).</p><p class=\"note key\">{key}</p>{body}</main></body></html>")


def write(rows: list[dict], out: Path) -> tuple[Path, Path]:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(rows), encoding="utf-8")
    js = out.with_suffix(".json")
    js.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return out, js
