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
    env: dict[str, str] = field(default_factory=dict)
    requires: tuple[Requirement, ...] = ()
    setup_commands: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()  # path prefixes created by the treatment's tools
    network_allow: tuple[str, ...] = ()  # extra egress hosts at agent run time
    expect_plugins: tuple[str, ...] = ()
    expect_mcp_servers: tuple[str, ...] = ()
    expect_skills: tuple[str, ...] = ()

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
        return d


PLAIN = TreatmentSpec(name="plain")


@dataclass(frozen=True)
class ArmSpec:
    label: ArmLabel
    treatment: TreatmentSpec


# --------------------------------------------------------------------------- tasks


@dataclass(frozen=True)
class GitSource:
    url: str
    base: str  # commit SHA the agent starts from
    fix: str | None = None  # upstream fix commit (derives hidden tests + reference)


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
    regression: str = "python -m pytest -q -p no:cacheprovider"  # pre-existing suite command
    source: GitSource | None = None
    diff_categories: dict[str, tuple[str, ...]] = field(default_factory=dict)  # overrides

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
    analyses: list[AnalysisResult] = field(default_factory=list)
    artifacts_dir: str = ""  # relative to the run's results dir

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
