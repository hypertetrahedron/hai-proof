"""In-memory tar helpers. All container file transfer is tar over stdin/stdout (no bind mounts)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path, PurePosixPath
from typing import Mapping

_EXCLUDE_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache"}


def tar_directory(src: Path, prefix: str = "", *, exclude_dirs: set[str] | None = None,
                  uid: int = 1000, gid: int = 1000) -> bytes:
    """Tar the *contents* of `src` (not src itself), optionally under `prefix/`.

    Ownership is set to uid/gid (the in-container `agent` user) so files are writable by the agent.
    """
    exclude = _EXCLUDE_DIRS if exclude_dirs is None else exclude_dirs
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(src)
            if any(part in exclude for part in rel.parts):
                continue
            arc = str(PurePosixPath(prefix) / rel.as_posix()) if prefix else rel.as_posix()
            info = tar.gettarinfo(str(p), arcname=arc)
            info.uid, info.gid, info.uname, info.gname = uid, gid, "agent", "agent"
            # Whole-second mtime: a fractional one makes tarfile emit a PAX header first, and
            # `docker build -` only sniffs the first 1 KiB to decide whether stdin is an archive.
            info.mtime = int(info.mtime)
            if p.is_file():
                # Normalise modes: Windows has no exec bit; keep scripts executable by extension.
                info.mode = 0o755 if p.suffix in {".sh", ""} and _looks_executable(p) else 0o644
                with p.open("rb") as fh:
                    tar.addfile(info, fh)
            elif p.is_dir():
                info.mode = 0o755
                tar.addfile(info)
    return buf.getvalue()


def tar_files(files: Mapping[str, bytes | str], *, mode: int = 0o644, uid: int = 1000, gid: int = 1000) -> bytes:
    """Tar a mapping of posix relative path -> content."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".sh") else mode
            info.uid, info.gid, info.uname, info.gname = uid, gid, "agent", "agent"
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def extract_tar(data: bytes, dest: Path) -> list[Path]:
    """Safely extract tar bytes into dest (rejects absolute paths, '..' and links). Returns files written."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    written: list[Path] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        for m in tar.getmembers():
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(root)) or m.issym() or m.islnk():
                continue
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                fh = tar.extractfile(m)
                if fh is not None:
                    target.write_bytes(fh.read())
                    written.append(target)
    return written


def read_tar_member(data: bytes, name: str) -> bytes | None:
    """Return one file's content from tar bytes, matched by basename-insensitive suffix."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        for m in tar.getmembers():
            if m.isfile() and (m.name == name or m.name.endswith("/" + name)):
                fh = tar.extractfile(m)
                return fh.read() if fh else None
    return None


def _looks_executable(p: Path) -> bool:
    try:
        with p.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False
