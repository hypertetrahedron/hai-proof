from pathlib import Path

import pytest

from hai_proof.config import ConfigError
from hai_proof.models import PLAIN
from hai_proof.treatments import load_treatment, resolve_treatment

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "treatments" / "openspec-beads"


def _mk(tmp_path, body, name="my-treat"):
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.toml").write_text(body)
    return d


def test_example_treatment():
    t = load_treatment(EXAMPLE)
    assert t.name == "openspec-beads" and not t.is_plain
    assert [r.name for r in t.requires] == ["openspec", "bd"]
    assert t.artifacts == ("openspec/", ".beads/")
    assert len(t.setup_commands) == 2 and t.user_dir is not None and t.project_dir is not None
    assert len(t.content_hash()) == 12


def test_defaults_and_name_from_dir(tmp_path):
    t = load_treatment(_mk(tmp_path, ""))
    assert t.name == "my-treat" and t.requires == () and t.env == {} and t.prompt_prefix == ""


def test_full_manifest(tmp_path):
    t = load_treatment(_mk(tmp_path, '''
prompt_prefix = "Use skills. "
[env]
FOO = "1"
[setup]
artifacts = ["docs/spec", "notes/"]
[network]
allow = ["example.com"]
[expect]
plugins = ["p"]
mcp_servers = ["m"]
skills = ["s"]
'''))
    assert t.env == {"FOO": "1"} and t.artifacts == ("docs/spec", "notes/")
    assert t.network_allow == ("example.com",) and t.expect_skills == ("s",)
    assert t.prompt_prefix == "Use skills. "


@pytest.mark.parametrize("body,msg", [
    ('foo = 1\nbar = 2\n', "bar, foo"),
    ('[[requires]]\nname = "x"\ninstall = "i"\n', "check"),
    ('name = "bad name"\n', "name"),
    ('[setup]\nartifacts = ["../x"]\n', "artifact"),
    ('[setup]\nartifacts = ["/abs"]\n', "artifact"),
    ('[setup]\nwhat = 1\n', "unknown keys in \\[setup\\]"),
    ('x = [', "invalid TOML"),
])
def test_invalid(tmp_path, body, msg):
    with pytest.raises(ConfigError, match=msg):
        load_treatment(_mk(tmp_path, body))


def test_missing_manifest(tmp_path):
    with pytest.raises(ConfigError, match="manifest"):
        load_treatment(tmp_path)


def test_resolve(tmp_path):
    assert resolve_treatment("plain", search_dirs=[]) is PLAIN
    d = _mk(tmp_path, "", name="alpha")
    assert resolve_treatment(str(d), search_dirs=[]).name == "alpha"
    assert resolve_treatment("alpha", search_dirs=[tmp_path]).name == "alpha"
    with pytest.raises(ConfigError, match="not found"):
        resolve_treatment("zzz", search_dirs=[tmp_path])
