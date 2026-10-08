import gzip
import os
import shlex
import subprocess
import sys

import pytest

from hai_proof import executor as ex
from hai_proof.executor import ExecError, LocalExecutor, SshExecutor, make_executor

SECRET = "sk-ant-SUPERSECRET"


class Recorder:
    def __init__(self, results=None):
        self.calls = []  # (argv, kwargs)
        self.results = list(results or [])

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.results:
            r = self.results.pop(0)
            return subprocess.CompletedProcess(argv, r[0], r[1] if len(r) > 1 else b"", r[2] if len(r) > 2 else b"")
        return subprocess.CompletedProcess(argv, 0, b"cid123\n", b"")


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(subprocess, "run", r)
    return r


def ssh(**kw):
    return SshExecutor("box", sleep=lambda s: None, **kw)


def test_make_executor():
    assert isinstance(make_executor("local"), LocalExecutor)
    e = make_executor("box", ssh_binary="myssh")
    assert isinstance(e, SshExecutor) and e.name == "box" and e.ssh_binary == "myssh"


def test_local_docker(rec):
    LocalExecutor().docker(["ps", "-a"])
    assert rec.calls[0][0] == ["docker", "ps", "-a"]
    assert rec.calls[0][1]["capture_output"] is True


def test_ssh_command_posix(rec, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    ssh().docker(["exec", "c", "sh", "-c", "echo 'hi there'; echo \"q\""])
    argv = rec.calls[0][0]
    assert argv[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    assert "ControlMaster=auto" in argv and "ControlPath=~/.ssh/hai-proof-%C" in argv
    assert "ControlPersist=120" in argv
    assert argv[-3:-1] == ["box", "--"]
    assert shlex.split(argv[-1]) == ["docker", "exec", "c", "sh", "-c", "echo 'hi there'; echo \"q\""]


def test_ssh_command_windows_no_control(rec, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    ssh(connect_timeout=3).docker(["ps"])
    argv = rec.calls[0][0]
    assert argv == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "box", "--", "docker ps"]


def test_exec_args_quoting(rec):
    ssh().exec("c1", ["bash", "-lc", "ls 'a b'"], workdir="/work dir", env={"K": "v w"}, input=b"x", detach=True)
    parts = shlex.split(rec.calls[0][0][-1])
    assert parts == ["docker", "exec", "-d", "-i", "-u", "agent", "-w", "/work dir", "-e", "K=v w", "c1",
                     "bash", "-lc", "ls 'a b'"]
    assert rec.calls[0][1]["input"] == b"x"


def test_exec_no_input_no_dash_i(rec):
    LocalExecutor().exec("c", ["true"])
    assert rec.calls[0][0] == ["docker", "exec", "-u", "agent", "c", "true"]


def test_tar_and_build(rec):
    e = LocalExecutor()
    e.put_tar("c", "/work", b"TAR")
    assert rec.calls[0][0] == ["docker", "cp", "-", "c:/work"] and rec.calls[0][1]["input"] == b"TAR"
    rec.results = [(0, b"OUT")]
    assert e.get_tar("c", "/out") == b"OUT"
    assert rec.calls[1][0] == ["docker", "cp", "c:/out", "-"]
    e.build_image("t:1", b"CTX", dockerfile="D", build_args={"A": "1", "B": "2"})
    assert rec.calls[2][0] == ["docker", "build", "-t", "t:1", "-f", "D", "--build-arg", "A=1",
                               "--build-arg", "B=2", "-"]
    assert gzip.decompress(rec.calls[2][1]["input"]) == b"CTX" and rec.calls[2][1]["timeout"] == 3600
    e.build_image("t:2", b"CTX")
    assert "-f" not in rec.calls[3][0]  # default Dockerfile: -f with a stdin context is ambiguous


def test_tar_directory_has_no_leading_pax_header(tmp_path):
    """`docker build -` sniffs only the first 1 KiB; a PAX header there hides the archive."""
    import io, os, tarfile
    from hai_proof.tarutil import tar_directory

    f = tmp_path / "Dockerfile"
    f.write_text("FROM x" + chr(10))
    os.utime(f, (1759600000.123456, 1759600000.123456))
    data = tar_directory(tmp_path)
    first = tarfile.open(fileobj=io.BytesIO(data)).getmembers()[0]
    assert first.name == "Dockerfile" and data[156:157] == b"0"  # regular-file typeflag, not 'x'


def test_image_exists(rec):
    e = LocalExecutor()
    assert e.image_exists("x") is True
    rec.results = [(1, b"", b"no such image")]
    assert e.image_exists("x") is False


def test_secret_env_ssh_not_in_argv(rec):
    cid = ssh().run_detached(["--name", "n", "img"], secret_env={"ANTHROPIC_API_KEY": SECRET, "B": "2"})
    assert cid == "cid123"
    argv, kw = rec.calls[0]
    assert all(SECRET not in a for a in argv)
    assert kw["input"] == f"ANTHROPIC_API_KEY={SECRET}\nB=2\n".encode()
    assert shlex.split(argv[-1]) == ["docker", "run", "-d", "--env-file", "/dev/stdin", "--name", "n", "img"]


def test_secret_env_local_posix(rec, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    LocalExecutor().run_detached(["img"], secret_env={"K": SECRET})
    argv, kw = rec.calls[0]
    assert argv == ["docker", "run", "-d", "--env-file", "/dev/stdin", "img"]
    assert SECRET.encode() in kw["input"] and all(SECRET not in a for a in argv)


def test_no_secret_env_no_flag(rec):
    LocalExecutor().run_detached(["img"])
    assert rec.calls[0][0] == ["docker", "run", "-d", "img"]


def test_secret_env_local_windows_tempfile(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    seen = {}

    def fake(argv, **kw):
        path = argv[argv.index("--env-file") + 1]
        seen["path"] = path
        with open(path, "rb") as fh:
            seen["content"] = fh.read()
        seen["input"] = kw.get("input")
        assert all(SECRET not in a for a in argv)
        return subprocess.CompletedProcess(argv, 0, b"abc\n", b"")

    monkeypatch.setattr(subprocess, "run", fake)
    assert LocalExecutor().run_detached(["img"], secret_env={"K": SECRET}) == "abc"
    assert seen["content"] == f"K={SECRET}\n".encode() and seen["input"] is None
    assert not os.path.exists(seen["path"])


def test_secret_tempfile_deleted_on_failure(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    paths = []

    def fake(argv, **kw):
        paths.append(argv[argv.index("--env-file") + 1])
        return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(ExecError):
        LocalExecutor().run_detached(["img"], secret_env={"K": SECRET})
    assert not os.path.exists(paths[0])


def test_check_raises_execerror(rec):
    rec.results = [(125, b"o", b"bad thing")]
    with pytest.raises(ExecError) as ei:
        LocalExecutor().docker(["run", "x"])
    assert ei.value.returncode == 125 and ei.value.stderr == b"bad thing" and ei.value.cmd == ["docker", "run", "x"]
    rec.results = [(125,)]
    assert LocalExecutor().docker(["run", "x"], check=False).returncode == 125


def test_ssh_retry_255_then_success(monkeypatch):
    r = Recorder([(255, b"", b"conn reset"), (255, b"", b"conn reset"), (0, b"ok")])
    monkeypatch.setattr(subprocess, "run", r)
    sleeps = []
    e = SshExecutor("box", sleep=sleeps.append)
    assert e.docker(["ps"]).stdout == b"ok"
    assert len(r.calls) == 3 and sleeps == [2, 4]


def test_ssh_255_exhausted(monkeypatch):
    r = Recorder([(255, b"", b"Connection refused")] * 5)
    monkeypatch.setattr(subprocess, "run", r)
    sleeps = []
    with pytest.raises(ExecError) as ei:
        SshExecutor("box", sleep=sleeps.append).docker(["ps"], check=False)
    assert len(r.calls) == 3 and sleeps == [2, 4]
    assert "box" in str(ei.value) and "hai-proof hosts check" in str(ei.value) and ei.value.returncode == 255


def test_no_retry_on_other_failure(monkeypatch):
    r = Recorder([(1, b"", b"nope")])
    monkeypatch.setattr(subprocess, "run", r)
    sleeps = []
    with pytest.raises(ExecError):
        SshExecutor("box", sleep=sleeps.append).docker(["ps"])
    assert len(r.calls) == 1 and sleeps == []


def test_remove_and_network_disconnect_never_raise(monkeypatch):
    def boom(*a, **k):
        raise OSError("x")

    monkeypatch.setattr(subprocess, "run", boom)
    e = LocalExecutor()
    e.remove("c")
    e.network_remove("n")
    e.network_disconnect("n", "c")
    r = Recorder([(255, b"", b"x")] * 6)
    monkeypatch.setattr(subprocess, "run", r)
    s = SshExecutor("box", sleep=lambda s: None)
    s.remove("c")
    s.network_disconnect("n", "c")


def test_network_cmds(rec):
    e = LocalExecutor()
    e.network_create("n", internal=True)
    e.network_create("m")
    e.network_connect("n", "c")
    assert [c[0] for c in rec.calls] == [
        ["docker", "network", "create", "--internal", "n"], ["docker", "network", "create", "m"],
        ["docker", "network", "connect", "n", "c"]]


def test_host_shell_ssh_quotes(rec):
    ssh().host_shell("curl -w '%{http_code}' x")
    assert shlex.split(rec.calls[0][0][-1]) == ["sh", "-c", "curl -w '%{http_code}' x"]


def test_host_shell_local_no_sh(monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda n: None)
    with pytest.raises(NotImplementedError):
        LocalExecutor().host_shell("true")


def test_host_shell_local_with_sh(rec, monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda n: "/bin/sh")
    LocalExecutor().host_shell("echo hi")
    assert rec.calls[0][0] == ["/bin/sh", "-c", "echo hi"]
