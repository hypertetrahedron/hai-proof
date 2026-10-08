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


def _transcript(*, plugins: list, cost: float, rate_limited: bool = False, bash: str = "pytest -q") -> str:
    init = {"type": "system", "subtype": "init", "model": "m", "tools": ["Bash"], "mcp_servers": [],
            "plugins": plugins}
    asst = {"type": "assistant", "parent_tool_use_id": None,
            "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": bash}}],
                        "usage": {"input_tokens": 5, "output_tokens": 1, "cache_creation_input_tokens": 1000,
                                  "cache_read_input_tokens": 0}}}
    if rate_limited:
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

    def __init__(self, *, rate_limit_once: str | None = None, image_has_tools: str = "", auth_code: str = "200"):
        self.auth_code = auth_code
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
            text = _transcript(plugins=[], cost=0.30 if is_b else 0.20, rate_limited=rl,
                               bash="bd ready && pytest -q" if is_b else "pytest -q")
            timing = {"wall_s": 90.0 if is_b else 60.0, "exit_code": 0, "timed_out": False}
            return _tar({"agent/transcript.jsonl": text, "agent/timing.json": json.dumps(timing),
                         "agent/stderr.log": "", "agent/done": ""})
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
    assert summary["verdict"] is not None
    assert summary["ratios"]["cost_usd"]["gm_ratio"] == pytest.approx(1.5, rel=1e-6)
    assert (run_dir / "report.html").is_file()
    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["cli_version"] == "2.1.289" and meta["finished_at"]
    assert set(meta["arm_analyses"]) == {"A", "B"}
    assert (run_dir / "arms" / "B" / "analysis-non-code-changes-arm.md").read_text().startswith("# Report")


def test_single_arm_run(tmp_path):
    fake = FakeDocker()
    run = _run_config(tmp_path, [ArmSpec("A", _treatment(tmp_path))], reps=1, analyses=False)
    run_dir = Runner(run, fake, {"ANTHROPIC_API_KEY": SECRET}, log=lambda s: None).execute()
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["verdict"] is None
    # single-arm trials are never run concurrently: no pair has two members
    assert all(t.arm == "A" for t in _trials(run_dir))


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
