import pytest

from hai_proof.config import (
    MODES, ConfigError, ProjectConfig, auth_env, load_project_config, resolve_host,
    select_tasks_for_mode,
)
from hai_proof.models import TaskSpec


def test_defaults_without_file(tmp_path):
    cfg = load_project_config(tmp_path)
    assert cfg.model is None and cfg.default_host == "local" and cfg.probe_runs == 5
    assert cfg.limits.cpus == 4 and cfg.egress == "proxy" and cfg.analyses == []


def test_full_file(tmp_path):
    (tmp_path / "hai-proof.toml").write_text(
        'default_host = "box"\nmodel = "claude-sonnet-5-5"\neffort = "high"\nanalyses = ["x"]\n'
        'results_dir = "out"\negress = "open"\n[limits]\ncpus = 2\nmemory = "4g"\n[probe]\nruns = 0\n'
    )
    cfg = load_project_config(tmp_path)
    assert (cfg.default_host, cfg.model, cfg.effort, cfg.results_dir) == ("box", "claude-sonnet-5-5", "high", "out")
    assert cfg.limits.cpus == 2 and cfg.limits.memory == "4g" and cfg.probe_runs == 0
    assert cfg.egress == "open" and cfg.analyses == ["x"]
    assert cfg.path("results_dir") == tmp_path / "out"


@pytest.mark.parametrize("body,msg", [
    ("bogus = 1\n", "bogus"),
    ('egress = "wide"\n', "egress"),
    ("[probe]\nruns = -1\n", "probe.runs"),
    ("model = [", "invalid TOML"),
])
def test_bad_config(tmp_path, body, msg):
    (tmp_path / "hai-proof.toml").write_text(body)
    with pytest.raises(ConfigError, match=msg):
        load_project_config(tmp_path)


def test_resolve_host_precedence(monkeypatch):
    cfg = ProjectConfig(default_host="cfg")
    monkeypatch.delenv("HAI_PROOF_HOST", raising=False)
    assert resolve_host(None, cfg) == "cfg"
    monkeypatch.setenv("HAI_PROOF_HOST", "env")
    assert resolve_host(None, cfg) == "env"
    assert resolve_host("cli", cfg) == "cli"
    monkeypatch.delenv("HAI_PROOF_HOST")
    assert resolve_host(None, ProjectConfig(default_host="")) == "local"


def _t(i, level):
    return TaskSpec(id=i, kind="bug", level=level, path=None, prompt="p")  # type: ignore[arg-type]


def test_modes():
    assert MODES["quick"] == dict(reps=3, max_level=2)
    tasks = [_t("a", 1), _t("b", 2), _t("c", 3)]
    assert [t.id for t in select_tasks_for_mode(tasks, "quick")] == ["a", "b"]
    assert len(select_tasks_for_mode(tasks, "lightning")) == 3
    with pytest.raises(ConfigError):
        select_tasks_for_mode(tasks, "nope")


def test_auth_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY.*CLAUDE_CODE_OAUTH_TOKEN"):
        auth_env()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    assert auth_env() == {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert auth_env() == {"ANTHROPIC_API_KEY": "key"}


def test_auth_env_rejects_swapped_credentials(monkeypatch):
    import pytest as _pytest

    from hai_proof.config import ConfigError, auth_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-xxxx")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with _pytest.raises(ConfigError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        auth_env()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-api03-xxxx")
    with _pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        auth_env()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-xxxx")
    assert auth_env() == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-xxxx"}


def test_auth_env_reads_dotenv(tmp_path, monkeypatch):
    from hai_proof.config import auth_env, read_dotenv

    for v in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    (tmp_path / ".env").write_text(
        "# comment\nANTHROPIC_API_KEY=\nexport CLAUDE_CODE_OAUTH_TOKEN=\"sk-ant-oat01-abc\"\nOTHER=x # note\n",
        encoding="utf-8")
    assert read_dotenv(tmp_path / ".env")["OTHER"] == "x"
    # empty ANTHROPIC_API_KEY (as in .env.example) falls through to the token
    assert auth_env(tmp_path) == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-abc"}
    # the process environment wins over the file
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-env")
    assert auth_env(tmp_path) == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-env"}


def test_auth_env_missing_names_dotenv(tmp_path, monkeypatch):
    import pytest as _pytest

    from hai_proof.config import ConfigError, auth_env

    for v in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    with _pytest.raises(ConfigError, match=r"\.env"):
        auth_env(tmp_path)
