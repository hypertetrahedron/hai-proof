"""Deterministic diff categorisation (DESIGN §3.7)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache

CATEGORIES = (
    "product_code",
    "tests",
    "docs",
    "planning",
    "config_tooling",
    "treatment_artifact",
    "other",
)

# Glob rules: patterns without "/" match the basename at any depth; patterns with "/" are
# anchored at the repo root, "**/" meaning any depth (including none), "**" any suffix.
_HARNESS = ("CLAUDE.md", "AGENTS.md", ".claude/**", "**/.claude/**", ".mcp.json",
            "requirements*.txt", "constraints*.txt")  # checked before docs ("*.txt")
_PRODUCT_EXT = (
    "py pyi js jsx mjs cjs ts tsx go rs java kt c h cpp cc hpp cs rb php swift scala sh bash "
    "sql lua pl r html css scss vue svelte"
).split()

DEFAULT_PATTERNS: dict[str, tuple[str, ...]] = {
    "config_tooling": _HARNESS
    + (
        "pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "noxfile.py", "*.toml", "*.ini",
        "*.cfg", "*.yaml", "*.yml", ".github/**", "**/.github/**", ".pre-commit-config.yaml",
        "Makefile", "Dockerfile", ".gitignore",
    ),
    "tests": (
        "tests/**", "test/**", "**/tests/**", "**/test/**", "**/test_*.py", "**/*_test.py",
        "**/conftest.py",
    ),
    "planning": ("ROADMAP.md", "**/ROADMAP.md", "TODO*", "PLAN*.md", "openspec/**", ".beads/**"),
    "docs": ("*.md", "*.rst", "docs/**", "**/docs/**", "*.txt", "LICENSE*"),
    "product_code": tuple(f"*.{e}" for e in _PRODUCT_EXT),
}

# precedence after artifacts and overrides
_ORDER = ("harness", "tests", "planning", "docs", "config_tooling", "product_code")


@lru_cache(maxsize=None)
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = "/" in pattern
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    body = "".join(out)
    return re.compile(("^" if anchored else r"^(?:.*/)?") + body + "$")


def _match(path: str, patterns: Iterable[str]) -> bool:
    return any(_compile(p).match(path) for p in patterns)


def _norm(path: str) -> str:
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _rename_target(path: str) -> str:
    if "=>" not in path:
        return path
    m = re.search(r"\{([^{}]*)=>([^{}]*)\}", path)
    if m:
        new = path[: m.start()] + m.group(2).strip() + path[m.end():]
        return re.sub(r"/{2,}", "/", new)
    return path.split("=>")[-1].strip()


def _to_int(s: str) -> int:
    s = s.strip()
    return int(s) if s.isdigit() else 0


def parse_numstat(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for line in (text or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        a, d, path = parts
        out.append((_rename_target(path.strip()), _to_int(a), _to_int(d)))
    return out


def categorize(
    path: str,
    *,
    artifacts: Iterable[str] = (),
    overrides: Mapping[str, Sequence[str]] | None = None,
) -> str:
    p = _norm(path)
    for a in artifacts:
        a = _norm(a)
        if a and (p.startswith(a) or p == a.rstrip("/")):
            return "treatment_artifact"
    for cat, pats in (overrides or {}).items():
        if _match(p, pats):
            return cat
    for key in _ORDER:
        pats = _HARNESS if key == "harness" else DEFAULT_PATTERNS[key]
        if _match(p, pats):
            return "config_tooling" if key == "harness" else key
    return "other"


def diff_breakdown(
    numstat_text: str,
    *,
    artifacts: Iterable[str] = (),
    overrides: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, dict[str, int]]:
    artifacts = tuple(artifacts)
    res = {c: {"files": 0, "lines": 0} for c in CATEGORIES}
    for path, added, deleted in parse_numstat(numstat_text):
        cat = categorize(path, artifacts=artifacts, overrides=overrides)
        res.setdefault(cat, {"files": 0, "lines": 0})
        res[cat]["files"] += 1
        res[cat]["lines"] += added + deleted
    return res
