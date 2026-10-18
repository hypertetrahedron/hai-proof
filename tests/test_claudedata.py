import json

from hai_proof import claudedata
from hai_proof.claudedata import classify_call, patch_stats, phase_stats, write_trial_data


def bash(cmd):
    return classify_call("Bash", {"command": cmd})


def test_classify_tools():
    assert classify_call("Edit", {"file_path": "a.py"}) == ("edit", False, False)
    assert classify_call("Read", {"file_path": "a.py"}) == ("explore", False, False)
    assert classify_call("Agent", {"prompt": "x"}) == ("delegate", False, False)
    assert classify_call("TodoWrite", {}) == ("other", False, False)


def test_classify_bash():
    assert bash("cat src/x.py | head") == ("explore", False, False)
    assert bash("python -m pytest -q tests") == ("test", True, False)
    assert bash("for i in $(seq 5); do timeout 9 python -m pytest t.py; done") == ("test", True, False)
    assert bash("python -m tornado.test.runtests tornado.test.gen_test") == ("test", True, False)
    assert bash("python -m gevent.tests") == ("test", True, False)
    assert bash("python -m json.tool x.json") == ("explore", False, False)
    assert bash("python /tmp/repro.py 100") == ("run", False, True)
    assert bash("sed -i 's/a/b/' src/x.py && python -m pytest -q") == ("edit", True, False)
    assert bash("cat > /tmp/t.py <<'EOF'\nprint(1)\nEOF") == ("edit", False, False)
    # a heredoc that writes a file, then runs a script: an edit that also runs code
    cmd = "python - <<'EOF'\nopen('x.py', 'w').write(s)\nEOF\npython /tmp/stress.py 150"
    assert bash(cmd) == ("edit", False, True)
    # the heredoc body itself is not "running code"
    assert bash("python - <<'EOF'\nprint(open('x.py').read())\nEOF") == ("explore", False, False)


def _call(start, phase, tests=False, code=False):
    return {"start": start, "phase": phase, "runs_tests": tests, "runs_code": code, "duration_s": 1}


def test_phase_stats():
    s = {"first_ts": 0.0, "last_ts": 100.0, "tool_calls": [
        _call(5, "explore"), _call(10, "explore"), _call(20, "edit"), _call(30, "test", tests=True),
        _call(40, "edit", code=True), _call(90, "test", tests=True),
    ]}
    st = phase_stats(s)
    assert st["first_edit_s"] == 20.0
    assert st["explore_before_first_edit"] == 2
    assert st["edit_calls"] == 2 and st["test_runs"] == 2 and st["code_runs"] == 1
    assert st["edit_test_cycles"] == 2
    assert st["tested_after_last_edit"] is True
    # explore 5..20, edit 20..30, test 30..40 + 90..100, the edit at 40 ran code until 90
    assert st["phase_time_s"]["explore"] == 15.0
    assert st["phase_time_s"]["edit"] == 10.0
    assert st["phase_time_s"]["test"] == 20.0
    assert st["phase_time_s"]["run"] == 50.0


def test_phase_stats_untested_final_edit():
    s = {"first_ts": 0.0, "last_ts": 10.0, "tool_calls": [_call(1, "test", tests=True), _call(2, "edit")]}
    assert phase_stats(s)["tested_after_last_edit"] is False


PATCH = """diff --git a/pkg/a.py b/pkg/a.py
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -1,2 +1,3 @@
-old
+new
+more
diff --git a/tests/t.py b/tests/t.py
new file mode 100644
--- /dev/null
+++ b/tests/t.py
@@ -0,0 +1 @@
+x = 1
"""


def test_patch_stats():
    assert patch_stats(PATCH) == {"diff_files": 2, "diff_added": 3, "diff_removed": 1}
    assert patch_stats("") == {"diff_files": 0, "diff_added": 0, "diff_removed": 0}


def test_write_trial_data_uses_git_diff(tmp_path):
    # An agent that edits only through Bash: no Edit/Write results, but the diff is real.
    proj = tmp_path / "claude_home" / "projects" / "-work"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(
        '{"type":"assistant","requestId":"r1","timestamp":"2026-10-11T00:00:00Z","message":{"usage":'
        '{"input_tokens":5,"output_tokens":3},"content":[{"type":"tool_use","id":"t1","name":"Bash",'
        '"input":{"command":"sed -i s/a/b/ x.py"}}]}}\n', encoding="utf-8")
    (tmp_path / "session.patch").write_text(PATCH, encoding="utf-8")
    st = write_trial_data(tmp_path, "t")
    assert (st["lines_added"], st["diff_added"], st["diff_removed"], st["diff_files"]) == (0, 3, 1, 2)
    html = (tmp_path / "session.html").read_text(encoding="utf-8")
    assert "<b>3/1</b><span>Lines +/− (git diff)</span>" in html
    assert "<b>0/0</b><span>Lines +/− via Edit/Write</span>" in html


def test_context_chart_has_labeled_y_axis():
    from hai_proof.claudedata import _context_svg, _nice_step

    assert [_nice_step(v) for v in (40_128, 1_000, 230_000, 5_253_612)] == [10_000, 200, 50_000, 2_000_000]

    def r(rid, ts, read, inp, write):
        return {"id": rid, "ts": ts, "usage": {"cache_read": read, "input": inp, "cache_write": write,
                                               "output": 10, "context": read + inp + write}}

    s = {"requests": [r("a", 0, 0, 2_000, 10_000), r("b", 60, 12_000, 1_000, 18_000), r("c", 120, 1_000, 128, 39_000)],
         "tool_calls": [{"request": "a", "is_error": False}, {"request": "b", "is_error": True}],
         "prompts": [{"ts": 0, "kind": "human"}, {"ts": 90, "kind": "human"}], "compactions": [{"ts": 100}],
         "subagents": [{"agent_id": "x1", "first_ts": 30, "last_ts": 80, "subagent_type": "Explore",
                        "description": "find the parser"}]}
    svg = _context_svg(s)
    assert "Context per request (tokens)" in svg and "Elapsed time (minutes)" in svg
    for tick in (">0<", ">10.0k<", ">20.0k<", ">30.0k<", ">40.0k<", ">50.0k<"):
        assert tick in svg
    # claude-lens lanes: three stacked context layers, turn ruler, tool lane with an error, a subagent bar
    assert all(f'class="tl-l{i}"' in svg for i in (1, 2, 3)) and 'class="tl-ctx"' in svg
    assert "Turn 1 · +0.0m" in svg and "Turn 2 · +1.5m" in svg
    assert "1 tool call(s), 1 error(s)" in svg and 'class="tl-err"' in svg
    assert "find the parser · Explore" in svg and "compaction" in svg
    assert svg.count('class="tl-miss"') == 1  # request c reads back 1k of a 30k prefix
    assert "context 40,128 = cache read 1,000 + uncached 128 + cache write 39,000" in svg


def test_pack_rows_separates_overlapping_spans():
    from hai_proof.claudedata import _pack_rows

    assert _pack_rows([(0, 10), (5, 15), (11, 20), (16, 30)]) == [0, 1, 0, 1]


def test_cost_state_fills_metrics_without_result(tmp_path):
    from hai_proof.models import AgentMetrics

    proj = tmp_path / "projects" / "-work"
    proj.mkdir(parents=True)
    early = {"type": "cost-state", "totalCostUSD": 1.0, "modelUsage": {}}
    final = {"type": "cost-state", "totalCostUSD": 15.5, "totalAPIDuration": 2000,
             "modelUsage": {"claude-opus-5-5": {"inputTokens": 10, "outputTokens": 200, "cacheReadInputTokens": 3000,
                                                "cacheCreationInputTokens": 40, "costUSD": 15.0},
                            "claude-haiku-5-5": {"inputTokens": 1, "outputTokens": 2, "costUSD": 0.5}}}
    (proj / "s1.jsonl").write_text(json.dumps({"type": "user"}) + "\n" + json.dumps(early) + "\n" + json.dumps(final) + "\n")
    cs = claudedata.cost_state(tmp_path)
    assert cs == {"cost_usd": 15.5, "input": 11, "output": 202, "cache_read": 3000, "cache_write": 40, "api_s": 2.0}

    m = AgentMetrics(wall_s=3600, timed_out=True, is_error=True, subtype="no_result")
    assert claudedata.apply_cost_state(m, cs)
    assert (m.cost_usd, m.tokens_output, m.tokens_total, m.cost_source) == (15.5, 202, 3253, "session")
    assert not claudedata.apply_cost_state(m, cs)  # already filled
    done = AgentMetrics(cost_usd=2.0, subtype="success")
    assert not claudedata.apply_cost_state(done, cs) and done.cost_usd == 2.0
    none = AgentMetrics(subtype="no_result")
    assert claudedata.apply_cost_state(none, claudedata.cost_state(tmp_path / "missing")) and none.cost_source == "none"
