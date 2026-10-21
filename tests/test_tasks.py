import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hai_proof.config import ConfigError
from hai_proof.tasks import _parse, build_task, is_test_path, load_suite, load_task

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


def test_prompt_variants(tmp_path):
    d = _task(tmp_path, 'id="V1"\nkind="bug"\nlevel=1\n', prompt="Full report.")
    (d / "prompts").mkdir()
    (d / "prompts" / "degraded.md").write_text("Shorter report.\n")
    t = load_task(d)
    assert t.prompt_for() == "Full report." and t.prompt_for("degraded") == "Shorter report."
    with pytest.raises(KeyError):
        t.prompt_for("other")
    (d / "prompts" / "empty.md").write_text("  \n")
    with pytest.raises(ConfigError, match="empty"):
        load_task(d)


def test_is_test_path():
    for p in ("tests/a.py", "pkg/tests/data/x.json", "test_x.py", "a/b_test.py", "a/conftest.py"):
        assert is_test_path(p), p
    for p in ("src/a.py", "README.md", "testing.py", "src/tests.py"):
        assert not is_test_path(p), p
    for p in ("pkg/x_test.go", "src/a.test.ts", "web/b.spec.js", "ui/__tests__/c.tsx",
              "core/src/test/java/d/E.java", "app/FooTest.kt", "lib/f_spec.rb"):
        assert is_test_path(p), p
    for p in ("tornado/test/util.py", "pkg/x.go", "src/main/java/d/E.java", "src/testing.ts"):
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


def test_build_task_exclude(tmp_path, upstream):
    up, base, fix = upstream
    d = _src_task(tmp_path, up, base, fix)
    tf = d / "task.toml"
    tf.write_text(tf.read_text() + 'exclude = ["conftest.py", "pkg/*"]\n')
    build_task(d)
    assert (d / "hidden_tests" / "tests" / "test_f.py").is_file()
    assert not (d / "hidden_tests" / "conftest.py").exists()
    assert not (d / "reference.patch").exists()


def test_source_exclude_validation(tmp_path):
    base = "a" * 40
    with pytest.raises(ConfigError, match="requires source.fix"):
        _parse(_task(tmp_path, f'id="X"\nkind="bug"\nlevel=1\n[source]\nurl="u"\nbase="{base}"\nexclude=["a"]\n',
                     name="x", repo=False), check_dirs=False)
    with pytest.raises(ConfigError, match="list of path patterns"):
        _parse(_task(tmp_path, f'id="Y"\nkind="bug"\nlevel=1\n[source]\nurl="u"\nbase="{base}"\nfix="{base}"\n'
                               'exclude="a"\n', name="y", repo=False), check_dirs=False)


def test_acceptance_cmd(tmp_path):
    head = 'kind="bug"\nlevel=1\n'
    t = _parse(_task(tmp_path, f'id="A"\n{head}acceptance=["tests/t.py"]\nacceptance_cmd="python -m unittest tests.t"\n',
                     name="a", repo=False), check_dirs=False)
    assert t.acceptance_cmd == "python -m unittest tests.t"
    with pytest.raises(ConfigError, match="needs 'acceptance'"):
        _parse(_task(tmp_path, f'id="B"\n{head}acceptance_cmd="x"\n', name="b", repo=False), check_dirs=False)
    with pytest.raises(ConfigError, match="only applies to pytest"):
        _parse(_task(tmp_path, f'id="C"\n{head}acceptance=["t.py"]\nacceptance_cmd="x"\nacceptance_args=["-x"]\n',
                     name="c", repo=False), check_dirs=False)
    with pytest.raises(ConfigError, match="non-empty string"):
        _parse(_task(tmp_path, f'id="D"\n{head}acceptance=["t.py"]\nacceptance_cmd=" "\n', name="d", repo=False),
               check_dirs=False)


def test_suites(tmp_path):
    head = 'kind="bug"\nlevel=1\n'
    t = _parse(_task(tmp_path, f'id="A"\n{head}suites=["standard", "smoke"]\n', name="a", repo=False), check_dirs=False)
    assert t.suites == ("standard", "smoke")
    assert _parse(_task(tmp_path, f'id="B"\n{head}', name="b", repo=False), check_dirs=False).suites == ()
    for i, bad in enumerate(['"standard"', '[""]', '["all"]']):
        with pytest.raises(ConfigError, match="suite"):
            _parse(_task(tmp_path, f'id="C{i}"\n{head}suites={bad}\n', name=f"c{i}", repo=False), check_dirs=False)


def test_cost_tier_and_report_order(tmp_path):
    head = 'kind="bug"\nlevel=1\n'
    t = _parse(_task(tmp_path, f'id="A"\n{head}cost_tier="medium"\nreport_order=7\n', name="a", repo=False),
               check_dirs=False)
    assert (t.cost_tier, t.report_order) == ("medium", 7)
    t = _parse(_task(tmp_path, f'id="B"\n{head}', name="b", repo=False), check_dirs=False)
    assert (t.cost_tier, t.report_order) == ("", None)
    for i, bad in enumerate(['cost_tier="cheap"', "report_order=0", "report_order=true", 'report_order="1"']):
        with pytest.raises(ConfigError, match="cost_tier|report_order"):
            _parse(_task(tmp_path, f'id="C{i}"\n{head}{bad}\n', name=f"c{i}", repo=False), check_dirs=False)


def test_content_hash(tmp_path):
    d = _task(tmp_path, 'id="A"\nkind="bug"\nlevel=1\n', hidden=True)
    (d / "repo" / "a.py").write_text("x = 1\n")
    (d / "hidden_tests" / "test_a.py").write_text("def test(): pass\n")
    h = load_task(d).content_hash()
    assert h == load_task(d).content_hash() and len(h) == 12
    # report metadata, baseline.json and caches don't change it
    (d / "task.toml").write_text('id="A"\nkind="bug"\nlevel=1\nsuites=["s"]\ncost_tier="low"\nreport_order=3\n')
    (d / "baseline.json").write_text("{}")
    (d / "hidden_tests" / "__pycache__").mkdir()
    (d / "hidden_tests" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    assert load_task(d).content_hash() == h
    # anything that can change a trial does
    changes = [
        lambda: (d / "hidden_tests" / "test_a.py").write_text("def test(): assert 0\n"),
        lambda: (d / "repo" / "a.py").write_text("x = 2\n"),
        lambda: (d / "prompt.md").write_text("Fix it now."),
        lambda: (d / "task.toml").write_text('id="A"\nkind="bug"\nlevel=1\ntimeout_s=60\n'),
    ]
    for change in changes:
        change()
        assert load_task(d).content_hash() != h
        h = load_task(d).content_hash()


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


def test_load_suite_across_dirs(tmp_path):
    pub, priv = tmp_path / "pub", tmp_path / "priv"
    pub.mkdir(), priv.mkdir()
    _task(pub, 'id="B1"\nkind="bug"\nlevel=1\n', name="b1")
    _task(priv, 'id="ACME-1"\nkind="bug"\nlevel=1\n', name="acme-1")
    assert [t.id for t in load_suite([pub, priv, tmp_path / "missing"])] == ["ACME-1", "B1"]
    _task(priv, 'id="B1"\nkind="bug"\nlevel=1\n', name="b1")
    with pytest.raises(ConfigError, match="duplicate task id 'B1'"):
        load_suite([pub, priv])


def test_task_dockerfile(tmp_path):
    d = _task(tmp_path, 'id="G1"\nkind="bug"\nlevel=1\n')
    plain_hash = load_task(d).content_hash()
    (d / "task.Dockerfile").write_text("RUN apt-get update && apt-get install -y golang-go\n")
    t = load_task(d)
    assert t.dockerfile.startswith("RUN apt-get") and t.content_hash() != plain_hash
    (d / "task.Dockerfile").write_text("FROM golang:1.22\n")
    with pytest.raises(ConfigError, match="FROM or USER"):
        load_task(d)


def test_user_and_ask_tool(tmp_path):
    head = 'kind="feature"\nlevel=2\n'
    t = _parse(_task(tmp_path, f'id="A"\n{head}user="reticent"\nask_tool="on"\n', name="a", repo=False),
               check_dirs=False)
    assert (t.user, t.ask_tool) == ("reticent", "on")
    t2 = _parse(_task(tmp_path, f'id="B"\n{head}', name="b", repo=False), check_dirs=False)
    assert (t2.user, t2.ask_tool) == ("", "")
    for i, bad in enumerate(['user="chatty"', 'ask_tool="yes"']):
        with pytest.raises(ConfigError, match="user|ask_tool"):
            _parse(_task(tmp_path, f'id="C{i}"\n{head}{bad}\n', name=f"c{i}", repo=False), check_dirs=False)


def test_user_setup_not_in_content_hash(tmp_path):
    d = _task(tmp_path, 'id="A"\nkind="feature"\nlevel=2\n', name="a")
    h = load_task(d).content_hash()
    (d / "task.toml").write_text('id="A"\nkind="feature"\nlevel=2\nuser="reticent"\nask_tool="on"\n')
    assert load_task(d).content_hash() == h


def test_check_user_setup(tmp_path):
    from types import SimpleNamespace as NS

    from hai_proof.tasks import check_user_setup

    head = 'kind="feature"\nlevel=2\n'
    a = _parse(_task(tmp_path, f'id="A"\n{head}user="reticent"\nask_tool="on"\n', name="a", repo=False),
               check_dirs=False)
    b = _parse(_task(tmp_path, f'id="B"\n{head}', name="b", repo=False), check_dirs=False)
    ok = NS(label="A", user="reticent", ask_tool="on")
    assert check_user_setup([a, b], [ok]) == []
    assert check_user_setup([b], [NS(label="A", user="conventional", ask_tool="off")]) == []
    with pytest.raises(ConfigError, match="pass --user reticent"):
        check_user_setup([a, b], [ok, NS(label="B", user="conventional", ask_tool="on")])
    w = check_user_setup([a], [NS(label="B", user="uninformative", ask_tool="off")])
    assert len(w) == 2 and "--user uninformative" in w[0] and "--ask-tool off" in w[1] and "declare on" in w[1]
