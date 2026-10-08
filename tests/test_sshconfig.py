import subprocess
from pathlib import Path

from hai_proof import sshconfig
from hai_proof.sshconfig import effective_config, list_host_aliases


def test_default_path():
    assert sshconfig.default_config_path() == Path.home() / ".ssh" / "config"


def test_aliases_basic_and_patterns(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(
        "# comment\n"
        "Host *\n  ServerAliveInterval 30\n"
        "host alpha beta\n  HostName a\n"
        "HOST=gamma\n"
        "Host delta *.example.com !eps q?x\n"
        "Host alpha\n"
        "Host !neg\n"
    )
    assert list_host_aliases(cfg) == ["alpha", "beta", "gamma", "delta"]


def test_include_relative_glob_and_cycle(tmp_path):
    (tmp_path / "conf.d").mkdir()
    (tmp_path / "conf.d" / "a.conf").write_text("Host inc-a\n")
    (tmp_path / "conf.d" / "b.conf").write_text("Host inc-b\nInclude ../config\n")
    cfg = tmp_path / "config"
    cfg.write_text("Host first\nInclude conf.d/*.conf\nHost last\nInclude missing/*\n")
    assert list_host_aliases(cfg) == ["first", "inc-a", "inc-b", "last"]


def test_missing_config(tmp_path):
    assert list_host_aliases(tmp_path / "nope") == []


def test_effective_config_parsing(monkeypatch):
    seen = {}

    def fake(argv, **kw):
        seen["argv"] = argv
        out = b"host box\nUser les\nhostname 10.0.0.5\nport 22\nuser other\nflag\n"
        return subprocess.CompletedProcess(argv, 0, out, b"")

    monkeypatch.setattr(subprocess, "run", fake)
    cfg = effective_config("box")
    assert seen["argv"] == ["ssh", "-G", "box"]
    assert cfg == {"host": "box", "user": "les", "hostname": "10.0.0.5", "port": "22"}


def test_effective_config_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 255, b"x y", b""))
    assert effective_config("box") == {}

    def boom(*a, **k):
        raise FileNotFoundError("ssh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert effective_config("box") == {}
