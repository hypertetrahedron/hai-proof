"""Claude Code's own session data for a trial: collect, parse, summarise, render.

After the agent exits, the container's ``~/.claude`` (session and subagent JSONL transcripts, file
history, todos, plans, debug logs, shell snapshots, ...) is copied into ``<trial>/claude_home/``,
without ``.credentials.json`` and with every known secret value scrubbed. ``summarize()`` parses
the transcripts into ``claude_data.json`` (requests, tool calls, subagents, edits, context growth,
compactions) and ``render_session_html()`` turns that into ``session.html``.

The transcript format rules follow claude-lens (github_src/claude-lens, jsonl_ingest.py):
assistant entries repeat once per content block under one ``requestId`` and the last copy carries
the complete usage; tool results join to calls by ``tool_use_id``; subagents live in
``projects/<proj>/<sessionId>/subagents/agent-<agentId>.jsonl`` and join to the launching call via
``toolUseResult.agentId``.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from html import escape as e
from pathlib import Path
from typing import Any, Iterator

from .tarutil import extract_tar

HOME = "/home/agent"
_SKIP_NAMES = {".credentials.json"}
_SECRET_PATTERNS = (re.compile(rb"sk-ant-[A-Za-z0-9_\-]{16,}"),)
_REDACT_KEY = re.compile(r"key|token|secret|oauth|password|email", re.I)
_TEXT_CAP = 4000  # chars kept per text/thinking/tool block in the session page


# --------------------------------------------------------------------------- collect


def collect(ex: Any, container: str, trial_dir: Path, secrets: list[str]) -> dict:
    """Copy ~/.claude and a redacted ~/.claude.json out of the container. Returns a manifest."""
    dest = trial_dir / "claude_home"
    data = ex.get_tar(container, f"{HOME}/.claude")
    files = extract_tar(data, dest, strip_components=1,
                        skip=lambda name: name.rsplit("/", 1)[-1] in _SKIP_NAMES)
    try:
        cfg = ex.get_tar(container, f"{HOME}/.claude.json")
        extract_tar(cfg, trial_dir / "claude_home_config")
        raw = trial_dir / "claude_home_config" / ".claude.json"
        if raw.is_file():
            doc = json.loads(raw.read_text(encoding="utf-8", errors="replace") or "{}")
            (dest / "claude.json.redacted").write_text(json.dumps(_redact(doc), indent=2), encoding="utf-8")
            raw.unlink()
        (trial_dir / "claude_home_config").rmdir()
    except Exception:  # noqa: BLE001 - the global config is optional
        pass
    for p in dest.rglob(".claude.json*"):  # e.g. backups/.claude.json.backup.<ts>
        try:
            p.write_text(json.dumps(_redact(json.loads(p.read_text(encoding="utf-8"))), indent=2), encoding="utf-8")
        except (OSError, ValueError):
            p.unlink(missing_ok=True)
    scrubbed = scrub_secrets(dest, secrets)
    total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    return {"files": len(files), "bytes": total, "scrubbed_files": scrubbed}


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("<redacted>" if _REDACT_KEY.search(k) else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def scrub_secrets(root: Path, secrets: list[str]) -> int:
    """Replace secret values (and anything shaped like an Anthropic key) in every file. Returns count."""
    needles = [s.encode() for s in secrets if s and len(s) >= 8]
    changed = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        data = p.read_bytes()
        new = data
        for n in needles:
            new = new.replace(n, b"<redacted>")
        for pat in _SECRET_PATTERNS:
            new = pat.sub(b"<redacted>", new)
        if new != data:
            p.write_bytes(new)
            changed += 1
    return changed


# --------------------------------------------------------------------------- parse


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def _ts(s: Any) -> float | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict):
                if isinstance(c.get("text"), str):
                    out.append(c["text"])
                elif "content" in c:
                    out.append(_text_of(c["content"]))
            elif isinstance(c, str):
                out.append(c)
        return "\n".join(out)
    return "" if content is None else str(content)


def summarise_input(name: str, inp: Any) -> str:
    """One line describing a tool call."""
    if not isinstance(inp, dict):
        return ""
    for k in ("command", "file_path", "path", "pattern", "url", "query", "description", "skill", "prompt"):
        v = inp.get(k)
        if isinstance(v, str) and v:
            v = v.strip().splitlines()[0] if v.strip() else v
            return v[:200]
    return json.dumps(inp)[:200]


SLOW_CALL_S = 120
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_EXPLORE_TOOLS = {"Read", "Grep", "Glob", "LS", "NotebookRead", "WebFetch", "WebSearch"}
_DELEGATE_TOOLS = {"Agent", "Task"}
# Also project runners such as `python -m tornado.test.runtests` and gevent's `python -m gevent.tests`.
_TEST_RE = re.compile(r"\b(pytest|py\.test|unittest|tox|nox)\b|\b(pixi|hatch|make)\s+(run\s+)?test"
                      r"|\bpython[0-9.]*\s+-m\s+[\w.]*\btests?\b")
_EDIT_RE = re.compile(
    r"\bsed\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*i|\bperl\s+-[a-zA-Z]*i|\bpatch\b|\bgit\s+(apply|checkout\s+--|restore)\b"
    r"|\btee\b|cat\s*>|>>?\s*['\"]?[\w./-]+\.(py|pyi|toml|cfg|ini|txt|md|rst|json|ya?ml)\b"
    r"|\.write_text\(|\.write_bytes\(|open\([^)]*['\"][wa]b?\+?['\"]")
_RUN_RE = re.compile(r"\bpython[0-9.]*\s+(-u\s+)?[\w./-]+\.py\b|\bpython[0-9.]*\s+-c\b|\bfor\s+\w+\s+in\b.*;\s*do\b")
_EDIT_RE_ANY = re.compile(r"write_text\(|write_bytes\(|open\([^)]*['\"][wa]b?\+?['\"]|\bsed\s+-i|cat\s*>")


def classify_call(name: str | None, inp: Any) -> tuple[str, bool, bool]:
    """Return (phase, runs_tests, runs_code) for a tool call.

    Phases: ``edit`` (changes files), ``test`` (runs tests), ``explore`` (reads/searches/inspects),
    ``run`` (executes a script or loop: reproductions, experiments), ``delegate`` (subagent), ``other``.
    Bash commands are classified by what they do, because agents often edit through ``sed -i``,
    heredocs or ``python -c`` rather than the Edit tool. A command can edit *and* run tests/code.
    """
    name = name or ""
    if name in _EDIT_TOOLS:
        return "edit", False, False
    if name in _EXPLORE_TOOLS:
        return "explore", False, False
    if name in _DELEGATE_TOOLS:
        return "delegate", False, False
    if name.lower() == "bash" and isinstance(inp, dict):
        cmd = str(inp.get("command") or "")
        tests = bool(_TEST_RE.search(cmd))
        # Only lines outside heredoc bodies decide whether code is *run* (a heredoc fed to
        # `python -` is the edit script itself).
        runs = bool(_RUN_RE.search(_strip_heredocs(cmd))) and not tests
        if _EDIT_RE_ANY.search(cmd) or any(_EDIT_RE.search(line) for line in cmd.splitlines()):
            return "edit", tests, runs
        return ("test" if tests else "run" if runs else "explore"), tests, runs
    return "other", False, False


def _strip_heredocs(cmd: str) -> str:
    out, end = [], None
    for line in cmd.splitlines():
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            end = m.group(1)
        out.append(line)
    return "\n".join(out)


def _usage(u: dict) -> dict:
    def n(k: str) -> int:
        v = u.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

    d = {"input": n("input_tokens"), "output": n("output_tokens"),
         "cache_read": n("cache_read_input_tokens"), "cache_write": n("cache_creation_input_tokens")}
    d["context"] = d["input"] + d["cache_read"] + d["cache_write"]
    return d


def parse_transcript(path: Path) -> dict:
    """Parse one session or subagent JSONL file."""
    requests: dict[str, dict] = {}
    tools: dict[str, dict] = {}
    entries: list[dict] = []  # chronological conversation for the session page
    prompts: list[dict] = []
    compactions: list[dict] = []
    edits: list[dict] = []
    agent_links: dict[str, str] = {}  # tool_use_id -> agentId
    meta: dict[str, Any] = {}
    first = last = None
    for ev in _iter_jsonl(path):
        t = ev.get("type")
        ts = _ts(ev.get("timestamp"))
        if ts is not None:
            first = ts if first is None else min(first, ts)
            last = ts if last is None else max(last, ts)
        for k in ("version", "cwd", "sessionId", "agentId", "gitBranch", "entrypoint", "permissionMode"):
            if k not in meta and ev.get(k) is not None:
                meta[k] = ev.get(k)
        if ev.get("isCompactSummary") or ev.get("compactMetadata") or t in ("summary", "compact-boundary"):
            compactions.append({"ts": ts, "kind": t, "meta": ev.get("compactMetadata")})
            continue
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        if t == "assistant":
            rid = ev.get("requestId") or msg.get("id") or f"anon-{len(requests)}"
            u = _usage(msg.get("usage") or {})
            r = requests.get(rid)
            if r is None:
                r = requests[rid] = {"id": rid, "ts": ts, "model": msg.get("model"), "usage": u,
                                     "stop_reason": msg.get("stop_reason"), "effort": ev.get("effort")}
            elif u["output"] >= r["usage"]["output"]:
                r["usage"] = u
                r["stop_reason"] = msg.get("stop_reason") or r["stop_reason"]
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "tool_use":
                    tid = b.get("id") or f"tool-{len(tools)}"
                    inp = b.get("input")
                    phase, runs_tests, runs_code = classify_call(b.get("name"), inp)
                    tools[tid] = {"id": tid, "name": b.get("name"), "summary": summarise_input(b.get("name"), inp),
                                  "input_bytes": len(json.dumps(inp)) if inp is not None else 0,
                                  "start": ts, "end": None, "result_bytes": 0, "is_error": False,
                                  "request": rid, "phase": phase, "runs_tests": runs_tests,
                                  "runs_code": runs_code}
                    if b.get("name") in ("Agent", "Task") and isinstance(inp, dict):
                        tools[tid]["subagent_type"] = inp.get("subagent_type")
                        tools[tid]["description"] = inp.get("description")
                    entries.append({"kind": "tool_use", "ts": ts, "id": tid, "name": b.get("name"),
                                    "input": json.dumps(inp, ensure_ascii=False)[:_TEXT_CAP]})
                elif bt in ("text", "thinking"):
                    txt = b.get("text") if bt == "text" else b.get("thinking")
                    if isinstance(txt, str) and txt.strip():
                        entries.append({"kind": bt, "ts": ts, "text": txt[:_TEXT_CAP]})
        elif t == "user":
            content = msg.get("content")
            tur = ev.get("toolUseResult")
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                                 for b in content):
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                        continue
                    tid = b.get("tool_use_id")
                    text = _text_of(b.get("content"))
                    err = bool(b.get("is_error"))
                    if isinstance(tur, dict) and (tur.get("isError") or tur.get("error")):
                        err = True
                    tc = tools.get(tid)
                    if tc is not None:
                        tc["end"] = ts
                        tc["result_bytes"] = len(text.encode("utf-8", "replace"))
                        tc["is_error"] = err
                    entries.append({"kind": "tool_result", "ts": ts, "id": tid, "is_error": err,
                                    "text": text[:_TEXT_CAP]})
                if isinstance(tur, dict):
                    if tur.get("agentId") and content:
                        tid = next((b.get("tool_use_id") for b in content
                                    if isinstance(b, dict) and b.get("type") == "tool_result"), None)
                        if tid:
                            agent_links[tid] = str(tur["agentId"])
                    if tur.get("filePath") and ("structuredPatch" in tur or "content" in tur):
                        added = removed = 0
                        for hunk in tur.get("structuredPatch") or []:
                            for line in (hunk.get("lines") or []) if isinstance(hunk, dict) else []:
                                if isinstance(line, str) and line.startswith("+"):
                                    added += 1
                                elif isinstance(line, str) and line.startswith("-"):
                                    removed += 1
                        if tur.get("type") == "create" and not tur.get("structuredPatch"):
                            added = len(str(tur.get("content") or "").splitlines())
                        edits.append({"ts": ts, "file": tur["filePath"], "added": added, "removed": removed,
                                      "type": tur.get("type") or "update"})
            elif not ev.get("isMeta"):
                text = _text_of(content)
                origin = ev.get("origin") if isinstance(ev.get("origin"), dict) else {}
                kind = origin.get("kind") or ("human" if text and not text.startswith("<") else "injected")
                if text.strip():
                    prompts.append({"ts": ts, "kind": kind, "text": text[:600]})
                    entries.append({"kind": "prompt", "ts": ts, "prompt_kind": kind, "text": text[:_TEXT_CAP]})
    for tid, aid in agent_links.items():
        if tid in tools:
            tools[tid]["agent_id"] = aid
    reqs = sorted(requests.values(), key=lambda r: r["ts"] or 0)
    calls = sorted(tools.values(), key=lambda c: c["start"] or 0)
    for c in calls:
        c["duration_s"] = round(c["end"] - c["start"], 3) if c["start"] is not None and c["end"] is not None else None
    return {"file": path.name, "meta": meta, "first_ts": first, "last_ts": last,
            "duration_s": round(last - first, 3) if first is not None and last is not None else None,
            "requests": reqs, "tool_calls": calls, "prompts": prompts, "compactions": compactions,
            "edits": edits, "entries": entries}


def cost_state(home: Path) -> dict | None:
    """Claude Code's own cost record: the last ``cost-state`` entry of each main session file, summed.

    Claude Code writes it when the session ends, including when it is stopped (SIGTERM at the trial's time
    limit), so it gives the exact cost and token totals of a session whose stream never reached its result
    event. It covers in-process subagents. Returns None when no session has one.
    """
    projects = home / "projects"
    found = []
    for main in sorted(projects.glob("*/*.jsonl")) if projects.is_dir() else []:
        last = None
        for ev in _iter_jsonl(main):
            if ev.get("type") == "cost-state":
                last = ev
        if last:
            found.append(last)
    if not found:
        return None
    out = {"cost_usd": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "api_s": 0.0}
    for ev in found:
        out["cost_usd"] += float(ev.get("totalCostUSD") or 0.0)
        out["api_s"] += float(ev.get("totalAPIDuration") or 0.0) / 1000.0
        for u in (ev.get("modelUsage") or {}).values():
            out["input"] += int(u.get("inputTokens") or 0)
            out["output"] += int(u.get("outputTokens") or 0)
            out["cache_read"] += int(u.get("cacheReadInputTokens") or 0)
            out["cache_write"] += int(u.get("cacheCreationInputTokens") or 0)
    return out


def apply_cost_state(m: Any, cs: dict | None) -> bool:
    """Fill an AgentMetrics that has no result event from a cost_state(); True if it changed."""
    if m.cost_source != "result" or m.subtype != "no_result" or m.cost_usd:
        return False
    if not cs:
        m.cost_source = "none"
        return True
    m.cost_usd, m.api_s = cs["cost_usd"], cs["api_s"]
    m.tokens_input, m.tokens_output = cs["input"], cs["output"]
    m.tokens_cache_read, m.tokens_cache_write = cs["cache_read"], cs["cache_write"]
    m.cost_source = "session"
    return True


def summarize(home: Path) -> dict:
    """Parse every session under a collected ~/.claude (``claude_home``)."""
    sessions = []
    projects = home / "projects"
    for main in sorted(projects.glob("*/*.jsonl")) if projects.is_dir() else []:
        s = parse_transcript(main)
        s["project"] = main.parent.name
        s["session_id"] = main.stem
        subs = []
        sub_dir = main.parent / main.stem / "subagents"
        launch = {c.get("agent_id"): c for c in s["tool_calls"] if c.get("agent_id")}
        for f in sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else []:
            sub = parse_transcript(f)
            aid = f.stem[len("agent-"):]
            sub["agent_id"] = aid
            call = launch.get(aid) or {}
            sub["launched_by"] = call.get("id")
            sub["subagent_type"] = call.get("subagent_type")
            sub["description"] = call.get("description")
            sub["stats"] = _stats(sub)
            subs.append(sub)
        s["subagents"] = subs
        s["stats"] = _stats(s, subs)
        sessions.append(s)
    other = {}
    if home.is_dir():
        for d in sorted(home.iterdir()):
            files = [p for p in d.rglob("*") if p.is_file()] if d.is_dir() else [d]
            other[d.name] = {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}
    return {"schema": 1, "sessions": sessions, "contents": other, "stats": combined_stats(sessions)}


def _stats(s: dict, subs: list[dict] | None = None) -> dict:
    reqs, calls = s["requests"], s["tool_calls"]
    by_tool: dict[str, int] = {}
    for c in calls:
        by_tool[c["name"] or "?"] = by_tool.get(c["name"] or "?", 0) + 1
    files = sorted({x["file"] for x in s["edits"]})
    out = {
        "requests": len(reqs),
        "tool_calls": len(calls),
        "tool_errors": sum(1 for c in calls if c["is_error"]),
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: -kv[1])),
        "tokens_input": sum(r["usage"]["input"] for r in reqs),
        "tokens_output": sum(r["usage"]["output"] for r in reqs),
        "tokens_cache_read": sum(r["usage"]["cache_read"] for r in reqs),
        "tokens_cache_write": sum(r["usage"]["cache_write"] for r in reqs),
        "peak_context": max((r["usage"]["context"] for r in reqs), default=0),
        "cache_misses": cache_misses(reqs),
        "compactions": len(s["compactions"]),
        "edits": len(s["edits"]),
        "files_edited": len(files),
        "lines_added": sum(x["added"] for x in s["edits"]),
        "lines_removed": sum(x["removed"] for x in s["edits"]),
        "prompts": len(s["prompts"]),
        "models": sorted({r["model"] for r in reqs if r.get("model")}),
        "duration_s": s["duration_s"],
        "tool_time_s": round(sum(c["duration_s"] or 0 for c in calls), 1),
    }
    out.update(phase_stats(s))
    if subs is not None:
        out["subagents"] = len(subs)
        out["subagent_tool_calls"] = sum(x["stats"]["tool_calls"] for x in subs)
        out["subagent_tokens_output"] = sum(x["stats"]["tokens_output"] for x in subs)
    return out


def cache_misses(reqs: list[dict]) -> int:
    """Requests after the first that read back less than half of the previous request's cached prefix
    (cache_read + cache_write). A warm prompt cache re-reads the whole prefix each turn, so these are the
    requests that paid to rewrite it: cache expiry after a long tool call, a changed prefix, a compaction."""
    n = 0
    for prev, cur in zip(reqs, reqs[1:]):
        prefix = prev["usage"]["cache_read"] + prev["usage"]["cache_write"]
        if prefix > 0 and cur["usage"]["cache_read"] < prefix / 2:
            n += 1
    return n


def phase_stats(s: dict) -> dict:
    """How the session spent its time, from the phase of each tool call.

    The interval from one tool call's start to the next one's (or to the end of the session) is
    attributed to the earlier call's phase, so it includes the model thinking about that result.
    """
    calls = [c for c in s["tool_calls"] if c.get("start") is not None]
    t0, t1 = s.get("first_ts"), s.get("last_ts")
    phases = ("explore", "edit", "test", "run", "delegate", "other")
    count = {p: 0 for p in phases}
    time_s = {p: 0.0 for p in phases}
    for i, c in enumerate(calls):
        p = c.get("phase") or "other"
        count[p] = count.get(p, 0) + 1
        nxt = calls[i + 1]["start"] if i + 1 < len(calls) else t1
        # An edit that also runs tests/code spends its time running, not editing.
        tp = "test" if c.get("runs_tests") else "run" if c.get("runs_code") else p
        if nxt is not None:
            time_s[tp] = time_s.get(tp, 0.0) + max(0.0, nxt - c["start"])
    edits = [c for c in calls if c.get("phase") == "edit"]
    tests = [c for c in calls if c.get("runs_tests")]
    cycles = 0
    last = None
    for c in calls:
        p = "test" if c.get("runs_tests") and c.get("phase") != "edit" else c.get("phase")
        if p == "test" and last == "edit":
            cycles += 1
        if p in ("edit", "test"):
            last = p
    first_edit = edits[0]["start"] if edits else None
    return {
        "phase_calls": count,
        "phase_time_s": {p: round(v, 1) for p, v in time_s.items()},
        "first_edit_s": round(first_edit - t0, 1) if first_edit is not None and t0 is not None else None,
        "explore_before_first_edit": sum(1 for c in calls if c.get("phase") == "explore"
                                         and (first_edit is None or c["start"] < first_edit)),
        "edit_calls": len(edits),
        "test_runs": len(tests),
        "code_runs": sum(1 for c in calls if c.get("runs_code")),
        "edit_test_cycles": cycles,
        "tested_after_last_edit": bool(edits and tests and tests[-1]["start"] >= edits[-1]["start"]),
        # Environment friction shows up as very long single commands (hanging test suites, sleeps).
        "slow_calls": sum(1 for c in calls if (c.get("duration_s") or 0) > SLOW_CALL_S),
        "longest_call_s": round(max((c.get("duration_s") or 0 for c in calls), default=0), 1),
    }


def combined_stats(sessions: list[dict]) -> dict:
    """Trial-level numbers stored on TrialResult.session (main sessions plus their subagents)."""
    if not sessions:
        return {}
    # Totals include subagents; subagents / subagent_tool_calls say how much of it was delegated.
    out: dict[str, Any] = {}
    for k in ("requests", "tool_calls", "tool_errors", "compactions", "edits", "lines_added", "lines_removed"):
        out[k] = sum(src["stats"][k] for s in sessions for src in [s] + s["subagents"])
    for k in ("subagents", "subagent_tool_calls"):
        out[k] = sum(s["stats"].get(k, 0) for s in sessions)
    out["sessions"] = len(sessions)
    out["peak_context"] = max(s["stats"]["peak_context"] for s in sessions)
    # Main conversations only: a subagent starts its own cache, so its first request is never a miss.
    out["cache_misses"] = sum(s["stats"].get("cache_misses", 0) for s in sessions)
    files = {x["file"] for s in sessions for x in s["edits"]}
    files |= {x["file"] for s in sessions for sub in s["subagents"] for x in sub["edits"]}
    out["files_edited"] = len(files)
    by_tool: dict[str, int] = {}
    for s in sessions:
        for src in [s] + s["subagents"]:
            for name, n in src["stats"]["by_tool"].items():
                by_tool[name] = by_tool.get(name, 0) + n
    out["by_tool"] = dict(sorted(by_tool.items(), key=lambda kv: -kv[1]))
    # How the (first) main session worked: phases of its own tool calls, not its subagents'.
    main = sessions[0]["stats"]
    for k in ("phase_calls", "phase_time_s", "first_edit_s", "explore_before_first_edit", "edit_calls",
              "test_runs", "code_runs", "edit_test_cycles", "tested_after_last_edit", "slow_calls",
              "longest_call_s"):
        out[k] = main.get(k)
    return out


def patch_stats(text: str) -> dict:
    """Lines and files changed according to the trial's git diff (``session.patch``)."""
    added = removed = 0
    files = set()
    for line in text.split("\n"):  # not splitlines(): a lone \r or U+2028 in a source line is not a line break
        if line.startswith("diff --git "):
            files.add(line.rsplit(" b/", 1)[-1])
        elif line.startswith(("+++", "---")):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"diff_files": len(files), "diff_added": added, "diff_removed": removed}


def write_trial_data(trial_dir: Path, title: str) -> dict:
    """Parse ``claude_home`` and write ``claude_data.json`` and ``session.html``. Returns the stats.

    ``lines_added``/``files_edited`` count only Edit/Write tool results; agents mostly edit through Bash
    (heredocs, sed), so once ``session.patch`` exists its git-diff counts are added as ``diff_*``."""
    data = summarize(trial_dir / "claude_home")
    patch = trial_dir / "session.patch"
    if patch.is_file() and data["stats"]:
        data["stats"].update(patch_stats(patch.read_text(encoding="utf-8", errors="replace")))
    (trial_dir / "claude_data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (trial_dir / "session.html").write_text(render_session_html(data, title), encoding="utf-8")
    return data["stats"]


# --------------------------------------------------------------------------- render

_CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--surface:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;
--line:#e3e2dd;--series:#2a78d6;--series2:#d6762a;--series3:#1f9e89;--series4:#8a5cc9;--good:#0b6b3a;--bad:#a8261b;--code:#f3f2ee}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#1a1a19;--surface:#222221;
--ink:#ffffff;--ink2:#c3c2b7;--muted:#8d8c84;--line:#3a3a38;--series:#3987e5;--series2:#e5913a;--series3:#3bbfa8;--series4:#a98be0;--good:#5fd18f;
--bad:#ff8a7a;--code:#2b2b29}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--surface:#222221;--ink:#ffffff;--ink2:#c3c2b7;
--muted:#8d8c84;--line:#3a3a38;--series:#3987e5;--series2:#e5913a;--series3:#3bbfa8;--series4:#a98be0;--good:#5fd18f;--bad:#ff8a7a;--code:#2b2b29}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1150px;margin:0 auto;padding:24px 16px 64px}h1{font-size:20px;margin:0 0 6px}
h2{font-size:16px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
.tile b{display:block;font-size:18px}.tile span{color:var(--ink2);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:var(--surface)}
th,td{border-bottom:1px solid var(--line);padding:3px 7px;text-align:right;vertical-align:top}
th.l,td.l{text-align:left}th{color:var(--ink2);font-weight:600}.tablewrap{overflow-x:auto}
.bad{color:var(--bad)}.note{color:var(--ink2);font-size:12.5px}
pre{background:var(--code);padding:6px 8px;white-space:pre-wrap;word-break:break-word;font-size:12px;margin:4px 0}
details{margin:2px 0}summary{cursor:pointer}.e{border-left:3px solid var(--line);padding:2px 0 2px 10px;margin:6px 0}
.e.tool{border-color:var(--series)}.e.err{border-color:var(--bad)}.e.prompt{border-color:var(--series2)}
.sub{margin-left:18px;border-left:2px dashed var(--line);padding-left:10px}.t{color:var(--muted);font-size:11.5px}
svg{max-width:100%;height:auto}
.tl-l1{fill:var(--series);opacity:.85}.tl-l2{fill:var(--series3);opacity:.85}.tl-l3{fill:var(--series2);opacity:.85}
.tl-ctx{fill:none;stroke:var(--ink);stroke-width:1.2}.tl-band{fill:var(--ink);opacity:.045}
.tl-strip{fill:var(--ink);opacity:.08}.tl-strip.b{opacity:.2}.tl-tick{stroke:var(--muted);opacity:.5}
.tl-num{font-size:10px;fill:var(--ink2)}.tl-lane{font-size:10px;fill:var(--ink2)}.tl-rule{stroke:var(--line)}
.tl-ev{stroke:var(--ink2);stroke-dasharray:3 2}.tl-miss{fill:var(--bad);stroke:var(--surface)}
.tl-hit{stroke:transparent;stroke-width:5}.tl-hit:hover{stroke:var(--ink);stroke-opacity:.3}
.tl-tool{fill:var(--ink2);opacity:.8}.tl-err{fill:var(--bad)}.tl-agent{fill:var(--series4);opacity:.8}
.tl-alab{font-size:9px;fill:var(--ink)}.tl-legend span{margin-right:14px;white-space:nowrap}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
i.tl-l1{background:var(--series)}i.tl-l2{background:var(--series3)}i.tl-l3{background:var(--series2)}
i.tl-tool{background:var(--ink2)}i.tl-err{background:var(--bad)}i.tl-agent{background:var(--series4)}
"""


def _fmt_s(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 60:.1f} min" if v >= 120 else f"{v:.1f} s"


def _k(n: int | float) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(int(n))


def _nice_step(span: float, n: int = 5) -> float:
    """A 1/2/2.5/5 x 10^k step that splits `span` into about `n` intervals."""
    raw = span / n if span > 0 else 1.0
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


# Context layers, bottom-up in cost order; they sum to the request's context, so the stack's outline is
# the context curve (claude-lens, template.html CTX_LAYERS).
_CTX_LAYERS = (("cache read", "l1", lambda u: u["cache_read"]),
               ("uncached input", "l2", lambda u: u["input"]),
               ("cache write", "l3", lambda u: u["cache_write"]))


def _pack_rows(spans: list[tuple[float, float]]) -> list[int]:
    """First-fit row per (start, end) span so that overlapping spans get different rows."""
    ends: list[float] = []
    rows = []
    for a, b in spans:
        r = next((i for i, end in enumerate(ends) if end < a), None)
        if r is None:
            ends.append(b)
            r = len(ends) - 1
        else:
            ends[r] = b
        rows.append(r)
    return rows


def _context_svg(s: dict) -> str:
    """Session timeline in the claude-lens layout: lanes over one elapsed-time axis.

    Turn ruler (one band per prompt), the context of each main-session request stacked as cache read /
    uncached input / cache write with the total as its outline, compactions and cache misses marked on it,
    tool calls per request (errors in red), and one bar per subagent run. claude-lens's cost-per-turn lane
    is left out: transcripts carry tokens, not prices. Hover titles give the values.
    """
    reqs = [r for r in s["requests"] if r["ts"] is not None]
    subs = sorted(((x["first_ts"], x["last_ts"], x) for x in s["subagents"]
                   if x.get("first_ts") is not None and x.get("last_ts") is not None), key=lambda v: v[0])
    if len(reqs) < 2:
        return '<p class="note">Not enough requests to chart.</p>'
    times = [r["ts"] for r in reqs] + [v for a, b, _ in subs for v in (a, b)]
    t0, t1 = min(times), max(times)
    peak = max(r["usage"]["context"] for r in reqs) or 1
    step = _nice_step(peak)
    ymax = step * math.ceil(peak / step)
    tools_per: dict[str, list[int]] = {}
    for c in s["tool_calls"]:
        n = tools_per.setdefault(c.get("request"), [0, 0])
        n[0] += 1
        n[1] += bool(c["is_error"])
    tool_max = max((tools_per.get(r["id"], [0])[0] for r in reqs), default=0)
    rows = _pack_rows([(a, b) for a, b, _ in subs])
    n_rows = max(rows) + 1 if rows else 0

    w, left, right, gap = 900, 78, 10, 6
    ruler_y, ruler_h = 6, 16
    ctx_y, ctx_h = ruler_y + ruler_h + gap, 190
    tool_y, tool_h = ctx_y + ctx_h + gap, (34 if tool_max else 0)
    agent_y, agent_lane, agent_gap = tool_y + tool_h + (gap if tool_h else 0), 12, 3
    agent_h = n_rows * (agent_lane + agent_gap) - agent_gap if n_rows else 0
    bottom = agent_y + agent_h if agent_h else tool_y + tool_h if tool_h else ctx_y + ctx_h
    h = bottom + 44
    lanes = [(ruler_y, ruler_h), (ctx_y, ctx_h)] + ([(tool_y, tool_h)] if tool_h else []) \
        + ([(agent_y, agent_h)] if agent_h else [])

    def x(t: float) -> float:
        return left + (t - t0) / ((t1 - t0) or 1) * (w - left - right)

    def y(v: float) -> float:
        return ctx_y + ctx_h - min(v, ymax) / ymax * ctx_h

    def tip(text: str) -> str:
        return f"<title>{e(text)}</title>"

    def mins(t: float) -> str:
        return f"+{(t - t0) / 60:.1f}m"

    out = []
    turns = sorted(p["ts"] for p in s["prompts"] if p.get("ts") is not None and p["ts"] <= t1)
    if not turns or turns[0] > t0:
        turns.insert(0, t0)
    for i, ta in enumerate(turns):
        xa, xb = x(max(ta, t0)), x(turns[i + 1]) if i + 1 < len(turns) else w - right
        bw = max(xb - xa, 1)
        if i % 2:
            out += [f'<rect x="{xa:.1f}" y="{ly}" width="{bw:.1f}" height="{lh}" class="tl-band"/>' for ly, lh in lanes]
        strip = "tl-strip b" if i % 2 else "tl-strip"
        label = tip(f"Turn {i + 1} · {mins(ta)}")
        out.append(f'<rect x="{xa:.1f}" y="{ruler_y}" width="{bw:.1f}" height="{ruler_h}" class="{strip}">{label}</rect>')
        out += [f'<line x1="{xa:.1f}" x2="{xa:.1f}" y1="{ly}" y2="{ly + lh}" class="tl-tick"/>' for ly, lh in lanes]
        if bw >= 14:
            out.append(f'<text x="{xa + 3:.1f}" y="{ruler_y + 12}" class="tl-num">{i + 1}</text>')

    for k in range(int(round(ymax / step)) + 1):
        v = k * step
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="var(--line)" '
                   f'stroke-width="{1 if k == 0 else 0.6}"/>'
                   f'<text x="{left - 6}" y="{y(v) + 4:.1f}" font-size="11" fill="var(--ink2)" '
                   f'text-anchor="end">{_k(v) if v else "0"}</text>')
    xs = [x(r["ts"]) for r in reqs]
    base = [0] * len(reqs)
    for _, cls, get in _CTX_LAYERS:
        upper = [b + get(r["usage"]) for b, r in zip(base, reqs)]
        pts = [f"{px:.1f},{y(u):.1f}" for px, u in zip(xs, upper)]
        pts += [f"{px:.1f},{y(b):.1f}" for px, b in zip(reversed(xs), reversed(base))]
        out.append(f'<polygon points="{" ".join(pts)}" class="tl-{cls}"/>')
        base = upper
    out.append('<polyline points="' + " ".join(f"{px:.1f},{y(r['usage']['context']):.1f}" for px, r in zip(xs, reqs))
               + '" class="tl-ctx"/>')
    for c in s["compactions"]:
        if c["ts"] is not None and t0 <= c["ts"] <= t1:
            cx = x(c["ts"])
            label = tip(mins(c["ts"]) + " compaction")
            out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{ctx_y}" y2="{ctx_y + ctx_h}" class="tl-ev">'
                       f'{label}</line>')
    for prev, cur in zip(reqs, reqs[1:]):
        prefix = prev["usage"]["cache_read"] + prev["usage"]["cache_write"]
        if prefix > 0 and cur["usage"]["cache_read"] < prefix / 2:
            u = cur["usage"]
            label = tip(f"{mins(cur['ts'])} cache miss · {_k(u['cache_write'])} tokens re-written")
            out.append(f'<circle cx="{x(cur["ts"]):.1f}" cy="{y(u["context"]):.1f}" r="4" class="tl-miss">'
                       f'{label}</circle>')
    for px, r in zip(xs, reqs):
        u = r["usage"]
        label = tip(f"{mins(r['ts'])} · context {u['context']:,} = cache read {u['cache_read']:,} + uncached "
                    f"{u['input']:,} + cache write {u['cache_write']:,} · output {u['output']:,}")
        out.append(f'<line x1="{px:.1f}" x2="{px:.1f}" y1="{y(u["context"]):.1f}" y2="{ctx_y + ctx_h}" class="tl-hit">'
                   f'{label}</line>')

    if tool_h:
        bw = max(1.5, min(6.0, (w - left - right) / len(reqs)))
        out.append(f'<text x="{left - 6}" y="{tool_y + tool_h - 1}" class="tl-lane" text-anchor="end">tools</text>'
                   f'<line x1="{left}" x2="{w - right}" y1="{tool_y + tool_h}" y2="{tool_y + tool_h}" class="tl-rule"/>')
        for px, r in zip(xs, reqs):
            n, err = tools_per.get(r["id"], [0, 0])
            if not n:
                continue
            bh = max(1.5, (tool_h - 2) * n / tool_max)
            label = tip(f"{mins(r['ts'])} · {n} tool call(s), {err} error(s)")
            out.append(f'<rect x="{px - bw / 2:.1f}" y="{tool_y + tool_h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                       f'class="tl-tool">{label}</rect>')
            if err:
                eh = max(1.5, bh * err / n)
                out.append(f'<rect x="{px - bw / 2:.1f}" y="{tool_y + tool_h - eh:.1f}" width="{bw:.1f}" '
                           f'height="{eh:.1f}" class="tl-err"/>')
    if agent_h:
        out.append(f'<text x="{left - 6}" y="{agent_y + agent_lane - 2}" class="tl-lane" text-anchor="end">agents</text>')
        for (a, b, sub), row in zip(subs, rows):
            ax, ay = x(a), agent_y + row * (agent_lane + agent_gap)
            aw = max(x(b) - ax, 3)
            label = str(sub.get("description") or sub.get("subagent_type") or sub["agent_id"])
            room = int((aw - 8) / 5.4)
            text = (label if len(label) <= room else label[:max(room - 1, 1)] + "…") if aw >= 46 else ""
            title = tip(f"{label} · {sub.get('subagent_type') or '?'} · {_fmt_s(b - a)}")
            out.append(f'<g>{title}'
                       f'<rect x="{ax:.1f}" y="{ay}" width="{aw:.1f}" height="{agent_lane}" rx="3" class="tl-agent"/>'
                       + (f'<text x="{ax + 4:.1f}" y="{ay + agent_lane - 3}" class="tl-alab">{e(text)}</text>'
                          if text else "") + "</g>")

    out += [f'<text x="{x(t0 + f * (t1 - t0)):.1f}" y="{bottom + 16}" font-size="11" fill="var(--ink2)" '
            f'text-anchor="{a}">{(f * (t1 - t0)) / 60:.0f}m</text>'
            for f, a in ((0, "start"), (.25, "middle"), (.5, "middle"), (.75, "middle"), (1, "end"))]
    cy = ctx_y + ctx_h / 2
    out.append(f'<text x="14" y="{cy:.1f}" font-size="12" fill="var(--ink)" text-anchor="middle" '
               f'transform="rotate(-90 14 {cy:.1f})">Context per request (tokens)</text>'
               f'<text x="{(left + w - right) / 2:.1f}" y="{h - 6}" font-size="12" fill="var(--ink)" '
               f'text-anchor="middle">Elapsed time (minutes)</text>')
    legend = "".join(f'<span><i class="sw tl-{cls}"></i>{name}</span>' for name, cls, _ in _CTX_LAYERS)
    return (f'<svg viewBox="0 0 {w} {h}" role="group" aria-label="Session timeline: turns, context, tool calls and '
            f'subagent runs over elapsed time">{"".join(out)}</svg>'
            f'<p class="note tl-legend">{legend}<span><i class="sw tl-tool"></i>tool calls per request</span>'
            '<span><i class="sw tl-err"></i>tool errors</span><span><i class="sw tl-agent"></i>subagent run</span></p>'
            '<p class="note">Top strip: one band per prompt (turn). The stacked area is each main-session API '
            "request's context (cache read + uncached input + cache write); its outline is the total. "
            'Dashed line: compaction. Circle: cache miss (less than half of the previous prefix read back). '
            'Hover a mark for its values.</p>')


def _entries_html(src: dict, subs_by_tool: dict[str, dict], t0: float | None) -> str:
    out = []
    results = {x["id"]: x for x in src["entries"] if x["kind"] == "tool_result"}
    calls = {c["id"]: c for c in src["tool_calls"]}
    for en in src["entries"]:
        rel = f'+{(en["ts"] - t0) / 60:.1f}m' if en.get("ts") and t0 else ""
        k = en["kind"]
        if k == "prompt":
            out.append(f'<div class="e prompt"><span class="t">{rel} prompt ({e(str(en["prompt_kind"]))})</span>'
                       f'<pre>{e(en["text"])}</pre></div>')
        elif k == "text":
            out.append(f'<div class="e"><span class="t">{rel} assistant</span><pre>{e(en["text"])}</pre></div>')
        elif k == "thinking":
            out.append(f'<div class="e"><details><summary class="t">{rel} thinking</summary>'
                       f'<pre>{e(en["text"])}</pre></details></div>')
        elif k == "tool_use":
            c = calls.get(en["id"], {})
            r = results.get(en["id"])
            err = r is not None and r["is_error"]
            dur = _fmt_s(c.get("duration_s"))
            head = (f'{rel} <b>{e(str(en["name"]))}</b> {e(c.get("summary", ""))} '
                    f'<span class="t">({dur}{", error" if err else ""})</span>')
            body = f'<pre>{e(en["input"])}</pre>'
            if r is not None:
                body += f'<div class="t">result</div><pre>{e(r["text"])}</pre>'
            out.append(f'<div class="e tool{" err" if err else ""}"><details><summary>{head}</summary>'
                       f'{body}</details></div>')
            sub = subs_by_tool.get(en["id"])
            if sub is not None:
                st = sub["stats"]
                out.append(f'<div class="sub"><div class="t">subagent {e(sub["agent_id"])} '
                           f'({e(str(sub.get("subagent_type") or "?"))}): {st["requests"]} requests, '
                           f'{st["tool_calls"]} tool calls, {_fmt_s(st["duration_s"])}</div>'
                           f'{_entries_html(sub, {}, t0)}</div>')
    return "".join(out)


def render_session_html(data: dict, title: str) -> str:
    parts = [f"<h1>{e(title)}</h1>"]
    if not data["sessions"]:
        parts.append('<p class="note">No Claude Code session transcripts were found.</p>')
    for s in data["sessions"]:
        st = s["stats"]
        m = s["meta"]
        tiles = [
            ("Duration", _fmt_s(s["duration_s"])), ("API requests", st["requests"]),
            ("Tool calls", st["tool_calls"]), ("Tool errors", st["tool_errors"]),
            ("Tool time", _fmt_s(st["tool_time_s"])), ("Subagents", st.get("subagents", 0)),
            ("Peak context", _k(st["peak_context"])), ("Compactions", st["compactions"]), ("Cache misses", st.get("cache_misses", "—")),
            ("Output tokens", _k(st["tokens_output"])), ("Cache read", _k(st["tokens_cache_read"])),
        ]
        ts = data["stats"]
        if "diff_added" in ts:
            tiles += [("Files changed (git diff)", ts["diff_files"]),
                      ("Lines +/− (git diff)", f'{ts["diff_added"]}/{ts["diff_removed"]}')]
        tiles.append(("Lines +/− via Edit/Write", f'{st["lines_added"]}/{st["lines_removed"]}'))
        parts.append(f'<p class="note">Session {e(s["session_id"])} · CLI {e(str(m.get("version", "?")))} · '
                     f'models {e(", ".join(st["models"]) or "?")} · cwd {e(str(m.get("cwd", "?")))}</p>')
        parts.append('<div class="tiles">' + "".join(f'<div class="tile"><b>{e(str(v))}</b><span>{e(k)}</span></div>'
                                                     for k, v in tiles) + "</div>")
        parts.append("<h2>Session timeline</h2>" + _context_svg(s))
        rows = "".join(f'<tr><td class="l">{e(n)}</td><td>{c}</td></tr>' for n, c in st["by_tool"].items())
        parts.append(f'<h2>Tools</h2><div class="tablewrap"><table><tr><th class="l">Tool</th><th>Calls</th></tr>'
                     f"{rows}</table></div>")
        if s["subagents"]:
            rows = "".join(
                f'<tr><td class="l">{e(x["agent_id"])}</td><td class="l">{e(str(x.get("subagent_type") or ""))}</td>'
                f'<td class="l">{e(str(x.get("description") or ""))}</td><td>{_fmt_s(x["duration_s"])}</td>'
                f'<td>{x["stats"]["requests"]}</td><td>{x["stats"]["tool_calls"]}</td>'
                f'<td>{_k(x["stats"]["tokens_output"])}</td><td>{x["stats"]["files_edited"]}</td></tr>'
                for x in s["subagents"])
            parts.append('<h2>Subagents</h2><div class="tablewrap"><table><tr><th class="l">Agent</th>'
                         '<th class="l">Type</th><th class="l">Description</th><th>Duration</th><th>Requests</th>'
                         f'<th>Tool calls</th><th>Output</th><th>Files edited</th></tr>{rows}</table></div>')
        edits: dict[str, list[int]] = {}
        for src in [s] + s["subagents"]:
            for x in src["edits"]:
                a = edits.setdefault(x["file"], [0, 0, 0])
                a[0] += 1
                a[1] += x["added"]
                a[2] += x["removed"]
        if edits:
            rows = "".join(f'<tr><td class="l">{e(f)}</td><td>{v[0]}</td><td>{v[1]}</td><td>{v[2]}</td></tr>'
                           for f, v in sorted(edits.items()))
            parts.append('<h2>Files edited with Edit/Write</h2><p class="note">Edits made through Bash (heredocs, '
                         'sed) are not listed here; session.patch has the full diff.</p>'
                         '<div class="tablewrap"><table><tr><th class="l">File</th>'
                         f'<th>Edits</th><th>+</th><th>−</th></tr>{rows}</table></div>')
        slow = sorted((c for src in [s] + s["subagents"] for c in src["tool_calls"] if c["duration_s"]),
                      key=lambda c: -c["duration_s"])[:15]
        if slow:
            rows = "".join(f'<tr><td class="l">{e(str(c["name"]))}</td><td class="l">{e(c["summary"])}</td>'
                           f'<td>{_fmt_s(c["duration_s"])}</td><td>{"error" if c["is_error"] else ""}</td></tr>'
                           for c in slow)
            parts.append('<h2>Slowest tool calls</h2><div class="tablewrap"><table><tr><th class="l">Tool</th>'
                         f'<th class="l">Call</th><th>Duration</th><th></th></tr>{rows}</table></div>')
        subs_by_tool = {x["launched_by"]: x for x in s["subagents"] if x.get("launched_by")}
        parts.append("<h2>Conversation</h2><p class=\"note\">Blocks are truncated to "
                     f"{_TEXT_CAP} characters; the full transcripts are under claude_home/projects/.</p>"
                     + _entries_html(s, subs_by_tool, s["first_ts"]))
    contents = "".join(f'<tr><td class="l">{e(k)}</td><td>{v["files"]}</td><td>{_k(v["bytes"])}</td></tr>'
                       for k, v in data.get("contents", {}).items())
    if contents:
        parts.append('<h2>Collected ~/.claude contents</h2><div class="tablewrap"><table><tr><th class="l">Entry</th>'
                     f'<th>Files</th><th>Bytes</th></tr>{contents}</table></div>')
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Session {e(title)}</title><style>{_CSS}</style></head><body><main>{''.join(parts)}</main></body></html>")
