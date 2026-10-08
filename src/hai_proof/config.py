"""Project configuration (hai-proof.toml), run modes, host and auth resolution."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Limits, TaskSpec


class ConfigError(Exception):
    """Invalid or missing configuration."""


MODES: dict[str, dict[str, int]] = {
    "lightning": dict(reps=1, max_level=3),
    "quick": dict(reps=3, max_level=2),
    "full": dict(reps=5, max_level=3),
}

_TOP_KEYS = {
    "default_host", "model", "effort", "cli_version", "tasks_dir", "treatments_dir",
    "analyses_dir", "results_dir", "ssh_binary", "analyses", "limits", "probe", "egress",
}


@dataclass
class ProjectConfig:
    root: Path = Path(".")
    default_host: str = "local"
    model: str | None = None
    effort: str | None = None
    cli_version: str = "latest"
    tasks_dir: str = "tasks"
    treatments_dir: str = "treatments"
    analyses_dir: str = "analyses"
    results_dir: str = "results"
    ssh_binary: str = "ssh"
    analyses: list[str] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)
    probe_runs: int = 5
    egress: str = "proxy"

    def path(self, attr: str) -> Path:
        """Resolve one of the *_dir settings against the project root."""
        return self.root / getattr(self, attr)


def load_project_config(root: Path) -> ProjectConfig:
    root = Path(root)
    cfg = ProjectConfig(root=root)
    f = root / "hai-proof.toml"
    if not f.is_file():
        return cfg
    try:
        with f.open("rb") as fh:
            d: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{f}: invalid TOML: {e}") from e
    unknown = sorted(set(d) - _TOP_KEYS)
    if unknown:
        raise ConfigError(f"{f}: unknown keys: {', '.join(unknown)}")
    for key in ("default_host", "model", "effort", "cli_version", "tasks_dir", "treatments_dir",
                "analyses_dir", "results_dir", "ssh_binary"):
        if key in d:
            if not isinstance(d[key], str) or not d[key]:
                raise ConfigError(f"{f}: '{key}' must be a non-empty string")
            setattr(cfg, key, d[key])
    if "analyses" in d:
        a = d["analyses"]
        if not isinstance(a, list) or not all(isinstance(x, str) for x in a):
            raise ConfigError(f"{f}: 'analyses' must be a list of strings")
        cfg.analyses = list(a)
    if "egress" in d:
        if d["egress"] not in ("proxy", "open"):
            raise ConfigError(f"{f}: egress must be 'proxy' or 'open'")
        cfg.egress = d["egress"]
    lim = d.get("limits", {})
    if lim:
        bad = sorted(set(lim) - {"cpus", "memory"})
        if bad:
            raise ConfigError(f"{f}: unknown [limits] keys: {', '.join(bad)}")
        cfg.limits = Limits(cpus=float(lim.get("cpus", 4.0)), memory=str(lim.get("memory", "8g")))
    probe = d.get("probe", {})
    if probe:
        bad = sorted(set(probe) - {"runs"})
        if bad:
            raise ConfigError(f"{f}: unknown [probe] keys: {', '.join(bad)}")
        runs = probe.get("runs", 5)
        if not isinstance(runs, int) or isinstance(runs, bool) or runs < 0:
            raise ConfigError(f"{f}: probe.runs must be an integer >= 0")
        cfg.probe_runs = runs
    return cfg


def resolve_host(cli_host: str | None, cfg: ProjectConfig) -> str:
    """CLI flag > HAI_PROOF_HOST > cfg.default_host > 'local'."""
    return cli_host or os.environ.get("HAI_PROOF_HOST") or cfg.default_host or "local"


def select_tasks_for_mode(tasks: list[TaskSpec], mode: str) -> list[TaskSpec]:
    if mode not in MODES:
        raise ConfigError(f"unknown mode '{mode}' (expected one of: {', '.join(MODES)})")
    max_level = MODES[mode]["max_level"]
    return [t for t in tasks if t.level <= max_level]


CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal .env file: KEY=VALUE lines, optional `export `, quotes, # comments."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            out[key] = value
    return out


def auth_env(root: Path | None = None) -> dict[str, str]:
    """Credentials to pass to the agent.

    Read from the process environment first, then from `<root>/.env` (gitignored). Keeping them in
    hai-proof's own file means they never depend on Claude Code's settings reaching subprocesses.
    ANTHROPIC_API_KEY wins over CLAUDE_CODE_OAUTH_TOKEN.
    """
    file_vals = read_dotenv(root / ".env") if root else {}
    found = {v: os.environ.get(v) or file_vals.get(v) for v in CREDENTIAL_VARS}
    key = found["ANTHROPIC_API_KEY"]
    if key:
        # `claude setup-token` produces an OAuth token (sk-ant-oat...), which the API rejects when it
        # is presented as an API key. Catch the mix-up here instead of after minutes of 401 retries.
        if key.startswith("sk-ant-oat"):
            raise ConfigError("ANTHROPIC_API_KEY holds an OAuth token (sk-ant-oat..., from `claude setup-token`). "
                              "Put it in CLAUDE_CODE_OAUTH_TOKEN instead and unset ANTHROPIC_API_KEY.")
        return {"ANTHROPIC_API_KEY": key}
    tok = found["CLAUDE_CODE_OAUTH_TOKEN"]
    if tok:
        if tok.startswith("sk-ant-api"):
            raise ConfigError("CLAUDE_CODE_OAUTH_TOKEN holds an API key (sk-ant-api...). "
                              "Put it in ANTHROPIC_API_KEY instead.")
        return {"CLAUDE_CODE_OAUTH_TOKEN": tok}
    where = f" or in {root / '.env'}" if root else ""
    raise ConfigError(f"no credentials: set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN in the environment{where}")
