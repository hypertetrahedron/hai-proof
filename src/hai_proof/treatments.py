"""Load treatment bundles (DESIGN §3.4, §3.6)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from .config import ConfigError
from .models import PLAIN, Requirement, TreatmentSpec

_TOP_KEYS = {"name", "prompt_prefix", "env", "requires", "setup", "network", "expect"}
_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")


def _str_list(v: Any, where: str) -> tuple[str, ...]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(v)


def _table(d: dict, key: str, allowed: set[str], mf: Path) -> dict:
    t = d.get(key, {})
    if not isinstance(t, dict):
        raise ConfigError(f"{mf}: [{key}] must be a table")
    bad = sorted(set(t) - allowed)
    if bad:
        raise ConfigError(f"{mf}: unknown keys in [{key}]: {', '.join(bad)}")
    return t


def _norm_artifact(a: str, mf: Path) -> str:
    if "\\" in a:
        raise ConfigError(f"{mf}: artifact '{a}' must use posix separators")
    p = PurePosixPath(a)
    if not a or p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", a):
        raise ConfigError(f"{mf}: artifact '{a}' must be a relative path inside the workspace")
    norm = p.as_posix()
    if norm == ".":
        raise ConfigError(f"{mf}: artifact '{a}' must name a path below the workspace root")
    return norm + "/" if a.endswith("/") else norm


def load_treatment(path: Path) -> TreatmentSpec:
    path = Path(path)
    mf = path / "manifest.toml"
    if not mf.is_file():
        raise ConfigError(f"treatment manifest not found: {mf}")
    try:
        with mf.open("rb") as f:
            d = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{mf}: invalid TOML: {e}") from e
    unknown = sorted(set(d) - _TOP_KEYS)
    if unknown:
        raise ConfigError(f"{mf}: unknown top-level keys: {', '.join(unknown)}")

    name = d.get("name", path.resolve().name)
    if not isinstance(name, str) or not _SLUG.match(name):
        raise ConfigError(f"{mf}: name {name!r} must match [A-Za-z0-9._-]+")
    prefix = d.get("prompt_prefix", "")
    if not isinstance(prefix, str):
        raise ConfigError(f"{mf}: prompt_prefix must be a string")

    env = d.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ConfigError(f"{mf}: [env] must be a table of string values")

    reqs_raw = d.get("requires", [])
    if not isinstance(reqs_raw, list) or not all(isinstance(r, dict) for r in reqs_raw):
        raise ConfigError(f"{mf}: 'requires' must be an array of tables ([[requires]])")
    reqs = []
    for i, r in enumerate(reqs_raw):
        missing = [k for k in ("name", "install", "check") if not isinstance(r.get(k), str) or not r[k].strip()]
        if missing:
            raise ConfigError(f"{mf}: requires[{i}] missing field(s): {', '.join(missing)}")
        extra = sorted(set(r) - {"name", "install", "check"})
        if extra:
            raise ConfigError(f"{mf}: requires[{i}] unknown keys: {', '.join(extra)}")
        reqs.append(Requirement(r["name"], r["install"], r["check"]))

    setup = _table(d, "setup", {"commands", "artifacts"}, mf)
    commands = _str_list(setup.get("commands", []), f"{mf}: setup.commands")
    artifacts = tuple(_norm_artifact(a, mf) for a in _str_list(setup.get("artifacts", []), f"{mf}: setup.artifacts"))
    net = _table(d, "network", {"allow"}, mf)
    allow = _str_list(net.get("allow", []), f"{mf}: network.allow")
    exp = _table(d, "expect", {"plugins", "mcp_servers", "skills"}, mf)

    return TreatmentSpec(
        name=name,
        path=path,
        prompt_prefix=prefix,
        env=dict(env),
        requires=tuple(reqs),
        setup_commands=commands,
        artifacts=artifacts,
        network_allow=allow,
        expect_plugins=_str_list(exp.get("plugins", []), f"{mf}: expect.plugins"),
        expect_mcp_servers=_str_list(exp.get("mcp_servers", []), f"{mf}: expect.mcp_servers"),
        expect_skills=_str_list(exp.get("skills", []), f"{mf}: expect.skills"),
    )


def resolve_treatment(ref: str, *, search_dirs: list[Path] | None = None) -> TreatmentSpec:
    """'plain' -> PLAIN; an existing directory path; or a name found in search_dirs."""
    if ref == "plain":
        return PLAIN
    dirs = [Path(p) for p in (search_dirs if search_dirs is not None else [Path("treatments")])]
    p = Path(ref)
    if p.is_dir() and (p / "manifest.toml").is_file():
        return load_treatment(p)
    for sd in dirs:
        cand = sd / ref
        if (cand / "manifest.toml").is_file():
            return load_treatment(cand)
    searched = ", ".join(str(d) for d in dirs) or "(none)"
    raise ConfigError(f"treatment '{ref}' not found (not a directory with manifest.toml; searched: {searched})")
