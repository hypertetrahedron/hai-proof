import pytest

from gunicorn import config
from gunicorn.reloader import Reloader


def test_reload_extra_files_keeps_patterns_unexpanded(tmp_path):
    c = config.Config()

    plain = tmp_path / "plain.txt"
    plain.write_text("plain")
    views = tmp_path / "views"
    views.mkdir()
    (views / "a.json").write_text("{}")

    pattern = str(views / "*.json")
    c.set("reload_extra_files", [str(plain), pattern])

    assert c.reload_extra_files == [str(plain), pattern]


def test_reload_extra_files_pattern_without_match_warns(tmp_path):
    c = config.Config()
    pattern = str(tmp_path / "*.nothing")

    with pytest.warns(RuntimeWarning):
        c.set("reload_extra_files", [pattern])

    assert c.reload_extra_files == [pattern]


def test_reload_extra_files_plain_path_must_exist(tmp_path):
    c = config.Config()

    pytest.raises(
        ValueError, c.set, "reload_extra_files", [str(tmp_path / "missing.txt")]
    )


def test_extra_patterns_expand_on_every_call(tmp_path):
    """Files created after startup are picked up without a restart."""
    views = tmp_path / "views"
    views.mkdir()
    first = views / "a.json"
    first.write_text("{}")

    r = Reloader(extra_files=[str(views / "*.json")])

    assert str(first) in r.get_files()

    second = views / "b.json"
    second.write_text("{}")

    assert str(second) in r.get_files()


def test_recursive_pattern_matches_nested_files(tmp_path):
    nested = tmp_path / "ui" / "deep" / "deeper"
    nested.mkdir(parents=True)
    target = nested / "config.json"
    target.write_text("{}")

    r = Reloader(extra_files=[str(tmp_path / "**" / "config.json")])

    assert str(target) in r.get_files()
