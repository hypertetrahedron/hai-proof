from pathlib import Path

import pytest

from hai_proof.models import PLAIN, TreatmentSpec
from hai_proof.streamjson import (
    dependency_usage,
    init_snapshot,
    is_auth_failure,
    is_rate_limited,
    isolation_problems,
    iter_tool_results,
    iter_tool_uses,
    leakage_flags,
    metrics_from_transcript,
    parse_transcript,
)

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return parse_transcript((FIX / name).read_text(encoding="utf-8"))


def treat(**kw):
    return TreatmentSpec(name="t", path=Path("."), **kw)


def test_parse_skips_garbage():
    t = load("success.jsonl")
    assert t.init and t.init["subtype"] == "init"
    assert t.result and t.result["subtype"] == "success"
    assert all(isinstance(e, dict) for e in t.events)
    assert parse_transcript("").events == []
    assert parse_transcript("junk\n[1,2]\n{bad").events == []


def test_tool_iteration():
    t = load("success.jsonl")
    uses = list(iter_tool_uses(t))
    assert [u["name"] for u in uses] == ["Skill", "Bash", "Task", "Bash", "WebFetch", "Bash", "Skill"]
    results = list(iter_tool_results(t))
    assert len(results) == 3
    assert "src/a.py:3: def parse()\nsrc/b.py:9: parse(x)" in results


def test_metrics_success():
    t = load("success.jsonl")
    m = metrics_from_transcript(t, wall_s=125.0, exit_code=0)
    assert m.cost_usd == pytest.approx(0.4321)
    assert m.api_s == pytest.approx(90.5)
    assert m.turns == 6
    # summed over modelUsage (both models), not top-level usage
    assert (m.tokens_input, m.tokens_output) == (119, 170)
    assert (m.tokens_cache_read, m.tokens_cache_write) == (9000, 3200)
    assert m.tokens_total == 119 + 170 + 9000 + 3200
    assert m.tool_calls == 7
    assert m.subagent_calls == 1
    assert m.skills_fired == ["openspec-flow:propose"]
    assert m.first_request_input_tokens == 10 + 500 + 3000
    assert m.terminal_reason == "completed"
    assert m.subtype == "success" and m.is_error is False
    assert m.wall_s == 125.0 and m.exit_code == 0 and m.timed_out is False


def test_metrics_usage_fallback_and_snake_case():
    t = load("max_turns.jsonl")
    m = metrics_from_transcript(t, wall_s=10.0)
    assert m.is_error and m.subtype == "error_max_turns" and m.terminal_reason == "max_turns"
    assert m.tokens_input == 50 and m.tokens_cache_read == 90000
    assert m.turns == 61 and m.cost_usd == 1.5
    snake = parse_transcript(
        '{"type":"result","subtype":"success","is_error":false,"num_turns":1,'
        '"modelUsage":{"m":{"input_tokens":1,"output_tokens":2,'
        '"cache_read_input_tokens":3,"cache_creation_input_tokens":4}}}'
    )
    m2 = metrics_from_transcript(snake, wall_s=1)
    assert (m2.tokens_input, m2.tokens_output, m2.tokens_cache_read, m2.tokens_cache_write) == (1, 2, 3, 4)


def test_metrics_no_result():
    t = load("no_result.jsonl")
    assert t.result is None
    m = metrics_from_transcript(t, wall_s=1800, timed_out=True)
    assert m.is_error and m.subtype == "no_result" and m.timed_out
    assert m.tool_calls == 1
    assert m.first_request_input_tokens == 1002


def test_init_snapshot():
    t = load("success.jsonl")
    snap = init_snapshot(t)
    assert "session_id" not in snap and "uuid" not in snap
    assert snap["model"] == "claude-sonnet-5-5"
    assert t.init["session_id"] == "s1"  # original untouched
    assert init_snapshot(parse_transcript("")) == {}


def test_isolation_ok_for_matching_treatment():
    snap = init_snapshot(load("success.jsonl"))
    tr = treat(
        expect_plugins=("openspec-flow",),
        expect_mcp_servers=("beads",),
        expect_skills=("propose", "/openspec-flow:propose", "openspec-flow:propose", "review"),
    )
    assert isolation_problems(snap, tr) == []


def test_isolation_problems_treatment():
    snap = init_snapshot(load("success.jsonl"))
    snap["mcp_servers"] = [{"name": "beads", "status": "failed"}]
    snap["plugin_errors"] = ["boom"]
    tr = treat(expect_plugins=("nope",), expect_skills=("ghost",), expect_mcp_servers=("beads", "other"))
    probs = isolation_problems(snap, tr)
    assert len(probs) == 5
    assert any("'nope'" in p for p in probs)
    assert any("failed" in p for p in probs)
    assert any("'other'" in p for p in probs)
    assert any("'ghost'" in p for p in probs)
    assert any("plugin_errors" in p for p in probs)
    assert any("not loaded" in p for p in probs)


def test_isolation_plain():
    assert isolation_problems({}, PLAIN) == ["no system/init event"]
    assert isolation_problems(init_snapshot(load("max_turns.jsonl")), PLAIN) == []
    probs = isolation_problems(init_snapshot(load("success.jsonl")), PLAIN)
    assert len(probs) == 2
    snap = {"plugins": ["foo"], "mcp_servers": [], "mcp_server_errors": [{"name": "x"}]}
    assert len(isolation_problems(snap, PLAIN)) == 2


def test_dependency_usage():
    t = load("success.jsonl")
    d = dependency_usage(t, ["openspec", "beads", "pytest", "grep", "open"])
    assert d == {"openspec": True, "beads": False, "pytest": True, "grep": True, "open": False}
    t2 = parse_transcript(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"1","name":"Read",'
        '"input":{"command":"bd ready"}},{"type":"tool_use","id":"2","name":"Bash",'
        '"input":{"command":"echo x;bd ready|cat && (bd list)"}}]}}'
    )
    assert dependency_usage(t2, ["bd"]) == {"bd": True}
    t3 = parse_transcript(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"1","name":"Bash",'
        '"input":{"command":"cat bdfile.txt; ls abd"}}]}}'
    )
    assert dependency_usage(t3, ["bd"]) == {"bd": False}


def test_leakage_flags():
    t = load("success.jsonl")
    flags = leakage_flags(t, ["GitHub.com/org/proj", "", "parse(x)", "absent-needle"])
    assert "tool_use WebFetch input contains 'GitHub.com/org/proj'" in flags
    assert any(f.startswith("tool_result") and "parse(x)" in f for f in flags)
    assert len(flags) == 2
    assert leakage_flags(t, ["", ""]) == []


def test_rate_limited():
    assert is_rate_limited(load("rate_limited.jsonl"))
    assert not is_rate_limited(load("max_turns.jsonl"))
    assert not is_rate_limited(load("success.jsonl"))
    assert is_rate_limited(load("no_result.jsonl"), stderr="Error: 529 Overloaded")
    assert not is_rate_limited(load("no_result.jsonl"), stderr="segfault")
    t = parse_transcript('{"type":"result","is_error":false,"result":"discussed 429 handling"}')
    assert not is_rate_limited(t)


def test_real_auth_failure_transcript():
    """Captured from Claude Code 2.1.292 with an invalid API key (2026-10-06)."""
    from hai_proof.models import PLAIN

    t = parse_transcript((FIX / "auth_failed_real.jsonl").read_text(encoding="utf-8"))
    assert is_auth_failure(t)
    m = metrics_from_transcript(t, wall_s=187.6)
    assert m.is_error and m.terminal_reason == "api_error" and m.cost_usd == 0
    assert not is_rate_limited(t)
    # built-in plugins ship with vanilla Claude Code and are not an isolation problem
    assert isolation_problems(init_snapshot(t), PLAIN) == []


def test_plain_arm_still_flags_installed_plugin():
    from hai_proof.models import PLAIN

    snap = {"plugins": [{"name": "x", "path": "builtin", "source": "x@builtin"},
                        {"name": "team-kit", "path": "/home/agent/.claude/plugins/team-kit", "source": "team-kit@corp"}],
            "mcp_servers": []}
    assert isolation_problems(snap, PLAIN) == ["plain arm has plugin 'team-kit'"]


def _tool_transcript(*uses, result_text=""):
    import json as _json

    events = [{"type": "assistant", "parent_tool_use_id": None,
               "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": n, "input": inp}
                                       for i, (n, inp) in enumerate(uses)]}}]
    if result_text:
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t0", "content": result_text}]}})
    return parse_transcript("\n".join(_json.dumps(e) for e in events))


def test_network_leakage_ignores_repo_url_in_local_files():
    """Regression (2026-10-07): rich's README contains its own URL; grepping the repo is not leakage."""
    from hai_proof.streamjson import network_leakage_flags

    url = "github.com/textualize/rich"
    t = _tool_transcript(("Bash", {"command": "grep -rn 'github.com/Textualize/rich' ."}),
                         result_text="README.md: https://github.com/Textualize/rich")
    assert network_leakage_flags(t, [url]) == []
    t = _tool_transcript(("WebFetch", {"url": "https://github.com/Textualize/rich/pull/1"}))
    assert network_leakage_flags(t, [url]) == [f"WebFetch request targets {url!r}"]
    t = _tool_transcript(("Bash", {"command": "git clone https://github.com/Textualize/rich /tmp/r"}))
    assert len(network_leakage_flags(t, [url])) == 1
