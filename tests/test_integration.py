"""End-to-end orchestration test: Runner → trial → analyses → report, against a fake Docker executor."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from hai_proof import cli
from hai_proof.analyses_spec import load_analysis
from hai_proof.models import PLAIN, ArmSpec, Limits, Requirement, RunConfig, TreatmentSpec
from hai_proof.report import load_run
from hai_proof.runner import Runner, make_plan
from hai_proof.tasks import load_task
from hai_proof.trial import GRADE, WRAP

ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-ant-test-SECRET-value"


def _cp(stdout: bytes | str = b"", rc: int = 0) -> subprocess.CompletedProcess:
    out = stdout.encode() if isinstance(stdout, str) else stdout
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=b"")


def _tar(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _session_jsonl() -> str:
    rows = [
        {"type": "user", "timestamp": "2026-10-09T10:00:00Z", "origin": {"kind": "human"},
         "message": {"role": "user", "content": "fix the bug"}},
        {"type": "assistant", "timestamp": "2026-10-09T10:00:05Z", "requestId": "r1",
         "message": {"model": "m", "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100},
                     "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"type": "user", "timestamp": "2026-10-09T10:00:09Z", "toolUseResult": {"stdout": "1 failed"},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "1 failed"}]}},
        {"type": "assistant", "timestamp": "2026-10-09T10:00:12Z", "requestId": "r2",
         "message": {"model": "m", "usage": {"input_tokens": 12, "output_tokens": 9, "cache_read_input_tokens": 150},
                     "content": [{"type": "tool_use", "id": "t2", "name": "Agent",
                                  "input": {"subagent_type": "Explore", "description": "find it", "prompt": "p"}}]}},
        {"type": "user", "timestamp": "2026-10-09T10:01:00Z", "toolUseResult": {"agentId": "ag1", "status": "completed"},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "found"}]}},
        {"type": "assistant", "timestamp": "2026-10-09T10:01:05Z", "requestId": "r3",
         "message": {"model": "m", "usage": {"input_tokens": 3, "output_tokens": 7, "cache_read_input_tokens": 400},
                     "content": [{"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "/work/a.py"}}]}},
        {"type": "user", "timestamp": "2026-10-09T10:01:06Z",
         "toolUseResult": {"filePath": "/work/a.py", "structuredPatch": [{"lines": ["-x = 1", "+x = 2", " y"]}]},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t3", "content": "ok"}]}},
    ]
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def _subagent_jsonl() -> str:
    rows = [
        {"type": "user", "timestamp": "2026-10-09T10:00:13Z", "isSidechain": True, "agentId": "ag1",
         "message": {"role": "user", "content": "find it"}},
        {"type": "assistant", "timestamp": "2026-10-09T10:00:20Z", "requestId": "s1", "isSidechain": True,
         "message": {"model": "m", "usage": {"input_tokens": 5, "output_tokens": 3},
                     "content": [{"type": "tool_use", "id": "u1", "name": "Grep", "input": {"pattern": "bug"}}]}},
        {"type": "user", "timestamp": "2026-10-09T10:00:21Z", "isSidechain": True,
         "message": {"content": [{"type": "tool_result", "tool_use_id": "u1", "content": "a.py:1", "is_error": True}]}},
    ]
    return "\n".join(json.dumps(r) for r in rows) + "\n"


USAGE_LIMIT_RESULT = {"type": "result", "subtype": "success", "is_error": True, "num_turns": 1,
                      "total_cost_usd": 0, "terminal_reason": "api_error", "api_error_status": 429,
                      "api_error": "usage_limit_reached", "result": "You've hit your session limit",
                      "api_error_params": {"rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"}}}


def _transcript(*, plugins: list, cost: float, rate_limited: bool = False, bash: str = "pytest -q",
                usage_limit: dict | None = None) -> str:
    init = {"type": "system", "subtype": "init", "model": "m", "tools": ["Bash"], "mcp_servers": [],
            "plugins": plugins}
    asst = {"type": "assistant", "parent_tool_use_id": None,
            "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": bash}}],
                        "usage": {"input_tokens": 5, "output_tokens": 1, "cache_creation_input_tokens": 1000,
                                  "cache_read_input_tokens": 0}}}
    if usage_limit is not None:
        res = usage_limit
    elif rate_limited:
        res = {"type": "result", "subtype": "error_during_execution", "is_error": True,
               "result": "API Error: 429 rate_limit_error", "total_cost_usd": 0.01, "num_turns": 1}
    else:
        res = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1000,
               "duration_api_ms": 800, "num_turns": 3, "result": "Fixed.", "total_cost_usd": cost,
               "modelUsage": {"m": {"inputTokens": int(cost * 1e5), "outputTokens": 100,
                                    "cacheReadInputTokens": 0, "cacheCreationInputTokens": 1000}}}
    return "\n".join(json.dumps(e) for e in (init, asst, res)) + "\n"


class FakeDocker:
    """Just enough Docker semantics for the orchestration layer."""

    def __init__(self, *, rate_limit_once: str | None = None, image_has_tools: str = "", auth_code: str = "200",
                 usage_limit_once: str | None = None, usage_limit_result: dict | None = None):
        self.auth_code = auth_code
        self.usage_limit_once = usage_limit_once  # container-name fragment to hit the usage limit once
        self.usage_limit_result = usage_limit_result
        self.name = "fake"
        self.calls: list[tuple] = []
        self.containers: dict[str, dict] = {}
        self.images: set[str] = set()
        self.secret_envs: list[dict] = []
        self.rate_limit_once = rate_limit_once  # container-name fragment to rate-limit once
        self.image_has_tools = image_has_tools
        self._n = 0

    # -- primitives used by images/runner
    def docker(self, args, *, input=None, timeout=None, check=True):
        self.calls.append(("docker", list(args)))
        if args[:2] == ["run", "--rm"] and "npm" in args:
            return _cp("2.1.289\n")
        if args[:2] == ["run", "--rm"]:
            return _cp(self.image_has_tools)
        if args[:2] == ["image", "inspect"]:
            return _cp("sha256:abc\n")
        if args[0] == "info":
            return _cp("8|17179869184|x86_64|27.0.0\n")
        return _cp()

    def image_exists(self, tag):
        return tag in self.images

    def build_image(self, tag, context_tar, *, dockerfile="Dockerfile", build_args=None, timeout=3600):
        self.calls.append(("build", tag))
        self.images.add(tag)

    def run_detached(self, run_args, *, secret_env=None):
        self.calls.append(("run", list(run_args)))
        self.secret_envs.append(dict(secret_env or {}))
        self._n += 1
        cid = f"c{self._n}"
        name = run_args[run_args.index("--name") + 1] if "--name" in run_args else cid
        self.containers[cid] = {"name": name, "done": False, "puts": [], "analysis_done": set()}
        return cid

    def put_tar(self, container, dest_dir, tar_bytes):
        self.calls.append(("put", container, dest_dir))
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
            self.containers[container]["puts"].append((dest_dir, t.getnames()))
            if dest_dir == "/tp" and "prompt.md" in t.getnames():
                self.containers[container]["prompt"] = t.extractfile("prompt.md").read().decode()

    def exec(self, container, cmd, *, user="agent", workdir=None, env=None, input=None, timeout=None,
             check=True, detach=False):
        self.calls.append(("exec", container, list(cmd), user))
        c = self.containers[container]
        if cmd[:2] == ["/usr/local/bin/python3", WRAP] and cmd[2] == "/tp/agent.json":
            c["done"] = True
            return _cp()
        if cmd[:2] == ["/usr/local/bin/python3", WRAP]:
            c["analysis_done"].add(cmd[2].rsplit("/", 1)[0])
            return _cp()
        if cmd[:2] == ["sh", "-c"] and "v1/models" in cmd[2]:
            assert SECRET not in cmd[2]  # expanded inside the container, never on the command line
            return _cp(self.auth_code)
        if cmd[:2] == ["test", "-f"]:
            return _cp(rc=0 if c["done"] else 1)
        if cmd[:2] == ["/usr/local/bin/python3", GRADE]:
            return _cp(json.dumps({"acceptance_pass": True, "regression_pass": True}) + "\n")
        if cmd[:2] == ["bash", "-c"] and "--numstat" in cmd[2]:
            return _cp("3\t1\tsrc/inventory/store.py\n10\t0\tROADMAP.md\n2\t0\t.beads/issues.jsonl\n")
        return _cp()

    def get_tar(self, container, src_path):
        c = self.containers[container]
        name = c["name"]
        if src_path == "/out/agent":
            is_b = "-b-" in name
            rl = bool(self.rate_limit_once and self.rate_limit_once in name)
            if rl:
                self.rate_limit_once = None
            ul = None
            if self.usage_limit_once and self.usage_limit_once in name:
                self.usage_limit_once = None
                ul = self.usage_limit_result
            text = _transcript(plugins=[], cost=0.30 if is_b else 0.20, rate_limited=rl,
                               bash="bd ready && pytest -q" if is_b else "pytest -q", usage_limit=ul)
            timing = {"wall_s": 90.0 if is_b else 60.0, "exit_code": 0, "timed_out": False}
            return _tar({"agent/transcript.jsonl": text, "agent/timing.json": json.dumps(timing),
                         "agent/stderr.log": "", "agent/done": ""})
        if src_path == "/home/agent/.claude":
            return _tar({".claude/projects/-work/s1.jsonl": _session_jsonl(),
                         ".claude/projects/-work/s1/subagents/agent-ag1.jsonl": _subagent_jsonl(),
                         ".claude/.credentials.json": '{"claudeAiOauth": "x"}',
                         ".claude/shell-snapshots/snap.sh": f"export ANTHROPIC_API_KEY={SECRET}\n"})
        if src_path == "/home/agent/.claude.json":
            return _tar({".claude.json": json.dumps({"primaryApiKey": SECRET, "numStartups": 3})})
        base = src_path.rsplit("/", 1)[-1]  # run-<analysis name>
        res = {"type": "result", "subtype": "success", "is_error": False, "result": f"# Report {base}\nok",
               "total_cost_usd": 0.05, "modelUsage": {"m": {"inputTokens": 10, "outputTokens": 10}}}
        return _tar({f"{base}/transcript.jsonl": json.dumps(res) + "\n",
                     f"{base}/timing.json": json.dumps({"wall_s": 5.0, "exit_code": 0})})

    def remove(self, container):
        self.calls.append(("rm", container))

    def network_create(self, name, *, internal=False):
        self.calls.append(("netcreate", name, internal))

    def network_remove(self, name):
        self.calls.append(("netrm", name))

    def network_connect(self, network, container):
        self.calls.append(("netconnect", network, container))

    def network_disconnect(self, network, container):
        self.calls.append(("netdisconnect", network, container))


def _treatment(tmp_path: Path) -> TreatmentSpec:
    d = tmp_path / "treat"
    (d / "user").mkdir(parents=True)
    (d / "user" / "CLAUDE.md").write_text("Always use beads.\n")
    return TreatmentSpec(name="beads", path=d, requires=(Requirement("bd", "npm i -g x", "bd --version"),),
                         artifacts=(".beads/",))


def _run_config(tmp_path: Path, arms, *, reps=2, analyses=True) -> RunConfig:
    task = load_task(ROOT / "examples" / "tasks" / "example-bug")
    specs = [load_analysis("non-code-changes", search_dirs=[ROOT / "analyses"]),
             load_analysis("non-code-changes-arm", search_dirs=[ROOT / "analyses"])] if analyses else []
    return RunConfig(run_id="test-run", host="fake", arms=arms, tasks=[task], reps=reps, mode="custom",
                     model="claude-test-model", cli_version="latest", analyses=specs, probe_runs=1,
                     limits=Limits(cpus=2, memory="4g"), results_dir=tmp_path / "results")


def _trials(run_dir: Path):
    """Trials with later records overriding earlier ones (the append-only log semantics)."""
    return load_run(run_dir)[1]


def test_comparative_run_end_to_end(tmp_path):
    fake = FakeDocker(rate_limit_once="-b-ex1-rep0")
    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))])
    run_dir = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()

    # secrets only ever travel via secret_env, never on an argv
    for call in fake.calls:
        assert SECRET not in json.dumps(call)
    assert all(e.get("ANTHROPIC_API_KEY") == SECRET for e in fake.secret_envs if e)

    trials = _trials(run_dir)
    scored = [t for t in trials if t.rep >= 0]
    # rate-limited pair was discarded (both members) and rerun
    assert any(t.rate_limited and t.status == "discarded" for t in scored)
    assert any(t.status == "discarded" and t.error and "partner" in t.error for t in scored)
    final_ok = [t for t in scored if t.status == "ok"]
    assert sorted((t.arm, t.rep) for t in final_ok) == [("A", 0), ("A", 1), ("B", 0), ("B", 1)]
    for t in final_ok:
        assert t.success and t.isolation_problems == []
        # .beads/ is a declared artifact only for B; for the plain arm it is ordinary planning churn
        expect = (1, 1) if t.arm == "B" else (2, 0)
        assert (t.diff_breakdown["planning"]["files"], t.diff_breakdown["treatment_artifact"]["files"]) == expect
        assert [a.ok for a in t.analyses] == [True]
    # Claude Code's own data: collected, parsed, credentials dropped, secrets scrubbed
    for t in final_ok:
        tdir = run_dir / t.artifacts_dir
        assert t.session["tool_calls"] == 4 and t.session["subagents"] == 1
        assert t.session["subagent_tool_calls"] == 1 and t.session["tool_errors"] == 1
        assert t.session["files_edited"] == 1 and t.session["peak_context"] == 403
        assert (tdir / "session.html").is_file() and (tdir / "claude_data.json").is_file()
        home = tdir / "claude_home"
        assert (home / "projects" / "-work" / "s1.jsonl").is_file()
        assert not (home / ".credentials.json").exists()
        for f in home.rglob("*"):
            if f.is_file():
                assert SECRET not in f.read_text(encoding="utf-8")
        cfg = json.loads((home / "claude.json.redacted").read_text())
        assert cfg == {"primaryApiKey": "<redacted>", "numStartups": 3}
    assert "session.html" in (run_dir / "report.html").read_text(encoding="utf-8")
    # cross-run comparison over the collected sessions
    from hai_proof.sessions_compare import compare, render_html

    rows = compare([run_dir])
    assert len(rows) == len(final_ok)  # a discarded pair is rerun into the same rep directory
    row = next(r for r in rows if r["success"])
    assert row["session"]["first_edit_s"] == 65.0  # the Edit call at 10:01:05 after the 10:00:00 prompt
    assert row["session"]["test_runs"] == 1 and row["session"]["edit_calls"] == 1
    assert [p for _, _, p, *_ in row["timeline"]] == ["test", "delegate", "edit"]
    assert "Timeline" in render_html(rows)
    b = next(t for t in final_ok if t.arm == "B")
    assert b.dependency_used == {"bd": True}
    assert {t.rep for t in trials} >= {-1, -2}  # warm-up and probe recorded

    # treatment overlay went to the config dir; the plain arm got none
    puts = {c["name"]: c["puts"] for c in fake.containers.values()}
    assert any(d == "/home/agent/.claude" for n, p in puts.items() if "-b-" in n for d, _ in p)
    assert not any(d == "/home/agent/.claude" for n, p in puts.items() if "-a-" in n for d, _ in p)

    # egress: one internal network + proxy per arm, grading disconnects it
    assert sum(1 for c in fake.calls if c[0] == "netcreate" and c[2]) == 2
    assert any(c[0] == "netdisconnect" for c in fake.calls)

    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["results"]["arms"]["B"]["runs"] > 0
    assert summary["ratios"]["cost_usd"]["gm_ratio"] == pytest.approx(1.5, rel=1e-6)
    assert (run_dir / "report.html").is_file()
    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["cli_version"] == "2.1.289" and meta["finished_at"]
    assert set(meta["arm_analyses"]) == {"A", "B"}
    assert (run_dir / "arms" / "B" / "analysis-non-code-changes-arm.md").read_text().startswith("# Report")


def test_spend_cap_stops_cleanly(tmp_path):
    fake = FakeDocker()
    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))], analyses=False)
    run.max_spend_usd = 0.0001  # the warm-up pair alone uses it up
    logs = []
    run_dir = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=logs.append).execute()
    meta = json.loads((run_dir / "run.json").read_text())
    assert "cap" in meta["stopped_early"] and "aborted" not in meta and meta["finished_at"]
    trials = _trials(run_dir)
    assert {t.rep for t in trials} == {-1}  # only the warm-up ran
    assert (run_dir / "report.html").is_file() and (run_dir / "resources.jsonl").is_file()
    assert any(m.startswith("stopping: spend") for m in logs)
    assert not [c for c in fake.containers.values() if c.get("running")]


def _usage_result(resets_at):
    res = json.loads(json.dumps(USAGE_LIMIT_RESULT))
    if resets_at is not None:
        res["api_error_params"]["rate_limit_info"]["resetsAt"] = resets_at
    return res


def test_usage_limit_waits_for_reset_and_reruns_pair(tmp_path):
    fake = FakeDocker(usage_limit_once="-b-ex1-rep0", usage_limit_result=_usage_result(10_000))
    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))], analyses=False)
    logs, sleeps = [], []
    r = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=logs.append)
    r.now = lambda: 10_000 - 3600.0  # the limit resets in an hour
    r.sleep = sleeps.append
    run_dir = r.execute()
    assert sleeps == [3600.0 + 120]
    trials = _trials(run_dir)
    scored = [t for t in trials if t.rep >= 0]
    assert any(t.status == "discarded" and t.usage_limit_resets_at == 10_000 for t in scored)
    assert any(t.status == "discarded" and "usage limit" in (t.error or "") and t.arm == "A" for t in scored)
    assert sorted((t.arm, t.rep) for t in scored if t.status == "ok") == [("A", 0), ("A", 1), ("B", 0), ("B", 1)]
    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["usage_limit_waits"][0]["wait_s"] == 3720 and "stopped_early" not in meta
    assert any("waiting 62 min" in m for m in logs)


def test_usage_limit_without_reset_stops_cleanly(tmp_path):
    fake = FakeDocker(usage_limit_once="-b-ex1-rep0", usage_limit_result=_usage_result(None))
    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))], analyses=False)
    r = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None)
    r.sleep = lambda s: (_ for _ in ()).throw(AssertionError("must not wait"))
    run_dir = r.execute()
    meta = json.loads((run_dir / "run.json").read_text())
    assert "usage limit" in meta["stopped_early"] and "aborted" not in meta
    assert (run_dir / "report.html").is_file()
    assert not [t for t in _trials(run_dir) if t.rep >= 0 and t.status == "ok" and t.task_id == "ex1"
                and t.rep == 0]


def test_resume_skips_finished_pairs(tmp_path):
    import dataclasses

    arms = [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))]
    run = _run_config(tmp_path, arms, reps=2, analyses=False)
    run_dir = Runner(run, FakeDocker(), {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    # simulate a controller killed during rep 1: drop rep 1's records, leave its trial dirs behind
    lines = (run_dir / "trials.jsonl").read_text().splitlines()
    keep = [ln for ln in lines if json.loads(ln)["rep"] != 1]
    (run_dir / "trials.jsonl").write_text("".join(ln + chr(10) for ln in keep))
    assert (run_dir / "trials" / "A" / "EX1" / "rep1" / "agent" / "transcript.jsonl").is_file()

    fake = FakeDocker()
    logs = []
    resumed = dataclasses.replace(run, resume=True, max_spend_usd=100.0)
    Runner(resumed, fake, {"ANTHROPIC_API_KEY": SECRET}, log=logs.append).execute()
    trials = _trials(run_dir)
    assert sorted((t.arm, t.rep) for t in trials if t.scored) == [("A", 0), ("A", 1), ("B", 0), ("B", 1)]
    # only rep 1 ran again: no warm-up, no probe, no second rep-0 pair
    runs = [c for c in fake.calls if c and c[0] == "run" and any("-ex1-" in str(x) for x in c)]
    assert runs and all("rep1" in json.dumps(c) for c in runs)
    meta = json.loads((run_dir / "run.json").read_text())
    (res,) = meta["resumes"]
    assert res["pairs_done"] == 1 and {o["trial"] for o in res["orphaned"]} == {"trials/A/EX1/rep1", "trials/B/EX1/rep1"}
    assert all(o["cost_usd"] > 0 for o in res["orphaned"])
    assert (run_dir / res["orphaned"][0]["moved_to"] / "agent" / "transcript.jsonl").is_file()
    assert any(m.startswith("resuming test-run: 1 pairs done") for m in logs)


def test_resume_rejects_changed_config(tmp_path):
    import dataclasses

    from hai_proof.runner import ResumeMismatch

    arms = [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))]
    run = _run_config(tmp_path, arms, reps=1, analyses=False)
    run_dir = Runner(run, FakeDocker(), {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    before = (run_dir / "run.json").read_text()
    with pytest.raises(ResumeMismatch, match="model"):
        Runner(dataclasses.replace(run, resume=True, model="other-model"), FakeDocker(),
               {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    assert (run_dir / "run.json").read_text() == before


def test_single_arm_run(tmp_path):
    fake = FakeDocker()
    run = _run_config(tmp_path, [ArmSpec("A", _treatment(tmp_path))], reps=1, analyses=False)
    run_dir = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["ratios"] == {}
    # single-arm trials are never run concurrently: no pair has two members
    assert all(t.arm == "A" for t in _trials(run_dir))


def test_prompt_variant_arm(tmp_path):
    import shutil

    task_dir = tmp_path / "tasks" / "example-bug"
    shutil.copytree(ROOT / "examples" / "tasks" / "example-bug", task_dir)
    (task_dir / "prompts").mkdir()
    (task_dir / "prompts" / "degraded.md").write_text("The report, minus one detail.\n")
    tdir = tmp_path / "degraded-prompt"
    tdir.mkdir()
    (tdir / "manifest.toml").write_text('prompt_variant = "degraded"\n')
    from hai_proof.treatments import load_treatment

    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", load_treatment(tdir))], reps=1, analyses=False)
    run = RunConfig(**{**run.__dict__, "tasks": [load_task(task_dir)]})
    fake = FakeDocker()
    Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    prompts = {c["name"]: c.get("prompt") for c in fake.containers.values() if "-rep0-" in c["name"]}
    a = [p for n, p in prompts.items() if "-a-" in n]
    b = [p for n, p in prompts.items() if "-b-" in n]
    assert a and b
    assert all(p == run.tasks[0].prompt for p in a)
    assert all(p == "The report, minus one detail." for p in b)


def test_cli_rejects_missing_prompt_variant(tmp_path, capsys):
    tasks = tmp_path / "tasks"
    import shutil

    shutil.copytree(ROOT / "examples" / "tasks" / "example-bug", tasks / "example-bug")
    (tmp_path / "treatments" / "degraded-prompt").mkdir(parents=True)
    (tmp_path / "treatments" / "degraded-prompt" / "manifest.toml").write_text('prompt_variant = "degraded"\n')
    (tmp_path / "hai-proof.toml").write_text('model = "claude-test-model"\n')
    rc = cli.main(["--root", str(tmp_path), "run", "--treatment", "degraded-prompt", "--reps", "1", "--dry-run"])
    err = capsys.readouterr()
    assert rc == 2 and "prompts/degraded.md" in err.out + err.err


def test_preflight_rejects_tool_leaking_into_control(tmp_path):
    fake = FakeDocker(image_has_tools="bd\n")
    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))], analyses=False)
    with pytest.raises(RuntimeError, match="unexpectedly contains"):
        Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()


def test_plan_counts(tmp_path):
    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", _treatment(tmp_path))], reps=5)
    plan = make_plan(run)
    assert plan.agent_runs == 10 and plan.probe_runs == 2 and plan.warmup_runs == 2
    assert plan.analysis_sessions == 10 + 2
    assert plan.budget_ceiling_usd > 0


def test_cli_dry_run(tmp_path, capsys):
    (tmp_path / "hai-proof.toml").write_text(
        f'model = "claude-test-model"\ntasks_dir = "{(ROOT / "examples" / "tasks").as_posix()}"\n'
        f'treatments_dir = "{(ROOT / "examples" / "treatments").as_posix()}"\n')
    rc = cli.main(["--root", str(tmp_path), "run", "--treatment", "openspec-beads", "--mode", "lightning",
                   "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and "shape=comparative" in out and "agent runs: 2" in out
    rc = cli.main(["--root", str(tmp_path), "run", "--arm-a", "plain", "--arm-b", "plain", "--dry-run"])
    assert rc == 0 and "shape=ab" in capsys.readouterr().out
    assert cli.main(["--root", str(tmp_path), "run", "--dry-run"]) == 2  # no arms chosen


def test_rejected_key_stops_before_any_trial(tmp_path):
    from hai_proof.runner import AuthError

    fake = FakeDocker(auth_code="401")
    run = _run_config(tmp_path, [ArmSpec("A", PLAIN), ArmSpec("B", PLAIN)], analyses=False)
    with pytest.raises(AuthError, match="HTTP 401"):
        Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    assert not (tmp_path / "results" / "test-run" / "trials.jsonl").exists()
    meta = json.loads((tmp_path / "results" / "test-run" / "run.json").read_text())
    assert "401" in meta["aborted"]


# --------------------------------------------------------------------------- user in the loop (DESIGN §3.8)

BRIEF = "I want the totals in cents, never floats."


class LoopDocker(FakeDocker):
    """FakeDocker plus per-call agent turns (/out/turns/NN) and the stand-in's `claude -p` calls."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.files: dict[str, dict[str, str]] = {}  # container -> path -> text, from every put_tar

    def put_tar(self, container, dest_dir, tar_bytes):
        super().put_tar(container, dest_dir, tar_bytes)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
            for m in t.getmembers():
                f = t.extractfile(m)
                if f is not None:
                    self.files.setdefault(container, {})[f"{dest_dir}/{m.name}"] = f.read().decode(errors="replace")

    def exec(self, container, cmd, *, user="agent", workdir=None, env=None, input=None, timeout=None,
             check=True, detach=False):
        c = self.containers[container]
        if cmd[:2] == ["/usr/local/bin/python3", WRAP] and "/tp/turn" in cmd[2]:
            self.calls.append(("exec", container, list(cmd), user))
            c.setdefault("turns", []).append(cmd[2])
            c["done"] = True
            return _cp()
        if cmd[:2] == ["bash", "-c"] and "claude -p --safe-mode" in cmd[2]:
            self.calls.append(("exec", container, list(cmd), user))
            d = cmd[2].split("cd ", 1)[1].split(" ", 1)[0]
            prompt = self.files[container][f"/si/{d[4:]}/prompt.txt"]
            if "WAITING for the user, or DONE" in prompt:
                out = "WAITING" if "QUESTION" in prompt.split("The agent's final message:", 1)[1] else "DONE"
            else:
                out = "B. Cents, as the brief says."
            return _cp(json.dumps({"type": "result", "result": out, "total_cost_usd": 0.001, "is_error": False}))
        return super().exec(container, cmd, user=user, workdir=workdir, env=env, input=input, timeout=timeout,
                            check=check, detach=detach)

    def get_tar(self, container, src_path):
        if src_path.startswith("/out/turns/"):
            tag = src_path.rsplit("/", 1)[-1]
            n = int(tag)
            final = "QUESTION: A) floats or B) cents?" if n == 0 else "Done."
            init = {"type": "system", "subtype": "init", "model": "m", "tools": ["Bash"], "mcp_servers": [],
                    "plugins": []}
            res = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "result": final,
                   "total_cost_usd": 0.1 * (n + 1), "duration_api_ms": 500,
                   "modelUsage": {"m": {"inputTokens": 10 * (n + 1), "outputTokens": 5 * (n + 1)}}}
            text = "\n".join(json.dumps(e) for e in (init, res)) + "\n"
            timing = {"wall_s": 30.0, "exit_code": 0, "timed_out": False,
                      "started_at": f"t{n}", "ended_at": f"t{n}e"}
            return _tar({f"{tag}/transcript.jsonl": text, f"{tag}/timing.json": json.dumps(timing),
                         f"{tag}/stderr.log": "", f"{tag}/done": ""})
        return super().get_tar(container, src_path)


def test_user_in_the_loop_run(tmp_path):
    import shutil

    from hai_proof.treatments import load_treatment

    task_dir = tmp_path / "tasks" / "example-bug"
    shutil.copytree(ROOT / "examples" / "tasks" / "example-bug", task_dir)
    (task_dir / "user.md").write_text(BRIEF + "\n")
    tdir = tmp_path / "planner"
    tdir.mkdir()
    (tdir / "manifest.toml").write_text('[workflow]\nturns = ["/plan {task_prompt}", "/apply"]\n')
    arms = [ArmSpec("A", PLAIN), ArmSpec("B", load_treatment(tdir), "informative")]
    run = _run_config(tmp_path, arms, reps=1, analyses=False)
    run = RunConfig(**{**run.__dict__, "tasks": [load_task(task_dir)], "stand_in_model": "claude-si"})
    fake = LoopDocker()
    run_dir = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()

    trials = {(t.arm, t.rep): t for t in _trials(run_dir)}
    a, b = trials[("A", 0)], trials[("B", 0)]
    # arm A is the conventional single session: unchanged path, no loop record
    assert a.user_loop == {} and not (run_dir / a.artifacts_dir / "user_loop.json").exists()
    assert b.status == "ok" and b.success
    assert b.user_loop["mode"] == "informative" and b.user_loop["stop_reason"] == "completed"
    assert (b.user_loop["agent_calls"], b.user_loop["scripted_turns"], b.user_loop["user_replies"]) == (3, 2, 1)
    # session totals come from the last call's result (Claude Code carries them across --resume)
    assert b.metrics.cost_usd == pytest.approx(0.3) and b.metrics.turns == 6 and b.metrics.wall_s == 90.0
    assert b.metrics.tokens_output == 15

    bc = next(cid for cid, c in fake.containers.items() if c["name"].endswith("-rep0-" + c["name"][-6:])
              and "-b-" in c["name"] and "turns" in c)
    msgs = [fake.files[bc][f"/tp/turn{n:02d}.md"] for n in range(3)]
    assert msgs == ["/plan " + run.tasks[0].prompt, "B. Cents, as the brief says.", "/apply"]
    specs = [json.loads(fake.files[bc][f"/tp/turn{n:02d}.json"]) for n in range(3)]
    sid = specs[0]["argv"][specs[0]["argv"].index("--session-id") + 1]
    assert all(s["argv"][s["argv"].index("--resume") + 1] == sid for s in specs[1:])
    assert [s["argv"][s["argv"].index("--max-budget-usd") + 1] for s in specs] == ["2.00", "1.90", "1.80"]
    # the brief only ever reaches the stand-in container, never an agent container
    agent_cids = [cid for cid, c in fake.containers.items() if "-user" not in c["name"]]
    assert not any(BRIEF in text for cid in agent_cids for text in fake.files.get(cid, {}).values())
    si = [cid for cid, c in fake.containers.items() if c["name"].endswith("-user")]
    assert si and any(BRIEF in text for text in fake.files[si[0]].values())
    assert ("rm", si[0]) in fake.calls
    si_run = next(c for c in fake.calls if c[0] == "run" and c[1][1].endswith("-user"))
    assert "--network" in si_run[1] and SECRET not in json.dumps(si_run)

    tdir_b = run_dir / b.artifacts_dir
    log = json.loads((tdir_b / "user_loop.json").read_text())
    assert [t["decision"] for t in log["turns"]] == ["waiting", "done", "done"]
    assert (tdir_b / "agent" / "turns" / "02" / "transcript.jsonl").is_file()
    assert json.loads((tdir_b / "agent" / "timing.json").read_text())["calls"] == 3

    summary = json.loads((run_dir / "summary.json").read_text())
    ul = summary["user_loop"]
    assert set(ul) == {"B"} and ul["B"]["user_replies"] == 1 and ul["B"]["passes_with_replies"] == 1
    meta = json.loads((run_dir / "run.json").read_text())
    assert [a["user"] for a in meta["arms"]] == ["conventional", "informative"]
    assert meta["user_loop"] == {"stand_in_model": "claude-si", "max_user_replies": 5}
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "User in the loop" in html and "planner (informative)" in html and "user_loop.json" in html

    # plain arms with a stand-in never feed the long-run baselines
    from hai_proof.baselines import plain_labels

    assert plain_labels(meta) == {"A"}
    assert plain_labels({"arms": [{"label": "A", "treatment": "plain", "user": "uninformative"}]}) == set()


ASK = {"questions": [{"question": "Floats or cents?", "header": "Money", "multiSelect": False,
                      "options": [{"label": "Floats"}, {"label": "Cents"}]}]}


class AskDocker(LoopDocker):
    """LoopDocker whose agent calls ask one AskUserQuestion through the wrapper's mailbox."""

    def exec(self, container, cmd, *, user="agent", workdir=None, env=None, input=None, timeout=None,
             check=True, detach=False):
        files = self.files.get(container, {})
        if cmd[:2] == ["sh", "-c"] and "/ask" in cmd[2]:
            out_dir = cmd[2].split("test -f ", 1)[1].split("/done", 1)[0]
            answered = any(p.startswith(f"{out_dir}/ask/") and p.endswith(".answer.json") for p in files)
            return _cp("DONE\n000.json\n" if answered else "000.json\n")
        if cmd[0] == "cat" and cmd[1].endswith("/ask/000.json"):
            return _cp(json.dumps(ASK))
        if cmd[:2] == ["bash", "-c"] and "claude -p --safe-mode" in cmd[2]:
            d = cmd[2].split("cd ", 1)[1].split(" ", 1)[0]
            if "question tool" in self.files[container][f"/si/{d[4:]}/prompt.txt"]:
                self.calls.append(("exec", container, list(cmd), user))
                return _cp(json.dumps({"type": "result", "result": "1: Cents", "total_cost_usd": 0.002,
                                       "is_error": False}))
        return super().exec(container, cmd, user=user, workdir=workdir, env=env, input=input, timeout=timeout,
                            check=check, detach=detach)


def test_ask_tool_run(tmp_path):
    import shutil

    task_dir = tmp_path / "tasks" / "example-bug"
    shutil.copytree(ROOT / "examples" / "tasks" / "example-bug", task_dir)
    (task_dir / "user.md").write_text(BRIEF + "\n")
    arms = [ArmSpec("A", PLAIN, "informative"), ArmSpec("B", PLAIN, "informative", ask_tool="on")]
    run = _run_config(tmp_path, arms, reps=1, analyses=False)
    run = RunConfig(**{**run.__dict__, "tasks": [load_task(task_dir)], "stand_in_model": "claude-si"})
    fake = AskDocker()
    run_dir = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()

    b = next(t for t in _trials(run_dir) if t.arm == "B" and t.rep == 0)
    assert b.status == "ok" and b.user_loop["tool_question_calls"] == 2 and b.user_loop["tool_questions"] == 2
    bc = next(cid for cid, c in fake.containers.items() if "-b-" in c["name"] and "turns" in c
              and not c["name"].endswith("-user"))
    spec = json.loads(fake.files[bc]["/tp/turn00.json"])
    argv = spec["argv"]
    assert argv[:2] == ["claude", "-p"] and "<prompt>" not in argv and spec["prompt_arg_index"] is None
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    assert spec["stdio"]["ask_dir"] == "/out/turns/00/ask"
    assert json.loads(fake.files[bc]["/out/turns/00/ask/000.answer.json"]) == {"answers": {"Floats or cents?": "Cents"}}
    log = json.loads((run_dir / b.artifacts_dir / "user_loop.json").read_text())
    assert log["turns"][0]["tool_questions"][0]["source"] == "stand-in"
    # arm A never gets the stdio flags
    ac = next(cid for cid, c in fake.containers.items() if "-a-" in c["name"] and "turns" in c
              and not c["name"].endswith("-user"))
    assert "--permission-prompt-tool" not in json.loads(fake.files[ac]["/tp/turn00.json"])["argv"]
    meta = json.loads((run_dir / "run.json").read_text())
    assert [a["ask_tool"] for a in meta["arms"]] == ["off", "on"]
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "plain (informative, ask tool)" in html and "Tool questions" in html
    ul = json.loads((run_dir / "summary.json").read_text())["user_loop"]
    assert ul["B"]["tool_questions"] == 2 and ul["B"]["trials_asking"] == 1 and ul["B"]["passes_asking"] == 1


def test_ask_tool_hidden_uses_the_same_input_mode_without_the_tool(tmp_path):
    import shutil

    task_dir = tmp_path / "tasks" / "example-bug"
    shutil.copytree(ROOT / "examples" / "tasks" / "example-bug", task_dir)
    arms = [ArmSpec("A", PLAIN, ask_tool="hidden"), ArmSpec("B", PLAIN, ask_tool="on")]
    run = _run_config(tmp_path, arms, reps=1, analyses=False)
    run = RunConfig(**{**run.__dict__, "tasks": [load_task(task_dir)]})
    fake = AskDocker()
    run_dir = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    specs = {}
    for cid, c in fake.containers.items():
        if "turns" in c and "-rep0-" in c["name"]:
            specs["-a-" in c["name"] and "A" or "B"] = json.loads(fake.files[cid]["/tp/turn00.json"])["argv"]
    for lab in "AB":
        assert specs[lab][specs[lab].index("--permission-prompt-tool") + 1] == "stdio"
    assert specs["A"][specs["A"].index("--disallowedTools") + 1] == "AskUserQuestion"
    assert "--disallowedTools" not in specs["B"]
    meta = json.loads((run_dir / "run.json").read_text())
    assert [a["ask_tool"] for a in meta["arms"]] == ["hidden", "on"]
    from hai_proof.models import ask_tool_mode

    assert [ask_tool_mode(v) for v in (True, False, None, "hidden")] == ["on", "off", "off", "hidden"]
