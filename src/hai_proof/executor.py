"""Executor: one small interface for container operations on the local machine or over SSH.

All file transfer is tar over stdin/stdout; secrets never appear on a command line.
"""

from __future__ import annotations

import os
import gzip
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from typing import Callable

CP = subprocess.CompletedProcess


class ExecError(RuntimeError):
    def __init__(self, message: str, *, cmd: list[str] | None = None, returncode: int | None = None,
                 stdout: bytes = b"", stderr: bytes = b""):
        super().__init__(message)
        self.cmd = cmd or []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _env_lines(secret_env: dict[str, str]) -> bytes:
    return "".join(f"{k}={v}\n" for k, v in secret_env.items()).encode()


class Executor(ABC):
    name: str

    # -- transport primitives -------------------------------------------------
    @abstractmethod
    def _run_docker(self, args: list[str], input: bytes | None, timeout: float | None) -> CP: ...

    @abstractmethod
    def host_shell(self, command: str, *, timeout: float | None = None, check: bool = True) -> CP: ...

    def _secret_env_args(self, secret_env: dict[str, str]) -> tuple[list[str], bytes | None, str | None]:
        """Return (docker flags, stdin, tempfile path to delete)."""
        return ["--env-file", "/dev/stdin"], _env_lines(secret_env), None

    # -- shared logic ---------------------------------------------------------
    def _check(self, proc: CP, args: list[str], check: bool) -> CP:
        if check and proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise ExecError(f"[{self.name}] `docker {' '.join(args[:3])}` failed (rc={proc.returncode}): {err[:500]}",
                            cmd=["docker", *args], returncode=proc.returncode,
                            stdout=proc.stdout or b"", stderr=proc.stderr or b"")
        return proc

    def docker(self, args: list[str], *, input: bytes | None = None, timeout: float | None = None,
               check: bool = True) -> CP:
        return self._check(self._run_docker(args, input, timeout), args, check)

    def put_tar(self, container: str, dest_dir: str, tar_bytes: bytes) -> None:
        self.docker(["cp", "-", f"{container}:{dest_dir}"], input=tar_bytes)

    def get_tar(self, container: str, src_path: str) -> bytes:
        return self.docker(["cp", f"{container}:{src_path}", "-"]).stdout

    def build_image(self, tag: str, context_tar: bytes, *, dockerfile: str = "Dockerfile",
                    build_args: dict[str, str] | None = None, timeout: float = 3600) -> None:
        # With a tar context on stdin, BuildKit rejects `-f Dockerfile` as ambiguous; the default
        # name is found inside the context, so only pass -f for a non-default name.
        args = ["build", "-t", tag]
        if dockerfile != "Dockerfile":
            args += ["-f", dockerfile]
        for k, v in (build_args or {}).items():
            args += ["--build-arg", f"{k}={v}"]
        args.append("-")
        # gzip: smaller over SSH, and Docker always recognises the compressed stream as a context.
        self.docker(args, input=gzip.compress(context_tar, compresslevel=6), timeout=timeout)

    def image_exists(self, tag: str) -> bool:
        return self.docker(["image", "inspect", tag], check=False).returncode == 0

    def run_detached(self, run_args: list[str], *, secret_env: dict[str, str] | None = None) -> str:
        flags: list[str] = []
        stdin: bytes | None = None
        tmp: str | None = None
        if secret_env:
            flags, stdin, tmp = self._secret_env_args(secret_env)
        try:
            proc = self.docker(["run", "-d", *flags, *run_args], input=stdin)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return proc.stdout.decode().strip()

    def exec(self, container: str, cmd: list[str], *, user: str = "agent", workdir: str | None = None,
             env: dict[str, str] | None = None, input: bytes | None = None, timeout: float | None = None,
             check: bool = True, detach: bool = False) -> CP:
        args = ["exec"]
        if detach:
            args.append("-d")
        if input is not None:
            args.append("-i")
        args += ["-u", user]
        if workdir:
            args += ["-w", workdir]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        args += [container, *cmd]
        return self.docker(args, input=input, timeout=timeout, check=check)

    def remove(self, container: str) -> None:
        try:
            self.docker(["rm", "-f", container], check=False, timeout=60)
        except Exception:
            pass

    def network_create(self, name: str, *, internal: bool = False) -> None:
        self.docker(["network", "create", *(["--internal"] if internal else []), name])

    def network_remove(self, name: str) -> None:
        try:
            self.docker(["network", "rm", name], check=False, timeout=60)
        except Exception:
            pass

    def network_connect(self, network: str, container: str) -> None:
        self.docker(["network", "connect", network, container])

    def network_disconnect(self, network: str, container: str) -> None:
        try:
            self.docker(["network", "disconnect", network, container], check=False, timeout=60)
        except Exception:
            pass


class LocalExecutor(Executor):
    name = "local"

    def _run_docker(self, args, input, timeout):
        return subprocess.run(["docker", *args], input=input, capture_output=True, timeout=timeout)

    def host_shell(self, command, *, timeout=None, check=True):
        sh = shutil.which("sh")
        if sh is None:
            raise NotImplementedError("host_shell on the local machine requires a POSIX `sh` (not found)")
        proc = subprocess.run([sh, "-c", command], capture_output=True, timeout=timeout)
        if check and proc.returncode != 0:
            raise ExecError(f"[local] shell command failed (rc={proc.returncode})", cmd=[sh, "-c", command],
                            returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        return proc

    def _secret_env_args(self, secret_env):
        if sys.platform != "win32":
            return super()._secret_env_args(secret_env)
        fd, path = tempfile.mkstemp(prefix="hai-proof-env-", suffix=".env")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(_env_lines(secret_env))
        except BaseException:
            os.unlink(path)
            raise
        return ["--env-file", path], None, path


class SshExecutor(Executor):
    def __init__(self, alias: str, *, ssh_binary: str = "ssh", connect_timeout: int = 10,
                 sleep: Callable[[float], None] = time.sleep, retry_delays: tuple[float, ...] = (2, 4)):
        self.name = alias
        self.alias = alias
        self.ssh_binary = ssh_binary
        self.connect_timeout = connect_timeout
        self._sleep = sleep
        self.retry_delays = retry_delays

    def _ssh_argv(self, remote_command: str) -> list[str]:
        argv = [self.ssh_binary, "-o", "BatchMode=yes", "-o", f"ConnectTimeout={self.connect_timeout}"]
        if sys.platform != "win32":
            argv += ["-o", "ControlMaster=auto", "-o", "ControlPath=~/.ssh/hai-proof-%C",
                     "-o", "ControlPersist=120"]
        return [*argv, self.alias, "--", remote_command]

    def _ssh(self, remote_command: str, input: bytes | None, timeout: float | None) -> CP:
        argv = self._ssh_argv(remote_command)
        attempts = len(self.retry_delays) + 1
        proc: CP | None = None
        for i in range(attempts):
            proc = subprocess.run(argv, input=input, capture_output=True, timeout=timeout)
            if proc.returncode != 255:
                return proc
            if i < attempts - 1:
                self._sleep(self.retry_delays[i])
        assert proc is not None
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ExecError(f"ssh connection to host '{self.alias}' failed after {attempts} attempts: {err[:300]}. "
                        f"Run `hai-proof hosts check {self.alias}` to diagnose.",
                        cmd=argv, returncode=255, stdout=proc.stdout or b"", stderr=proc.stderr or b"")

    def _run_docker(self, args, input, timeout):
        return self._ssh(shlex.join(["docker", *args]), input, timeout)

    def host_shell(self, command, *, timeout=None, check=True):
        proc = self._ssh(shlex.join(["sh", "-c", command]), None, timeout)
        if check and proc.returncode != 0:
            raise ExecError(f"[{self.name}] remote shell command failed (rc={proc.returncode})",
                            cmd=self._ssh_argv(command), returncode=proc.returncode,
                            stdout=proc.stdout, stderr=proc.stderr)
        return proc


def make_executor(host: str, *, ssh_binary: str = "ssh") -> Executor:
    if host == "local":
        return LocalExecutor()
    return SshExecutor(host, ssh_binary=ssh_binary)
