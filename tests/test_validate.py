import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_integration import ROOT, FakeDocker, _cp  # noqa: E402

from hai_proof.tasks import load_task  # noqa: E402
from hai_proof.trial import GRADE  # noqa: E402
from hai_proof.validate import format_validation, validate_task  # noqa: E402


class GradingFake(FakeDocker):
    """Grader results in order: start state, then with reference.patch applied."""

    def __init__(self, results):
        super().__init__()
        self.results = list(results)

    def exec(self, container, cmd, **kw):
        if cmd[:2] == ["/usr/local/bin/python3", GRADE]:
            return _cp(json.dumps(self.results.pop(0)) + "\n")
        return super().exec(container, cmd, **kw)


def _task():
    return load_task(ROOT / "examples" / "tasks" / "example-bug")


def test_valid_task():
    fake = GradingFake([{"acceptance_pass": False, "regression_pass": True},
                        {"acceptance_pass": True, "regression_pass": True, "duration_s": 0.5}])
    v = validate_task(fake, "base:1", _task())
    assert v.ok and not v.problems, format_validation(v)
    run = next(c for c in fake.calls if c[0] == "run")[1]
    assert run[:2] == ["--network", "none"]  # validation is offline
    assert any(c[0] == "rm" for c in fake.calls)


def test_already_solved_and_slow_task():
    fake = GradingFake([{"acceptance_pass": True, "regression_pass": True},
                        {"acceptance_pass": True, "regression_pass": True, "duration_s": 95}])
    v = validate_task(fake, "base:1", _task())
    assert not v.ok
    assert any("already PASS" in p for p in v.problems)
    assert any("95s" in w for w in v.warnings)
