#!/usr/bin/env python3
"""Grade a finished trial (runs in the container, network disconnected). Stdlib only.

Usage: hai_proof_grade.py <spec.json>  -> prints one JSON object on stdout.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

TAIL = 4000
# In the container `python` is the /opt/venv interpreter; on a dev host use the current one.
PYTHON = "python"


# Grading runs with the network disconnected. The trial's egress-proxy variables would only make
# libraries that honour them (websockets, requests, ...) route local test traffic to a dead proxy.
_PROXY_VARS = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
               "all_proxy", "no_proxy"}


# Bytecode is compiled into a fresh directory, never read from the agent's __pycache__. CPython trusts a
# .pyc whose recorded source mtime (whole seconds) and size match, so a same-size edit landing in the same
# second as a compile (e.g. `git stash; pytest; git stash pop` around a one-character fix) leaves stale
# bytecode that would grade the old code. pytest's assertion rewriting honours the same prefix.
_PYCACHE: str | None = None


def _env() -> dict:
    global _PYCACHE
    if _PYCACHE is None:
        import tempfile
        _PYCACHE = tempfile.mkdtemp(prefix="hai-proof-grade-pyc-")
    env = {k: v for k, v in os.environ.items() if k not in _PROXY_VARS}
    env["PYTHONPYCACHEPREFIX"] = _PYCACHE
    return env


def _run(cmd, cwd: str, timeout: float, shell: bool = False) -> tuple[int | None, str, bool]:
    """Returns (rc, combined_output, timed_out).

    Runs in its own process group so a timeout kills the whole tree: with ``shell=True`` killing only the
    shell would leave pytest running into the next grading step.
    """
    kw = {} if os.name == "nt" else {"start_new_session": True}
    try:
        p = subprocess.Popen(cmd, cwd=cwd, shell=shell, env=_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, **kw)
    except OSError as e:
        return 127, f"failed to start: {e}", False
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out.decode("utf-8", "replace"), False
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            p.kill()
        else:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        out, _ = p.communicate()
        return None, out.decode("utf-8", "replace"), True


def _tail(s: str) -> str:
    return s[-TAIL:]


def _ignore_args(acceptance: list[str]) -> list[str]:
    paths: list[str] = []
    for a in acceptance:
        p = a.split("::", 1)[0]
        if p and p not in paths:
            paths.append(p)
    return [f"--ignore={p}" for p in paths]


def grade(spec: dict) -> dict:
    t0 = time.monotonic()
    cwd = spec.get("cwd", "/work")
    timeout = float(spec.get("timeout_s", 900))
    custom = spec.get("custom_grader")
    if custom:
        rc, out, to = _run([custom], cwd, timeout)
        res: dict = {}
        try:
            lines = out.strip().splitlines()
            parsed = json.loads(lines[-1]) if lines else {}
            res = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            res = {}
        if to or not res:
            res.setdefault("acceptance_pass", False)
            res.setdefault("regression_pass", False)
            res["note"] = "custom grader timed out" if to else "custom grader produced no JSON"
        res.setdefault("grader_rc", rc)
        res.setdefault("acceptance_pass", None)
        res.setdefault("regression_pass", None)
        res.setdefault("acceptance_tail", "")
        res.setdefault("regression_tail", _tail(out))
        res["duration_s"] = time.monotonic() - t0
        return res

    notes: list[str] = []
    acceptance = list(spec.get("acceptance") or [])
    result: dict = {"acceptance_pass": None, "regression_pass": None, "acceptance_rc": None,
                    "regression_rc": None, "acceptance_tail": "", "regression_tail": ""}
    acc_cmd = spec.get("acceptance_cmd")
    if acc_cmd:
        # The project's own runner (e.g. `python -m unittest tests.x`); exit code 0 means pass.
        rc, out, to = _run(acc_cmd, cwd, timeout, shell=True)
        result.update(acceptance_rc=rc, acceptance_tail=_tail(out), acceptance_pass=(rc == 0))
        if to:
            notes.append("acceptance timed out")
    elif acceptance:
        extra = list(spec.get("acceptance_args") or [])
        rc, out, to = _run([PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra, *acceptance], cwd,
                           timeout)
        result.update(acceptance_rc=rc, acceptance_tail=_tail(out), acceptance_pass=(rc == 0))
        if to:
            notes.append("acceptance timed out")
    else:
        notes.append("no acceptance tests listed")

    reg = spec.get("regression")
    if reg:
        # --ignore is a pytest flag; other runners (e.g. tornado.test.runtests) would reject it.
        ignore = _ignore_args(acceptance) if "pytest" in reg else []
        cmd = (reg + " " + " ".join(ignore)).strip()
        rc, out, to = _run(cmd, cwd, timeout, shell=True)
        result.update(regression_rc=rc, regression_tail=_tail(out))
        if to:
            result["regression_pass"] = False
            notes.append("regression timed out")
        elif rc == 5:
            result["regression_pass"] = None
            notes.append("regression: no tests collected")
        else:
            result["regression_pass"] = rc == 0
    if notes:
        result["note"] = "; ".join(notes)
    result["duration_s"] = time.monotonic() - t0
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: hai_proof_grade.py <spec.json>", file=sys.stderr)
        return 2
    spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    print(json.dumps(grade(spec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
