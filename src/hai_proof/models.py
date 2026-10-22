"""Shared data model. Every module exchanges these types; keep them plain and JSON-serializable."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ArmLabel = Literal["A", "B"]
Mode = Literal["lightning", "quick", "full", "custom"]
TrialStatus = Literal["ok", "error", "discarded", "excluded"]
# Who answers the agent between turns (DESIGN §3.8): nobody (the classic single session), a stand-in that
# always says "use your best judgement", or a stand-in that answers from the task's user brief.
UserMode = Literal["conventional", "uninformative", "informative", "reticent"]
USER_MODES: tuple[str, ...] = ("conventional", "uninformative", "informative", "reticent")
# Modes whose stand-in answers from the task's user brief.
BRIEF_MODES: tuple[str, ...] = ("informative", "reticent")
TASK_PROMPT_SLOT = "{task_prompt}"
# --ask-tool (DESIGN §3.8): off = plain `claude -p`; on = stream-json input with stdio permission prompts, which
# offers AskUserQuestion; hidden = the same input mode with AskUserQuestion disallowed (the control for "on").
ASK_TOOL_MODES = ("off", "on", "hidden")


def ask_tool_mode(value: Any) -> str:
    """run.json value -> mode; runs from before 'hidden' recorded a bool."""
    if value is True:
        return "on"
    return value if value in ASK_TOOL_MODES else "off"


# --------------------------------------------------------------------------- treatments


@dataclass(frozen=True)
class Requirement:
    """An external tool a treatment needs (DESIGN §3.4)."""

    name: str
    install: str  # shell command run at image build time
    check: str  # shell command that must exit 0 after install


@dataclass(frozen=True)
class TreatmentSpec:
    """A harness-modification bundle, or the plain control (path is None)."""

    name: str
    path: Path | None = None
    prompt_prefix: str = ""
    prompt_variant: str = ""  # use each task's prompts/<variant>.md instead of prompt.md
    env: dict[str, str] = field(default_factory=dict)
    requires: tuple[Requirement, ...] = ()
    setup_commands: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()  # path prefixes created by the treatment's tools
    network_allow: tuple[str, ...] = ()  # extra egress hosts at agent run time
    expect_plugins: tuple[str, ...] = ()
    expect_mcp_servers: tuple[str, ...] = ()
    expect_skills: tuple[str, ...] = ()
    # Scripted user turns (DESIGN §3.8), e.g. a planning skill then an execution skill. "{task_prompt}" is
    # replaced with the task prompt. Empty: one turn, the task prompt.
    workflow: tuple[str, ...] = ()

    @property
    def is_plain(self) -> bool:
        return self.path is None

    @property
    def user_dir(self) -> Path | None:
        return self.path / "user" if self.path and (self.path / "user").is_dir() else None

    @property
    def project_dir(self) -> Path | None:
        return self.path / "project" if self.path and (self.path / "project").is_dir() else None

    @property
    def dockerfile(self) -> Path | None:
        return self.path / "Dockerfile" if self.path and (self.path / "Dockerfile").is_file() else None

    def content_hash(self) -> str:
        """Stable short hash of the manifest plus every file in the bundle."""
        h = hashlib.sha256()
        h.update(json.dumps(_jsonable(self.manifest_dict()), sort_keys=True).encode())
        if self.path:
            for f in sorted(p for p in self.path.rglob("*") if p.is_file()):
                h.update(f.relative_to(self.path).as_posix().encode())
                h.update(f.read_bytes())
        return h.hexdigest()[:12]

    def manifest_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("path")
        if not d["workflow"]:  # keeps the hash (and image tag) of treatments that predate workflows
            d.pop("workflow")
        return d

    def turns(self, task_prompt: str) -> list[str]:
        """The scripted user messages for one task, in order."""
        if not self.workflow:
            return [task_prompt]
        return [m.replace(TASK_PROMPT_SLOT, task_prompt) for m in self.workflow]


PLAIN = TreatmentSpec(name="plain")


@dataclass(frozen=True)
class ArmSpec:
    label: ArmLabel
    treatment: TreatmentSpec
    user: UserMode = "conventional"
    ask_tool: str = "off"  # ASK_TOOL_MODES

    @property
    def sdk_input(self) -> bool:
        """Calls use stream-json input and stdio permission prompts (ask tool on or hidden)."""
        return self.ask_tool != "off"

    @property
    def multi_turn(self) -> bool:
        """Trials run the turn loop (trial.run_turns) rather than one `claude -p` session."""
        return self.user != "conventional" or len(self.treatment.workflow) > 1 or self.sdk_input

    @property
    def display_name(self) -> str:
        tags = [self.user] if self.user != "conventional" else []
        tags += {"on": ["ask tool"], "hidden": ["ask tool hidden"]}.get(self.ask_tool, [])
        return self.treatment.name + (f" ({', '.join(tags)})" if tags else "")


# --------------------------------------------------------------------------- tasks


@dataclass(frozen=True)
class GitSource:
    url: str
    base: str  # commit SHA the agent starts from
    fix: str | None = None  # upstream fix commit (derives hidden tests + reference)
    exclude: tuple[str, ...] = ()  # paths (fnmatch) of the fix left out of hidden tests + reference


@dataclass(frozen=True)
class TaskSpec:
    id: str
    kind: Literal["bug", "feature"]
    level: int  # 1..3
    path: Path  # task directory
    prompt: str
    origin: Literal["synthetic", "upstream-fix", "injected", "authored"] = "synthetic"
    timeout_s: int = 1800
    budget_usd: float = 5.0
    max_turns: int = 60
    install: str = "uv pip install --python /opt/venv/bin/python -e ."  # run in /work at image build
    acceptance: tuple[str, ...] = ()  # pytest node ids / paths for the hidden tests
    acceptance_args: tuple[str, ...] = ()  # extra pytest args for acceptance (e.g. a test DB URL)
    acceptance_cmd: str = ""  # shell command replacing pytest for acceptance (the project's own runner)
    regression: str = "python -m pytest -q -p no:cacheprovider"  # pre-existing suite command
    source: GitSource | None = None
    diff_categories: dict[str, tuple[str, ...]] = field(default_factory=dict)  # overrides
    prompt_variants: dict[str, str] = field(default_factory=dict)  # prompts/<name>.md, e.g. "degraded"
    user_brief: str = ""  # user.md: what the user wants and knows, for the informative stand-in (DESIGN §3.8)
    dockerfile: str = ""  # task.Dockerfile: root build steps (toolchains, apt packages) before repo/ and install
    suites: tuple[str, ...] = ()  # named task sets this task belongs to, e.g. "standard", "smoke"
    cost_tier: str = ""  # "low" | "medium" | "high": fixed report grouping (docs/task-catalog.md)
    report_order: int | None = None  # fixed position in reports, by plain-arm output tokens
    user: str = ""  # USER_MODES: the user in the loop the task is meant for ("" = any); setup, not content
    ask_tool: str = ""  # ASK_TOOL_MODES: the ask-tool setting the task is meant for ("" = any)

    def content_hash(self) -> str:
        """Short hash of everything that can change a trial's outcome.

        Leaves out report and run-setup metadata (suites, cost_tier, report_order, user, ask_tool), the
        generated baseline.json,
        caches, and repo/ when it is generated from [source] (source.lock.json pins it instead). The user
        brief (user.md) only reaches the stand-in, never a conventional trial, so it has its own hash.
        """
        h = hashlib.sha256()
        d = asdict(self)
        for k in ("path", "suites", "cost_tier", "report_order", "user", "ask_tool", "user_brief"):
            d.pop(k)
        h.update(json.dumps(_jsonable(d), sort_keys=True).encode())
        skip_top = {"task.toml", "baseline.json", "user.md"} | ({"repo"} if self.source is not None else set())
        for f in sorted(p for p in self.path.rglob("*") if p.is_file()):
            parts = f.relative_to(self.path).parts
            if parts[0] in skip_top or any(x in ("__pycache__", ".pytest_cache", ".git") for x in parts)                     or f.suffix == ".pyc":
                continue
            h.update("/".join(parts).encode())
            h.update(f.read_bytes())
        return h.hexdigest()[:12]

    def brief_hash(self) -> str | None:
        """Short hash of the user brief (DESIGN §3.8), or None without one."""
        return hashlib.sha256(self.user_brief.encode()).hexdigest()[:12] if self.user_brief else None

    def prompt_for(self, variant: str = "") -> str:
        """The task prompt, or the named variant of it (KeyError if the task has none)."""
        return self.prompt_variants[variant] if variant else self.prompt

    @property
    def repo_dir(self) -> Path:
        return self.path / "repo"

    @property
    def hidden_tests_dir(self) -> Path:
        return self.path / "hidden_tests"

    @property
    def custom_grader(self) -> Path | None:
        p = self.path / "grade.sh"
        return p if p.is_file() else None


# --------------------------------------------------------------------------- analyses


@dataclass(frozen=True)
class AnalysisSpec:
    name: str
    scope: Literal["trial", "arm"]
    prompt: str
    budget_usd: float = 1.0


# --------------------------------------------------------------------------- run config


@dataclass(frozen=True)
class Limits:
    cpus: float = 4.0
    memory: str = "8g"


@dataclass
class RunConfig:
    run_id: str
    host: str  # "local" or an ssh alias
    arms: list[ArmSpec]  # 1 or 2; arms[0] is the reference
    tasks: list[TaskSpec]
    reps: int
    mode: Mode
    model: str
    effort: str | None = None
    cli_version: str = "latest"
    analyses: list[AnalysisSpec] = field(default_factory=list)
    probe_runs: int = 5  # context-tax probe runs per arm; 0 disables
    warmup: bool = True
    egress: Literal["proxy", "open"] = "proxy"
    limits: Limits = field(default_factory=Limits)
    seed: int = 0
    max_pair_retries: int = 2
    results_dir: Path = Path("results")
    harness: dict[str, Any] = field(default_factory=dict)  # hai-proof version / code hash, see harness.py
    resource_gate: bool = True  # memory / leak check before each pair (resources.py)
    max_spend_usd: float | None = None  # stop cleanly before a pair that could take the run past this
    resume: bool = False  # continue the run in results_dir/run_id: skip finished pairs (runner.Runner._resume)
    stand_in_model: str = "claude-sonnet-5-5"  # the user stand-in's model (DESIGN §3.8), same for both arms
    max_user_replies: int = 5  # stand-in replies per trial; after that the script moves on or the trial ends
    tool_answers: str = "brief"  # reticent stand-in's ask-tool answers: brief (one sentence) or full (as in text)
    reticence: str = "standard"  # reticent stand-in: standard, or strict (tighter plan rule + filter pass)
    limit_scale: float = 1.0  # multiplies every task's time limit, turn limit and budget, for both arms

    def task_limits(self, task: TaskSpec) -> tuple[int, int, float]:
        """(timeout_s, max_turns, budget_usd) for a task's trials, after --limit-scale."""
        s = self.limit_scale
        return round(task.timeout_s * s), max(1, round(task.max_turns * s)), round(task.budget_usd * s, 2)

    @property
    def user_loop(self) -> dict[str, Any] | None:
        """run.json record of the stand-in settings; None when no arm uses the turn loop."""
        if not any(a.multi_turn for a in self.arms):
            return None
        loop = {"stand_in_model": self.stand_in_model, "max_user_replies": self.max_user_replies}
        if self.tool_answers != "brief":
            loop["tool_answers"] = self.tool_answers
        if self.reticence != "standard":
            loop["reticence"] = self.reticence
        return loop

    @property
    def single_arm(self) -> bool:
        return len(self.arms) == 1

    @property
    def shape(self) -> Literal["comparative", "ab", "single"]:
        if self.single_arm:
            return "single"
        # plain vs treatment is the comparative case; anything else (incl. the A/A plain-vs-plain
        # calibration) is reported with A/B wording.
        a, b = self.arms[0].treatment, self.arms[1].treatment
        return "comparative" if a.is_plain and not b.is_plain else "ab"


# --------------------------------------------------------------------------- results


@dataclass
class AgentMetrics:
    """Everything measured about one `claude -p` session (DESIGN §5)."""

    wall_s: float = 0.0  # in-container monotonic timer
    api_s: float = 0.0
    cost_usd: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    turns: int = 0
    tool_calls: int = 0
    subagent_calls: int = 0
    skills_fired: list[str] = field(default_factory=list)
    first_request_input_tokens: int = 0  # input + cache_read + cache_write of request #1
    terminal_reason: str | None = None
    subtype: str | None = None
    is_error: bool = False
    exit_code: int | None = None
    timed_out: bool = False
    # where cost/tokens came from: "result" (the stream's result event), "session" (Claude Code's cost-state
    # record in its session file, written even when the session is stopped, e.g. at the time limit) or "none"
    cost_source: str = "result"

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output + self.tokens_cache_read + self.tokens_cache_write


@dataclass
class AnalysisResult:
    name: str
    ok: bool
    report_path: str | None = None  # relative to the run's results dir
    cost_usd: float = 0.0
    wall_s: float = 0.0
    tokens_total: int = 0
    error: str | None = None


@dataclass
class TrialResult:
    run_id: str
    arm: ArmLabel
    treatment: str
    task_id: str
    rep: int  # 0-based; -1 = warm-up, -2 = probe
    pair_id: str
    status: TrialStatus = "ok"
    error: str | None = None
    started_at: str = ""
    metrics: AgentMetrics | None = None
    acceptance_pass: bool | None = None
    regression_pass: bool | None = None
    diff_breakdown: dict[str, dict[str, int]] = field(default_factory=dict)  # category -> {files, lines}
    dependency_used: dict[str, bool] = field(default_factory=dict)
    init_snapshot: dict[str, Any] = field(default_factory=dict)
    isolation_problems: list[str] = field(default_factory=list)
    leakage_flags: list[str] = field(default_factory=list)
    rate_limited: bool = False
    usage_limit_resets_at: float | None = None  # set when the account usage limit stopped the trial
    analyses: list[AnalysisResult] = field(default_factory=list)
    artifacts_dir: str = ""  # relative to the run's results dir
    session: dict[str, Any] = field(default_factory=dict)  # claudedata.combined_stats + collection manifest
    user_loop: dict[str, Any] = field(default_factory=dict)  # turn-loop summary (userloop.summary); {} if one turn

    @property
    def success(self) -> bool:
        return bool(self.acceptance_pass) and bool(self.regression_pass)

    @property
    def scored(self) -> bool:
        return self.status == "ok" and self.rep >= 0


def _jsonable(o: Any) -> Any:
    if isinstance(o, Path):
        return o.as_posix()
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def to_json(obj: Any) -> Any:
    """Dataclass -> JSON-ready structure (Paths become posix strings)."""
    return _jsonable(asdict(obj))


def trial_from_json(d: dict[str, Any]) -> TrialResult:
    d = dict(d)
    m = d.pop("metrics", None)
    analyses = [AnalysisResult(**a) for a in d.pop("analyses", [])]
    t = TrialResult(**d, analyses=analyses)
    t.metrics = AgentMetrics(**m) if m else None
    return t
