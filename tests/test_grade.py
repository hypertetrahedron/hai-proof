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


def test_acceptance_args(tmp_path):
    _w(tmp_path / "tests/hidden/test_h.py",
       "def test_h(request):\n    assert request.config.getoption('markexpr') == 'not slow'\n")
    spec = {"cwd": str(tmp_path), "acceptance": ["tests/hidden/test_h.py"], "regression": None}
    assert grade.grade(spec)["acceptance_pass"] is False
    assert grade.grade({**spec, "acceptance_args": ["-m", "not slow"]})["acceptance_pass"] is True


def test_acceptance_cmd_replaces_pytest(tmp_path):
    _w(tmp_path / "tests/test_h.py",
       "import unittest\n\nclass T(unittest.TestCase):\n    def test_h(self):\n        self.assertTrue(OK)\n")
    _w(tmp_path / "tests/__init__.py", "")
    cmd = f'"{sys.executable}" -m unittest tests.test_h'
    spec = {"cwd": str(tmp_path), "acceptance": ["tests/test_h.py"], "acceptance_cmd": cmd, "regression": None}
    r = grade.grade(spec)
    assert r["acceptance_pass"] is False and "NameError" in r["acceptance_tail"]
    _w(tmp_path / "tests/test_h.py",
       "import unittest\nOK = True\n\nclass T(unittest.TestCase):\n    def test_h(self):\n        self.assertTrue(OK)\n")
    r = grade.grade(spec)
    assert r["acceptance_pass"] is True and r["acceptance_rc"] == 0 and "Ran 1 test" in r["acceptance_tail"]


def test_non_pytest_regression_gets_no_ignore_flags(tmp_path):
    _w(tmp_path / "tests/hidden/test_h.py", "def test_h():\n    assert True\n")
    reg = f'"{sys.executable}" -c "import sys; sys.exit(len(sys.argv) > 1)"'
    r = grade.grade({"cwd": str(tmp_path), "acceptance": ["tests/hidden/test_h.py"], "regression": reg})
    assert r["regression_pass"] is True


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


def test_stale_bytecode_is_not_graded(tmp_path):
    """A same-size fix written in the same second as a compile leaves a .pyc CPython still trusts."""
    import os
    import subprocess

    mod = tmp_path / "m.py"
    _w(mod, "def f(b, d):\n    return b - d\n")
    st = os.stat(mod)
    subprocess.run([sys.executable, "-c", "import m"], cwd=tmp_path, check=True)  # caches the buggy version
    assert list((tmp_path / "__pycache__").glob("m.*.pyc"))
    _w(mod, "def f(b, d):\n    return b + d\n")
    os.utime(mod, ns=(st.st_atime_ns, st.st_mtime_ns))
    stale = subprocess.run([sys.executable, "-c", "import m; print(m.f(0, 1))"], cwd=tmp_path,
                           capture_output=True, text=True).stdout.strip()
    assert stale == "-1"  # the trap: plain import still runs the old bytecode
    _w(tmp_path / "tests/hidden/test_h.py", "import m\n\ndef test_h():\n    assert m.f(0, 1) == 1\n")
    r = grade.grade({"cwd": str(tmp_path), "acceptance": ["tests/hidden/test_h.py"], "regression": None,
                     "acceptance_args": ["--rootdir", str(tmp_path), "-p", "no:cacheprovider"]})
    assert r["acceptance_pass"] is True, r["acceptance_tail"]
