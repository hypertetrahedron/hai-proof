import pathlib

import click
import pytest
from click.testing import CliRunner


def make_cli(**path_kwargs):
    @click.command()
    @click.option("--config", type=click.Path(**path_kwargs))
    def cli(config):
        click.echo(f"config={config}")

    return cli


def test_default_unchanged():
    result = CliRunner().invoke(make_cli(), ["--config", "anything.bin"])
    assert result.exit_code == 0
    assert result.output.strip() == "config=anything.bin"


def test_tuple_accepts_and_rejects():
    cli = make_cli(suffixes=(".yml", ".yaml"))
    runner = CliRunner()
    for name in ("app.yml", "app.yaml"):
        result = runner.invoke(cli, ["--config", name])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"config={name}"
    result = runner.invoke(cli, ["--config", "app.json"])
    assert result.exit_code == 2
    assert ".yml" in result.output and ".yaml" in result.output


def test_single_string_and_list():
    runner = CliRunner()
    cli = make_cli(suffixes=".toml")
    assert runner.invoke(cli, ["--config", "a.toml"]).exit_code == 0
    assert runner.invoke(cli, ["--config", "a.tom"]).exit_code == 2
    assert runner.invoke(cli, ["--config", "toml"]).exit_code == 2
    cli = make_cli(suffixes=[".a", ".b"])
    assert runner.invoke(cli, ["--config", "x.b"]).exit_code == 0
    assert runner.invoke(cli, ["--config", "x.c"]).exit_code == 2


def test_case_insensitive():
    result = CliRunner().invoke(make_cli(suffixes=".yml"), ["--config", "APP.YML"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(make_cli(suffixes=".YML"), ["--config", "app.yml"])
    assert result.exit_code == 0, result.output


def test_checked_for_existing_files(tmp_path):
    good = tmp_path / "a.txt"
    bad = tmp_path / "a.csv"
    good.write_text("x")
    bad.write_text("x")
    cli = make_cli(exists=True, suffixes=".txt")
    runner = CliRunner()
    assert runner.invoke(cli, ["--config", str(good)]).exit_code == 0
    assert runner.invoke(cli, ["--config", str(bad)]).exit_code == 2


def test_missing_file_still_checked(tmp_path):
    cli = make_cli(suffixes=".txt")
    runner = CliRunner()
    assert runner.invoke(cli, ["--config", str(tmp_path / "nope.md")]).exit_code == 2
    assert runner.invoke(cli, ["--config", str(tmp_path / "nope.txt")]).exit_code == 0


def test_dash_skipped_with_allow_dash():
    result = CliRunner().invoke(
        make_cli(suffixes=".txt", allow_dash=True), ["--config", "-"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "config=-"


def test_path_type_and_direct_convert():
    t = click.Path(suffixes=".md", path_type=pathlib.Path)
    assert t.convert("README.md", None, None) == pathlib.Path("README.md")
    with pytest.raises(click.BadParameter):
        t.convert("README.txt", None, None)
