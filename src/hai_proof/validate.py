"""`hai-proof validate-task`: prove a task is well-formed on the execution host (DESIGN §4).

No agent runs and no API spend. For each task, in a fresh offline container built exactly like a trial:
  1. start state: hidden acceptance tests must FAIL (else the task is already solved);
  2. reference.patch applied: acceptance and the pre-existing regression suite must both PASS;
  3. the regression suite should be fast (DESIGN §4.1 asks for under a minute).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import images
from .executor import Executor
from .models import TaskSpec
from .tarutil import tar_files
from .trial import run_grader

SLOW_SUITE_S = 60.0


@dataclass
class TaskValidation:
    task_id: str
    ok: bool = False
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    base: dict = field(default_factory=dict)
    reference: dict = field(default_factory=dict)


def validate_task(ex: Executor, base_image: str, task: TaskSpec, *, cpus: float = 4, memory: str = "8g",
                  label: str = "hai-proof.validate=1") -> TaskValidation:
    v = TaskValidation(task_id=task.id)
    ref = task.path / "reference.patch"
    if not task.acceptance:
        v.problems.append("task.toml has no acceptance tests")
    if not ref.is_file():
        v.problems.append("no reference.patch")
    if v.problems:
        return v

    image = images.build_trial(ex, base_image, task)
    cid = ex.run_detached(["--network", "none", "--label", label, "--cpus", str(cpus), "--memory", memory,
                           image, "sleep", "infinity"])
    try:
        v.base = run_grader(ex, cid, task)
        if v.base.get("acceptance_pass"):
            v.problems.append("hidden acceptance tests already PASS at the start state (nothing to solve)")
        if v.base.get("regression_pass") is False:
            v.warnings.append("pre-existing suite fails at the start state; those failures are visible "
                              "hints to the agent and must be fixed for the trial to count as a success")

        ex.put_tar(cid, "/tp", tar_files({"reference.patch": ref.read_bytes()}))
        ex.exec(cid, ["chown", "-R", "agent:agent", "/tp"], user="root")
        r = ex.exec(cid, ["bash", "-c", "git apply --whitespace=nowarn /tp/reference.patch"],
                    workdir="/work", check=False)
        if r.returncode != 0:
            v.problems.append(f"reference.patch does not apply: {r.stderr.decode(errors='replace')[-500:]}")
            return v

        v.reference = run_grader(ex, cid, task)
        if not v.reference.get("acceptance_pass"):
            v.problems.append("hidden acceptance tests FAIL with reference.patch applied")
        if not v.reference.get("regression_pass"):
            v.problems.append("pre-existing suite FAILS with reference.patch applied")
        dur = float(v.reference.get("duration_s") or 0)
        if dur > SLOW_SUITE_S:
            v.warnings.append(f"grading took {dur:.0f}s (> {SLOW_SUITE_S:.0f}s); every trial pays this")
    finally:
        ex.remove(cid)
    v.ok = not v.problems
    return v


def format_validation(v: TaskValidation) -> str:
    lines = [f"[{'ok' if v.ok else 'FAIL'}] {v.task_id}"]
    if v.base:
        lines.append(f"    start state: acceptance={v.base.get('acceptance_pass')} "
                     f"regression={v.base.get('regression_pass')}")
    if v.reference:
        lines.append(f"    reference:   acceptance={v.reference.get('acceptance_pass')} "
                     f"regression={v.reference.get('regression_pass')} "
                     f"({float(v.reference.get('duration_s') or 0):.1f}s)")
    lines += [f"    problem: {p}" for p in v.problems]
    lines += [f"    warning: {w}" for w in v.warnings]
    if not v.ok:
        tail = (v.reference or v.base).get("acceptance_tail") or ""
        if tail:
            lines.append("    acceptance output (tail):")
            lines += ["      " + t for t in tail.strip().splitlines()[-15:]]
    return "\n".join(lines)
