#!/usr/bin/env python3
"""Run the agent command with timing next to the process (DESIGN 3.1 step 4). Stdlib only.

Usage: hai_proof_wrap.py <spec.json>
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_WIN = os.name == "nt"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _terminate(proc: subprocess.Popen, grace: float = 10.0) -> None:
    if _WIN:
        try:
            proc.terminate()
        except OSError:
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    if _WIN:
        proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    proc.wait()


def build_argv(argv: list[str], prompt: str, index: int | None) -> list[str]:
    out = list(argv)
    if index is not None:
        out.insert(index, prompt)
    return out


def run(spec: dict) -> dict:
    out_dir = Path(spec.get("out_dir", "/out/agent"))
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        prompt = ""
        if spec.get("prompt_file"):
            prompt = Path(spec["prompt_file"]).read_text(encoding="utf-8")
        argv = build_argv(spec["argv"], prompt, spec.get("prompt_arg_index"))
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (spec.get("env") or {}).items()})
        for k in spec.get("unset_env") or []:
            env.pop(k, None)
        timeout = spec.get("timeout_s")

        popen_kw: dict = {}
        if _WIN:
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kw["start_new_session"] = True

        started_at = _utc()
        t0 = time.monotonic()
        timed_out = False
        with open(out_dir / "transcript.jsonl", "wb") as so, open(out_dir / "stderr.log", "wb") as se:
            try:
                proc = subprocess.Popen(argv, cwd=spec.get("cwd") or None, env=env, stdin=subprocess.DEVNULL,
                                        stdout=so, stderr=se, **popen_kw)
            except OSError as e:
                se.write(f"hai_proof_wrap: failed to start: {e}\n".encode())
                timing = {"wall_s": 0.0, "exit_code": 127, "timed_out": False,
                          "started_at": started_at, "ended_at": _utc()}
                (out_dir / "timing.json").write_text(json.dumps(timing))
                return timing
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate(proc)
        wall = time.monotonic() - t0
        timing = {"wall_s": wall, "exit_code": proc.returncode, "timed_out": timed_out,
                  "started_at": started_at, "ended_at": _utc()}
        (out_dir / "timing.json").write_text(json.dumps(timing))
        return timing
    finally:
        (out_dir / "done").touch()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: hai_proof_wrap.py <spec.json>", file=sys.stderr)
        return 2
    spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    run(spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
