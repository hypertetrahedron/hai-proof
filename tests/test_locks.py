import json
import os
import socket
import subprocess
import sys
import threading

import pytest

from hai_proof import baselines, locks
from hai_proof.models import AgentMetrics, TaskSpec, TrialResult


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_pid_alive():
    assert locks.pid_alive(os.getpid())
    assert not locks.pid_alive(dead_pid())


def test_live_lock_is_not_taken(tmp_path):
    lock = tmp_path / "x.lock"
    assert locks.try_acquire(lock) is None
    holder = locks.try_acquire(lock)
    assert holder["pid"] == os.getpid()
    locks.release(lock)
    assert not lock.exists()


def test_stale_lock_on_this_machine_is_taken_over(tmp_path):
    lock = tmp_path / "x.lock"
    lock.write_text(json.dumps({"pid": dead_pid(), "host": socket.gethostname(), "since": 0}))
    assert locks.try_acquire(lock) is None
    assert locks.read_holder(lock)["pid"] == os.getpid()
    assert [p.name for p in tmp_path.iterdir()] == ["x.lock"]


def test_lock_from_another_machine_is_never_broken(tmp_path):
    lock = tmp_path / "x.lock"
    lock.write_text(json.dumps({"pid": dead_pid(), "host": "other-machine", "since": 0}))
    assert locks.try_acquire(lock)["host"] == "other-machine"
    with pytest.raises(locks.LockHeld, match="other-machine"):
        with locks.held(lock, timeout_s=0.2, poll_s=0.05):
            pass
    locks.release(lock)  # not ours: left in place
    assert lock.exists()


def test_concurrent_baseline_updates_keep_every_sample(tmp_path):
    d = tmp_path / "t1"
    d.mkdir()
    (d / "prompt.md").write_text("Fix it.")
    t = TaskSpec(id="t1", kind="bug", level=1, path=d, prompt="Fix it.")
    h = t.content_hash()

    def one(i):
        run = {"run_id": f"20261023-0000{i:02d}-aaaa", "started_at": "2026-10-23T00:00:00+00:00", "model": "m",
               "effort": None, "cli_version": "2.1.300", "arms": [{"label": "A", "treatment": "plain"}],
               "tasks": [{"id": "t1", "hash": h}]}
        trials = [TrialResult(run_id=run["run_id"], arm="A", treatment="plain", task_id="t1", rep=r,
                              pair_id=f"t1-{r}", status="ok", acceptance_pass=True, regression_pass=True,
                              metrics=AgentMetrics(cost_usd=1.0, wall_s=10, tokens_input=1, tokens_output=1, turns=1))
                  for r in range(3)]
        baselines.update([t], [(run, trials)])

    threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    doc = json.loads((d / "baseline.json").read_text())
    assert sum(len(e["samples"]) for e in doc["entries"]) == 24
    assert t.content_hash() == h
    assert sorted(p.name for p in d.iterdir()) == ["baseline.json", "prompt.md"]


def test_lock_and_temp_files_stay_out_of_the_task_hash(tmp_path):
    d = tmp_path / "t1"
    d.mkdir()
    (d / "prompt.md").write_text("Fix it.")
    t = TaskSpec(id="t1", kind="bug", level=1, path=d, prompt="Fix it.")
    h = t.content_hash()
    with locks.held(d / locks.TASK_LOCK):
        (d / ".hai-proof.baseline.json.1.tmp").write_text("x")
        assert t.content_hash() == h
