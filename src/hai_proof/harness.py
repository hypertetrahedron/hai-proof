"""Which hai-proof produced a run: recorded in run.json as "harness" so results can be split by it."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from . import __version__

_PKG = Path(__file__).resolve().parent


def code_hash(root: Path) -> str:
    """Short hash of the controller package and the trial/proxy images (wrapper, grader, Dockerfiles):
    everything on the harness side that can change a trial's outcome, committed or not."""
    h = hashlib.sha256()
    for base in (_PKG, Path(root) / "image"):
        if not base.is_dir():
            continue
        for f in sorted(p for p in base.rglob("*") if p.is_file()):
            if "__pycache__" in f.parts or f.suffix == ".pyc":
                continue
            h.update(f.relative_to(base.parent).as_posix().encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def harness_info(root: Path) -> dict[str, Any]:
    commit = _git(root, "rev-parse", "--short=12", "HEAD")
    status = _git(root, "status", "--porcelain", "--", "src", "image") if commit else None
    return {"version": __version__, "code_hash": code_hash(root), "git_commit": commit,
            "git_dirty": bool(status) if status is not None else None}
