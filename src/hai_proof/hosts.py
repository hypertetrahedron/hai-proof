"""Host discovery, probing and preflight checks for execution hosts (DESIGN 3.5)."""

from __future__ import annotations

import getpass
import platform
import re
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .executor import ExecError, Executor
from .sshconfig import effective_config


@dataclass
class HostInfo:
    alias: str
    hostname: str = ""
    user: str = ""
    reachable: bool = False
    auth_ok: bool = False
    engine_version: str | None = None
    ncpu: int | None = None
    mem_bytes: int | None = None
    arch: str | None = None
    free_disk_gb: float | None = None
    docker_without_sudo: bool | None = None
    error: str | None = None


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


_PROBE_SCRIPT = (
    "v=$(docker version --format '{{.Server.Version}}' 2>&1); "
    "echo ===VERSION===; echo \"$v\"; "
    "i=$(docker info --format '{{.NCPU}} {{.MemTotal}} {{.Architecture}} {{.DockerRootDir}}' 2>&1); "
    "echo ===INFO===; echo \"$i\"; "
    "root=$(echo \"$i\" | awk '{print $4}'); d=/; [ -d \"$root\" ] && d=$root; "
    "echo ===DF===; df -Pk \"$d\" 2>&1 | tail -n 1; echo ===END==="
)
_SECTION = re.compile(r"^===(VERSION|INFO|DF|END)===$")


def _sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    cur: str | None = None
    for line in text.splitlines():
        m = _SECTION.match(line.strip())
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _classify_error(text: str, info: HostInfo) -> None:
    low = text.lower()
    if "permission denied while trying to connect to the docker daemon" in low:
        info.docker_without_sudo = False
        info.error = "permission denied on docker socket (user not in docker group?)"
    elif "command not found" in low or ": not found" in low or "no such file or directory" in low:
        info.error = "docker not installed"
    elif "cannot connect to the docker daemon" in low or "is the docker daemon running" in low:
        info.error = "docker daemon not running"
    else:
        info.error = text.strip().splitlines()[0][:200] if text.strip() else "docker returned no output"


def _parse_probe(stdout: str, info: HostInfo) -> None:
    sec = _sections(stdout)
    version = sec.get("VERSION", "")
    if re.match(r"^\d+(\.\d+)*", version):
        info.engine_version = version.splitlines()[0].strip()
        info.docker_without_sudo = True
    else:
        _classify_error(version, info)
        return
    parts = sec.get("INFO", "").split()
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        info.ncpu, info.mem_bytes, info.arch = int(parts[0]), int(parts[1]), parts[2]
    else:
        info.error = "docker info failed: " + sec.get("INFO", "")[:200]
    df = sec.get("DF", "").split()
    if len(df) >= 4 and df[3].isdigit():
        info.free_disk_gb = round(int(df[3]) / (1024 * 1024), 1)


def _probe_local(info: HostInfo, timeout: int) -> HostInfo:
    info.hostname = platform.node()
    try:
        info.user = getpass.getuser()
    except Exception:
        pass
    info.auth_ok = True
    try:
        ver = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                             capture_output=True, timeout=timeout + 10)
    except FileNotFoundError:
        info.reachable = True
        info.error = "docker not installed"
        return info
    except subprocess.TimeoutExpired:
        info.error = "timed out talking to docker"
        return info
    info.reachable = True
    out = ver.stdout.decode(errors="replace").strip()
    err = ver.stderr.decode(errors="replace").strip()
    if ver.returncode != 0 or not re.match(r"^\d", out):
        _classify_error(err or out, info)
        return info
    info.engine_version = out.splitlines()[0]
    info.docker_without_sudo = True
    try:
        i = subprocess.run(["docker", "info", "--format", "{{.NCPU}} {{.MemTotal}} {{.Architecture}} {{.DockerRootDir}}"],
                           capture_output=True, timeout=timeout + 10)
        parts = i.stdout.decode(errors="replace").split()
        if i.returncode == 0 and len(parts) >= 3:
            info.ncpu, info.mem_bytes, info.arch = int(parts[0]), int(parts[1]), parts[2]
            root = Path(parts[3]) if len(parts) > 3 else Path.home()
            target = root if root.exists() else Path.home()
            info.free_disk_gb = round(shutil.disk_usage(target).free / 1024**3, 1)
    except (subprocess.SubprocessError, ValueError, OSError):
        pass
    return info


def probe(alias: str, *, ssh_binary: str = "ssh", timeout: int = 5) -> HostInfo:
    info = HostInfo(alias=alias)
    if alias == "local":
        return _probe_local(info, timeout)
    cfg = effective_config(alias, ssh_binary=ssh_binary)
    info.hostname = cfg.get("hostname", "")
    info.user = cfg.get("user", "")
    argv = [ssh_binary, "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", alias, "--",
            shlex.join(["sh", "-c", _PROBE_SCRIPT])]
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout + 20)
    except subprocess.TimeoutExpired:
        info.error = "timed out"
        return info
    except OSError as e:
        info.error = f"cannot run {ssh_binary}: {e}"
        return info
    stdout = proc.stdout.decode(errors="replace")
    stderr = proc.stderr.decode(errors="replace")
    if proc.returncode == 255:
        if "permission denied" in stderr.lower():
            info.reachable = True
            info.error = "ssh authentication failed (permission denied)"
        else:
            info.error = (stderr.strip().splitlines() or ["ssh connection failed"])[-1][:200]
        return info
    info.reachable = True
    info.auth_ok = True
    if "===VERSION===" not in stdout:
        info.error = (stderr.strip() or f"probe failed (rc={proc.returncode})")[:200]
        return info
    _parse_probe(stdout, info)
    return info


def probe_all(aliases: list[str], *, max_workers: int = 8, **kw) -> list[HostInfo]:
    if not aliases:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(aliases)))) as pool:
        return list(pool.map(lambda a: probe(a, **kw), aliases))


_MEM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")
_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def parse_mem(s: str) -> int:
    """'8g' / '512m' / '1024' -> bytes (binary units; optional trailing b/ib)."""
    m = _MEM.match(s)
    if not m:
        raise ValueError(f"invalid memory size: {s!r}")
    unit = m.group(2).lower()
    if unit.endswith("ib"):
        unit = unit[:-2]
    elif unit.endswith("b") and len(unit) > 1:
        unit = unit[:-1]
    if unit not in _UNITS:
        raise ValueError(f"invalid memory size: {s!r}")
    return int(float(m.group(1)) * _UNITS[unit])


_CURL = "curl -sS -o /dev/null -w '%{http_code}' --max-time 10 https://api.anthropic.com/v1/messages"
_WGET = "wget -q --spider --timeout=10 https://api.anthropic.com/v1/messages"


def _check_api(executor: Executor) -> CheckResult:
    try:
        r = executor.host_shell(_CURL, timeout=30, check=False)
        out = r.stdout.decode(errors="replace").strip()
        err = r.stderr.decode(errors="replace").strip()
        if r.returncode == 127 or "not found" in err.lower():
            w = executor.host_shell(_WGET, timeout=30, check=False)
            # wget exits 8 when the server answered with an HTTP error status: still reachable.
            if w.returncode in (0, 8):
                return CheckResult("api", True, "api.anthropic.com reachable (via wget)")
            return CheckResult("api", False, f"api.anthropic.com unreachable (via wget, rc={w.returncode})")
        if r.returncode == 0 and re.fullmatch(r"\d{3}", out) and out != "000":
            return CheckResult("api", True, f"api.anthropic.com reachable (HTTP {out})")
        return CheckResult("api", False, f"api.anthropic.com unreachable (curl rc={r.returncode}, "
                                         f"code={out or 'none'}): {err[:150]}")
    except (ExecError, NotImplementedError, subprocess.SubprocessError) as e:
        return CheckResult("api", False, f"could not run API check: {e}")


def check_host(executor: Executor, info: HostInfo, *, cpus: float, memory: str,
               min_disk_gb: float = 20) -> list[CheckResult]:
    results: list[CheckResult] = []
    if info.engine_version and info.docker_without_sudo is not False:
        results.append(CheckResult("engine", True, f"docker {info.engine_version}"))
    elif info.docker_without_sudo is False:
        results.append(CheckResult("engine", False, "docker requires sudo for this user"))
    else:
        results.append(CheckResult("engine", False, info.error or "docker engine not available"))

    need_mem = 2 * parse_mem(memory)
    if info.ncpu is None or info.mem_bytes is None:
        results.append(CheckResult("capacity", False, "CPU/memory unknown"))
    else:
        ok = info.ncpu >= 2 * cpus and info.mem_bytes >= need_mem
        results.append(CheckResult(
            "capacity", ok,
            f"{info.ncpu} cpus (need >= {2 * cpus:g}), {info.mem_bytes / 1024**3:.1f} GB RAM "
            f"(need >= {need_mem / 1024**3:.1f} GB)"))

    if info.free_disk_gb is None:
        results.append(CheckResult("disk", False, "free disk unknown"))
    else:
        results.append(CheckResult("disk", info.free_disk_gb >= min_disk_gb,
                                   f"{info.free_disk_gb:.1f} GB free (need >= {min_disk_gb:g} GB)"))

    results.append(_check_api(executor))
    return results


def format_table(infos: list[HostInfo]) -> str:
    headers = ["ALIAS", "REACHABLE", "AUTH", "ENGINE", "CPUS", "MEM_GB", "ARCH", "FREE_GB", "NO-SUDO", "ERROR"]

    def yn(v: bool | None) -> str:
        return "-" if v is None else ("yes" if v else "no")

    rows = [[
        i.alias, yn(i.reachable), yn(i.auth_ok if i.reachable else None), i.engine_version or "-",
        "-" if i.ncpu is None else str(i.ncpu),
        "-" if i.mem_bytes is None else f"{i.mem_bytes / 1024**3:.1f}",
        i.arch or "-",
        "-" if i.free_disk_gb is None else f"{i.free_disk_gb:.1f}",
        yn(i.docker_without_sudo), i.error or "",
    ] for i in infos]
    widths = [max(len(h), *(len(r[c]) for r in rows)) if rows else len(h) for c, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()]
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    return "\n".join(lines)
