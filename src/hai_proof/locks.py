"""Lock files for state that several controllers share (DESIGN §3.2).

Several people or agents may drive hai-proof at once from one checkout. A lock is a file created with
O_EXCL that records the holder's pid and machine; a lock whose holder process is gone on this machine is
stale and is taken over. A lock held from another machine is never broken automatically.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


# In tasks/<ID>/: guards repo/ rebuilds and baseline.json updates. Files named .hai-proof* stay out of the
# task hash (TaskSpec.content_hash), so holding the lock never changes it.
TASK_LOCK = ".hai-proof.lock"


class LockHeld(RuntimeError):
    """Another live controller holds the lock."""


def pid_alive(pid: int) -> bool:
    """True if a process with this pid runs on this machine (or we can't tell: the safe answer)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # Never os.kill(pid, 0) on Windows: it terminates the process.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _holder() -> dict:
    return {"pid": os.getpid(), "host": socket.gethostname(), "since": time.time()}


def read_holder(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _stale(info: dict | None) -> bool:
    if info is None:
        return False  # being written right now, or unreadable: not ours to break
    return info.get("host") == socket.gethostname() and not pid_alive(int(info.get("pid", 0)))


def describe(info: dict | None) -> str:
    if not info:
        return "another controller"
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.get("since", 0)))
    return f"pid {info.get('pid')} on {info.get('host')} (since {when})"


def try_acquire(path: Path) -> dict | None:
    """Take the lock, or return the live holder's record. A stale lock is replaced."""
    path = Path(path)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            info = read_holder(path)
            if not _stale(info):
                return info or {}
            # Move the stale lock aside, then check what was moved: another waiter may have replaced it
            # with a live lock in between, which is put back.
            aside = path.with_name(f"{path.name}.stale-{os.getpid()}")
            try:
                os.replace(path, aside)
            except FileNotFoundError:
                continue
            moved = read_holder(aside)
            if moved is not None and not _stale(moved):
                os.replace(aside, path)
                return moved
            aside.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(_holder(), fh)
        return None
    return read_holder(path) or {}


def release(path: Path) -> None:
    path = Path(path)
    info = read_holder(path)
    if info and info.get("pid") == os.getpid() and info.get("host") == socket.gethostname():
        for i in range(50):
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError:  # Windows: a waiter is reading the holder record right now
                if i == 49:
                    raise
                time.sleep(0.05)


@contextmanager
def held(path: Path, *, timeout_s: float = 600, poll_s: float = 0.5, what: str = "") -> Iterator[None]:
    """Hold the lock for the block, waiting up to timeout_s for another holder to finish."""
    deadline = time.monotonic() + timeout_s
    while (info := try_acquire(path)) is not None:
        if time.monotonic() >= deadline:
            raise LockHeld(f"{what or path} is locked by {describe(info)}; if that process is gone, "
                           f"delete {path}")
        time.sleep(poll_s)
    try:
        yield
    finally:
        release(path)


def write_atomic(path: Path, text: str) -> None:
    """Replace a file so readers see the old or the new content, never a partial write."""
    path = Path(path)
    tmp = path.with_name(f".hai-proof.{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for i in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: a reader has the file open
            if i == 19:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.1)
