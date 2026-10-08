import pytest

from hai_proof.diffbreakdown import (
    CATEGORIES,
    categorize,
    diff_breakdown,
    parse_numstat,
)


def test_parse_numstat_basic_binary_rename():
    text = (
        "10\t2\tsrc/a.py\n"
        "-\t-\timg/logo.png\n"
        "1\t1\told.py => new.py\n"
        "3\t0\tsrc/{old => new}/mod.py\n"
        "4\t4\tsrc/{ => sub}/mod.py\n"
        "garbage line\n"
    )
    assert parse_numstat(text) == [
        ("src/a.py", 10, 2),
        ("img/logo.png", 0, 0),
        ("new.py", 1, 1),
        ("src/new/mod.py", 3, 0),
        ("src/sub/mod.py", 4, 4),
    ]


@pytest.mark.parametrize(
    "path,cat",
    [
        ("src/pkg/mod.py", "product_code"),
        ("main.go", "product_code"),
        ("tests/test_x.py", "tests"),
        ("test/helper.py", "tests"),
        ("pkg/tests/data.json", "tests"),
        ("pkg/sub/test_thing.py", "tests"),
        ("test_root.py", "tests"),
        ("pkg/thing_test.py", "tests"),
        ("conftest.py", "tests"),
        ("pkg/conftest.py", "tests"),
        ("README.md", "docs"),
        ("sub/dir/NOTES.rst", "docs"),
        ("docs/guide/index.html", "docs"),
        ("notes.txt", "docs"),
        ("LICENSE", "docs"),
        ("LICENSE-MIT", "docs"),
        ("ROADMAP.md", "planning"),
        ("sub/ROADMAP.md", "planning"),
        ("TODO", "planning"),
        ("TODO.md", "planning"),
        ("PLAN-v2.md", "planning"),
        ("openspec/changes/x/proposal.md", "planning"),
        (".beads/issues.jsonl", "planning"),
        ("CLAUDE.md", "config_tooling"),
        ("AGENTS.md", "config_tooling"),
        ("sub/CLAUDE.md", "config_tooling"),
        (".claude/settings.json", "config_tooling"),
        (".claude/commands/x.md", "config_tooling"),
        (".mcp.json", "config_tooling"),
        ("pyproject.toml", "config_tooling"),
        ("sub/pyproject.toml", "config_tooling"),
        ("tox.ini", "config_tooling"),
        (".github/workflows/ci.yml", "config_tooling"),
        ("Makefile", "config_tooling"),
        (".gitignore", "config_tooling"),
        ("data/blob.bin", "other"),
        ("./src/a.py", "product_code"),
        ("src\\win\\a.py", "product_code"),
    ],
)
def test_default_categories(path, cat):
    assert categorize(path) == cat


def test_artifacts_take_precedence():
    arts = ("openspec/", ".beads/")
    assert categorize("openspec/specs/a.md", artifacts=arts) == "treatment_artifact"
    assert categorize(".beads/db.sqlite", artifacts=arts) == "treatment_artifact"
    assert categorize("src/openspec/a.py", artifacts=arts) == "product_code"
    assert categorize("openspec/a.md") == "planning"
    # artifacts beat overrides
    assert categorize("openspec/a.md", artifacts=arts, overrides={"docs": ["openspec/**"]}) == "treatment_artifact"


def test_overrides_beat_defaults_and_order():
    ov = {"docs": ["examples/**"], "tests": ["examples/**", "scripts/*.py"]}
    assert categorize("examples/demo.py", overrides=ov) == "docs"  # first listed wins
    assert categorize("scripts/run.py", overrides=ov) == "tests"
    assert categorize("scripts/sub/run.py", overrides=ov) == "product_code"  # anchored, single level
    assert categorize("tests/test_a.py", overrides={"product_code": ["tests/**"]}) == "product_code"
    assert categorize("src/a.py", overrides=ov) == "product_code"


def test_root_vs_nested_globs():
    assert categorize("setup.py") == "config_tooling"
    assert categorize("pkg/setup.py") == "config_tooling"
    assert categorize("tests/sub/deep/x.py") == "tests"
    assert categorize("src/tests_helper.py") == "product_code"
    assert categorize("src/docs_gen.py") == "product_code"


def test_diff_breakdown():
    text = (
        "10\t2\tsrc/a.py\n"
        "5\t5\tsrc/b.py\n"
        "20\t0\ttests/test_a.py\n"
        "3\t1\tREADME.md\n"
        "7\t0\tROADMAP.md\n"
        "1\t1\tpyproject.toml\n"
        "30\t0\topenspec/changes/x/spec.md\n"
        "-\t-\tdata/x.bin\n"
    )
    bd = diff_breakdown(text, artifacts=("openspec/",))
    assert set(bd) == set(CATEGORIES)
    assert bd["product_code"] == {"files": 2, "lines": 22}
    assert bd["tests"] == {"files": 1, "lines": 20}
    assert bd["docs"] == {"files": 1, "lines": 4}
    assert bd["planning"] == {"files": 1, "lines": 7}
    assert bd["config_tooling"] == {"files": 1, "lines": 2}
    assert bd["treatment_artifact"] == {"files": 1, "lines": 30}
    assert bd["other"] == {"files": 1, "lines": 0}


def test_diff_breakdown_empty_and_overrides():
    bd = diff_breakdown("")
    assert all(v == {"files": 0, "lines": 0} for v in bd.values())
    assert set(bd) == set(CATEGORIES)
    bd = diff_breakdown("2\t3\tsrc/gen/x.py\n", overrides={"other": ["src/gen/**"]})
    assert bd["other"] == {"files": 1, "lines": 5}
    assert bd["product_code"]["files"] == 0
