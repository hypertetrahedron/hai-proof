"""Load analysis definitions (DESIGN §3.7)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .config import ConfigError
from .models import AnalysisSpec

_KEYS = {"name", "scope", "prompt", "prompt_file", "budget_usd"}


def _find(name_or_path: str, search_dirs: list[Path]) -> Path:
    p = Path(name_or_path)
    if p.suffix == ".toml" and p.is_file():
        return p
    for d in search_dirs:
        cand = Path(d) / f"{name_or_path}.toml"
        if cand.is_file():
            return cand
    searched = ", ".join(str(d) for d in search_dirs) or "(none)"
    raise ConfigError(f"analysis '{name_or_path}' not found (searched: {searched})")


def load_analysis(name_or_path: str, *, search_dirs: list[Path]) -> AnalysisSpec:
    f = _find(name_or_path, search_dirs)
    try:
        with f.open("rb") as fh:
            d = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{f}: invalid TOML: {e}") from e
    unknown = sorted(set(d) - _KEYS)
    if unknown:
        raise ConfigError(f"{f}: unknown keys: {', '.join(unknown)}")
    name = d.get("name", f.stem)
    scope = d.get("scope", "trial")
    if scope not in ("trial", "arm"):
        raise ConfigError(f"{f}: scope must be 'trial' or 'arm', got {scope!r}")
    budget = d.get("budget_usd", 1.0)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
        raise ConfigError(f"{f}: budget_usd must be a number > 0")
    if ("prompt" in d) == ("prompt_file" in d):
        raise ConfigError(f"{f}: exactly one of 'prompt' or 'prompt_file' is required")
    if "prompt_file" in d:
        pf = f.parent / d["prompt_file"]
        if not pf.is_file():
            raise ConfigError(f"{f}: prompt_file not found: {pf}")
        prompt = pf.read_text(encoding="utf-8")
    else:
        prompt = d["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ConfigError(f"{f}: prompt is empty")
    return AnalysisSpec(name=name, scope=scope, prompt=prompt.strip() + "\n", budget_usd=float(budget))
