import json

import pytest

from hai_proof import baselines
from hai_proof.models import AgentMetrics, TaskSpec, TrialResult


def task(tmp_path, tid="t1"):
    d = tmp_path / tid
    d.mkdir(exist_ok=True)
    (d / "prompt.md").write_text("Fix it.")
    return TaskSpec(id=tid, kind="bug", level=1, path=d, prompt="Fix it.")


def run(run_id="20261011-000000-aaaa", hashes=None, model="m1", cli="2.1.296", treatment_a="plain"):
    return {"run_id": run_id, "started_at": "2026-10-11T00:00:00+00:00", "model": model, "effort": None,
            "cli_version": cli,
            "arms": [{"label": "A", "treatment": treatment_a}, {"label": "B", "treatment": "X"}],
            "tasks": [{"id": t, "hash": h} for t, h in (hashes or {}).items()]}


def trial(arm, tid, rep, ok=True, cost=1.0, status="ok"):
    return TrialResult(run_id="r", arm=arm, treatment="x", task_id=tid, rep=rep, pair_id=f"{tid}-{rep}",
                       status=status, metrics=AgentMetrics(cost_usd=cost, wall_s=10 * cost, tokens_input=100,
                                                           tokens_output=int(50 * cost), turns=3),
                       acceptance_pass=ok, regression_pass=ok)


def test_update_plain_only_dedup_and_stats(tmp_path):
    t = task(tmp_path)
    h = t.content_hash()
    trials = [trial("A", "t1", 0, cost=1.0), trial("A", "t1", 1, ok=False, cost=3.0), trial("A", "t1", 2, cost=2.0),
              trial("A", "t1", -2, cost=0.01), trial("A", "t1", 3, status="error"), trial("B", "t1", 0, cost=9.0)]
    added, notes = baselines.update([t], [(run(hashes={"t1": h}), trials)])
    assert added == {"t1": 4} and notes == []
    doc = json.loads((t.path / "baseline.json").read_text())
    assert doc["task"] == "t1" and doc["current_task_hash"] == h and len(doc["entries"]) == 1
    e = doc["entries"][0]
    assert (e["model"], e["cli_version"], e["effort"], e["task_hash"]) == ("m1", "2.1.296", "default", h)
    sm = e["summary"]
    assert (sm["trials"], sm["passes"], sm["excluded"]) == (3, 2, 1)
    c = sm["metrics"]["cost_usd"]
    assert c["mean"] == pytest.approx(2.0) and c["var"] == pytest.approx(1.0) and c["median"] == 2.0
    assert (c["min"], c["max"]) == (1.0, 3.0) and c["cv"] == pytest.approx(0.5)
    assert sm["metrics"]["tokens_total"]["mean"] == pytest.approx(200)
    lo, hi = sm["pass_rate_wilson95"]
    assert lo < 2 / 3 < hi
    assert sm["runs"] == [{"run_id": "20261011-000000-aaaa", "date": "2026-10-11", "trials": 3, "passes": 2,
                           "excluded": 1}]
    # folding the same run again adds nothing
    added, _ = baselines.update([t], [(run(hashes={"t1": h}), trials)])
    assert added == {"t1": 0}
    # another CLI version gets its own entry; a second run on the same key accumulates
    baselines.update([t], [(run("r2", hashes={"t1": h}, cli="2.1.300"), [trial("A", "t1", 0)]),
                           (run("r3", hashes={"t1": h}), [trial("A", "t1", 0, cost=4.0)])])
    doc = baselines.load(t.path)
    assert [(e["cli_version"], e["summary"]["trials"]) for e in doc["entries"]] == [("2.1.296", 4), ("2.1.300", 1)]
    assert doc["entries"][0]["summary"]["metrics"]["cost_usd"]["mean"] == pytest.approx(2.5)
    assert len(baselines.current_entries(t)) == 2


def test_hashless_runs_need_legacy_and_skip(tmp_path):
    t = task(tmp_path)
    r = run()  # no task hashes recorded
    added, notes = baselines.update([t], [(r, [trial("A", "t1", 0)])])
    assert added == {} and "no task hash" in notes[0]
    added, _ = baselines.update([t], [(r, [trial("A", "t1", 0)])], legacy=True, skip=[("t1", r["run_id"])])
    assert added == {}
    added, _ = baselines.update([t], [(r, [trial("A", "t1", 0)])], legacy=True)
    assert added == {"t1": 1}
    e = baselines.load(t.path)["entries"][0]
    assert e["task_hash"] == t.content_hash() and e["samples"][0]["hash_assumed"] is True


def test_no_plain_arm_and_unknown_task(tmp_path):
    t = task(tmp_path)
    added, _ = baselines.update([t], [(run(hashes={"t1": "h"}, treatment_a="Y"), [trial("A", "t1", 0)])])
    assert added == {}
    added, notes = baselines.update([t], [(run(hashes={"zz": "h"}), [trial("A", "zz", 0)])])
    assert added == {} and "not in the library" in notes[0]


def test_extended_sample_fields_and_refresh(tmp_path):
    t = task(tmp_path)
    r = run(hashes={"t1": t.content_hash()})
    r["harness"] = {"code_hash": "abc123"}
    tr = trial("A", "t1", 0)
    tr.metrics.tokens_cache_read = 300
    tr.metrics.first_request_input_tokens = 17_000
    tr.metrics.terminal_reason, tr.metrics.subtype = "completed", "success"
    tr.diff_breakdown = {"product_code": {"files": 2, "lines": 40}, "tests": {"files": 1, "lines": 10}}
    tr.artifacts_dir = "A/t1/rep0"
    late = trial("A", "t1", 1, ok=False)
    late.metrics.subtype = "error_max_turns"
    timed = trial("A", "t1", 2, ok=False)
    timed.metrics.timed_out = True
    # session stats come from the trial's claude_data.json when a results dir is given
    d = tmp_path / "res" / "A" / "t1" / "rep0"
    d.mkdir(parents=True)
    (d / "claude_data.json").write_text(json.dumps({"stats": {"cache_misses": 2, "first_edit_s": 30.5,
                                                              "test_runs": 4, "code_runs": 1}}))
    baselines.update([t], [(r, [tr, late, timed], tmp_path / "res")])
    e = baselines.load(t.path)["entries"][0]
    s = e["samples"][0]
    assert s["harness"] == "abc123" and s["end_reason"] == "completed"
    assert s["first_request_input_tokens"] == 17_000
    assert s["cache_read_share"] == pytest.approx(300 / 450)
    assert (s["cache_misses"], s["first_edit_s"], s["test_runs"], s["code_runs"]) == (2, 30.5, 4, 1)
    assert (s["diff_files"], s["diff_lines"]) == (3, 50)
    sm = e["summary"]
    assert sm["end_reasons"] == {"completed": 1, "error_max_turns": 1, "timeout": 1}
    assert sm["harness_versions"] == ["abc123"] and sm["timeouts"] == 1
    assert sm["metrics"]["cache_misses"]["n"] == 1  # only the trial with session data
    # re-importing refreshes samples in place (here: session stats now from the trial record)
    tr.session = {"cache_misses": 5}
    added, _ = baselines.update([t], [(r, [tr, late, timed])])
    assert added == {"t1": 0}
    e = baselines.load(t.path)["entries"][0]
    assert len(e["samples"]) == 3 and e["samples"][0]["cache_misses"] == 5


def test_wilson():
    assert baselines.wilson(0, 0) is None
    lo, hi = baselines.wilson(4, 11)
    assert lo == pytest.approx(0.152, abs=0.002) and hi == pytest.approx(0.646, abs=0.002)
