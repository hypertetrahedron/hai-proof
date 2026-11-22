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
RESULT_GRACE_S = 10.0  # how long the CLI may take to exit after its final result before it is stopped
# A result with only background shells still running (a dev server, a watcher) keeps the call open this long,
# as Claude Code's own print-mode ceiling did, so a forgotten server cannot hold a trial to its time limit.
SHELL_WAIT_S = 600.0
# Background subagents are waited for until they finish (bounded by the call's timeout), as in an
# interactive session; the CLI's own 10-minute print-mode ceiling would otherwise kill them.
BG_CEILING_ENV = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"
_DONE_STATUSES = {"completed", "killed", "failed", "stopped", "cancelled", "error"}


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


class BackgroundTasks:
    """Background tasks the main agent has running, from the CLI's stream-json system events."""

    def __init__(self):
        self.running: dict[str, str] = {}  # task_id -> task_type (local_agent, local_bash, ...)

    def update(self, d: dict) -> None:
        if d.get("type") != "system":
            return
        sub = d.get("subtype")
        if sub == "background_tasks_changed":
            self.running = {str(t.get("task_id")): str(t.get("task_type") or "") for t in d.get("tasks") or []
                            if isinstance(t, dict) and t.get("task_id")}
        elif sub == "task_started" and d.get("task_id") and not d.get("owned_by_subagent"):
            self.running.setdefault(str(d["task_id"]), str(d.get("task_type") or ""))
        elif sub == "task_notification" and d.get("task_id"):
            self.running.pop(str(d["task_id"]), None)
        elif sub == "task_updated" and d.get("task_id"):
            if str((d.get("patch") or {}).get("status") or "") in _DONE_STATUSES:
                self.running.pop(str(d["task_id"]), None)

    def agents(self) -> bool:
        return any("agent" in t for t in self.running.values())

    def any(self) -> bool:
        return bool(self.running)


class Session:
    """Read the CLI's stream-json output: copy it to the transcript, track background tasks and results.

    With stdio (`claude -p --input-format stream-json --permission-prompt-tool stdio`, DESIGN 3.8) it also
    sends the prompt on stdin and answers the CLI's `can_use_tool` control requests: AskUserQuestion goes
    through a file mailbox that the controller answers (ask/NNN.json -> ask/NNN.answer.json), every other
    tool is allowed (the session runs with bypassPermissions, so only tools that need the user ask).

    The call ends at the first result after which no background subagent is running. While one is, the CLI
    stays alive and wakes the agent for another turn (and another result) when the subagent finishes, as an
    interactive session does; ending the call there would grade work a delegate never finished.
    """

    def __init__(self, proc: subprocess.Popen, transcript, stdio: bool, ask_dir: Path, answer_timeout_s: float):
        self.proc, self.transcript, self.stdio, self.ask_dir = proc, transcript, stdio, ask_dir
        self.answer_timeout_s = answer_timeout_s
        self.tasks = BackgroundTasks()
        self.results = 0  # result events seen
        self.at_result: list[tuple[bool, bool]] = []  # (agents running, anything running) at each result
        self.final = threading.Event()  # set when the call is over: later output is drained, not recorded
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
        if not self.stdio:
            return
        with self.lock:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def pump(self) -> None:
        for raw in self.proc.stdout:
            if self.final.is_set():
                continue  # drain without recording, so the CLI never blocks on a full pipe
            self.transcript.write(raw)
            self.transcript.flush()
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            self.tasks.update(d)
            if d.get("type") == "control_request" and self.stdio:
                self.answer(d)
            elif d.get("type") == "result":
                with self.lock:
                    self.at_result.append((self.tasks.agents(), self.tasks.any()))
                    self.results += 1

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
        env[BG_CEILING_ENV] = "0"
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
        timed_out = stopped_after_result = shell_wait_cut = False
        bg_waits, bg_wait_s = 0, 0.0
        with open(out_dir / "transcript.jsonl", "wb") as so, open(out_dir / "stderr.log", "wb") as se:
            try:
                proc = subprocess.Popen(argv, cwd=spec.get("cwd") or None, env=env,
                                        stdin=subprocess.PIPE if stdio else subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=se, **popen_kw)
            except OSError as e:
                se.write(f"hai_proof_wrap: failed to start: {e}\n".encode())
                timing = {"wall_s": 0.0, "exit_code": 127, "timed_out": False,
                          "started_at": started_at, "ended_at": _utc()}
                (out_dir / "timing.json").write_text(json.dumps(timing))
                return timing
            session = Session(proc, so, bool(stdio), Path((stdio or {}).get("ask_dir") or out_dir / "ask"),
                              float((stdio or {}).get("answer_timeout_s") or 600))
            pump = threading.Thread(target=session.pump, daemon=True)
            pump.start()
            if stdio:
                session.send({"type": "user", "message": {"role": "user", "content": prompt}})

            def finish() -> None:
                nonlocal stopped_after_result
                session.final.set()
                session.close_stdin()
                try:
                    proc.wait(timeout=RESULT_GRACE_S)
                except subprocess.TimeoutExpired:
                    stopped_after_result = True
                    _terminate(proc)

            deadline = None if timeout is None else t0 + float(timeout)
            handled = 0
            waiting_since: float | None = None  # a result arrived with a background subagent still running
            shell_deadline: float | None = None
            while proc.poll() is None:
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    timed_out = True
                    session.final.set()
                    _terminate(proc)
                    break
                with session.lock:
                    new = session.at_result[handled:]
                    handled = len(session.at_result)
                if new:
                    if waiting_since is not None:
                        bg_wait_s += now - waiting_since
                        waiting_since = None
                    agents, anything = new[-1]
                    shell_deadline = None
                    if agents:
                        bg_waits += 1
                        waiting_since = now
                    elif anything:
                        shell_deadline = now + SHELL_WAIT_S
                    else:
                        finish()
                        break
                if shell_deadline is not None and now >= shell_deadline:
                    shell_wait_cut = True
                    finish()
                    break
                time.sleep(0.2)
            if waiting_since is not None:
                bg_wait_s += time.monotonic() - waiting_since
            pump.join(timeout=30)
        wall = time.monotonic() - t0
        timing = {"wall_s": wall, "exit_code": proc.returncode, "timed_out": timed_out,
                  "started_at": started_at, "ended_at": _utc(), "results": session.results,
                  "bg_agent_waits": bg_waits, "bg_wait_s": round(bg_wait_s, 3), "shell_wait_cut": shell_wait_cut,
                  "stopped_after_result": stopped_after_result}
        if stdio:
            timing.update({"questions": session.asked, "ask_wait_s": round(session.ask_wait_s, 3),
                           "control_requests": session.control})
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
