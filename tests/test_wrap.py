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
