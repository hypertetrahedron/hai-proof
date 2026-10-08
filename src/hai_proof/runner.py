"""Run orchestration: images, preflight, egress, warm-up, probe, interleaved pairs, analyses, report."""

from __future__ import annotations

import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import images
from .analyses import run_arm_analyses
from .executor import Executor
from .models import AnalysisResult, ArmSpec, RunConfig, TaskSpec, TrialResult, to_json
from .trial import AUTH_FAILED, TrialContext, run_trial

DEFAULT_ALLOW = ("api.anthropic.com",)


@dataclass
class Plan:
    """What a run will do, for --dry-run and the pre-run confirmation."""

    agent_runs: int
    probe_runs: int
    warmup_runs: int
    analysis_sessions: int
    budget_ceiling_usd: float
    lines: list[str] = field(default_factory=list)


def make_plan(run: RunConfig) -> Plan:
    arms = len(run.arms)
    agent_runs = len(run.tasks) * run.reps * arms
    probe_runs = run.probe_runs * arms
    warmup = arms if run.warmup else 0
    trial_an = [a for a in run.analyses if a.scope == "trial"]
    arm_an = [a for a in run.analyses if a.scope == "arm"]
    sessions = agent_runs * len(trial_an) + arms * len(arm_an)
    ceiling = sum(t.budget_usd for t in run.tasks) * run.reps * arms
    ceiling += probe_runs * 1.0 + (min(run.tasks, key=lambda t: t.level).budget_usd * arms if warmup else 0)
    ceiling += agent_runs * sum(a.budget_usd for a in trial_an) + arms * sum(a.budget_usd for a in arm_an)
    lines = [
        f"run {run.run_id}  shape={run.shape}  mode={run.mode}  reps={run.reps}  host={run.host}",
        "arms: " + ", ".join(f"{a.label}={a.treatment.name}" for a in run.arms),
        "tasks: " + ", ".join(f"{t.id}(L{t.level})" for t in run.tasks),
        f"agent runs: {agent_runs}  probe runs: {probe_runs}  warm-up runs: {warmup}  "
        f"analysis sessions: {sessions}",
        f"spend ceiling (sum of --max-budget-usd caps): ${ceiling:,.2f}",
    ]
    return Plan(agent_runs, probe_runs, warmup, sessions, ceiling, lines)


class AuthError(RuntimeError):
    """Credentials were rejected; nothing further in the run can succeed."""


class Runner:
    def __init__(self, run: RunConfig, ex: Executor, auth_env: dict[str, str], *,
                 log: Callable[[str], None] = print):
        self.run, self.ex, self.auth_env, self.log = run, ex, auth_env, log
        self.run_dir = run.results_dir / run.run_id
        self._lock = threading.Lock()
        self.arm_images: dict[str, str] = {}
        self.base_image = ""
        self.ctx: TrialContext | None = None
        self.meta: dict = {}

    # ------------------------------------------------------------------ public

    def execute(self) -> Path:
        run = self.run
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.meta = self._initial_meta()
        self._write_meta()
        try:
            self._build_images()
            self._preflight_auth()
            self._preflight_tool_absence()
            self._setup_egress()
            self.ctx.trial_analyses = [a for a in run.analyses if a.scope == "trial"]
            if run.warmup:
                self.log("warm-up pair (unscored)")
                easiest = min(run.tasks, key=lambda t: (t.level, t.id))
                self._run_group(easiest, rep=-1, pair_id="warmup")
            for i in range(run.probe_runs):
                self.log(f"context-tax probe {i + 1}/{run.probe_runs}")
                self._run_group(run.tasks[0], rep=-2, pair_id=f"probe-{i}", probe=True)
            rng = random.Random(run.seed)
            for rep in range(run.reps):
                order = list(run.tasks)
                rng.shuffle(order)
                for task in order:
                    self._run_scored_group(task, rep, rng)
            self._arm_analyses()
        except AuthError as e:
            self.log(f"error: {e}")
            self.meta["aborted"] = str(e)
            raise
        except KeyboardInterrupt:
            self.log("interrupted — cleaning up containers")
            self.meta["interrupted"] = True
            raise
        finally:
            self._teardown()
            self.meta["finished_at"] = _now()
            self._write_meta()
            self._report()
        return self.run_dir

    # ------------------------------------------------------------------ setup

    def _initial_meta(self) -> dict:
        r = self.run
        return {
            "run_id": r.run_id, "started_at": _now(), "finished_at": None, "host": r.host, "host_info": {},
            "shape": r.shape, "mode": r.mode, "reps": r.reps, "model": r.model, "effort": r.effort,
            "cli_version": r.cli_version, "seed": r.seed, "egress": r.egress,
            "limits": {"cpus": r.limits.cpus, "memory": r.limits.memory},
            "arms": [{"label": a.label, "treatment": a.treatment.name,
                      "treatment_hash": a.treatment.content_hash(), "image": None, "image_digest": None,
                      "manifest": to_json(a.treatment)} for a in r.arms],
            "tasks": [{"id": t.id, "kind": t.kind, "level": t.level, "origin": t.origin} for t in r.tasks],
            "analyses": [a.name for a in r.analyses], "arm_analyses": {},
        }

    def _build_images(self) -> None:
        run, ex = self.run, self.ex
        version = images.resolve_cli_version(ex, run.cli_version)
        self.meta["cli_version"] = version
        self.log(f"building base image (Claude Code {version}) on {ex.name}")
        self.base_image = images.build_base(ex, version)
        trial_images: dict[tuple[str, str], str] = {}
        for i, arm in enumerate(run.arms):
            self.log(f"building arm {arm.label} image ({arm.treatment.name})")
            arm_image = images.build_treatment(ex, self.base_image, arm.treatment)
            self.arm_images[arm.label] = arm_image
            self.meta["arms"][i]["image"] = arm_image
            self.meta["arms"][i]["image_digest"] = self._digest(arm_image)
            for task in run.tasks:
                trial_images[(arm.label, task.id)] = images.build_trial(ex, arm_image, task)
        self.meta["host_info"] = self._host_info()
        self.ctx = TrialContext(ex=ex, run=run, run_dir=self.run_dir, auth_env=self.auth_env,
                                trial_images=trial_images, log=self.log)
        self._write_meta()

    def _preflight_auth(self) -> None:
        """Free credential check from the execution host before any trial spends time or money.

        Only API keys can be checked this way (GET /v1/models). The key is expanded inside the
        container, so it never appears on a command line on the host.
        """
        if "ANTHROPIC_API_KEY" not in self.auth_env:
            return
        cid = self.ex.run_detached(["--label", f"hai-proof.run={self.run.run_id}", self.base_image,
                                    "sleep", "120"], secret_env=self.auth_env)
        try:
            r = self.ex.exec(cid, ["sh", "-c",
                                   'curl -s -o /dev/null -w "%{http_code}" --max-time 20 '
                                   '-H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" '
                                   'https://api.anthropic.com/v1/models'], check=False, timeout=60)
        finally:
            self.ex.remove(cid)
        code = r.stdout.decode().strip()
        self.meta["auth_check"] = code
        if code in ("401", "403"):
            raise AuthError(f"ANTHROPIC_API_KEY was rejected by the API (HTTP {code}); no trials were run")
        if code != "200":
            self.log(f"warning: credential check returned HTTP {code or 'nothing'}; continuing")

    def _preflight_tool_absence(self) -> None:
        """Each arm's image must not contain tools declared by any *other* arm (DESIGN §3.4, §3.6)."""
        for arm in self.run.arms:
            others = {r.name for a in self.run.arms if a.label != arm.label for r in a.treatment.requires}
            others -= {r.name for r in arm.treatment.requires}
            if not others:
                continue
            script = " ; ".join(f"command -v {n} >/dev/null 2>&1 && echo {n}" for n in sorted(others))
            r = self.ex.docker(["run", "--rm", "--entrypoint", "sh", self.arm_images[arm.label], "-c",
                                script + " ; true"])
            found = r.stdout.decode().split()
            if found:
                raise RuntimeError(f"arm {arm.label} image unexpectedly contains {found}; "
                                   "the base image must not ship treatment tools")

    def _setup_egress(self) -> None:
        if self.run.egress != "proxy":
            return
        proxy_image = images.build_proxy(self.ex)
        for arm in self.run.arms:
            net = f"tp-{self.run.run_id}-{arm.label}-net".lower()
            proxy = f"tp-{self.run.run_id}-{arm.label}-proxy".lower()
            self.ex.network_create(net, internal=True)
            allow = " ".join(sorted(set(DEFAULT_ALLOW) | set(arm.treatment.network_allow)))
            self.ex.run_detached(["--name", proxy, "--label", f"hai-proof.run={self.run.run_id}",
                                  "-e", f"ALLOW_HOSTS={allow}", proxy_image])
            self.ex.network_connect(net, proxy)
            self.ctx.arm_networks[arm.label] = net
            self.ctx.arm_proxies[arm.label] = f"http://{proxy}:3128"

    # ------------------------------------------------------------------ trials

    def _run_group(self, task: TaskSpec, *, rep: int, pair_id: str, probe: bool = False,
                   order: list[ArmSpec] | None = None) -> list[TrialResult]:
        arms = order or self.run.arms
        if len(arms) == 1:
            results = [run_trial(self.ctx, arms[0], task, rep, pair_id, probe=probe)]
        else:
            with ThreadPoolExecutor(max_workers=len(arms)) as pool:
                futs = []
                for arm in arms:
                    futs.append(pool.submit(run_trial, self.ctx, arm, task, rep, pair_id, probe=probe))
                    time.sleep(0.05)
                results = [f.result() for f in futs]
        for r in results:
            self._record(r)
        failed = [r for r in results if r.error and r.error.startswith(AUTH_FAILED)]
        if failed:
            raise AuthError(f"{failed[0].error}; stopping the run")
        return results

    def _run_scored_group(self, task: TaskSpec, rep: int, rng: random.Random) -> None:
        for attempt in range(self.run.max_pair_retries + 1):
            order = list(self.run.arms)
            rng.shuffle(order)
            pair_id = f"{task.id}-r{rep}" + (f"-retry{attempt}" if attempt else "")
            self.log(f"rep {rep + 1}/{self.run.reps}  task {task.id}  "
                     f"[{' & '.join(a.label for a in order)}]" + (f"  retry {attempt}" if attempt else ""))
            results = self._run_group(task, rep=rep, pair_id=pair_id, order=order)
            retry = any(r.rate_limited or r.status == "error" for r in results)
            if not retry:
                for r in results:
                    m = r.metrics
                    self.log(f"   {r.arm}: {r.status} success={r.success} "
                             + (f"wall={m.wall_s:.0f}s cost=${m.cost_usd:.3f}" if m else ""))
                return
            # A pair with a transient failure is not comparable: discard both members and rerun.
            for r in results:
                if r.status == "ok":
                    r.status = "discarded"
                    r.error = "partner trial failed; pair discarded"
                    self._record(r)
        self.log(f"   gave up on {task.id} rep {rep} after {self.run.max_pair_retries} retries")

    def _record(self, r: TrialResult) -> None:
        with self._lock, (self.run_dir / "trials.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(to_json(r)) + "\n")

    # ------------------------------------------------------------------ wrap-up

    def _arm_analyses(self) -> None:
        specs = [a for a in self.run.analyses if a.scope == "arm"]
        if not specs:
            return
        for arm in self.run.arms:
            self.log(f"arm-scope analyses for arm {arm.label}")
            res: dict[str, AnalysisResult] = run_arm_analyses(
                self.ctx, arm, specs, self.run_dir / "trials", image=self.base_image)
            # run.json contract: arm_analyses = {label: {name: relative report path}}; full results beside it.
            self.meta["arm_analyses"][arm.label] = {k: v.report_path for k, v in res.items() if v.report_path}
            self.meta.setdefault("arm_analysis_results", {})[arm.label] = {k: to_json(v) for k, v in res.items()}

    def _teardown(self) -> None:
        try:
            r = self.ex.docker(["ps", "-aq", "--filter", f"label=hai-proof.run={self.run.run_id}"], check=False)
            for cid in r.stdout.decode().split():
                self.ex.remove(cid)
        except Exception as e:  # noqa: BLE001
            self.log(f"cleanup warning: {e}")
        if self.ctx:
            for net in self.ctx.arm_networks.values():
                self.ex.network_remove(net)

    def _report(self) -> None:
        try:
            from .report import load_run, write_report

            meta, trials = load_run(self.run_dir)
            summary_path, html_path = write_report(self.run_dir, meta, trials)
            self.log(f"report: {html_path}")
        except Exception as e:  # noqa: BLE001
            self.log(f"report generation failed: {e}")

    def _write_meta(self) -> None:
        (self.run_dir / "run.json").write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    def _digest(self, image: str) -> str | None:
        r = self.ex.docker(["image", "inspect", "--format", "{{.Id}}", image], check=False)
        return r.stdout.decode().strip() or None

    def _host_info(self) -> dict:
        r = self.ex.docker(["info", "--format",
                            "{{.NCPU}}|{{.MemTotal}}|{{.Architecture}}|{{.ServerVersion}}"], check=False)
        parts = r.stdout.decode().strip().split("|")
        if len(parts) != 4:
            return {}
        return {"ncpu": int(parts[0]), "mem_bytes": int(parts[1]), "arch": parts[2], "engine_version": parts[3]}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + f"{random.randrange(16**4):04x}"
