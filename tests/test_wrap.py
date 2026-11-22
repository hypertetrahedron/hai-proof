import importlib.util
import json
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "image" / "base" / "hai_proof_wrap.py"
_spec = importlib.util.spec_from_file_location("hai_proof_wrap", SRC)
wrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wrap)


def _run(tmp_path, argv, **kw):
    out = tmp_path / "out" / "agent"
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello prompt", encoding="utf-8")
    spec = {"argv": argv, "cwd": str(tmp_path), "env": {}, "prompt_file": str(prompt),
            "timeout_s": 30, "out_dir": str(out), **kw}
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    rc = wrap.main([str(sp)])
    return rc, out


def test_success_with_prompt_and_env(tmp_path):
    code = "import sys,os;print(sys.argv[1]);print(os.environ.get('FOO'));print(os.environ.get('GONE','unset'))"
    # argv = [python, -c, code]; insert prompt at index 3 -> becomes sys.argv[1]
    rc, out = _run(tmp_path, [sys.executable, "-c", code], prompt_arg_index=3,
                   env={"FOO": "bar", "GONE": "x"}, unset_env=["GONE"])
    assert rc == 0
    assert (out / "transcript.jsonl").read_text().splitlines() == ["hello prompt", "bar", "unset"]
    t = json.loads((out / "timing.json").read_text())
    assert t["exit_code"] == 0 and t["timed_out"] is False and t["wall_s"] >= 0
    assert t["started_at"] <= t["ended_at"]
    assert (out / "done").exists() and (out / "stderr.log").exists()


def test_nonzero_exit(tmp_path):
    _, out = _run(tmp_path, [sys.executable, "-c", "import sys;sys.exit(3)"])
    t = json.loads((out / "timing.json").read_text())
    assert t["exit_code"] == 3 and not t["timed_out"]


def test_timeout_kills(tmp_path):
    t0 = time.monotonic()
    _, out = _run(tmp_path, [sys.executable, "-c", "import time;print('x',flush=True);time.sleep(60)"],
                  timeout_s=1)
    assert time.monotonic() - t0 < 30
    t = json.loads((out / "timing.json").read_text())
    assert t["timed_out"] is True and t["exit_code"] != 0
    assert (out / "done").exists()


def test_start_failure_still_writes_done(tmp_path):
    _, out = _run(tmp_path, ["/definitely/not/a/binary"])
    t = json.loads((out / "timing.json").read_text())
    assert t["exit_code"] == 127
    assert (out / "done").exists()


def test_build_argv():
    assert wrap.build_argv(["a", "b"], "P", 1) == ["a", "P", "b"]
    assert wrap.build_argv(["a"], "P", None) == ["a"]


FAKE_STDIO_CLAUDE = r'''
import json, sys
def emit(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
msg = json.loads(sys.stdin.readline())
emit({"type": "system", "subtype": "init", "tools": ["AskUserQuestion", "Bash"]})
emit({"type": "control_request", "request_id": "r1",
      "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"}}})
r1 = json.loads(sys.stdin.readline())
q = {"questions": [{"question": "Which?", "header": "H", "multiSelect": False,
                    "options": [{"label": "A", "description": ""}, {"label": "B", "description": ""}]}]}
emit({"type": "control_request", "request_id": "r2",
      "request": {"subtype": "can_use_tool", "tool_name": "AskUserQuestion", "input": q}})
r2 = json.loads(sys.stdin.readline())
emit({"type": "result", "subtype": "success", "result": json.dumps([msg, r1, r2])})
assert sys.stdin.readline() == ""  # the wrapper closes stdin after the result
'''


def test_stdio_session_answers_questions_through_the_mailbox(tmp_path):
    import threading

    ask = tmp_path / "ask"

    def user():
        for _ in range(200):
            if (ask / "000.json").exists():
                q = json.loads((ask / "000.json").read_text())
                (ask / "000.answer.json").write_text(json.dumps({"answers": {q["questions"][0]["question"]: "B"}}))
                return
            time.sleep(0.05)

    th = threading.Thread(target=user)
    th.start()
    rc, out = _run(tmp_path, [sys.executable, "-c", FAKE_STDIO_CLAUDE],
                   stdio={"ask_dir": str(ask), "answer_timeout_s": 20})
    th.join()
    assert rc == 0
    lines = [json.loads(x) for x in (out / "transcript.jsonl").read_text().splitlines()]
    msg, r1, r2 = json.loads(lines[-1]["result"])
    assert msg == {"type": "user", "message": {"role": "user", "content": "hello prompt"}}
    assert r1["response"]["response"] == {"behavior": "allow", "updatedInput": {"command": "ls"}}
    assert r2["response"]["request_id"] == "r2"
    assert r2["response"]["response"]["updatedInput"]["answers"] == {"Which?": "B"}
    t = json.loads((out / "timing.json").read_text())
    assert t["exit_code"] == 0 and t["questions"] == 1
    assert t["control_requests"] == [["Bash", "allow"], ["AskUserQuestion", "allow"]]


def test_stdio_session_denies_an_unanswered_question(tmp_path):
    rc, out = _run(tmp_path, [sys.executable, "-c", FAKE_STDIO_CLAUDE],
                   stdio={"ask_dir": str(tmp_path / "ask"), "answer_timeout_s": 1})
    lines = [json.loads(x) for x in (out / "transcript.jsonl").read_text().splitlines()]
    r2 = json.loads(lines[-1]["result"])[2]
    assert r2["response"]["response"]["behavior"] == "deny"
    assert json.loads((out / "timing.json").read_text())["control_requests"][-1] == ["AskUserQuestion", "deny"]


LINGERING_CLAUDE = r'''
import json, sys, time
def emit(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
sys.stdin.readline()
emit({"type": "result", "subtype": "success", "result": "done"})
time.sleep(30)  # a background task keeps the CLI alive after its result
emit({"type": "result", "subtype": "success", "result": "woken again"})
'''


def test_stdio_session_ends_the_call_at_the_first_result(tmp_path, monkeypatch):
    monkeypatch.setattr(wrap, "RESULT_GRACE_S", 0.5)
    rc, out = _run(tmp_path, [sys.executable, "-c", LINGERING_CLAUDE], stdio={"ask_dir": str(tmp_path / "ask")})
    lines = [json.loads(x) for x in (out / "transcript.jsonl").read_text().splitlines()]
    assert [x["result"] for x in lines] == ["done"]
    t = json.loads((out / "timing.json").read_text())
    assert t["stopped_after_result"] is True and t["timed_out"] is False and t["wall_s"] < 15


DELEGATING_CLAUDE = r'''
import json, os, sys, time
def emit(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
if STDIO:
    sys.stdin.readline()
emit({"type": "system", "subtype": "ceiling", "value": os.environ.get("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS")})
emit({"type": "system", "subtype": "task_started", "task_id": "a1", "task_type": "local_agent"})
emit({"type": "system", "subtype": "task_started", "task_id": "s9", "task_type": "local_bash", "owned_by_subagent": True})
emit({"type": "system", "subtype": "background_tasks_changed",
      "tasks": [{"task_id": "a1", "task_type": "local_agent"}]})
emit({"type": "result", "subtype": "success", "result": "the delegate is working, I'll review when it reports back"})
time.sleep(1.5)  # the subagent finishes; the CLI wakes the agent for another turn
emit({"type": "system", "subtype": "task_notification", "task_id": "a1", "status": "completed"})
emit({"type": "system", "subtype": "background_tasks_changed", "tasks": []})
emit({"type": "result", "subtype": "success", "result": "reviewed and verified"})
if STDIO:
    assert sys.stdin.readline() == ""  # stdin closes only after the final result
'''


def _results(out):
    lines = [json.loads(x) for x in (out / "transcript.jsonl").read_text().splitlines()]
    return lines, [x["result"] for x in lines if x.get("type") == "result"]


def test_stdio_call_waits_for_a_background_subagent(tmp_path, monkeypatch):
    monkeypatch.setattr(wrap, "RESULT_GRACE_S", 2)
    rc, out = _run(tmp_path, [sys.executable, "-c", "STDIO = True\n" + DELEGATING_CLAUDE],
                   stdio={"ask_dir": str(tmp_path / "ask")})
    lines, results = _results(out)
    assert results == ["the delegate is working, I'll review when it reports back", "reviewed and verified"]
    t = json.loads((out / "timing.json").read_text())
    assert t["exit_code"] == 0 and t["results"] == 2 and t["bg_agent_waits"] == 1 and t["bg_wait_s"] >= 1
    assert t["stopped_after_result"] is False and t["shell_wait_cut"] is False


def test_print_call_waits_for_a_background_subagent_with_no_cli_ceiling(tmp_path):
    rc, out = _run(tmp_path, [sys.executable, "-c", "STDIO = False\n" + DELEGATING_CLAUDE])
    lines, results = _results(out)
    assert lines[0]["value"] == "0"  # the CLI's own 10-minute ceiling is off; the wrapper decides
    assert results[-1] == "reviewed and verified"
    t = json.loads((out / "timing.json").read_text())
    assert t["exit_code"] == 0 and t["results"] == 2 and t["bg_agent_waits"] == 1


SHELL_ONLY_CLAUDE = r'''
import json, sys, time
def emit(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
sys.stdin.readline()
emit({"type": "system", "subtype": "background_tasks_changed", "tasks": [{"task_id": "b1", "task_type": "local_bash"}]})
emit({"type": "result", "subtype": "success", "result": "server is up"})
time.sleep(60)  # a forgotten dev server
'''


def test_background_shells_alone_get_a_bounded_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(wrap, "SHELL_WAIT_S", 0.5)
    monkeypatch.setattr(wrap, "RESULT_GRACE_S", 0.5)
    _, out = _run(tmp_path, [sys.executable, "-c", SHELL_ONLY_CLAUDE], stdio={"ask_dir": str(tmp_path / "ask")})
    t = json.loads((out / "timing.json").read_text())
    assert t["shell_wait_cut"] is True and t["timed_out"] is False and t["wall_s"] < 15
    assert t["bg_agent_waits"] == 0


def test_background_task_tracking():
    bt = wrap.BackgroundTasks()
    bt.update({"type": "system", "subtype": "task_started", "task_id": "x", "task_type": "local_bash",
               "owned_by_subagent": True})
    assert not bt.any()
    bt.update({"type": "system", "subtype": "task_started", "task_id": "a", "task_type": "local_agent"})
    assert bt.agents()
    bt.update({"type": "system", "subtype": "task_updated", "task_id": "a", "patch": {"status": "killed"}})
    assert not bt.any()
    bt.update({"type": "system", "subtype": "background_tasks_changed",
               "tasks": [{"task_id": "b", "task_type": "local_bash"}]})
    assert bt.any() and not bt.agents()
    bt.update({"type": "system", "subtype": "task_notification", "task_id": "b", "status": "completed"})
    assert not bt.any()
