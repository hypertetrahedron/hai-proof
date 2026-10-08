import subprocess

import pytest

from hai_proof.executor import ExecError, Executor
from hai_proof.hosts import HostInfo, check_host, format_table, parse_mem, probe, probe_all

GOOD = (b"===VERSION===\n27.1.2\n===INFO===\n8 16777216000 x86_64 /var/lib/docker\n"
        b"===DF===\n/dev/sda1 100000000 50000000 52428800 50% /\n===END===\n")


@pytest.fixture
def fake_ssh(monkeypatch):
    state = {"rc": 0, "out": GOOD, "err": b"", "calls": []}

    def run(argv, **kw):
        state["calls"].append(argv)
        if "-G" in argv:
            return subprocess.CompletedProcess(argv, 0, b"hostname 1.2.3.4\nuser les\n", b"")
        return subprocess.CompletedProcess(argv, state["rc"], state["out"], state["err"])

    monkeypatch.setattr(subprocess, "run", run)
    return state


def test_probe_success(fake_ssh):
    i = probe("box", timeout=7)
    assert (i.reachable, i.auth_ok, i.engine_version, i.ncpu, i.arch) == (True, True, "27.1.2", 8, "x86_64")
    assert i.mem_bytes == 16777216000 and i.free_disk_gb == 50.0 and i.docker_without_sudo is True
    assert i.hostname == "1.2.3.4" and i.user == "les" and i.error is None
    argv = fake_ssh["calls"][-1]
    assert "BatchMode=yes" in argv and "ConnectTimeout=7" in argv and "box" in argv


def test_probe_auth_denied(fake_ssh):
    fake_ssh.update(rc=255, out=b"", err=b"box: Permission denied (publickey).")
    i = probe("box")
    assert i.reachable and not i.auth_ok and "permission denied" in i.error.lower()


def test_probe_unreachable(fake_ssh):
    fake_ssh.update(rc=255, out=b"", err=b"ssh: connect to host x port 22: Connection timed out")
    i = probe("box")
    assert not i.reachable and not i.auth_ok and "timed out" in i.error


def test_probe_docker_permission(fake_ssh):
    fake_ssh["out"] = (b"===VERSION===\npermission denied while trying to connect to the Docker daemon socket at "
                       b"unix:///var/run/docker.sock\n===INFO===\nx\n===DF===\n/ 1 1 1 1% /\n===END===\n")
    i = probe("box")
    assert i.reachable and i.auth_ok and i.docker_without_sudo is False and i.engine_version is None


@pytest.mark.parametrize("msg", ["sh: 1: docker: not found", "bash: docker: command not found"])
def test_probe_docker_missing(fake_ssh, msg):
    fake_ssh["out"] = f"===VERSION===\n{msg}\n===INFO===\n{msg}\n===DF===\n===END===\n".encode()
    assert probe("box").error == "docker not installed"


def test_probe_daemon_down(fake_ssh):
    fake_ssh["out"] = (b"===VERSION===\nCannot connect to the Docker daemon at unix:///x. "
                       b"Is the docker daemon running?\n===END===\n")
    assert probe("box").error == "docker daemon not running"


def test_probe_timeout(monkeypatch):
    def run(argv, **kw):
        if "-G" in argv:
            return subprocess.CompletedProcess(argv, 1, b"", b"")
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(subprocess, "run", run)
    i = probe("box")
    assert not i.reachable and i.error == "timed out"


def test_probe_local_no_docker(monkeypatch):
    def run(argv, **kw):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", run)
    i = probe("local")
    assert i.error == "docker not installed" and i.engine_version is None


def test_probe_all_order(fake_ssh):
    res = probe_all(["c", "a", "b"], max_workers=3)
    assert [r.alias for r in res] == ["c", "a", "b"]
    assert probe_all([]) == []


@pytest.mark.parametrize("s,n", [("8g", 8 * 1024**3), ("512m", 512 * 1024**2), ("1024", 1024), ("2GB", 2 * 1024**3),
                                 ("1.5g", int(1.5 * 1024**3)), ("4GiB", 4 * 1024**3), ("10k", 10240)])
def test_parse_mem(s, n):
    assert parse_mem(s) == n


@pytest.mark.parametrize("s", ["", "abc", "8x", "g8"])
def test_parse_mem_invalid(s):
    with pytest.raises(ValueError):
        parse_mem(s)


class FakeExec(Executor):
    name = "fake"

    def __init__(self, results):
        self.results = list(results)
        self.cmds = []

    def _run_docker(self, args, input, timeout):
        raise AssertionError

    def host_shell(self, command, *, timeout=None, check=True):
        self.cmds.append(command)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return subprocess.CompletedProcess(command, r[0], r[1], r[2] if len(r) > 2 else b"")


def good_info(**kw):
    d = dict(alias="box", reachable=True, auth_ok=True, engine_version="27", ncpu=16, mem_bytes=64 * 1024**3,
             free_disk_gb=100.0, docker_without_sudo=True)
    d.update(kw)
    return HostInfo(**d)


def by_name(rs):
    return {r.name: r for r in rs}


def test_check_all_ok():
    ex = FakeExec([(0, b"401")])
    rs = check_host(ex, good_info(), cpus=4, memory="8g")
    assert [r.name for r in rs] == ["engine", "capacity", "disk", "api"]
    assert all(r.ok for r in rs)
    assert "api.anthropic.com/v1/messages" in ex.cmds[0] and "curl" in ex.cmds[0]


def test_check_engine_failures():
    info = good_info(engine_version=None, error="docker not installed")
    r = by_name(check_host(FakeExec([(0, b"405")]), info, cpus=4, memory="8g"))
    assert not r["engine"].ok and "not installed" in r["engine"].detail
    r = by_name(check_host(FakeExec([(0, b"405")]), good_info(docker_without_sudo=False), cpus=4, memory="8g"))
    assert not r["engine"].ok and "sudo" in r["engine"].detail


def test_check_capacity_boundaries():
    def cap(**kw):
        return by_name(check_host(FakeExec([(0, b"401")]), good_info(**kw), cpus=4, memory="8g"))["capacity"].ok

    assert cap(ncpu=8, mem_bytes=16 * 1024**3)
    assert not cap(ncpu=7)
    assert not cap(mem_bytes=15 * 1024**3)
    assert not cap(ncpu=None)


def test_check_disk():
    def disk(**kw):
        return by_name(check_host(FakeExec([(0, b"401")]), good_info(**kw), cpus=1, memory="1g"))["disk"].ok

    assert not disk(free_disk_gb=10)
    assert not disk(free_disk_gb=None)
    r = by_name(check_host(FakeExec([(0, b"401")]), good_info(free_disk_gb=10), cpus=1, memory="1g",
                           min_disk_gb=5))
    assert r["disk"].ok


def test_check_api_failures():
    for res in [(0, b"000"), (7, b"000", b"Could not resolve host"), (28, b"")]:
        r = by_name(check_host(FakeExec([res]), good_info(), cpus=1, memory="1g"))
        assert not r["api"].ok
    r = by_name(check_host(FakeExec([ExecError("ssh down")]), good_info(), cpus=1, memory="1g"))
    assert not r["api"].ok and "ssh down" in r["api"].detail
    r = by_name(check_host(FakeExec([NotImplementedError("no sh")]), good_info(), cpus=1, memory="1g"))
    assert not r["api"].ok


def test_check_api_wget_fallback():
    ex = FakeExec([(127, b"", b"sh: curl: not found"), (8, b"")])
    r = by_name(check_host(ex, good_info(), cpus=1, memory="1g"))
    assert r["api"].ok and "wget" in r["api"].detail and "wget" in ex.cmds[1]
    ex = FakeExec([(127, b"", b"curl: not found"), (4, b"")])
    assert not by_name(check_host(ex, good_info(), cpus=1, memory="1g"))["api"].ok


def test_format_table():
    t = format_table([good_info(arch="x86_64"), HostInfo(alias="dead", error="timed out")])
    lines = t.splitlines()
    assert len(lines) == 3
    assert lines[0].split()[:3] == ["ALIAS", "REACHABLE", "AUTH"]
    assert "box" in lines[1] and "27" in lines[1] and "64.0" in lines[1] and "100.0" in lines[1]
    assert "dead" in lines[2] and "timed out" in lines[2]
    assert format_table([]).startswith("ALIAS")
