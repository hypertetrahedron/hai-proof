from pathlib import Path

import pytest

from hai_proof.analyses_spec import load_analysis
from hai_proof.config import ConfigError

ANALYSES = Path(__file__).resolve().parents[1] / "analyses"


def test_shipped_trial_analysis():
    a = load_analysis("non-code-changes", search_dirs=[ANALYSES])
    assert a.scope == "trial" and a.budget_usd == 1.0
    assert "did not directly" in a.prompt and "final response" in a.prompt
    assert "baseline" in a.prompt and "/analysis/transcript.jsonl" in a.prompt
    assert "/analysis/workspace" in a.prompt and "/analysis/diff_breakdown.json" in a.prompt


def test_shipped_arm_analysis():
    a = load_analysis("non-code-changes-arm", search_dirs=[ANALYSES])
    assert a.scope == "arm" and "/analysis/trials/*/report.md" in a.prompt


def test_by_path_and_inline(tmp_path):
    f = tmp_path / "x.toml"
    f.write_text('scope = "trial"\nprompt = "hello"\n')
    a = load_analysis(str(f), search_dirs=[])
    assert a.name == "x" and a.prompt.strip() == "hello"


@pytest.mark.parametrize("body,msg", [
    ('scope = "run"\nprompt = "p"\n', "scope"),
    ('prompt = "p"\nbudget_usd = 0\n', "budget"),
    ('scope = "arm"\n', "prompt"),
    ('prompt_file = "missing.md"\n', "not found"),
    ('prompt = "p"\nzzz = 1\n', "zzz"),
    ('prompt = "  "\n', "empty"),
])
def test_invalid(tmp_path, body, msg):
    (tmp_path / "a.toml").write_text(body)
    with pytest.raises(ConfigError, match=msg):
        load_analysis("a", search_dirs=[tmp_path])


def test_not_found(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_analysis("nope", search_dirs=[tmp_path])
