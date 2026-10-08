import json
import re

from hai_proof.models import AgentMetrics, AnalysisResult, TrialResult, to_json
from hai_proof.report import build_summary, load_run, render_html, write_report

TASKS = [
    {"id": "t1", "kind": "bug", "level": 1, "origin": "synthetic"},
    {"id": "t2", "kind": "feature", "level": 2, "origin": "injected"},
]


def mk_run(shape="comparative", reps=3, treatment="X", tasks=TASKS):
    if shape == "single":
        arms = [{"label": "B", "treatment": treatment, "treatment_hash": "abc", "image": "i", "image_digest": "d"}]
    else:
        a = "plain" if shape == "comparative" else "Y"
        arms = [
            {"label": "A", "treatment": a, "treatment_hash": "h0", "image": "i", "image_digest": "d0"},
            {"label": "B", "treatment": treatment, "treatment_hash": "h1", "image": "i", "image_digest": "d1"},
        ]
    return {
        "run_id": "r1", "started_at": "2026-10-04", "finished_at": "2026-10-04", "host": "local",
        "host_info": {"ncpu": 8, "mem_bytes": 16 * 2**30, "arch": "x86_64", "engine_version": "27"},
        "shape": shape, "mode": "quick", "reps": reps, "model": "m", "effort": None, "cli_version": "1.0",
        "arms": arms, "tasks": tasks, "analyses": [], "arm_analyses": {},
    }


def mk_trial(arm, task, rep, cost=1.0, wall=10.0, tok=1000, ok=True, status="ok", pair=None, **kw):
    m = AgentMetrics(wall_s=wall, cost_usd=cost, tokens_input=tok, turns=5, tool_calls=7, subagent_calls=1,
                     skills_fired=["s1"], first_request_input_tokens=kw.pop("first", 0))
    return TrialResult(
        run_id="r1", arm=arm, treatment="x", task_id=task, rep=rep, pair_id=pair or f"{task}-{rep}",
        status=status, metrics=m, acceptance_pass=ok, regression_pass=ok,
        diff_breakdown={"product_code": {"files": 1, "lines": 10}, "docs": {"files": 1, "lines": 5 if arm == "B" else 0}},
        init_snapshot={"tools": [arm]}, **kw,
    )


def comparative_trials(reps=3, bcost=2.0):
    out = []
    for t in ("t1", "t2"):
        for r in range(reps):
            jitter = 1 + 0.02 * r
            out.append(mk_trial("A", t, r, cost=1.0 * jitter, wall=10 * jitter, tok=1000))
            out.append(mk_trial("B", t, r, cost=bcost * jitter, wall=14 * jitter, tok=1500))
    return out


def test_comparative_summary_structure():
    run = mk_run()
    trials = comparative_trials()
    trials.append(mk_trial("A", "t1", -1))  # warm-up
    trials.append(mk_trial("A", "t1", -2, first=1000))
    trials.append(mk_trial("A", "t1", -2, first=1200))
    trials.append(mk_trial("B", "t1", -2, first=5000))
    trials.append(mk_trial("B", "t2", 0, status="error", error="boom", pair="px"))
    trials[0].analyses.append(AnalysisResult(name="n", ok=True, report_path="A/t1/rep0/analysis-n.md", cost_usd=0.5))
    s = build_summary(run, trials, n_boot=200)
    for k in ("schema", "run", "verdict", "ratios", "pass_k", "per_task", "probe", "excluded",
              "analysis_cost", "trials_table"):
        assert k in s
    assert s["schema"] == 1
    assert s["verdict"]["label"]
    assert set(s["ratios"]) == {"cost_usd", "tokens_total", "wall_s"}
    assert abs(s["ratios"]["cost_usd"]["gm_ratio"] - 2.0) < 0.05
    assert s["probe"]["A"]["median_first_request_input_tokens"] == 1100
    assert s["probe"]["B"]["runs"] == 1
    assert len(s["excluded"]) == 1 and s["excluded"][0]["error"] == "boom"
    pt = s["per_task"][0]
    assert pt["task_id"] == "t1"
    assert pt["arms"]["A"]["runs"] == 3 and pt["arms"]["A"]["passes"] == 3
    assert abs(pt["arms"]["A"]["median_cost_usd"] - 1.02) < 1e-9
    assert pt["arms"]["B"]["diff_breakdown_median_lines"]["docs"] == 5
    assert pt["arms"]["A"]["skills_fired"] == ["s1"]
    assert pt["ratio"]["cost_usd"] > 1.5
    assert s["analysis_cost"]["A"] == {"cost_usd": 0.5, "sessions": 1}
    assert all(r["rep"] >= 0 for r in s["trials_table"])
    assert s["warmup_trials"] == 1
    json.dumps(s)


def test_single_arm_has_null_verdict():
    run = mk_run("single", reps=2)
    trials = [mk_trial("B", t, r) for t in ("t1", "t2") for r in range(2)]
    s = build_summary(run, trials, n_boot=100)
    assert s["verdict"] is None and s["ratios"] == {}
    assert s["probe"] is None
    assert s["per_task"][0]["ratio"] is None
    html_ = render_html(s)
    assert "SINGLE-ARM — NO COMPARATIVE VERDICT" in html_
    assert "Forest plot" not in html_


def test_ab_stamp():
    run = mk_run("ab")
    s = build_summary(run, comparative_trials(), n_boot=100)
    h = render_html(s)
    assert "A/B COMPARISON" in h and "Plain Claude Code was not an arm" in h
    assert "<svg" in h and "Forest plot" in h


def test_lightning_indicative():
    run = mk_run(reps=1)
    trials = comparative_trials(reps=1, bcost=3.0)
    s = build_summary(run, trials, n_boot=100)
    assert s["verdict"] is not None and s["verdict"]["indicative"] is True
    h = render_html(s)
    assert "INDICATIVE" in h


def test_html_comparative_sections_and_no_external():
    run = mk_run()
    run["analyses"] = ["n"]
    trials = comparative_trials()
    trials[0].analyses.append(AnalysisResult(name="n", ok=True, report_path="A/t1/rep0/analysis-n.md"))
    trials.append(mk_trial("A", "t1", -2, first=1000))
    trials.append(mk_trial("B", "t1", -2, first=5000))
    trials.append(mk_trial("A", "t2", 1, status="discarded", error="rl", pair="pz", rate_limited=True))
    h = render_html(build_summary(run, trials, n_boot=100))
    assert "COMPARATIVE" in h
    for section in ("Context-tax probe", "Forest plot", "Per-task table", "Success disagreements",
                    "Behavior differences", "Change breakdown", "Analyses", "Excluded / discarded",
                    "Isolation audit", "excluded from all verdicts"):
        assert section in h
    assert "+4,000 input tokens" in h
    assert "<details>" in h
    assert not re.search(r"(src|href)=[\"']https?://", h)
    assert "http://" not in h and "https://" not in h
    assert "analysis-n.md" in h


def test_malicious_treatment_escaped():
    run = mk_run(treatment="<script>alert(1)</script>")
    h = render_html(build_summary(run, comparative_trials(), n_boot=100))
    assert "<script>" not in h
    assert "&lt;script&gt;" in h


def test_load_run_override_and_write(tmp_path):
    run = mk_run()
    (tmp_path / "run.json").write_text(json.dumps(run))
    a = mk_trial("A", "t1", 0, cost=1.0)
    a_bad = mk_trial("A", "t1", 0, cost=1.0, status="error", error="x")
    b = mk_trial("B", "t1", 0, cost=2.0)
    lines = [json.dumps(to_json(t)) for t in (a_bad, b, a)] + [""]
    (tmp_path / "trials.jsonl").write_text("\n".join(lines))
    run2, trials = load_run(tmp_path)
    assert run2["run_id"] == "r1"
    assert len(trials) == 2
    assert next(t for t in trials if t.arm == "A").status == "ok"

    (tmp_path / "A").mkdir()
    run["arm_analyses"] = {"A": {"n": "A/n.md"}}
    run["analyses"] = ["n"]
    (tmp_path / "A" / "n.md").write_text("# report <b>x</b>")
    sp, hp = write_report(tmp_path, run, trials)
    assert sp.exists() and hp.exists()
    assert json.loads(sp.read_text())["schema"] == 1
    page = hp.read_text(encoding="utf-8")
    assert "&lt;b&gt;x&lt;/b&gt;" in page
