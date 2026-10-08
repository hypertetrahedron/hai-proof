"""Parse `claude -p --output-format stream-json --verbose` transcripts (DESIGN §5, §3.4)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from .models import AgentMetrics, TreatmentSpec

SUBAGENT_TOOLS = ("Task", "Agent")
_NOISY_INIT_KEYS = ("session_id", "uuid")
_BAD_MCP_STATUS = {"failed", "error"}
_RATE_MARKERS = ("429", "rate limit", "rate_limit", "overloaded")


@dataclass
class Transcript:
    events: list[dict] = field(default_factory=list)
    init: dict | None = None
    result: dict | None = None


def parse_transcript(text: str) -> Transcript:
    events: list[dict] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            events.append(obj)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    return Transcript(events=events, init=init, result=result)


def _blocks(event: dict) -> list[dict]:
    msg = event.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict)]


def iter_tool_uses(t: Transcript) -> Iterator[dict]:
    for e in t.events:
        if e.get("type") != "assistant":
            continue
        for b in _blocks(e):
            if b.get("type") == "tool_use":
                yield b


def _flatten(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict):
                if isinstance(c.get("text"), str):
                    parts.append(c["text"])
                elif "content" in c:
                    parts.append(_flatten(c["content"]))
        return "\n".join(parts)
    return str(content)


def iter_tool_results(t: Transcript) -> Iterator[str]:
    for e in t.events:
        if e.get("type") != "user":
            continue
        for b in _blocks(e):
            if b.get("type") == "tool_result":
                yield _flatten(b.get("content"))


def _num(d: dict, *keys: str) -> float:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return 0


def _usage_tuple(d: dict) -> tuple[int, int, int, int]:
    return (
        int(_num(d, "inputTokens", "input_tokens")),
        int(_num(d, "outputTokens", "output_tokens")),
        int(_num(d, "cacheReadInputTokens", "cache_read_input_tokens", "cacheReadTokens")),
        int(_num(d, "cacheCreationInputTokens", "cache_creation_input_tokens", "cacheWriteTokens")),
    )


def _skill_name(block: dict) -> str | None:
    inp = block.get("input")
    if not isinstance(inp, dict):
        return None
    for k in ("skill", "command", "name"):
        v = inp.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def metrics_from_transcript(
    t: Transcript, *, wall_s: float, exit_code: int | None = None, timed_out: bool = False
) -> AgentMetrics:
    m = AgentMetrics(wall_s=wall_s, exit_code=exit_code, timed_out=timed_out)
    r = t.result
    if r is None:
        m.is_error = True
        m.subtype = "no_result"
    else:
        m.cost_usd = float(_num(r, "total_cost_usd", "cost_usd"))
        m.api_s = float(_num(r, "duration_api_ms")) / 1000.0
        m.turns = int(_num(r, "num_turns"))
        m.terminal_reason = r.get("terminal_reason")
        m.subtype = r.get("subtype")
        # A session that never reached the model can still report subtype "success"; the
        # terminal_reason (e.g. "api_error") is what tells us it failed.
        m.is_error = bool(r.get("is_error")) or "error" in str(r.get("terminal_reason") or "").lower()
        mu = r.get("modelUsage") or r.get("model_usage")
        if isinstance(mu, dict) and mu:
            for v in mu.values():
                if isinstance(v, dict):
                    i, o, cr, cw = _usage_tuple(v)
                    m.tokens_input += i
                    m.tokens_output += o
                    m.tokens_cache_read += cr
                    m.tokens_cache_write += cw
        elif isinstance(r.get("usage"), dict):
            m.tokens_input, m.tokens_output, m.tokens_cache_read, m.tokens_cache_write = _usage_tuple(r["usage"])
    skills: list[str] = []
    for b in iter_tool_uses(t):
        m.tool_calls += 1
        name = b.get("name")
        if name in SUBAGENT_TOOLS:
            m.subagent_calls += 1
        elif name == "Skill":
            s = _skill_name(b)
            if s and s not in skills:
                skills.append(s)
    m.skills_fired = skills
    for e in t.events:
        if e.get("type") != "assistant" or e.get("parent_tool_use_id"):
            continue
        msg = e.get("message")
        u = msg.get("usage") if isinstance(msg, dict) else None
        if isinstance(u, dict):
            i, _o, cr, cw = _usage_tuple(u)
            m.first_request_input_tokens = i + cr + cw
            break
    return m


def init_snapshot(t: Transcript) -> dict:
    if not t.init:
        return {}
    return {k: v for k, v in t.init.items() if k not in _NOISY_INIT_KEYS}


def _names(items: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(items, (list, tuple)):
        return out
    for it in items:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict) and isinstance(it.get("name"), str):
            out.append(it["name"])
    return out


def _skill_forms(name: str) -> set[str]:
    n = name.lstrip("/")
    return {n, n.split(":")[-1]}


def isolation_problems(snapshot: dict, treatment: TreatmentSpec) -> list[str]:
    if not snapshot:
        return ["no system/init event"]
    problems: list[str] = []
    plugins = _names(snapshot.get("plugins"))
    mcp = snapshot.get("mcp_servers")
    mcp_list = mcp if isinstance(mcp, list) else []
    if treatment.is_plain:
        # Plugins Claude Code ships with ("...@builtin", path "builtin") are part of vanilla Claude Code.
        raw = snapshot.get("plugins") if isinstance(snapshot.get("plugins"), list) else []
        for entry in raw:
            if not _is_builtin_plugin(entry):
                names = _names([entry])
                problems.append(f"plain arm has plugin {names[0] if names else entry!r}")
        for n in _names(mcp_list):
            problems.append(f"plain arm has MCP server {n!r}")
    for want in treatment.expect_plugins:
        if not any(p == want or p.split("@")[0] == want for p in plugins):
            problems.append(f"expected plugin {want!r} not loaded")
    status: dict[str, str] = {}
    for s in mcp_list:
        if isinstance(s, dict) and isinstance(s.get("name"), str):
            status[s["name"]] = str(s.get("status", "")).lower()
        elif isinstance(s, str):
            status[s] = ""
    for want in treatment.expect_mcp_servers:
        if want not in status:
            problems.append(f"expected MCP server {want!r} not present")
        elif status[want] in _BAD_MCP_STATUS:
            problems.append(f"MCP server {want!r} status is {status[want]!r}")
    avail: set[str] = set()
    for key in ("skills", "slash_commands"):
        for n in _names(snapshot.get(key)):
            avail |= _skill_forms(n)
    for want in treatment.expect_skills:
        if not (_skill_forms(want) & avail):
            problems.append(f"expected skill {want!r} not available")
    for key in ("plugin_errors", "mcp_server_errors"):
        v = snapshot.get(key)
        if v:
            problems.append(f"{key}: {json.dumps(v, default=str)[:300]}")
    return problems


def dependency_usage(t: Transcript, names: Iterable[str]) -> dict[str, bool]:
    names = list(names)
    pats = {n: re.compile(r"(^|[\s;&|(`$])" + re.escape(n) + r"(\s|$|;|&|\|)") for n in names}
    used = {n: False for n in names}
    for b in iter_tool_uses(t):
        if b.get("name") != "Bash":
            continue
        inp = b.get("input")
        cmd = inp.get("command") if isinstance(inp, dict) else None
        if not isinstance(cmd, str):
            continue
        for n, p in pats.items():
            if not used[n] and p.search(cmd):
                used[n] = True
    return used


def leakage_flags(t: Transcript, needles: Iterable[str]) -> list[str]:
    needles = [n for n in needles if n]
    flags: list[str] = []
    if not needles:
        return flags
    for b in iter_tool_uses(t):
        blob = json.dumps(b.get("input"), default=str, ensure_ascii=False).lower()
        for n in needles:
            if n.lower() in blob:
                f = f"tool_use {b.get('name')} input contains {n!r}"
                if f not in flags:
                    flags.append(f)
    for text in iter_tool_results(t):
        low = text.lower()
        for n in needles:
            if n.lower() in low:
                f = f"tool_result contains {n!r}"
                if f not in flags:
                    flags.append(f)
    return flags


_NET_TOOLS = {"WebFetch", "WebSearch"}
_NET_CMD = re.compile(r"\b(curl|wget|git\s+(clone|fetch|pull|ls-remote)|pip\s+download|uv\s+pip\s+download|"
                      r"python3?\s+-m\s+pip\s+download)\b|https?://", re.I)


def network_leakage_flags(t: Transcript, url_needles: Iterable[str]) -> list[str]:
    """Flag attempts to *reach* the upstream project over the network.

    Unlike `leakage_flags`, the repo URL is only flagged inside network requests (WebFetch/WebSearch, or
    a Bash command that downloads/clones): a project's own README and metadata contain its URL, so
    reading or grepping the repo must not count as leakage.
    """
    needles = [n.lower() for n in url_needles if n]
    flags: list[str] = []
    for b in iter_tool_uses(t):
        name = b.get("name")
        inp = b.get("input") or {}
        if name in _NET_TOOLS:
            blob = json.dumps(inp, default=str, ensure_ascii=False).lower()
        elif name == "Bash" and _NET_CMD.search(str(inp.get("command", ""))):
            blob = str(inp.get("command", "")).lower()
        else:
            continue
        for n in needles:
            f = f"{name} request targets {n!r}"
            if n in blob and f not in flags:
                flags.append(f)
    return flags


def _is_builtin_plugin(entry: Any) -> bool:
    if isinstance(entry, dict):
        return entry.get("path") == "builtin" or str(entry.get("source", "")).endswith("@builtin")
    return isinstance(entry, str) and entry.endswith("@builtin")


def api_error_statuses(t: Transcript) -> list[int]:
    """HTTP statuses from `system/api_retry` events (Claude Code's own retry loop)."""
    out = []
    for e in t.events:
        if e.get("type") == "system" and e.get("subtype") == "api_retry":
            try:
                out.append(int(e.get("error_status")))
            except (TypeError, ValueError):
                pass
    return out


def is_auth_failure(t: Transcript) -> bool:
    """The session could not authenticate: retrying, or running more trials, is pointless."""
    if any(code in (401, 403) for code in api_error_statuses(t)):
        return True
    return any(e.get("type") == "system" and e.get("subtype") == "api_retry"
               and "authentication" in str(e.get("error", "")).lower() for e in t.events)


def is_rate_limited(t: Transcript, stderr: str = "") -> bool:
    texts: list[str] = []
    r = t.result
    if r and r.get("is_error"):
        for k in ("result", "error", "api_error", "terminal_reason", "subtype"):
            v = r.get(k)
            if v:
                texts.append(v if isinstance(v, str) else json.dumps(v, default=str))
        for e in t.events:
            if e.get("type") == "system" and "error" in str(e.get("subtype", "")).lower():
                texts.append(json.dumps(e, default=str))
    failed = bool(r) and (r.get("is_error") or "error" in str(r.get("terminal_reason") or "").lower())
    if failed and any(code in (429, 529) for code in api_error_statuses(t)):
        return True
    if stderr:
        texts.append(stderr)
    low = "\n".join(texts).lower()
    return any(m in low for m in _RATE_MARKERS)
