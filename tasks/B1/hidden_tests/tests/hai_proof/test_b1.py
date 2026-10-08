import click
import pytest
from click.testing import CliRunner


@pytest.mark.parametrize(
    ("kwargs", "value", "expected"),
    [
        ({"min": 0, "min_open": True}, "0", 1),
        ({"min": 0, "min_open": True}, "-7", 1),
        ({"max": 10, "max_open": True}, "10", 9),
        ({"max": 10, "max_open": True}, "99", 9),
        ({"min": 0, "max": 10}, "-3", 0),
        ({"min": 0, "max": 10}, "42", 10),
        ({"min": 0, "max": 10, "min_open": True, "max_open": True}, "5", 5),
    ],
)
def test_int_range_clamp(kwargs, value, expected):
    t = click.IntRange(clamp=True, **kwargs)
    assert t.convert(value, None, None) == expected


def test_open_clamp_in_command():
    @click.command()
    @click.option(
        "--level",
        type=click.IntRange(0, 10, min_open=True, max_open=True, clamp=True),
    )
    def cli(level):
        click.echo(f"level={level}")

    runner = CliRunner()
    assert runner.invoke(cli, ["--level=0"]).output.strip() == "level=1"
    assert runner.invoke(cli, ["--level=99"]).output.strip() == "level=9"
