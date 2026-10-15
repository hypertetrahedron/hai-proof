"""`hai-proof regrade`: grade a finished trial's final patch again in a fresh container (no API spend).

The trial's `session.patch` (its git diff against the start state) is applied to the task in a fresh
offline container built like a trial, and the current grader runs on it. That separates the agent's work
from anything else in the trial container at grading time, e.g. stale bytecode (fixed in the grader on
2026-10-11) or environment leftovers. The task must still be at the version the trial ran (task hash).

With --write, a changed result is appended to trials.jsonl as a new record for the same trial (later
records override earlier ones) and the old/new grades are kept in the trial dir as regrade.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import images
from .executor import Executor
from .models import TaskSpec, TrialResult, to_json
from .tarutil import tar_files
from .trial import CONTAINER_SYSCTLS, baseline_script, run_grader


@dataclass
class Regrade:
    arm: str
    task_id: str
    rep: int
    artifacts_dir: str
    old: dict
    new: dict = field(default_factory=dict)
    problem: str | None = None

    @property
    def old_pass(self) -> bool:
        return bool(self.old.get("acceptance_pass")) and bool(self.old.get("regression_pass"))

    @property
    def new_pass(self) -> bool | None:
        if self.problem or not self.new:
            return None
        return bool(self.new.get("acceptance_pass")) and bool(self.new.get("regression_pass"))

    @property
    def changed(self) -> bool:
        return self.new_pass is not None and self.new_pass != self.old_pass


def grade_patch(ex: Executor, base_image: str, task: TaskSpec, patch: bytes, *, cpus: float = 4,
                memory: str = "8g") -> tuple[dict, str | None]:
    """Apply `patch` to the task's start state in a fresh offline container and grade it."""
    image = images.build_trial(ex, base_image, task)
    cid = ex.run_detached(["--network", "none", "--label", "hai-proof.regrade=1", "--cpus", str(cpus),
                           "--memory", memory, *CONTAINER_SYSCTLS, image, "sleep", "infinity"])
    try:
        ex.exec(cid, ["bash", "-c", baseline_script()], workdir="/work")
        if patch.strip():
            ex.put_tar(cid, "/tp", tar_files({"session.patch": patch}))
            ex.exec(cid, ["chown", "-R", "agent:agent", "/tp"], user="root")
            r = ex.exec(cid, ["bash", "-c", "git apply --whitespace=nowarn /tp/session.patch"],
                        workdir="/work", check=False)
            if r.returncode != 0:
                return {}, f"session.patch does not apply: {r.stderr.decode(errors='replace')[-300:]}"
        return run_grader(ex, cid, task), None
    finally:
        ex.remove(cid)


def select(run: dict, trials: list[TrialResult], tasks: dict[str, TaskSpec], *, failed_only: bool = True,
           only: set[tuple[str, str, int]] | None = None) -> tuple[list[TrialResult], list[str]]:
    """Scored trials to regrade, and notes on the ones skipped (task gone or changed since the run)."""
    hashes = {t["id"]: t.get("hash") for t in run.get("tasks", [])}
    picked, notes = [], []
    for t in trials:
        if t.rep < 0 or t.status != "ok" or not t.artifacts_dir:
            continue
        if only is not None and (t.arm, t.task_id, t.rep) not in only:
            continue
        if failed_only and t.success:
            continue
        task = tasks.get(t.task_id)
        if task is None:
            notes.append(f"{t.arm}/{t.task_id}/rep{t.rep}: task not in the library")
            continue
        h = hashes.get(t.task_id)
        if h and h != task.content_hash():
            notes.append(f"{t.arm}/{t.task_id}/rep{t.rep}: task changed since the run ({h} -> {task.content_hash()})")
            continue
        picked.append(t)
    return picked, notes


def regrade_run(ex: Executor, base_image: str, results_dir: Path, run: dict, trials: list[TrialResult],
                tasks: dict[str, TaskSpec], *, failed_only: bool = True,
                only: set[tuple[str, str, int]] | None = None, write: bool = False,
                cpus: float = 4, memory: str = "8g", log: Callable[[str], None] = print) -> list[Regrade]:
    picked, notes = select(run, trials, tasks, failed_only=failed_only, only=only)
    for n in notes:
        log(f"skip {n}")
    out: list[Regrade] = []
    for t in picked:
        d = Path(results_dir) / t.artifacts_dir
        old = json.loads((d / "grade.json").read_text(encoding="utf-8")) if (d / "grade.json").is_file() else {
            "acceptance_pass": t.acceptance_pass, "regression_pass": t.regression_pass}
        rg = Regrade(t.arm, t.task_id, t.rep, t.artifacts_dir, old)
        patch = d / "session.patch"
        if not patch.is_file():
            rg.problem = "no session.patch"
        else:
            rg.new, rg.problem = grade_patch(ex, base_image, tasks[t.task_id], patch.read_bytes(),
                                             cpus=cpus, memory=memory)
        old_s = "pass" if rg.old_pass else "FAIL"
        new_s = rg.problem or ("pass" if rg.new_pass else "FAIL")
        log(f"{t.arm}/{t.task_id}/rep{t.rep}: was {old_s}, regrade {new_s}" + ("  <-- changed" if rg.changed else ""))
        if write and rg.changed:
            _write(results_dir, t, rg)
        out.append(rg)
    return out


def _write(results_dir: Path, t: TrialResult, rg: Regrade) -> None:
    d = Path(results_dir) / t.artifacts_dir
    (d / "regrade.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                "reason": "session.patch re-graded in a fresh container",
                                                "old": rg.old, "new": rg.new}, indent=1), encoding="utf-8")
    t.acceptance_pass = rg.new.get("acceptance_pass")
    t.regression_pass = rg.new.get("regression_pass")
    with (Path(results_dir) / "trials.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(to_json(t)) + "\n")
