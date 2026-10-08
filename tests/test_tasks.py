import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hai_proof.config import ConfigError
from hai_proof.tasks import build_task, is_test_path, load_suite, load_task

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "tasks" / "example-bug"
SHA = "a" * 40


def _task(tmp_path, toml, name="t", prompt="Fix it.", repo=True, hidden=False):
    d = tmp_path / name
    d.mkdir()
    (d / "task.toml").write_text(toml)
    if prompt is not None:
        (d / "prompt.md").write_text(prompt)
    if repo:
        (d / "repo").mkdir()
    if hidden:
        (d / "hidden_tests").mkdir()
    return d


# ---------------------------------------------------------------- loading


def test_example_task_loads():
    t = load_task(EXAMPLE)
    assert t.id == "EX1" and t.kind == "bug" and t.level == 1 and t.origin == "synthetic"
    assert t.acceptance == ("tests/hidden/test_example_bug.py",)
    assert t.install.endswith("-e '.[test]'") and t.repo_dir.is_dir()
    assert "hidden" not in t.prompt.lower() and "test" not in t.prompt.lower()


def test_defaults_and_overrides(tmp_path):
    d = _task(tmp_path, 'id="X"\nkind="feature"\nlevel=2\n')
    t = load_task(d)
    assert t.timeout_s == 1800 and t.max_turns == 60 and t.budget_usd == 5.0 and t.acceptance == ()
    d2 = _task(tmp_path, 'id="Y"\nkind="bug"\nlevel=3\nregression="make t"\nacceptance=["a.py"]\n'
                         '[diff_categories]\ntests=["spec/**"]\n', name="t2", hidden=True)
    t2 = load_task(d2)
    assert t2.regression == "make t" and t2.diff_categories == {"tests": ("spec/**",)}


@pytest.mark.parametrize("toml,msg", [
    ('id="X"\nkind="bug"\nlevel=4\n', "level"),
    ('id="X"\nkind="chore"\nlevel=1\n', "kind"),
    ('id="X"\nkind="bug"\nlevel=1\norigin="mine"\n', "origin"),
    ('kind="bug"\nlevel=1\n', "missing required key 'id'"),
    ('id="X"\nkind="bug"\nlevel=1\nnope=1\n', "nope"),
    ('id="X"\nkind="bug"\nlevel=1\nacceptance=["../x"]\n', "acceptance"),
    ('id="X"\nkind="bug"\nlevel=1\n[source]\nurl="u"\nbase="abc"\n', "40-character"),
    ('id="X"\nkind="bug"\nlevel=1\n[source]\nurl="u"\nbase="%s"\nfix="zz"\n' % SHA, "source.fix"),
])
def test_invalid_toml(tmp_path, toml, msg):
    with pytest.raises(ConfigError, match=msg):
        load_task(_task(tmp_path, toml))


def test_missing_pieces(tmp_path):
    with pytest.raises(ConfigError, match="prompt.md"):
        load_task(_task(tmp_path, 'id="X"\nkind="bug"\nlevel=1\n', prompt=None))
    with pytest.raises(ConfigError, match="empty"):
        load_task(_task(tmp_path, 'id="X"\nkind="bug"\nlevel=1\n', name="b", prompt="  \n"))
    with pytest.raises(ConfigError, match="repo/"):
        load_task(_task(tmp_path, 'id="X"\nkind="bug"\nlevel=1\n', name="c", repo=False))
    with pytest.raises(ConfigError, match="hidden_tests/"):
        load_task(_task(tmp_path, 'id="X"\nkind="bug"\nlevel=1\nacceptance=["a.py"]\n', name="d"))


def test_source_task_loads_unbuilt(tmp_path):
    d = _task(tmp_path, 'id="X"\nkind="bug"\nlevel=1\n[source]\nkind="git"\nurl="u"\nbase="%s"\nfix="%s"\n'
              % (SHA, "b" * 40), repo=False)
    t = load_task(d)
    assert t.source and t.source.base == SHA and t.source.fix == "b" * 40


def test_load_suite(tmp_path):
    for i, lvl in (("B2", 2), ("B1", 1), ("F1", 1)):
        _task(tmp_path, f'id="{i}"\nkind="bug"\nlevel={lvl}\n', name=i.lower())
    assert [t.id for t in load_suite(tmp_path)] == ["B1", "B2", "F1"]
    assert [t.id for t in load_suite(tmp_path, ["F1", "B1"])] == ["B1", "F1"]
    with pytest.raises(ConfigError, match="ZZ"):
        load_suite(tmp_path, ["B1", "ZZ"])
    with pytest.raises(ConfigError, match="not found"):
        load_suite(tmp_path / "none")


def test_is_test_path():
    for p in ("tests/a.py", "pkg/tests/data/x.json", "test_x.py", "a/b_test.py", "a/conftest.py"):
        assert is_test_path(p), p
    for p in ("src/a.py", "README.md", "testing.py", "src/tests.py"):
        assert not is_test_path(p), p


# ---------------------------------------------------------------- build_task


def _run(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def upstream(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    up = tmp_path / "upstream"
    (up / "pkg").mkdir(parents=True)
    (up / "tests").mkdir()
    _run(up, "init", "-q")
    (up / "pkg" / "__init__.py").write_text("def f():\n    return 1\n")
    (up / "tests" / "test_f.py").write_text("from pkg import f\n\ndef test_f():\n    assert f() == 1\n")
    (up / "README.md").write_text("hi\n")
    _run(up, "add", "-A")
    _run(up, "commit", "-qm", "base")
    base = _run(up, "rev-parse", "HEAD")
    (up / "pkg" / "__init__.py").write_text("def f():\n    return 2\n")
    (up / "tests" / "test_f.py").write_text("from pkg import f\n\ndef test_f():\n    assert f() == 2\n")
    (up / "conftest.py").write_text("# new\n")
    _run(up, "add", "-A")
    _run(up, "commit", "-qm", "fix")
    return up, base, _run(up, "rev-parse", "HEAD")


def _src_task(tmp_path, url, base, fix):
    fixline = f'fix = "{fix}"\n' if fix else ""
    return _task(tmp_path, f'id="S1"\nkind="bug"\nlevel=1\norigin="upstream-fix"\n'
                           f'[source]\nkind="git"\nurl="{Path(url).as_posix()}"\nbase="{base}"\n{fixline}',
                 name="s1", repo=False)


def test_build_task(tmp_path, upstream, capsys):
    up, base, fix = upstream
    d = _src_task(tmp_path, up, base, fix)
    build_task(d)
    assert (d / "repo" / "pkg" / "__init__.py").read_text().endswith("return 1\n")
    assert not (d / "repo" / ".git").exists()
    assert (d / "hidden_tests" / "tests" / "test_f.py").read_text().endswith("== 2\n")
    assert (d / "hidden_tests" / "conftest.py").is_file()
    patch = (d / "reference.patch").read_text()
    assert "pkg/__init__.py" in patch and "test_f" not in patch
    lock = json.loads((d / "source.lock.json").read_text())
    assert lock["base"] == base and lock["fix"] == fix and lock["url"] and lock["built"]
    out = capsys.readouterr().out
    assert "tests/test_f.py" in out and "acceptance" in out
    work = tmp_path / "work"
    shutil.copytree(d / "repo", work)
    _run(work, "init", "-q")
    _run(work, "apply", str(d / "reference.patch"))
    assert (work / "pkg" / "__init__.py").read_text().endswith("return 2\n")


def test_build_task_refuses_overwrite_then_force(tmp_path, upstream):
    up, base, fix = upstream
    d = _src_task(tmp_path, up, base, fix)
    build_task(d)
    with pytest.raises(ConfigError, match="already exists"):
        build_task(d)
    (d / "repo" / "junk.txt").write_text("x")
    build_task(d, force=True)
    assert not (d / "repo" / "junk.txt").exists()


def test_build_task_without_fix_or_source(tmp_path, upstream):
    up, base, _ = upstream
    d = _src_task(tmp_path, up, base, None)
    build_task(d)
    assert (d / "repo" / "README.md").is_file()
    assert not (d / "hidden_tests").exists() and not (d / "reference.patch").exists()
    assert json.loads((d / "source.lock.json").read_text())["fix"] is None
    with pytest.raises(ConfigError, match="requires a \\[source\\]"):
        build_task(_task(tmp_path, 'id="N"\nkind="bug"\nlevel=1\n', name="n"))


def test_build_task_bad_url(tmp_path):
    d = _src_task(tmp_path, tmp_path / "nonexistent", SHA, None)
    with pytest.raises(ConfigError, match="git"):
        build_task(d)


# ---------------------------------------------------------------- shipped example


def _pytest(cwd, *args):
    env = dict(os.environ, PYTHONPATH="src", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=cwd, env=env, capture_output=True, text=True)


def test_example_reference_patch_fixes_hidden_tests(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(EXAMPLE / "repo", work)
    shutil.copytree(EXAMPLE / "hidden_tests", work, dirs_exist_ok=True)
    hidden = "tests/hidden/test_example_bug.py"

    assert _pytest(work, "tests/test_basic.py").returncode == 0
    before = _pytest(work, hidden)
    assert before.returncode != 0, before.stdout

    _run(work, "init", "-q")
    _run(work, "apply", str((EXAMPLE / "reference.patch").resolve()))
    after = _pytest(work, hidden)
    assert after.returncode == 0, after.stdout
    assert _pytest(work, "tests/test_basic.py").returncode == 0


def test_build_task_applies_inject_patch(tmp_path, upstream):
    """Injected bug: an author-written patch on top of `base`, applied inside the clone."""
    up, base, _ = upstream
    d = _src_task(tmp_path, up, base, None)
    (d / "inject.patch").write_text(
        "diff --git a/pkg/__init__.py b/pkg/__init__.py\n"
        "--- a/pkg/__init__.py\n+++ b/pkg/__init__.py\n"
        "@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 0\n", encoding="utf-8", newline="\n")
    build_task(d)
    assert (d / "repo" / "pkg" / "__init__.py").read_text().endswith("return 0\n")
    assert not (d / "repo" / ".git").exists()


def test_load_suite_ids_ignores_other_broken_tasks(tmp_path):
    good = _task(tmp_path, 'id="G1"\nkind="bug"\nlevel=1\n', name="g1")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "task.toml").write_text('id="X1"\nkind="bug"\nlevel=1\n')  # no prompt.md yet
    assert [t.id for t in load_suite(good.parent, ["G1"])] == ["G1"]
    with pytest.raises(ConfigError, match="prompt.md"):
        load_suite(good.parent)
