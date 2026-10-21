"""Load task definitions and build open-repo tasks (DESIGN §4, §4.1)."""

from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from .config import ConfigError
from .models import ASK_TOOL_MODES, USER_MODES, GitSource, TaskSpec

_TOP_KEYS = {
    "id", "kind", "level", "origin", "timeout_s", "budget_usd", "max_turns", "install",
    "acceptance", "acceptance_args", "acceptance_cmd", "regression", "source", "diff_categories",
    "suites", "cost_tier", "report_order", "user", "ask_tool",
}
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")
_KINDS = ("bug", "feature")
COST_TIERS = ("low", "medium", "high")
_ORIGINS = ("synthetic", "upstream-fix", "injected", "authored")
_DEFAULTS = TaskSpec(id="", kind="bug", level=1, path=Path("."), prompt="")


def _read(path: Path) -> dict[str, Any]:
    tf = path / "task.toml"
    if not tf.is_file():
        raise ConfigError(f"task manifest not found: {tf}")
    try:
        with tf.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{tf}: invalid TOML: {e}") from e


def _int(d: dict, key: str, default: int, tf: Path, minimum: int = 1) -> int:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ConfigError(f"{tf}: '{key}' must be an integer >= {minimum}")
    return v


def _parse_source(d: dict, tf: Path) -> GitSource | None:
    s = d.get("source")
    if s is None:
        return None
    if not isinstance(s, dict):
        raise ConfigError(f"{tf}: [source] must be a table")
    bad = sorted(set(s) - {"kind", "url", "base", "fix", "exclude"})
    if bad:
        raise ConfigError(f"{tf}: unknown keys in [source]: {', '.join(bad)}")
    if s.get("kind", "git") != "git":
        raise ConfigError(f"{tf}: source.kind must be 'git'")
    for k in ("url", "base"):
        if not isinstance(s.get(k), str) or not s[k]:
            raise ConfigError(f"{tf}: source.{k} is required")
    for k in ("base", "fix"):
        v = s.get(k)
        if v is not None and not (isinstance(v, str) and _SHA.match(v)):
            raise ConfigError(f"{tf}: source.{k} must be a full 40-character lowercase hex SHA, got {v!r}")
    exclude = s.get("exclude", [])
    if not (isinstance(exclude, list) and all(isinstance(p, str) and p for p in exclude)):
        raise ConfigError(f"{tf}: source.exclude must be a list of path patterns")
    if exclude and not s.get("fix"):
        raise ConfigError(f"{tf}: source.exclude requires source.fix")
    return GitSource(url=s["url"], base=s["base"], fix=s.get("fix"), exclude=tuple(exclude))


def _parse(path: Path, *, check_dirs: bool) -> TaskSpec:
    path = Path(path)
    tf = path / "task.toml"
    d = _read(path)
    unknown = sorted(set(d) - _TOP_KEYS)
    if unknown:
        raise ConfigError(f"{tf}: unknown keys: {', '.join(unknown)}")
    for k in ("id", "kind", "level"):
        if k not in d:
            raise ConfigError(f"{tf}: missing required key '{k}'")
    tid = d["id"]
    if not isinstance(tid, str) or not _SLUG.match(tid):
        raise ConfigError(f"{tf}: id {tid!r} must match [A-Za-z0-9._-]+")
    if d["kind"] not in _KINDS:
        raise ConfigError(f"{tf}: kind must be one of {', '.join(_KINDS)}, got {d['kind']!r}")
    level = d["level"]
    if isinstance(level, bool) or level not in (1, 2, 3):
        raise ConfigError(f"{tf}: level must be 1, 2 or 3, got {level!r}")
    origin = d.get("origin", "synthetic")
    if origin not in _ORIGINS:
        raise ConfigError(f"{tf}: origin must be one of {', '.join(_ORIGINS)}, got {origin!r}")

    budget = d.get("budget_usd", _DEFAULTS.budget_usd)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
        raise ConfigError(f"{tf}: budget_usd must be a number > 0")

    acceptance = d.get("acceptance", [])
    if not isinstance(acceptance, list) or not all(isinstance(a, str) and a for a in acceptance):
        raise ConfigError(f"{tf}: acceptance must be a list of strings")
    acceptance_args = d.get("acceptance_args", [])
    if not isinstance(acceptance_args, list) or not all(isinstance(a, str) and a for a in acceptance_args):
        raise ConfigError(f"{tf}: acceptance_args must be a list of strings")
    acceptance_cmd = d.get("acceptance_cmd", "")
    if not isinstance(acceptance_cmd, str) or ("acceptance_cmd" in d and not acceptance_cmd.strip()):
        raise ConfigError(f"{tf}: acceptance_cmd must be a non-empty string")
    if acceptance_cmd and not acceptance:
        raise ConfigError(f"{tf}: acceptance_cmd needs 'acceptance' (the hidden test files it runs)")
    if acceptance_cmd and acceptance_args:
        raise ConfigError(f"{tf}: acceptance_args only applies to pytest; put them in acceptance_cmd")
    for a in acceptance:
        fp = a.split("::", 1)[0]
        if "\\" in fp or PurePosixPath(fp).is_absolute() or ".." in PurePosixPath(fp).parts:
            raise ConfigError(f"{tf}: acceptance entry '{a}' must be a relative posix path")

    for k in ("install", "regression"):
        if k in d and (not isinstance(d[k], str) or not d[k].strip()):
            raise ConfigError(f"{tf}: '{k}' must be a non-empty string")

    cats_raw = d.get("diff_categories", {})
    if not isinstance(cats_raw, dict) or not all(
        isinstance(v, list) and all(isinstance(x, str) for x in v) for v in cats_raw.values()
    ):
        raise ConfigError(f"{tf}: [diff_categories] must map category names to lists of glob strings")

    suites = d.get("suites", [])
    if not isinstance(suites, list) or not all(isinstance(s, str) and s.strip() for s in suites):
        raise ConfigError(f"{tf}: suites must be a list of non-empty strings")
    if "all" in suites:
        raise ConfigError(f"{tf}: 'all' is reserved and can't be a suite name")

    cost_tier = d.get("cost_tier", "")
    if cost_tier and cost_tier not in COST_TIERS:
        raise ConfigError(f"{tf}: cost_tier must be one of {', '.join(COST_TIERS)}, got {cost_tier!r}")
    report_order = d.get("report_order")
    if report_order is not None and (isinstance(report_order, bool) or not isinstance(report_order, int)
                                     or report_order < 1):
        raise ConfigError(f"{tf}: report_order must be a positive integer, got {report_order!r}")

    user = d.get("user", "")
    if user and user not in USER_MODES:
        raise ConfigError(f"{tf}: user must be one of {', '.join(USER_MODES)}, got {user!r}")
    ask_tool = d.get("ask_tool", "")
    if ask_tool and ask_tool not in ASK_TOOL_MODES:
        raise ConfigError(f"{tf}: ask_tool must be one of {', '.join(ASK_TOOL_MODES)}, got {ask_tool!r}")

    source = _parse_source(d, tf)

    pf = path / "prompt.md"
    if not pf.is_file():
        raise ConfigError(f"{path}: prompt.md is required")
    prompt = pf.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ConfigError(f"{pf}: prompt is empty")

    variants = {}
    for vf in sorted((path / "prompts").glob("*.md")):
        text = vf.read_text(encoding="utf-8").strip()
        if not text:
            raise ConfigError(f"{vf}: prompt is empty")
        variants[vf.stem] = text

    brief = ""
    uf = path / "user.md"
    if uf.is_file():
        brief = uf.read_text(encoding="utf-8").strip()
        if not brief:
            raise ConfigError(f"{uf}: user brief is empty")
        if re.search(r"hidden[ _-]?tests?", brief, re.I):
            raise ConfigError(f"{uf}: the user brief must not mention the hidden tests")

    dockerfile = ""
    dfile = path / "task.Dockerfile"
    if dfile.is_file():
        dockerfile = dfile.read_text(encoding="utf-8").strip()
        if re.search(r"(?im)^\s*(FROM|USER)\b", dockerfile):
            raise ConfigError(f"{dfile}: must not contain FROM or USER (it runs as root inside the trial image build)")

    if check_dirs and source is None:
        if not (path / "repo").is_dir():
            raise ConfigError(f"{path}: repo/ directory is required for tasks without [source]")
        if acceptance and not (path / "hidden_tests").is_dir():
            raise ConfigError(f"{path}: hidden_tests/ directory is required when acceptance is set")

    return TaskSpec(
        id=tid,
        kind=d["kind"],
        level=level,
        path=path,
        prompt=prompt,
        origin=origin,
        timeout_s=_int(d, "timeout_s", _DEFAULTS.timeout_s, tf),
        budget_usd=float(budget),
        max_turns=_int(d, "max_turns", _DEFAULTS.max_turns, tf),
        install=d.get("install", _DEFAULTS.install),
        acceptance=tuple(acceptance),
        acceptance_args=tuple(acceptance_args),
        acceptance_cmd=acceptance_cmd,
        regression=d.get("regression", _DEFAULTS.regression),
        source=source,
        diff_categories={k: tuple(v) for k, v in cats_raw.items()},
        prompt_variants=variants,
        user_brief=brief,
        suites=tuple(suites),
        cost_tier=cost_tier,
        report_order=report_order,
        user=user,
        ask_tool=ask_tool,
        dockerfile=dockerfile,
    )


def check_user_setup(tasks: Sequence[TaskSpec], arms: Sequence[Any]) -> list[str]:
    """Check each arm's user and ask-tool settings against what the tasks declare (`user`, `ask_tool`).

    A task that declares a user mode only means something with someone answering, so running it with the
    conventional user (the default: nobody answers) is refused. Any other difference is deliberate (an
    uninformative control, say) and comes back as a warning line.
    """
    warnings = []
    for arm in arms:
        conv = [t.id for t in tasks if t.user and arm.user == "conventional"]
        if conv:
            want = "/".join(sorted({t.user for t in tasks if t.id in conv}))
            raise ConfigError(f"arm {arm.label}: tasks {', '.join(conv)} need a user in the loop, but nobody answers "
                              f"(--user conventional); pass --user {want} as the tasks declare, "
                              "or another mode on purpose")
        for key, val in (("user", arm.user), ("ask_tool", arm.ask_tool)):
            off = [t.id for t in tasks if getattr(t, key) and getattr(t, key) != val and t.id not in conv]
            if off:
                want = sorted({getattr(t, key) for t in tasks if t.id in off})
                warnings.append(f"arm {arm.label}: --{key.replace('_', '-')} {val}, but "
                                f"{', '.join(off)} declare {'/'.join(want)}")
    return warnings


def load_task(path: Path) -> TaskSpec:
    """Load `<path>/task.toml` + `prompt.md`.

    Tasks with a [source] are validated leniently on disk layout (repo/ and hidden_tests/ are
    produced by `build_task`, so an unbuilt task still loads).
    """
    return _parse(Path(path), check_dirs=True)


def load_suite(tasks_dir: Path | Sequence[Path], ids: list[str] | None = None) -> list[TaskSpec]:
    """Tasks under one directory or several (ids must be unique across them)."""
    dirs = [Path(tasks_dir)] if isinstance(tasks_dir, (str, Path)) else [Path(d) for d in tasks_dir]
    if not dirs or not dirs[0].is_dir():
        raise ConfigError(f"tasks directory not found: {dirs[0] if dirs else '(none)'}")
    tomls = [p for d in dirs if d.is_dir() for p in sorted(d.glob("*/task.toml"))]
    if ids is not None:
        # Fully load only the requested tasks, so one half-written task can't block the others.
        wanted = set(ids)
        tomls = [p for p in tomls if _peek_id(p) in wanted]
    tasks = [load_task(p.parent) for p in tomls]
    seen: dict[str, Path] = {}
    for t in tasks:
        if t.id in seen:
            raise ConfigError(f"duplicate task id '{t.id}' in {seen[t.id]} and {t.path}")
        seen[t.id] = t.path
    if ids is not None:
        unknown = [i for i in ids if i not in seen]
        if unknown:
            raise ConfigError(
                f"unknown task id(s): {', '.join(unknown)} (available: {', '.join(sorted(seen)) or 'none'})"
            )
        tasks = [t for t in tasks if t.id in set(ids)]
    return sorted(tasks, key=lambda t: t.id)


def _peek_id(task_toml: Path) -> str:
    """The task's id without validating the rest of task.toml (falls back to the directory name)."""
    try:
        with task_toml.open("rb") as fh:
            return str(tomllib.load(fh).get("id", task_toml.parent.name))
    except (OSError, tomllib.TOMLDecodeError):
        return task_toml.parent.name


# --------------------------------------------------------------------------- build-task


def is_test_path(p: str) -> bool:
    """Test files by common conventions (posix repo-relative path).

    Python: tests/**, test_*.py, *_test.py, conftest.py. Other languages, for tasks from users' own repos:
    *_test.go, *.test.* / *.spec.* (JS/TS), __tests__/**, src/test/** and *Test.java / *Test.kt (JVM),
    *_spec.rb, *Tests.cs. A bare test/ directory is not a test path (tornado keeps product code under it).
    """
    pp = PurePosixPath(p)
    name, dirs = pp.name, pp.parts[:-1]
    return (
        "tests" in dirs
        or "__tests__" in dirs
        or any(a == "src" and b == "test" for a, b in zip(dirs, dirs[1:]))
        or any(fnmatch.fnmatch(name, pat) for pat in _TEST_NAMES)
    )


_TEST_NAMES = ("test_*.py", "*_test.py", "conftest.py", "*_test.go", "*.test.*", "*.spec.*", "*Test.java",
               "*Test.kt", "*_spec.rb", "*Tests.cs")


def _rm_readonly(func, path, _exc):  # git object files are read-only on Windows
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(p: Path) -> None:
    if not p.is_dir():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=_rm_readonly)
    else:
        shutil.rmtree(p, onerror=_rm_readonly)


def _git(git: str, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    # core.eol=lf: with a `* text=auto` .gitattributes, git would otherwise use the platform eol (CRLF on Windows).
    cmd = [git, "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.safecrlf=false", *args]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True)
    if check and r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        raise ConfigError(f"git {' '.join(args[:2])} failed ({r.returncode}): {err}")
    return r


def build_task(task_dir: Path, *, git: str = "git", force: bool = False) -> None:
    """Materialise an open-repo task: repo/ at `base`, plus hidden_tests/ and reference.patch from `fix`."""
    task_dir = Path(task_dir)
    task = _parse(task_dir, check_dirs=False)
    src = task.source
    if src is None:
        raise ConfigError(f"{task_dir}: build-task requires a [source] table in task.toml")

    repo_out = task_dir / "repo"
    hidden_out = task_dir / "hidden_tests"
    patch_out = task_dir / "reference.patch"
    if repo_out.exists() and any(repo_out.iterdir()) and not force:
        raise ConfigError(f"{repo_out} already exists and is not empty; pass force=True (--force) to rebuild")

    with tempfile.TemporaryDirectory(prefix="hai-proof-build-", ignore_cleanup_errors=True) as tmp:
        clone = Path(tmp) / "clone"
        try:
            _git(git, Path(tmp), "clone", "--filter=blob:none", "--no-checkout", src.url, str(clone))
            _git(git, clone, "checkout", "--quiet", src.base)
            if src.fix and _git(git, clone, "cat-file", "-e", f"{src.fix}^{{commit}}", check=False).returncode != 0:
                _git(git, clone, "fetch", "--quiet", "origin", src.fix)

            if force:
                _rmtree(repo_out)
            # Injected bugs (DESIGN §4.1): an author-written patch applied on top of `base`. Applied
            # in the clone (its own repo) so paths resolve against the project root, then copied.
            inject = task_dir / "inject.patch"
            if inject.is_file():
                _git(git, clone, "apply", "--whitespace=nowarn", str(inject.resolve()))
            shutil.copytree(clone, repo_out, ignore=shutil.ignore_patterns(".git"))

            suggestions: list[str] = []
            if src.fix:
                raw = _git(git, clone, "diff", "--name-status", "-z", "--no-renames", src.base, src.fix).stdout
                parts = raw.decode("utf-8").split("\0")
                changed: list[tuple[str, str]] = []
                for i in range(0, len(parts) - 1, 2):
                    changed.append((parts[i][:1], parts[i + 1]))
                # Parts of a multi-fix upstream change that belong to other defects (DESIGN §4.1).
                changed = [(s, p) for s, p in changed if not any(fnmatch.fnmatch(p, x) for x in src.exclude)]
                tests = [(s, p) for s, p in changed if is_test_path(p)]
                others = [p for s, p in changed if not is_test_path(p)]

                if force:
                    _rmtree(hidden_out)
                    patch_out.unlink(missing_ok=True)
                for status, p in tests:
                    if status == "D":
                        continue
                    blob = _git(git, clone, "show", f"{src.fix}:{p}").stdout
                    dest = hidden_out / p
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(blob)
                    name = PurePosixPath(p).name
                    if fnmatch.fnmatch(name, "test_*.py") or fnmatch.fnmatch(name, "*_test.py"):
                        suggestions.append(p)
                if others:
                    patch = _git(git, clone, "diff", "--binary", "--no-renames", src.base, src.fix, "--", *others).stdout
                    patch_out.write_bytes(patch)
                if not task.acceptance:
                    if suggestions:
                        print(f"{task_dir}: task.toml has no 'acceptance'; suggested:")
                        print("acceptance = [" + ", ".join(json.dumps(s) for s in suggestions) + "]")
                    else:
                        print(f"{task_dir}: task.toml has no 'acceptance' and the fix touched no test files")
        finally:
            pass

    (task_dir / "source.lock.json").write_text(
        json.dumps(
            {"url": src.url, "base": src.base, "fix": src.fix, "built": _dt.date.today().isoformat()},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
