"""The `ask` question key through the Python API, without a TTY.

Any prompt here would fail (no interactive session), so a question that is prompted when it should be
skipped shows up as an error.
"""

from __future__ import annotations

import pytest
import yaml

from copier import run_copy, run_update
from copier._user_data import load_answersfile_data

from .helpers import build_file_tree, git_save


def _template(src, questions: dict) -> None:
    build_file_tree(
        {
            (src / "copier.yml"): yaml.safe_dump(questions),
            (src / "{{ _copier_conf.answers_file }}.jinja"): (
                "{{ _copier_answers|to_nice_yaml }}"
            ),
            (src / "context.yml.jinja"): "extra: {{ extra }}\n",
        }
    )


def test_unasked_question_records_default_without_defaults_flag(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    _template(
        src,
        {
            "name": {"type": "str"},
            "extra": {"type": "str", "default": "d", "ask": False},
        },
    )
    run_copy(str(src), dst, data={"name": "n"})
    answers = load_answersfile_data(dst)
    assert answers["extra"] == "d"
    assert yaml.safe_load((dst / "context.yml").read_text()) == {"extra": "d"}


def test_templated_ask(tmp_path_factory: pytest.TempPathFactory) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    _template(
        src,
        {
            "advanced": {"type": "bool", "default": False},
            "extra": {
                "type": "str",
                "default": "d",
                "ask": "{{ advanced }}",
            },
        },
    )
    run_copy(str(src), dst, data={"advanced": False})
    assert load_answersfile_data(dst)["extra"] == "d"


def test_unasked_question_without_default_is_not_recorded(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    _template(
        src,
        {
            "name": {"type": "str"},
            "extra": {"type": "str", "ask": False},
        },
    )
    run_copy(str(src), dst, data={"name": "n"})
    assert "extra" not in load_answersfile_data(dst)


def test_when_false_beats_ask_flag(tmp_path_factory: pytest.TempPathFactory) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    _template(
        src,
        {
            "name": {"type": "str"},
            "extra": {"type": "str", "default": "d", "when": False, "ask": False},
        },
    )
    run_copy(str(src), dst, data={"name": "n"}, ask=["extra"])
    assert "extra" not in load_answersfile_data(dst)


def test_update_keeps_previous_answer_of_unasked_question(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    src, dst = map(tmp_path_factory.mktemp, ("src", "dst"))
    _template(
        src,
        {
            "name": {"type": "str"},
            "extra": {"type": "str", "default": "d", "ask": False},
        },
    )
    git_save(src, tag="v1")
    run_copy(str(src), dst, data={"name": "n", "extra": "prev"})
    assert load_answersfile_data(dst)["extra"] == "prev"
    git_save(dst)
    # Interactive update, nothing passed: `name` was answered and is skipped, `extra` is not asked.
    run_update(dst, skip_answered=True, overwrite=True)
    assert load_answersfile_data(dst)["extra"] == "prev"
    git_save(dst, allow_empty=True)
    # Without --skip-answered a normal question would be prompted again, but `extra` still is not,
    # and keeps its answer rather than going back to the default.
    run_update(dst, data={"name": "n"}, overwrite=True)
    assert load_answersfile_data(dst)["extra"] == "prev"
