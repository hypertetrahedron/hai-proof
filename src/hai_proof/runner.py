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

from . import images, locks
from .analyses import run_arm_analyses
from .executor import Executor
from .models import AnalysisResult, ArmSpec, RunConfig, TaskSpec, TrialResult, ask_tool_mode, to_json
from .resources import GB, ResourceError, ResourceGate, parse_mem
from .trial import AUTH_FAILED, USAGE_LIMIT, TrialContext, run_trial

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
    ceiling = sum(run.task_limits(t)[2] for t in run.tasks) * run.reps * arms
    ceiling += probe_runs * 1.0 + (run.task_limits(min(run.tasks, key=lambda t: t.level))[2] * arms if warmup else 0)
    ceiling += agent_runs * sum(a.budget_usd for a in trial_an) + arms * sum(a.budget_usd for a in arm_an)
    lines = [
        f"run {run.run_id}  shape={run.shape}  mode={run.mode}  reps={run.reps}  host={run.host}",
        "arms: " + ", ".join(f"{a.label}={a.display_name}" for a in run.arms),
        "tasks: " + ", ".join(f"{t.id}(L{t.level})" for t in run.tasks),
        f"agent runs: {agent_runs}  probe runs: {probe_runs}  warm-up runs: {warmup}  "
        f"analysis sessions: {sessions}",
        f"spend ceiling (sum of --max-budget-usd caps): ${ceiling:,.2f}",
    ]
    if run.limit_scale != 1.0:
        lines.append(f"limits: every task's time limit, turn limit and budget x{run.limit_scale:g} (both arms)")
    loop_arms = [a for a in run.arms if a.multi_turn]
    if loop_arms:
        lines.append(
            "user in the loop: " + ", ".join(
                f"{a.label}={a.user}{({'on': ' + ask tool', 'hidden': ' + ask tool hidden'}).get(a.ask_tool, '')}, "
                f"{len(a.treatment.workflow) or 1} scripted turn(s)" for a in loop_arms)
            + (f"; stand-in {run.stand_in_model}, up to {run.max_user_replies} replies per trial"
               + (f", {run.tool_answers} tool answers" if run.tool_answers != "brief" else "")
               + (f", {run.reticence} reticence" if run.reticence != "standard" else "")
               + " (its cost is small and not in the ceiling)" if any(a.user != "conventional" for a in loop_arms) else ""))
        own: dict[tuple[str, str], list[str]] = {}
        for t in run.tasks:
            if t.tool_answers or t.reticence:
                own.setdefault(run.stand_in_settings(t), []).append(t.id)
        if own and any(a.user == "reticent" for a in loop_arms):
            lines.append("stand-in set by the task: " + "; ".join(
                f"{', '.join(ids)} = {ta} tool answers, {rt} reticence" for (ta, rt), ids in own.items()))
    return Plan(agent_runs, probe_runs, warmup, sessions, ceiling, lines)


class AuthError(RuntimeError):
    """Credentials were rejected; nothing further in the run can succeed."""


class SpendCapReached(RuntimeError):
    """The next pair could take the run past --max-spend; the run stops cleanly and is reported."""


class ResumeMismatch(RuntimeError):
    """--resume was given a configuration that differs from the run being resumed."""


# run.json keys that must match for a resumed run to stay one experiment
RESUME_KEYS = ("shape", "reps", "model", "effort", "seed", "egress", "limits", "user_loop")


class UsageLimitStop(RuntimeError):
    """The account usage limit has no usable reset time; the run stops cleanly and is reported."""


USAGE_WAIT_MAX_S = 6 * 3600  # longest single wait for a usage-limit reset (the 5-hour window fits)
USAGE_WAIT_SLACK_S = 120  # wait this long past the reported reset
USAGE_WAITS_MAX = 8  # give up after this many waits in one run (e.g. a weekly limit)


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
        self.gate: ResourceGate | None = None
        self.spent = 0.0  # agent cost of every recorded trial (warm-up and probes included)
        self.max_pair = 0.0  # most expensive pair so far: the reserve kept below max_spend_usd
        self.usage_waits = 0
        self.done_groups: set[tuple[str, int]] = set()  # (task, rep) finished before a resume
        self.done_probes = 0
        self.warmup_done = False
        self.resume_cli_version: str | None = None
        self.sleep: Callable[[float], None] = time.sleep
        self.now: Callable[[], float] = time.time

    # ------------------------------------------------------------------ public

    def execute(self) -> Path:
        """Run under the run dir's controller.lock: a second controller on the same run (a resume while the
        first is alive, or a new run that drew the same id) is refused before it touches anything."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        lock = self.run_dir / "controller.lock"
        holder = locks.try_acquire(lock)
        if holder is not None:
            raise locks.LockHeld(f"run {self.run.run_id} is in use by {locks.describe(holder)}; "
                                 f"if that controller is gone, delete {lock}")
        try:
            if not self.run.resume and (self.run_dir / "run.json").exists():
                raise locks.LockHeld(f"{self.run_dir} already holds a run; use --resume to continue it")
            return self._execute()
        finally:
            locks.release(lock)

    def _execute(self) -> Path:
        run = self.run
        self.meta = self._initial_meta()
        if run.resume:
            self._resume()
        self._write_meta()
        try:
            self._build_images()
            self._preflight_auth()
            self._preflight_tool_absence()
            self._setup_egress()
            self.ctx.trial_analyses = [a for a in run.analyses if a.scope == "trial"]
            if run.resource_gate:
                # A pair runs one container per arm at the memory limit, plus headroom for grading/proxies.
                need = len(run.arms) * parse_mem(run.limits.memory) + 2 * GB
                self.gate = ResourceGate(self.ex, run.run_id, self.run_dir, need_host=need, log=self.log)
            if run.warmup and not self.warmup_done:
                self.log("warm-up pair (unscored)")
                easiest = min(run.tasks, key=lambda t: (t.level, t.id))
                self._check_resources("warm-up")
                self._run_group(easiest, rep=-1, pair_id="warmup")
            for i in range(self.done_probes, run.probe_runs):
                self.log(f"context-tax probe {i + 1}/{run.probe_runs}")
                self._check_resources(f"probe {i + 1}")
                self._run_group(run.tasks[0], rep=-2, pair_id=f"probe-{i}", probe=True)
            rng = random.Random(run.seed)
            for rep in range(run.reps):
                order = list(run.tasks)
                rng.shuffle(order)
                for task in order:
                    if (task.id, rep) in self.done_groups:
                        continue
                    self._run_scored_group(task, rep, rng)
            self._arm_analyses()
        except (SpendCapReached, UsageLimitStop) as e:
            self.log(f"stopping: {e}")
            self.meta["stopped_early"] = str(e)
        except (AuthError, ResourceError, ResumeMismatch) as e:
            self.log(f"error: {e}")
            self.meta["aborted"] = str(e)
            raise
        except KeyboardInterrupt:
            self.log("interrupted — cleaning up containers")
            self.meta["interrupted"] = True
            raise
        finally:
            self._teardown()
            if self.gate:
                try:  # anything still listed here after teardown is a leak
                    s = self.gate.snapshot("after teardown")
                    self.gate._write(s)
                    if s.run_containers:
                        self.log(f"resources: containers left after teardown: {', '.join(s.run_containers)}")
                except Exception as e:  # noqa: BLE001
                    self.log(f"resources: final snapshot failed: {e}")
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
            "arms": [{"label": a.label, "treatment": a.treatment.name, "user": a.user, "ask_tool": a.ask_tool,
                      "treatment_hash": a.treatment.content_hash(), "image": None, "image_digest": None,
                      "manifest": to_json(a.treatment)} for a in r.arms],
            "tasks": [{"id": t.id, "kind": t.kind, "level": t.level, "origin": t.origin, "hash": t.content_hash(),
                       "cost_tier": t.cost_tier, "report_order": t.report_order, "brief_hash": t.brief_hash()}
                      for t in r.tasks],
            "analyses": [a.name for a in r.analyses], "arm_analyses": {}, "harness": r.harness,
            "user_loop": r.user_loop, "limit_scale": r.limit_scale,
        }

    def _resume(self) -> None:
        """Continue a run whose controller died: same run dir, finished pairs kept, the rest run.

        The configuration must match the original (RESUME_KEYS, arms and treatment hashes, task ids and
        hashes); the CLI version is checked after the images resolve it. Containers and networks the dead
        controller left behind are removed. Trial dirs without a record (the pair that was in flight) are
        moved to orphaned/, and their agent cost is counted towards --max-spend.
        """
        from .report import load_run

        old, trials = load_run(self.run_dir)
        new = self.meta
        diffs = [f"{k}: {old.get(k)!r} -> {new.get(k)!r}" for k in RESUME_KEYS if old.get(k) != new.get(k)]
        if old.get("limit_scale", 1.0) != new.get("limit_scale", 1.0):  # runs before --limit-scale ran at 1
            diffs.append(f"limit_scale: {old.get('limit_scale', 1.0)!r} -> {new.get('limit_scale', 1.0)!r}")
        arms = lambda m: [(a["label"], a["treatment"], a.get("treatment_hash"), a.get("user", "conventional"),  # noqa: E731
                           ask_tool_mode(a.get("ask_tool"))) for a in m.get("arms", [])]
        tasks = lambda m: sorted((t["id"], t.get("hash"), t.get("brief_hash")) for t in m.get("tasks", []))  # noqa: E731
        if arms(old) != arms(new):
            diffs.append(f"arms: {arms(old)} -> {arms(new)}")
        if tasks(old) != tasks(new):
            diffs.append(f"tasks: {tasks(old)} -> {tasks(new)}")
        if diffs:
            raise ResumeMismatch("cannot resume, the configuration differs: " + "; ".join(diffs))

        labels = {a.label for a in self.run.arms}
        ok: dict[tuple[str, int], set[str]] = {}
        pairs: dict[str, float] = {}
        recorded = set()
        for t in trials:
            cost = t.metrics.cost_usd if t.metrics else 0.0
            self.spent += cost
            pairs[t.pair_id] = pairs.get(t.pair_id, 0.0) + cost
            if t.artifacts_dir:
                recorded.add(t.artifacts_dir)
            if t.rep >= 0 and t.status == "ok":
                ok.setdefault((t.task_id, t.rep), set()).add(t.arm)
        self.max_pair = max(pairs.values(), default=0.0)
        self.done_groups = {g for g, arms_ok in ok.items() if arms_ok >= labels}
        self.warmup_done = any(t.rep == -1 for t in trials)
        self.done_probes = len({t.pair_id for t in trials if t.rep == -2})
        orphaned = self._move_orphans(recorded)

        self._remove_leftovers()
        history = list(old.get("resumes", []))
        history.append({"at": _now(), "previous_finished_at": old.get("finished_at"),
                        "previous_stop": old.get("stopped_early") or old.get("aborted"),
                        "pairs_done": len(self.done_groups), "orphaned": orphaned})
        self.resume_cli_version = old.get("cli_version")
        keep = {k: old[k] for k in ("started_at", "usage_limit_waits", "corrections") if k in old}
        self.meta.update(keep)
        self.meta["resumes"] = history
        self.log(f"resuming {self.run.run_id}: {len(self.done_groups)} pairs done, spend so far "
                 f"${self.spent:.2f}" + (f", {len(orphaned)} orphaned trial(s) set aside" if orphaned else ""))

    def _move_orphans(self, recorded: set[str]) -> list[dict]:
        """Scored trial dirs with no trials.jsonl record: the pair in flight when the controller died."""
        from . import streamjson

        out = []
        base = self.run_dir / "trials"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for d in sorted(base.glob("*/*/rep*")) if base.is_dir() else []:
            rel = d.relative_to(self.run_dir).as_posix()
            if rel in recorded or not d.is_dir():
                continue
            tp = d / "agent" / "transcript.jsonl"
            cost = 0.0
            if tp.is_file():
                tr = streamjson.parse_transcript(tp.read_text(encoding="utf-8", errors="replace"))
                cost = streamjson.metrics_from_transcript(tr, wall_s=0.0).cost_usd
            dest = self.run_dir / "orphaned" / stamp / d.relative_to(base)
            dest.parent.mkdir(parents=True, exist_ok=True)
            d.rename(dest)
            self.spent += cost
            out.append({"trial": rel, "cost_usd": round(cost, 4), "moved_to": dest.relative_to(self.run_dir).as_posix()})
        return out

    def _remove_leftovers(self) -> None:
        r = self.ex.docker(["ps", "-aq", "--filter", f"label=hai-proof.run={self.run.run_id}"], check=False)
        cids = r.stdout.decode().split()
        for cid in cids:
            self.ex.remove(cid)
        for arm in self.run.arms:
            self.ex.network_remove(f"tp-{self.run.run_id}-{arm.label}-net".lower())
        if cids:
            self.log(f"removed {len(cids)} container(s) left by the previous controller")

    def _build_images(self) -> None:
        run, ex = self.run, self.ex
        version = images.resolve_cli_version(ex, run.cli_version)
        if run.resume and self.resume_cli_version not in (None, version):
            raise ResumeMismatch(f"cannot resume: the run used Claude Code {self.resume_cli_version}, "
                                 f"this would use {version}")
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
                                trial_images=trial_images, log=self.log, stand_in_image=self.base_image)
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
        """Run one trial per arm concurrently. If the account usage limit stopped any of them, the pair
        is discarded, the run waits for the limit to reset and the pair is run again."""
        pid = pair_id
        for n in range(1, USAGE_WAITS_MAX + 2):
            results = self._run_group_once(task, rep=rep, pair_id=pid, probe=probe, order=order)
            limited = [r for r in results if r.error and r.error.startswith(USAGE_LIMIT)]
            if not limited:
                return results
            self._wait_for_usage_reset(limited, pid)
            pid = f"{pair_id}-ulwait{n}"  # a distinct id keeps the discarded pair's records
        raise UsageLimitStop(f"account usage limit still reached at {pair_id} after {USAGE_WAITS_MAX} waits")

    def _wait_for_usage_reset(self, limited: list[TrialResult], pair_id: str) -> None:
        resets = [r.usage_limit_resets_at for r in limited if r.usage_limit_resets_at]
        if not resets:
            raise UsageLimitStop(f"account usage limit reached at {pair_id} and no reset time was reported")
        self.usage_waits += 1
        wait = max(resets) - self.now() + USAGE_WAIT_SLACK_S
        if self.usage_waits > USAGE_WAITS_MAX or wait > USAGE_WAIT_MAX_S:
            when = datetime.fromtimestamp(max(resets), timezone.utc).isoformat(timespec="minutes")
            raise UsageLimitStop(f"account usage limit reached at {pair_id}; it resets at {when}, "
                                 f"{wait / 3600:.1f} h away (wait {self.usage_waits}/{USAGE_WAITS_MAX})")
        wait = max(wait, 60.0)
        self.log(f"   account usage limit reached at {pair_id}; pair discarded, waiting {wait / 60:.0f} min "
                 "for the reset, then rerunning it")
        self.meta.setdefault("usage_limit_waits", []).append({"at": _now(), "pair_id": pair_id,
                                                               "wait_s": round(wait)})
        self._write_meta()
        self.sleep(wait)

    def _run_group_once(self, task: TaskSpec, *, rep: int, pair_id: str, probe: bool = False,
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
        pair_cost = sum(r.metrics.cost_usd for r in results if r.metrics)
        self.spent += pair_cost
        self.max_pair = max(self.max_pair, pair_cost)
        if any(r.error and r.error.startswith(USAGE_LIMIT) for r in results):
            for r in results:  # the pair is not comparable: discard the member that finished too
                if r.status == "ok":
                    r.status = "discarded"
                    r.error = "partner trial hit the account usage limit; pair discarded"
        for r in results:
            self._record(r)
        failed = [r for r in results if r.error and r.error.startswith(AUTH_FAILED)]
        if failed:
            raise AuthError(f"{failed[0].error}; stopping the run")
        return results

    def _check_resources(self, where: str) -> None:
        cap = self.run.max_spend_usd
        if cap is not None and self.spent + self.max_pair > cap:
            raise SpendCapReached(f"spend ${self.spent:.2f} + largest pair so far ${self.max_pair:.2f} would pass "
                                  f"the ${cap:.2f} cap; not starting {where}")
        if self.gate:
            self.gate.check(where)

    def _run_scored_group(self, task: TaskSpec, rep: int, rng: random.Random) -> None:
        for attempt in range(self.run.max_pair_retries + 1):
            order = list(self.run.arms)
            rng.shuffle(order)
            pair_id = f"{task.id}-r{rep}" + (f"-retry{attempt}" if attempt else "")
            self.log(f"rep {rep + 1}/{self.run.reps}  task {task.id}  "
                     f"[{' & '.join(a.label for a in order)}]" + (f"  retry {attempt}" if attempt else ""))
            self._check_resources(f"{task.id} rep {rep}" + (f" retry {attempt}" if attempt else ""))
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
