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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_WIN = os.name == "nt"
RESULT_GRACE_S = 10.0  # stdio mode: how long the CLI may take to exit after its result before it is stopped


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


class StdioSession:
    """Drive `claude -p --input-format stream-json --permission-prompt-tool stdio` (DESIGN 3.8).

    Sends the prompt as a stream-json user message, copies stdout to the transcript, and answers the CLI's
    `can_use_tool` control requests: AskUserQuestion goes through a file mailbox that the controller answers
    (ask/NNN.json -> ask/NNN.answer.json), every other tool is allowed (the session runs with
    bypassPermissions, so only tools that need the user ask).

    The call ends at the first result event, as `claude -p` does: stdin is closed and nothing after the result
    is copied. In this input mode the CLI stays alive while a background task the agent started is still
    running, and when that task ends it wakes the agent for another turn; run() stops the process instead.
    """

    def __init__(self, proc: subprocess.Popen, transcript, ask_dir: Path, answer_timeout_s: float):
        self.proc, self.transcript, self.ask_dir = proc, transcript, ask_dir
        self.answer_timeout_s = answer_timeout_s
        self.result = threading.Event()
        self.lock = threading.Lock()
        self.asked = 0
        self.ask_wait_s = 0.0
        self.control = []  # (tool name, behaviour) for every control request

    def send(self, obj: dict) -> None:
        with self.lock:
            try:
                self.proc.stdin.write((json.dumps(obj) + "\n").encode())
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def close_stdin(self) -> None:
        with self.lock:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def pump(self) -> None:
        for raw in self.proc.stdout:
            if self.result.is_set():
                continue  # drain without recording, so the CLI never blocks on a full pipe
            self.transcript.write(raw)
            self.transcript.flush()
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if d.get("type") == "control_request":
                self.answer(d)
            elif d.get("type") == "result":
                self.result.set()
                self.close_stdin()

    def answer(self, d: dict) -> None:
        rid, req = d.get("request_id"), d.get("request") or {}
        if req.get("subtype") != "can_use_tool":
            self.control.append([req.get("subtype"), "unsupported"])
            self.send({"type": "control_response", "response": {"subtype": "error", "request_id": rid,
                                                                "error": "unsupported control request"}})
            return
        tool, inp = req.get("tool_name"), req.get("input") or {}
        if tool == "AskUserQuestion":
            resp = self.ask(inp)
        else:
            resp = {"behavior": "allow", "updatedInput": inp}
        self.control.append([tool, resp["behavior"]])
        self.send({"type": "control_response", "response": {"subtype": "success", "request_id": rid,
                                                            "response": resp}})

    def ask(self, inp: dict) -> dict:
        n = self.asked
        self.asked += 1
        self.ask_dir.mkdir(parents=True, exist_ok=True)
        q, a = self.ask_dir / f"{n:03d}.json", self.ask_dir / f"{n:03d}.answer.json"
        tmp = q.with_suffix(".tmp")
        tmp.write_text(json.dumps(inp), encoding="utf-8")
        tmp.replace(q)
        t0 = time.monotonic()
        answer = None
        while time.monotonic() - t0 < self.answer_timeout_s and self.proc.poll() is None:
            if a.exists():
                try:
                    answer = json.loads(a.read_text(encoding="utf-8"))
                    break
                except ValueError:
                    pass  # partly written
            time.sleep(0.5)
        self.ask_wait_s += time.monotonic() - t0
        if not isinstance(answer, dict) or not isinstance(answer.get("answers"), dict):
            return {"behavior": "deny", "message": "The user did not answer. Make a reasonable assumption and continue."}
        return {"behavior": "allow", "updatedInput": {**inp, "answers": answer["answers"]}}


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
        stdio = spec.get("stdio")

        popen_kw: dict = {}
        if _WIN:
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kw["start_new_session"] = True

        started_at = _utc()
        t0 = time.monotonic()
        timed_out = False
        session = None
        with open(out_dir / "transcript.jsonl", "wb") as so, open(out_dir / "stderr.log", "wb") as se:
            try:
                if stdio:
                    proc = subprocess.Popen(argv, cwd=spec.get("cwd") or None, env=env, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=se, **popen_kw)
                else:
                    proc = subprocess.Popen(argv, cwd=spec.get("cwd") or None, env=env, stdin=subprocess.DEVNULL,
                                            stdout=so, stderr=se, **popen_kw)
            except OSError as e:
                se.write(f"hai_proof_wrap: failed to start: {e}\n".encode())
                timing = {"wall_s": 0.0, "exit_code": 127, "timed_out": False,
                          "started_at": started_at, "ended_at": _utc()}
                (out_dir / "timing.json").write_text(json.dumps(timing))
                return timing
            pump = None
            if stdio:
                session = StdioSession(proc, so, Path(stdio.get("ask_dir") or out_dir / "ask"),
                                       float(stdio.get("answer_timeout_s") or 600))
                pump = threading.Thread(target=session.pump, daemon=True)
                pump.start()
                session.send({"type": "user", "message": {"role": "user", "content": prompt}})
            stopped_after_result = False
            if session is None:
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _terminate(proc)
            else:
                deadline = None if timeout is None else t0 + float(timeout)
                while proc.poll() is None:
                    if session.result.wait(0.5):
                        try:
                            proc.wait(timeout=RESULT_GRACE_S)
                        except subprocess.TimeoutExpired:
                            stopped_after_result = True
                            _terminate(proc)
                        break
                    if deadline is not None and time.monotonic() >= deadline:
                        timed_out = True
                        _terminate(proc)
                        break
            if pump is not None:
                pump.join(timeout=30)
        wall = time.monotonic() - t0
        timing = {"wall_s": wall, "exit_code": proc.returncode, "timed_out": timed_out,
                  "started_at": started_at, "ended_at": _utc()}
        if session is not None:
            timing.update({"questions": session.asked, "ask_wait_s": round(session.ask_wait_s, 3),
                           "control_requests": session.control, "stopped_after_result": stopped_after_result})
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
