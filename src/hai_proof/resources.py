"""Resource gate between trial pairs: memory on both machines and leaked Docker objects.

A long run can be killed by memory pressure on the controller machine (the runner process) or starve on
the execution host. Before each pair the runner records a snapshot to ``resources.jsonl``, removes this
run's leftover trial containers, and waits while memory is short; if it stays short, the run stops cleanly
(teardown and report) instead of being killed mid-trial.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

GB = 1024**3


class ResourceError(RuntimeError):
    """Memory stayed below the minimum for the whole wait; the run stops cleanly."""


def parse_mem(spec: str) -> int:
    """Docker-style memory size ("8g", "512m", "1024") to bytes."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)b?\s*", str(spec).lower())
    if not m:
        raise ValueError(f"bad memory size: {spec!r}")
    return int(float(m.group(1)) * 1024 ** " kmgt".index(m.group(2) or " "))


def _meminfo(text: str) -> tuple[int, int] | None:
    vals = {}
    for line in text.splitlines():
        k, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            vals[k.strip()] = int(parts[0]) * 1024
    if "MemAvailable" in vals and "MemTotal" in vals:
        return vals["MemAvailable"], vals["MemTotal"]
    return None


def local_memory() -> tuple[int, int] | None:
    """(available, total) bytes on the controller machine, or None if unknown."""
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullAvailPhys), int(st.ullTotalPhys)
        return None
    try:
        return _meminfo(Path("/proc/meminfo").read_text())
    except OSError:
        return None


def self_rss() -> int | None:
    """Resident memory of this (controller) process in bytes, or None if unknown."""
    if sys.platform == "win32":
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        try:
            get_proc = ctypes.windll.kernel32.GetCurrentProcess
            get_proc.restype = ctypes.c_void_p  # a HANDLE; the default int return truncates it on 64-bit
            if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(get_proc()), ctypes.byref(pmc), pmc.cb):
                return int(pmc.WorkingSetSize)
        except (AttributeError, OSError):
            return None
        return None
    try:
        m = re.search(r"^VmRSS:\s+(\d+)\s+kB", Path(f"/proc/{os.getpid()}/status").read_text(), re.M)
        return int(m.group(1)) * 1024 if m else None
    except OSError:
        return None


@dataclass
class Snapshot:
    ts: float
    where: str
    local_avail: int | None = None
    local_total: int | None = None
    host_avail: int | None = None
    host_total: int | None = None
    controller_rss: int | None = None
    run_containers: list[str] = field(default_factory=list)  # this run's trial containers (should be none)
    other_containers: list[str] = field(default_factory=list)  # hai-proof containers of other runs
    networks: list[str] = field(default_factory=list)  # hai-proof networks on the host
    removed: list[str] = field(default_factory=list)
    waited_s: float = 0.0


class ResourceGate:
    """Called between pairs. `need_host` is the memory a pair needs on the execution host."""

    def __init__(self, ex: Any, run_id: str, run_dir: Path, *, need_host: int, need_local: int = 2 * GB,
                 rss_warn: int = 1 * GB, wait_s: float = 900, poll_s: float = 30,
                 log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                 local_mem: Callable[[], tuple[int, int] | None] = local_memory,
                 rss: Callable[[], int | None] = self_rss):
        self.ex, self.run_id, self.path = ex, run_id, Path(run_dir) / "resources.jsonl"
        self.need_host, self.need_local, self.rss_warn = need_host, need_local, rss_warn
        self.wait_s, self.poll_s, self.log, self.sleep = wait_s, poll_s, log, sleep
        self.local_mem, self.rss = local_mem, rss
        self.rss_start: int | None = None
        self._host_mem_ok = True  # False once the host can't report memory (e.g. no POSIX shell locally)

    def host_memory(self) -> tuple[int, int] | None:
        if not self._host_mem_ok:
            return None
        try:
            r = self.ex.host_shell("cat /proc/meminfo", timeout=30, check=False)
            got = _meminfo(r.stdout.decode(errors="replace")) if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            got = None
        if got is None:
            self._host_mem_ok = False
            self.log("resources: execution host memory unavailable (no /proc/meminfo); host memory not gated")
        return got

    def _docker_lines(self, args: list[str]) -> list[str]:
        try:
            r = self.ex.docker(args, check=False, timeout=60)
            return [x for x in r.stdout.decode(errors="replace").split() if x]
        except Exception:  # noqa: BLE001
            return []

    def snapshot(self, where: str) -> Snapshot:
        s = Snapshot(ts=time.time(), where=where)
        lm = self.local_mem()
        if lm:
            s.local_avail, s.local_total = lm
        hm = self.host_memory()
        if hm:
            s.host_avail, s.host_total = hm
        s.controller_rss = self.rss()
        mine = f"tp-{self.run_id}-".lower()
        names = self._docker_lines(["ps", "-a", "--filter", "label=hai-proof.run", "--format", "{{.Names}}"])
        s.run_containers = [n for n in names if n.startswith(mine) and not n.endswith("-proxy")]
        s.other_containers = [n for n in names if not n.startswith(mine)]
        s.networks = [n for n in self._docker_lines(["network", "ls", "--format", "{{.Name}}"]) if n.startswith("tp-")]
        return s

    def _short(self, s: Snapshot) -> list[str]:
        out = []
        if s.local_avail is not None and s.local_avail < self.need_local:
            out.append(f"controller machine {s.local_avail / GB:.1f} GB free < {self.need_local / GB:.1f} GB")
        if s.host_avail is not None and s.host_avail < self.need_host:
            out.append(f"execution host {s.host_avail / GB:.1f} GB available < {self.need_host / GB:.1f} GB")
        return out

    def _write(self, s: Snapshot) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(s)) + "\n")

    def check(self, where: str) -> Snapshot:
        """Snapshot, clean up this run's leaks, and wait while memory is short. Raises ResourceError."""
        s = self.snapshot(where)
        if s.run_containers:
            self.log(f"resources: leaked trial containers before {where}: {', '.join(s.run_containers)}; removing")
            for name in s.run_containers:
                try:
                    self.ex.remove(name)
                    s.removed.append(name)
                except Exception as e:  # noqa: BLE001
                    self.log(f"resources: could not remove {name}: {e}")
        if s.other_containers:
            self.log(f"resources: warning: {len(s.other_containers)} hai-proof container(s) from other runs on the "
                     f"host ({', '.join(s.other_containers[:4])}{' …' if len(s.other_containers) > 4 else ''})")
        if s.controller_rss is not None:
            if self.rss_start is None:
                self.rss_start = s.controller_rss
            elif s.controller_rss - self.rss_start > self.rss_warn:
                self.log(f"resources: warning: controller memory grew {(s.controller_rss - self.rss_start) / GB:.1f} GB "
                         "since the start of the run")
        waited = 0.0
        short = self._short(s)
        while short and waited < self.wait_s:
            self.log(f"resources: waiting before {where}: {'; '.join(short)}")
            self.sleep(self.poll_s)
            waited += self.poll_s
            nxt = self.snapshot(where)
            nxt.removed, s = s.removed, nxt
            short = self._short(s)
        s.waited_s = waited
        self._write(s)
        if short:
            raise ResourceError(f"not enough memory before {where} after waiting {waited:.0f} s: {'; '.join(short)}")
        return s
