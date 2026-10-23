from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

import subliminal.cli.commands.download_best as dl
from subliminal.cli.cli import subliminal as subliminal_cli

if TYPE_CHECKING:
    from tests.conftest import CliRunner

pytestmark = [
    pytest.mark.core,
    pytest.mark.usefixtures('provider_manager'),
    pytest.mark.usefixtures('disabled_providers'),
    pytest.mark.usefixtures('refiner_manager'),
]


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    captured: list[tuple[str, str | None]] = []
    orig_scan_path = dl.scan_path

    def spy_scan_path(filepath: str, *, name: str | None = None) -> object:
        captured.append((os.fspath(filepath), name))
        return orig_scan_path(filepath, name=name)

    monkeypatch.setattr(dl, 'scan_path', spy_scan_path)
    return captured


def _download(cli_runner: CliRunner, name: str, path: str) -> object:
    return cli_runner.run(subliminal_cli, ['download', '-l', 'en', '-p', 'podnapisi', '--name', name, path])


def _names(captured: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    return [(os.path.basename(p), n) for p, n in captured]


def test_cli_download_name_sed(cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _spy(monkeypatch)
    with cli_runner.isolated_filesystem():
        result = _download(
            cli_runner, r's/.*YP-1R-([0-9]+)x([0-9]+).*/My Little Pony S\1E\2.mkv/', 'YP-1R-01x05-720p.mkv'
        )
        assert result.exit_code == 0
        assert ('YP-1R-01x05-720p.mkv', 'My Little Pony S01E05.mkv') in _names(captured)


def test_cli_download_name_static(cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _spy(monkeypatch)
    # a static name starting with 's' and containing non-alphanumeric characters is not a substitution
    static_name = 's.w.a.t.2017.s01e01.720p.hdtv.x264-killers.mkv'
    with cli_runner.isolated_filesystem():
        result = _download(cli_runner, static_name, 'badly-named-video.mkv')
        assert result.exit_code == 0
        assert ('badly-named-video.mkv', static_name) in _names(captured)


def test_cli_download_name_ampersand(cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _spy(monkeypatch)
    with cli_runner.isolated_filesystem():
        result = _download(cli_runner, r's/.*_-_([0-9]+)_.*/Panty & Stocking S01E\1.mkv/', 'Garterbelt_-_07_xyz.mkv')
        assert result.exit_code == 0
        assert ('Garterbelt_-_07_xyz.mkv', 'Panty & Stocking S01E07.mkv') in _names(captured)


def test_cli_download_name_ampersand_is_not_whole_match(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _spy(monkeypatch)
    with cli_runner.isolated_filesystem():
        result = _download(cli_runner, 's/[0-9]+/[&]/', 'ep12.mkv')
        assert result.exit_code == 0
        assert ('ep12.mkv', 'ep[&].mkv') in _names(captured)


def test_cli_download_name_no_match_falls_back(cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _spy(monkeypatch)
    video_name = 'Marvels.Agents.of.S.H.I.E.L.D.S02E06.720p.HDTV.x264-KILLERS.mkv'
    with cli_runner.isolated_filesystem():
        result = _download(cli_runner, r's/NOPE-([0-9]+)/E\1/', video_name)
        assert result.exit_code == 0
        assert (video_name, None) in _names(captured)


def test_cli_download_name_bad_group_reference_falls_back(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _spy(monkeypatch)
    with cli_runner.isolated_filesystem():
        # the pattern compiles but the replacement refers to a missing group
        result = _download(cli_runner, r's/(a)/X\2Y/', 'aaa.mkv')
        assert result.exit_code == 0
        assert ('aaa.mkv', None) in _names(captured)


def test_cli_download_name_flags(cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _spy(monkeypatch)
    cases = [('s/a/X/', 'aaa.mkv'), ('s/a/X/g', 'aab.mkv'), ('s/a/X/gi', 'AaB.mkv'), ('s/a/X/i', 'AAc.mkv')]
    with cli_runner.isolated_filesystem():
        for expr, video in cases:
            assert _download(cli_runner, expr, video).exit_code == 0
    assert _names(captured) == [
        ('aaa.mkv', 'Xaa.mkv'),
        ('aab.mkv', 'XXb.mkv'),
        ('AaB.mkv', 'XXB.mkv'),
        ('AAc.mkv', 'XAc.mkv'),
    ]


@pytest.mark.parametrize(
    ('expr', 'video', 'expected'),
    [
        ('s|a|b|', 'aa.mkv', 'ba.mkv'),
        ('s#a#b#g', 'aa.mkv', 'bb.mkv'),
        (r's/a\/b/c/', 'a/b.mkv', 'c.mkv'),  # escaped delimiter is a literal delimiter in the pattern
        (r's|a|b\|c|', 'aa.mkv', 'b|ca.mkv'),  # ... and in the replacement
    ],
)
def test_cli_download_name_delimiters(
    cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch, expr: str, video: str, expected: str
) -> None:
    captured = _spy(monkeypatch)
    with cli_runner.isolated_filesystem():
        os.makedirs(os.path.dirname(video) or '.', exist_ok=True)
        assert _download(cli_runner, expr, video).exit_code == 0
    assert any(n == expected for _, n in captured)


def test_cli_download_name_applies_to_whole_path(cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _spy(monkeypatch)
    with cli_runner.isolated_filesystem():
        os.makedirs('shows/Season 02')
        result = _download(cli_runner, r's#Season ([0-9]+)/Episode ([0-9]+)#Show S\1E\2#', 'shows/Season 02/Episode 05.mkv')
        assert result.exit_code == 0
        # the part of the path that is not matched ('shows/') is kept
        assert [n for _, n in captured] == ['shows/Show S02E05.mkv']


def test_cli_download_name_invalid_expression(cli_runner: CliRunner) -> None:
    with cli_runner.isolated_filesystem():
        result = _download(cli_runner, 's/(/x/', 'foo.mkv')
        assert result.exit_code == 2


def test_cli_download_name_unsupported_flag(cli_runner: CliRunner) -> None:
    with cli_runner.isolated_filesystem():
        assert _download(cli_runner, 's/a/b/x', 'foo.mkv').exit_code == 2
        assert _download(cli_runner, 's/a/b/gx', 'foo.mkv').exit_code == 2
