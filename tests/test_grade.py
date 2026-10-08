import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "image" / "base" / "hai_proof_grade.py"
_s = importlib.util.spec_from_file_location("hai_proof_grade", SRC)
grade = importlib.util.module_from_spec(_s)
_s.loader.exec_module(grade)
grade.PYTHON = sys.executable
REG = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_pass_pass(tmp_path):
    _w(tmp_path / "tests/test_a.py", "def test_a():\n    assert True\n")
    _w(tmp_path / "tests/hidden/test_h.py", "def test_h():\n    assert True\n")
    r = grade.grade({"cwd": str(tmp_path), "acceptance": ["tests/hidden/test_h.py"], "regression": REG,
                     "timeout_s": 120})
    assert r["acceptance_pass"] is True and r["regression_pass"] is True
    assert r["acceptance_rc"] == 0 and r["regression_rc"] == 0
    assert "duration_s" in r and "acceptance_tail" in r and "regression_tail" in r


def test_acceptance_fails_regression_ignores_hidden(tmp_path):
    _w(tmp_path / "tests/test_a.py", "def test_a():\n    assert True\n")
    _w(tmp_path / "tests/hidden/test_h.py", "def test_h():\n    assert False\n")
    r = grade.grade({"cwd": str(tmp_path), "acceptance": ["tests/hidden/test_h.py::test_h"], "regression": REG})
    assert r["acceptance_pass"] is False
    assert r["regression_pass"] is True  # hidden test excluded from regression


def test_regression_fail(tmp_path):
    _w(tmp_path / "tests/test_a.py", "def test_a():\n    assert False\n")
    _w(tmp_path / "tests/hidden/test_h.py", "def test_h():\n    assert True\n")
    r = grade.grade({"cwd": str(tmp_path), "acceptance": ["tests/hidden/test_h.py"], "regression": REG})
    assert r["acceptance_pass"] is True and r["regression_pass"] is False


def test_regression_no_tests_is_null(tmp_path):
    _w(tmp_path / "tests/hidden/test_h.py", "def test_h():\n    assert True\n")
    r = grade.grade({"cwd": str(tmp_path), "acceptance": ["tests/hidden/test_h.py"], "regression": REG})
    assert r["regression_rc"] == 5
    assert r["regression_pass"] is None and "no tests" in r["note"]


def test_empty_acceptance(tmp_path):
    _w(tmp_path / "test_a.py", "def test_a():\n    assert True\n")
    r = grade.grade({"cwd": str(tmp_path), "acceptance": [], "regression": REG})
    assert r["acceptance_pass"] is None and r["regression_pass"] is True


def test_timeout(tmp_path):
    _w(tmp_path / "test_slow.py", "import time\ndef test_s():\n    time.sleep(30)\n")
    r = grade.grade({"cwd": str(tmp_path), "acceptance": ["test_slow.py"], "regression": None, "timeout_s": 2})
    assert r["acceptance_pass"] is False and "timed out" in r["note"]


@pytest.mark.skipif(sys.platform == "win32", reason="needs an executable script with a shebang")
def test_custom_grader(tmp_path):
    script = tmp_path / "g.sh"
    _w(script, '#!/bin/sh\necho noise\necho \'{"acceptance_pass": true, "regression_pass": false}\'\n')
    script.chmod(0o755)
    r = grade.grade({"cwd": str(tmp_path), "custom_grader": str(script), "timeout_s": 30})
    assert r["acceptance_pass"] is True and r["regression_pass"] is False


def test_custom_grader_no_json(tmp_path):
    r = grade.grade({"cwd": str(tmp_path), "custom_grader": str(tmp_path / "missing.sh"), "timeout_s": 5})
    assert r["acceptance_pass"] is False and "note" in r


def test_cli_prints_json(tmp_path):
    _w(tmp_path / "test_a.py", "def test_a():\n    assert True\n")
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"cwd": str(tmp_path), "acceptance": ["test_a.py"], "regression": None}))
    cp = subprocess.run([sys.executable, str(SRC), str(spec)], capture_output=True, text=True)
    assert cp.returncode == 0
    assert isinstance(json.loads(cp.stdout), dict)
