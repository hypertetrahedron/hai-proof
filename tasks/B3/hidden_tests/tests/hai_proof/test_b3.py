"""Layout dashboards must lay out stacked sidebars correctly and honour runtime size changes."""

import io
from typing import List

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

WIDTH = 40
HEIGHT = 12


def render(layout: Layout, width: int = WIDTH, height: int = HEIGHT) -> List[str]:
    console = Console(
        file=io.StringIO(),
        width=width,
        height=height,
        color_system=None,
        force_terminal=False,
        legacy_windows=False,
        _environ={},
    )
    console.print(layout)
    return console.file.getvalue().splitlines()


def make_dashboard(side_size: int = 14) -> Layout:
    layout = Layout(name="root")
    layout.split_row(Layout(name="side", size=side_size), Layout(name="main"))
    layout["side"].split_column(
        Layout(Panel("S1"), name="s1"), Layout(Panel("S2"), name="s2")
    )
    layout["main"].update(Panel("MAIN"))
    return layout


def test_stacked_sidebar_stays_left_of_main():
    lines = render(make_dashboard())
    assert len(lines) == HEIGHT
    assert all(len(line) == WIDTH for line in lines)
    s2_row = next(line for line in lines if "S2" in line)
    assert "MAIN" not in s2_row
    assert s2_row.index("S2") < 14
    main_row = next(line for line in lines if "MAIN" in line)
    assert "S1" in main_row
    assert main_row.index("MAIN") >= 14


def test_three_level_nesting_keeps_rows_aligned():
    layout = Layout(name="root")
    layout.split_row(Layout(name="left", size=10), Layout(name="mid"), Layout(name="right", size=10))
    layout["left"].split_column(Layout(Panel("L1")), Layout(Panel("L2")))
    layout["mid"].split_column(Layout(Panel("M1")), Layout(Panel("M2")), Layout(Panel("M3")))
    layout["right"].update(Panel("R"))
    lines = render(layout)
    assert len(lines) == HEIGHT
    assert all(len(line) == WIDTH for line in lines)
    for tag in ("L1", "L2"):
        row = next(line for line in lines if tag in line)
        assert row.index(tag) < 10
    for tag in ("M1", "M2", "M3"):
        row = next(line for line in lines if tag in line)
        assert 10 <= row.index(tag) < 30
    assert next(line for line in lines if " R" in line).index(" R") >= 30


def test_changing_size_after_first_render_takes_effect():
    layout = make_dashboard(14)
    first = render(layout)
    assert first[0][:14] == "╭" + "─" * 12 + "╮"
    layout["side"].size = 22
    second = render(layout)
    assert second != first
    assert second == render(make_dashboard(22))
    assert second[0][:22] == "╭" + "─" * 20 + "╮"


def test_changing_ratio_after_first_render_takes_effect():
    layout = Layout(name="root")
    layout.split_row(Layout(name="a", ratio=1), Layout(name="b", ratio=1))
    render(layout)
    assert [r.region.width for r in layout.map.values()] == [20, 20]
    layout["b"].ratio = 3
    render(layout)
    widths = {l.name: r.region.width for l, r in layout.map.items()}
    assert widths == {"a": 10, "b": 30}


def test_changing_minimum_size_after_first_render_takes_effect():
    layout = Layout(name="root")
    layout.split_row(Layout(name="a", ratio=1), Layout(name="b", ratio=9))
    render(layout)
    widths = {l.name: r.region.width for l, r in layout.map.items()}
    assert widths == {"a": 4, "b": 36}
    layout["a"].minimum_size = 12
    render(layout)
    widths = {l.name: r.region.width for l, r in layout.map.items()}
    assert widths["a"] == 12
    assert widths["a"] + widths["b"] == WIDTH


def test_resizing_a_fixed_row_between_refreshes():
    layout = Layout(name="root")
    layout.split_column(Layout(name="header", size=3), Layout(name="body"))
    render(layout)
    layout["header"].size = 5
    render(layout)
    heights = {l.name: r.region.height for l, r in layout.map.items()}
    assert heights == {"header": 5, "body": HEIGHT - 5}


def render_table(table: Table, width: int = 60) -> str:
    console = Console(
        file=io.StringIO(),
        width=width,
        color_system=None,
        force_terminal=False,
        legacy_windows=False,
        _environ={},
    )
    console.print(table)
    return console.file.getvalue()


def make_jobs_table(status) -> Table:
    table = Table("job", "status")
    table.add_row("build", status)
    return table


def test_table_widens_when_cell_text_is_edited_in_place():
    status = Text("starting")
    table = make_jobs_table(status)
    before = render_table(table)
    status.plain = "finished successfully"
    after = render_table(table)
    assert after != before
    assert after == render_table(make_jobs_table(Text("finished successfully")))
    assert "finished successfully" in after


def test_table_follows_header_changes_after_first_render():
    table = make_jobs_table(Text("ok"))
    render_table(table)
    table.columns[1].header = "current state of the job"
    after = render_table(table)
    expected = Table("job", "current state of the job")
    expected.add_row("build", Text("ok"))
    assert after == render_table(expected)


def test_table_follows_column_max_width_changes_after_first_render():
    table = make_jobs_table(Text("finished successfully"))
    render_table(table)
    table.columns[1].max_width = 8
    after = render_table(table)
    expected = make_jobs_table(Text("finished successfully"))
    expected.columns[1].max_width = 8
    assert after == render_table(expected)


def test_table_inside_layout_tracks_edited_cell():
    status = Text("starting")
    layout = Layout(name="root")
    layout.split_row(Layout(name="side", size=10), Layout(name="main"))
    layout["main"].update(make_jobs_table(status))
    render(layout, width=60)
    status.plain = "finished successfully"
    lines = render(layout, width=60)
    assert any("finished successfully" in line for line in lines)
