"""Minimal OpenSSH client-config reader: host alias discovery and `ssh -G` effective settings."""

from __future__ import annotations

import glob
import os
import re
import shlex
import subprocess
from pathlib import Path

_KV = re.compile(r"^(\w+)\s*(?:=\s*|\s+)(.*)$")


def default_config_path() -> Path:
    """`%USERPROFILE%\\.ssh\\config` on Windows, `~/.ssh/config` elsewhere."""
    return Path.home() / ".ssh" / "config"


def _tokens(value: str) -> list[str]:
    try:
        parts = shlex.split(value, comments=False, posix=False)
    except ValueError:
        parts = value.split()
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def _is_concrete(pattern: str) -> bool:
    return bool(pattern) and not pattern.startswith("!") and "*" not in pattern and "?" not in pattern


def _expand_include(pattern: str, base: Path) -> list[Path]:
    pattern = os.path.expanduser(pattern)
    if not os.path.isabs(pattern):
        pattern = str(base / pattern)
    return [Path(p) for p in sorted(glob.glob(pattern)) if Path(p).is_file()]


def _collect(path: Path, base: Path, seen: set[Path], out: list[str]) -> None:
    try:
        key = path.resolve()
    except OSError:
        return
    if key in seen:
        return
    seen.add(key)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _KV.match(line)
        if not m:
            continue
        keyword, value = m.group(1).lower(), m.group(2).strip()
        if keyword == "host":
            for tok in _tokens(value):
                if tok.startswith("#"):
                    break
                if _is_concrete(tok) and tok not in out:
                    out.append(tok)
        elif keyword == "include":
            for tok in _tokens(value):
                for inc in _expand_include(tok, base):
                    _collect(inc, base, seen, out)


def list_host_aliases(config_path: Path | None = None) -> list[str]:
    """Concrete Host aliases in file order (Includes followed), de-duplicated.

    Relative Include paths resolve against the config file's directory (~/.ssh for the default).
    """
    path = config_path if config_path is not None else default_config_path()
    out: list[str] = []
    _collect(path, path.parent, set(), out)
    return out


def effective_config(alias: str, *, ssh_binary: str = "ssh", timeout: float = 10) -> dict[str, str]:
    """Run `ssh -G <alias>`; lowercase keys, first occurrence wins. {} on any failure."""
    try:
        proc = subprocess.run([ssh_binary, "-G", alias], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}
    result: dict[str, str] = {}
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            result.setdefault(parts[0].lower(), parts[1].strip())
    return result
