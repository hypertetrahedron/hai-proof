import json

from hai_proof import regrade
from hai_proof.models import AgentMetrics, TaskSpec, TrialResult
from hai_proof.report import load_run


def task(tmp_path, tid="t1"):
    d = tmp_path / "tasks" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "prompt.md").write_text("Fix it.")
    return TaskSpec(id=tid, kind="bug", level=1, path=d, prompt="Fix it.")


def trial(arm, rep, ok, *, tid="t1", status="ok"):
    return TrialResult(run_id="r", arm=arm, treatment="x", task_id=tid, rep=rep, pair_id=f"{tid}-r{rep}",
                       status=status, metrics=AgentMetrics(cost_usd=1.0), acceptance_pass=ok, regression_pass=ok,
                       artifacts_dir=f"trials/{arm}/{tid}/rep{rep}")


def setup_run(tmp_path, trials, hashes):
    rd = tmp_path / "run"
    rd.mkdir()
    (rd / "run.json").write_text(json.dumps({"run_id": "r", "tasks": [{"id": k, "hash": v} for k, v in hashes.items()]}))
    with (rd / "trials.jsonl").open("w") as fh:
        for t in trials:
            fh.write(json.dumps(__import__("hai_proof.models", fromlist=["to_json"]).to_json(t)) + "\n")
            d = rd / t.artifacts_dir
            d.mkdir(parents=True, exist_ok=True)
            (d / "grade.json").write_text(json.dumps({"acceptance_pass": t.acceptance_pass,
                                                      "regression_pass": t.regression_pass}))
            (d / "session.patch").write_text("diff --git a/x b/x\n")
    return rd


def test_select_failed_only_and_task_changes(tmp_path):
    t1 = task(tmp_path)
    t2 = task(tmp_path, "t2")
    trials = [trial("A", 0, False), trial("B", 0, True), trial("A", -1, False), trial("A", 1, False, status="error"),
              trial("B", 1, False, tid="t2"), trial("A", 2, False, tid="gone")]
    run = {"tasks": [{"id": "t1", "hash": t1.content_hash()}, {"id": "t2", "hash": "oldhash"}]}
    picked, notes = regrade.select(run, trials, {"t1": t1, "t2": t2})
    assert [(t.arm, t.task_id, t.rep) for t in picked] == [("A", "t1", 0)]
    assert any("task changed since the run" in n for n in notes) and any("not in the library" in n for n in notes)
    picked, _ = regrade.select(run, trials, {"t1": t1, "t2": t2}, failed_only=False)
    assert {(t.arm, t.rep) for t in picked} == {("A", 0), ("B", 0)}
    picked, _ = regrade.select(run, trials, {"t1": t1}, failed_only=False, only={("B", "t1", 0)})
    assert [(t.arm, t.rep) for t in picked] == [("B", 0)]


def test_regrade_run_records_changes(tmp_path, monkeypatch):
    t1 = task(tmp_path)
    rd = setup_run(tmp_path, [trial("A", 0, False), trial("B", 0, False)], {"t1": t1.content_hash()})
    outcomes = iter([({"acceptance_pass": True, "regression_pass": True}, None),
                     ({"acceptance_pass": False, "regression_pass": True}, None)])
    monkeypatch.setattr(regrade, "grade_patch", lambda *a, **k: next(outcomes))
    run, trials = load_run(rd)
    logs = []
    res = regrade.regrade_run(None, "base", rd, run, trials, {"t1": t1}, write=True, log=logs.append)
    assert [(r.arm, r.old_pass, r.new_pass, r.changed) for r in res] == [("A", False, True, True), ("B", False, False, False)]
    assert any("<-- changed" in m for m in logs)
    _, trials = load_run(rd)
    by = {t.arm: t for t in trials}
    assert by["A"].success is True and by["B"].success is False  # later record overrides
    rj = json.loads((rd / "trials" / "A" / "t1" / "rep0" / "regrade.json").read_text())
    assert rj["old"]["acceptance_pass"] is False and rj["new"]["acceptance_pass"] is True
    assert not (rd / "trials" / "B" / "t1" / "rep0" / "regrade.json").exists()


def test_regrade_problem_and_dry(tmp_path, monkeypatch):
    t1 = task(tmp_path)
    rd = setup_run(tmp_path, [trial("A", 0, False)], {"t1": t1.content_hash()})
    monkeypatch.setattr(regrade, "grade_patch", lambda *a, **k: ({}, "session.patch does not apply: x"))
    run, trials = load_run(rd)
    (r,) = regrade.regrade_run(None, "base", rd, run, trials, {"t1": t1}, write=True, log=lambda m: None)
    assert r.new_pass is None and not r.changed and r.problem.startswith("session.patch")
    assert len((rd / "trials.jsonl").read_text().splitlines()) == 1  # nothing appended
