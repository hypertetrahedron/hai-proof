import io
import re

import pytest

from rich import box
from rich.console import Console
from rich.measure import Measurement
from rich.panel import Panel
from rich.table import Column, Table
from rich.text import Text
from rich.tree import Tree


def render(renderable, width=40, **kwargs):
    console = Console(
        width=width,
        file=io.StringIO(),
        color_system=None,
        legacy_windows=False,
        **kwargs,
    )
    console.print(renderable)
    return console.file.getvalue()


def make_table(*headers, **kwargs):
    return Table(*headers, box=box.ASCII, **kwargs)


def test_column_max_lines_truncates_with_marker():
    table = make_table()
    table.add_column("Name", width=10, max_lines=2)
    table.add_column("N", width=3)
    table.add_row("alpha beta gamma delta epsilon", "1")
    table.add_row("short", "2")
    table.add_row("one two three four five six", "3\n4\n5")
    assert render(table) == (
        "+------------------+\n"
        "| Name       | N   |\n"
        "|------------+-----|\n"
        "| alpha beta | 1   |\n"
        "| gamma…     |     |\n"
        "| short      | 2   |\n"
        "| one two    | 3   |\n"
        "| three fou… | 4   |\n"
        "|            | 5   |\n"
        "+------------------+\n"
    )


def test_defaults_do_not_change_output():
    def build(**kwargs):
        table = make_table(**kwargs)
        table.add_column("A", width=8)
        table.add_column("B")
        table.add_row("aa bb cc dd ee ff", "x\ny\nz")
        table.add_row("short", "q")
        return table

    plain = render(build())
    assert render(build(max_lines=None)) == plain
    assert render(build(max_lines=50)) == plain
    assert "…" not in plain


def test_table_column_row_precedence():
    table = make_table(max_lines=1)
    table.add_column("A", width=8)
    table.add_column("B", width=8, max_lines=2)
    table.add_column("C", width=8, more_marker=">>")
    table.add_row("aa bb cc dd ee", "aa bb cc dd ee", "aa bb cc dd ee")
    table.add_row("aa bb cc dd ee", "aa bb cc dd ee", "aa bb cc dd ee", max_lines=3)
    assert render(table) == (
        "+--------------------------------+\n"
        "| A        | B        | C        |\n"
        "|----------+----------+----------|\n"
        "| aa bb c… | aa bb cc | aa bb >> |\n"
        "|          | dd ee    |          |\n"
        "| aa bb cc | aa bb cc | aa bb cc |\n"
        "| dd ee    | dd ee    | dd ee    |\n"
        "+--------------------------------+\n"
    )


def test_row_override_can_loosen_and_tighten():
    table = make_table()
    table.add_column("A", width=6, max_lines=1)
    table.add_row("aa bb cc dd")
    table.add_row("aa bb cc dd", max_lines=2)
    table.add_row("aa bb cc dd", max_lines=1)
    out = render(table)
    assert out.splitlines()[3:] == [
        "| aa bb… |",
        "| aa bb  |",
        "| cc dd  |",
        "| aa bb… |",
        "+--------+",
    ]


def test_last_line_edge_cases():
    table = make_table()
    table.add_column("A", width=10, max_lines=1)
    table.add_column("B", width=6)
    table.add_row("abcdefghij klm", "1")  # kept line is exactly the column width
    table.add_row("ab   \ncd", "1")  # trailing whitespace is removed
    table.add_row("a\n\n\nb", "2")  # blank kept line
    table.add_row("fits", "3")
    assert render(table) == (
        "+---------------------+\n"
        "| A          | B      |\n"
        "|------------+--------|\n"
        "| abcdefghi… | 1      |\n"
        "| ab…        | 1      |\n"
        "| a…         | 2      |\n"
        "| fits       | 3      |\n"
        "+---------------------+\n"
    )
    table = make_table(max_lines=2)
    table.add_column("A", width=6)
    table.add_row("a\n\nb")
    assert render(table).splitlines()[3:5] == ["| a      |", "| …      |"]


def test_marker_variants():
    table = make_table(max_lines=1, more_marker="")
    table.add_column("A", width=6)
    table.add_row("abcdef ghi")
    table.add_row("ab \ncd")
    assert render(table).splitlines()[3:5] == ["| abcdef |", "| ab     |"]

    table = make_table(max_lines=1)
    table.add_column("A", width=1)
    table.add_column("B", width=3, more_marker="12345678")
    table.add_row("a b", "a b c")
    assert render(table).splitlines()[3] == "| … | 123 |"

    table = make_table(max_lines=1, more_marker="[more]")
    table.add_column("A", width=8)
    table.add_row("one two three")
    assert render(table).splitlines()[3] == "| on[more] |"


def test_padding_is_not_counted():
    table = make_table(padding=(1, 2), max_lines=1)
    table.add_column("A", width=6)
    table.add_column("B", width=6)
    table.add_row("aaa bbb ccc", "x")
    assert render(table) == (
        "+---------------------+\n"
        "|          |          |\n"
        "|  A       |  B       |\n"
        "|          |          |\n"
        "|----------+----------|\n"
        "|          |          |\n"
        "|  aaa…    |  x       |\n"
        "|          |          |\n"
        "+---------------------+\n"
    )


def test_header_and_footer_are_limited():
    table = make_table(max_lines=1, show_footer=True)
    table.add_column("Head er long", "Foot er long", width=6, more_marker="~")
    table.add_column("B", "f", width=3, vertical="middle")
    table.add_row("aa bb cc dd", "1\n2\n3")
    assert render(table) == (
        "+--------------+\n"
        "| Head~  | B   |\n"
        "|--------+-----|\n"
        "| aa bb~ | 1…  |\n"
        "|--------+-----|\n"
        "| Foot~  | f   |\n"
        "+--------------+\n"
    )


def test_column_widths_do_not_depend_on_max_lines():
    def build(**kwargs):
        table = make_table(**kwargs)
        table.add_column("Description")
        table.add_column("Other")
        table.add_row("a fairly long description of something " * 3, "x " * 30)
        return table

    full = render(build(), width=50).splitlines()
    cut = render(build(max_lines=1), width=50).splitlines()
    assert full[0] == cut[0]
    assert full[2] == cut[2]
    assert len(cut) == 5
    assert cut[3].count("…") == 2
    console = Console(width=50, file=io.StringIO())
    assert Measurement.get(console, console.options, build()) == Measurement.get(
        console, console.options, build(max_lines=1)
    )


def test_vertical_alignment_uses_truncated_height():
    table = make_table()
    table.add_column("A", width=4, max_lines=3)
    table.add_column("B", width=3, vertical="middle")
    table.add_column("C", width=3, vertical="bottom")
    table.add_row("a\nb\nc\nd\ne", "x", "y")
    assert render(table).splitlines()[3:] == [
        "| a    |     |     |",
        "| b    | x   |     |",
        "| c…   |     | y   |",
        "+------------------+",
    ]


def test_renderables_in_cells():
    table = make_table()
    table.add_column("A", width=12, max_lines=2)
    table.add_column("B", width=3)
    table.add_row(Panel("a\nb\nc\nd"), "x")
    inner = Table(box=box.ASCII)
    inner.add_column("i")
    inner.add_row("1")
    inner.add_row("2")
    table.add_row(inner, "y")
    table.add_row(Text("one\ntwo\nthree"), "z")
    lines = render(table, width=60).splitlines()
    assert lines[3:] == [
        "| ╭──────────╮ | x   |",
        "| │ a        … |     |",
        "| +---+        | y   |",
        "| | i |…       |     |",
        "| one          | z   |",
        "| two…         |     |",
        "+--------------------+",
    ]


def test_styles_are_preserved_and_applied_to_marker():
    table = make_table(max_lines=1)
    table.add_column("A", width=8)
    table.add_row("[red]alpha beta gamma[/red]")
    console = Console(
        width=40,
        file=io.StringIO(),
        force_terminal=True,
        color_system="standard",
        legacy_windows=False,
    )
    console.print(table)
    out = console.file.getvalue()
    assert re.search(r"\x1b\[31m[^\x1b]*…", out)
    assert "gamma" not in re.sub(r"\x1b\[[0-9;]*m", "", out)


def test_no_wrap_and_markup_columns():
    table = make_table(max_lines=2)
    table.add_column("A", width=6)
    table.add_column("B", width=6, no_wrap=True)
    table.add_row("[b]aa[/b] bb cc dd ee", "aaa bbb ccc ddd")
    assert render(table).splitlines()[3:5] == [
        "| aa bb  | aaa b… |",
        "| cc dd… |        |",
    ]


def test_late_configuration_and_column_objects():
    table = make_table()
    table.add_column("A", width=6)
    table.add_row("aa bb cc dd")
    assert "…" not in render(table)
    table.max_lines = 1
    assert render(table).splitlines()[3] == "| aa bb… |"
    table.columns[0].max_lines = 2
    assert render(table).splitlines()[3:5] == ["| aa bb  |", "| cc dd  |"]
    table.columns[0].max_lines = 1
    table.columns[0].more_marker = "+"
    assert render(table).splitlines()[3] == "| aa bb+ |"

    table = make_table(Column("A", width=6, max_lines=1), "B")
    table.add_row("aa bb cc dd", "p q r s t u v w x y z " * 3)
    out = render(table, width=30).splitlines()
    assert out[3].startswith("| aa bb… |")
    assert out[4].startswith("|        |")


def test_validation():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            Table(max_lines=bad)
        with pytest.raises(ValueError):
            make_table().add_column("A", max_lines=bad)
        table = make_table()
        table.add_column("A")
        with pytest.raises(ValueError):
            table.add_row("x", max_lines=bad)
        assert table.row_count == 0
    table = make_table(max_lines=1)
    table.add_column("A", max_lines=None)
    table.add_row("x", max_lines=None)


def lines_of(renderable, width=30):
    return [line.rstrip() for line in render(renderable, width=width).splitlines()]


def test_linelimit_renderable():
    from rich.linelimit import LineLimit

    assert lines_of(LineLimit("a\nb\nc", 2)) == ["a", "b…"]
    assert lines_of(LineLimit("a\nb\nc", 3)) == ["a", "b", "c"]
    assert lines_of(LineLimit("a\nb\nc", None)) == ["a", "b", "c"]
    assert lines_of(LineLimit("a\nb\nc", 1, more_marker="")) == ["a"]
    assert lines_of(LineLimit("a\nb\nc", 1, more_marker=" [+2]")) == ["a [+2]"]
    assert lines_of(LineLimit("one two three four", 1), width=8) == ["one two…"]
    assert lines_of(LineLimit("abcdefgh ijk", 1), width=8) == ["abcdefg…"]
    assert lines_of(LineLimit("ab  \ncd", 1)) == ["ab…"]
    for bad in (0, -3):
        with pytest.raises(ValueError):
            LineLimit("x", bad)
    console = Console(width=30, file=io.StringIO())
    assert Measurement.get(
        console, console.options, LineLimit("hello world\nx", 1)
    ) == Measurement.get(console, console.options, "hello world\nx")


def test_linelimit_keeps_style():
    from rich.linelimit import LineLimit

    console = Console(
        width=20,
        file=io.StringIO(),
        force_terminal=True,
        color_system="standard",
        legacy_windows=False,
    )
    console.print(LineLimit("[green]aaa[/green] bbb\n[green]ccc[/green]", 1))
    out = console.file.getvalue()
    assert re.search(r"\x1b\[32m[^\x1b]*\x1b", out)
    assert re.sub(r"\x1b\[[0-9;]*m", "", out).strip() == "aaa bbb…"


def test_panel_max_lines():
    panel = Panel("alpha beta gamma delta epsilon zeta", max_lines=2, padding=(1, 1))
    assert render(panel, width=20) == (
        "╭──────────────────╮\n"
        "│                  │\n"
        "│ alpha beta gamma │\n"
        "│ delta epsilon…   │\n"
        "│                  │\n"
        "╰──────────────────╯\n"
    )
    short = Panel("a\nb", max_lines=2)
    assert render(short, width=10) == render(Panel("a\nb"), width=10)
    assert render(Panel("a\nb\nc", max_lines=1, more_marker=">>"), width=10) == (
        "╭────────╮\n"
        "│ a>>    │\n"
        "╰────────╯\n"
    )
    with pytest.raises(ValueError):
        Panel("x", max_lines=0)
    with pytest.raises(ValueError):
        Panel.fit("x", max_lines=-1)


def test_panel_fit_and_width_are_computed_from_full_content():
    fit = Panel.fit("a b\nc\nlonger line here", max_lines=2)
    assert render(fit, width=40) == (
        "╭──────────────────╮\n"
        "│ a b              │\n"
        "│ c…               │\n"
        "╰──────────────────╯\n"
    )
    console = Console(width=40, file=io.StringIO())
    assert Measurement.get(console, console.options, fit) == Measurement.get(
        console, console.options, Panel.fit("a b\nc\nlonger line here")
    )


def test_panel_height_with_max_lines():
    panel = Panel("a\nb\nc\nd\ne", max_lines=3, height=7)
    assert render(panel, width=10) == (
        "╭────────╮\n"
        "│ a      │\n"
        "│ b      │\n"
        "│ c…     │\n"
        "│        │\n"
        "│        │\n"
        "╰────────╯\n"
    )
    # height smaller than max_lines behaves as before: cropped, no marker
    panel = Panel("a\nb\nc\nd\ne", max_lines=4, height=4)
    assert render(panel, width=10) == (
        "╭────────╮\n"
        "│ a      │\n"
        "│ b      │\n"
        "╰────────╯\n"
    )


def test_tree_max_lines_inheritance_and_override():
    tree = Tree("root\nline2\nline3", max_lines=2)
    child = tree.add("one two three four five six seven eight nine ten", more_marker="~")
    child.add("deep deep deep deep deep deep deep deep deep")
    tree.add("x\ny\nz", max_lines=3)
    tree.add("p\nq\nr", max_lines=None)
    assert lines_of(tree, width=24) == [
        "root",
        "line2…",
        "├── one two three four",
        "│   five six seven eigh~",
        "│   └── deep deep deep",
        "│       deep deep deep~",
        "├── x",
        "│   y",
        "│   z",
        "└── p",
        "    q…",
    ]


def test_tree_unlimited_by_default_and_hide_root():
    def build(**kwargs):
        tree = Tree("root", hide_root=True, **kwargs)
        tree.add("a\nb\nc")
        return tree

    assert render(build(), width=20) == render(build(max_lines=None), width=20)
    assert lines_of(build(max_lines=1), width=20) == ["a…"]
    # children added before the attribute is changed keep what they inherited
    tree = Tree("root")
    tree.add("a\nb")
    tree.max_lines = 1
    tree.add("c\nd")
    assert lines_of(tree, width=20) == ["root", "├── a", "│   b", "└── c…"]
    with pytest.raises(ValueError):
        Tree("x", max_lines=0)
    with pytest.raises(ValueError):
        Tree("x").add("y", max_lines=0)


def test_tree_with_renderable_label():
    tree = Tree("root", guide_style="none")
    tree.add(Panel("a\nb\nc"), max_lines=2)
    out = lines_of(tree, width=20)
    assert out[0] == "root"
    assert len(out) == 3
    assert "╭" in out[1]
    assert out[2].endswith("…")


def test_table_inside_limited_panel():
    inner = make_table(max_lines=1)
    inner.add_column("A", width=6)
    inner.add_row("aa bb cc dd")
    outer = Panel(inner, max_lines=3)
    assert lines_of(outer, width=20) == [
        "╭──────────────────╮",
        "│ +--------+       │",
        "│ | A      |       │",
        "│ |--------|…      │",
        "╰──────────────────╯",
    ]


def numbered_table(count, **kwargs):
    table = make_table("n", "name", **kwargs)
    for i in range(count):
        table.add_row(str(i), f"name{i}")
    return table


def test_hidden_placeholder_in_line_marker():
    from rich.linelimit import LineLimit

    assert lines_of(LineLimit("a\nb\nc\nd", 1, more_marker=" (+{hidden})")) == [
        "a (+3)"
    ]
    assert lines_of(LineLimit("a\nb\nc\nd", 3, more_marker="{hidden}{hidden}")) == [
        "a",
        "b",
        "c11",
    ]
    table = make_table(max_lines=2, more_marker="+{hidden}")
    table.add_column("A", width=6)
    table.add_row("a\nb\nc\nd\ne")
    assert render(table).splitlines()[3:5] == ["| a      |", "| b+3    |"]
    assert lines_of(Panel("a\nb\nc", max_lines=1, more_marker="+{hidden}"), 10)[
        1
    ] == "│ a+2    │"


def test_table_max_rows():
    table = numbered_table(5, max_rows=2, show_footer=True)
    table.columns[0].footer = "F"
    table.rows[0].end_section = True
    table.rows[3].end_section = True  # hidden, so ignored
    assert render(table, width=30) == (
        "+------------------+\n"
        "| n        | name  |\n"
        "|----------+-------|\n"
        "| 0        | name0 |\n"
        "|----------+-------|\n"
        "| 1        | name1 |\n"
        "| … 3 more |       |\n"
        "|----------+-------|\n"
        "| F        |       |\n"
        "+------------------+\n"
    )
    table.show_lines = True
    assert render(table, width=30).splitlines()[4:9] == [
        "|----------+-------|",
        "| 1        | name1 |",
        "|----------+-------|",
        "| … 3 more |       |",
        "|----------+-------|",
    ]
    # the real rows are untouched
    assert table.row_count == 5
    assert [row for row in table.columns[1].cells] == [f"name{i}" for i in range(5)]


def test_table_max_rows_not_exceeded_means_no_marker():
    plain = render(numbered_table(3))
    assert render(numbered_table(3, max_rows=3)) == plain
    assert render(numbered_table(3, max_rows=10)) == plain
    assert render(numbered_table(3, max_rows=None)) == plain
    assert "more" not in plain
    one = numbered_table(4, max_rows=1)
    assert render(one).splitlines()[3:6] == [
        "| 0        | name0 |",
        "| … 3 more |       |",
        "+------------------+",
    ]
    with pytest.raises(ValueError):
        Table(max_rows=0)
    with pytest.raises(ValueError):
        Table(max_rows=-2)


def test_table_max_rows_layout_comes_from_shown_rows():
    wide = make_table("Name", max_rows=1, rows_marker="+{hidden}")
    wide.add_row("ab")
    wide.add_row("a very very long hidden row indeed")
    assert render(wide, width=60) == (
        "+------+\n"
        "| Name |\n"
        "|------|\n"
        "| ab   |\n"
        "| +1   |\n"
        "+------+\n"
    )
    console = Console(width=60, file=io.StringIO())
    assert Measurement.get(console, console.options, wide).maximum == 8


def test_table_max_rows_marker_wraps_and_respects_column_options():
    table = make_table(max_rows=1)
    table.add_column("A", width=6)
    table.add_column("B", width=3)
    for i in range(4):
        table.add_row(f"r{i}", "x")
    assert render(table).splitlines()[3:7] == [
        "| r0     | x   |",
        "| … 3    |     |",
        "| more   |     |",
        "+--------------+",
    ]
    table.columns[0].max_lines = 1
    assert render(table).splitlines()[4:6] == ["| … 3…   |     |", "+--------------+"]


def test_table_max_rows_marker_style_and_row_styles():
    table = make_table(max_rows=1, row_styles=["", "on red"])
    table.add_column("A")
    for i in range(3):
        table.add_row(f"r{i}")
    console = Console(
        width=30,
        file=io.StringIO(),
        force_terminal=True,
        color_system="standard",
        legacy_windows=False,
    )
    console.print(table)
    out = console.file.getvalue()
    assert re.search(r"\x1b\[2;41m[^\x1b]*… 2 more", out)
    assert not re.search(r"\x1b\[[0-9;]*41m[^\x1b]*r0", out)


def test_table_max_rows_with_max_lines_and_late_changes():
    table = make_table(max_rows=2, max_lines=1)
    table.add_column("A", width=6)
    table.add_row("a b c d e f g")
    table.add_row("x\ny")
    table.add_row("hidden")
    lines = render(table).splitlines()
    assert lines[3:6] == ["| a b c… |", "| x…     |", "| … 1…   |"]
    table.max_rows = None
    assert "hidden" in render(table)
    table.max_rows = 1
    table.rows_marker = "!"
    assert render(table).splitlines()[3:5] == ["| a b c… |", "| !      |"]


def test_tree_max_children():
    tree = Tree("root", max_children=2)
    for i in range(4):
        child = tree.add(f"c{i}")
        for j in range(3):
            child.add(f"g{j}")
    tree.add("last")
    tree.children[0].max_children = None
    assert lines_of(tree, width=30) == [
        "root",
        "├── c0",
        "│   ├── g0",
        "│   ├── g1",
        "│   └── g2",
        "├── c1",
        "│   ├── g0",
        "│   ├── g1",
        "│   └── … 1 more",
        "└── … 3 more",
    ]


def test_tree_max_children_options():
    def build(count, **kwargs):
        tree = Tree("root", **kwargs)
        for i in range(count):
            tree.add(f"item{i}")
        return tree

    assert render(build(3, max_children=3)) == render(build(3))
    assert render(build(3, max_children=None)) == render(build(3))
    assert lines_of(build(5, max_children=1, children_marker="+{hidden}")) == [
        "root",
        "├── item0",
        "└── +4",
    ]
    tree = Tree("root", max_children=1)
    tree.add("a", max_children=2).add("b")
    tree.children[0].add("c")
    tree.children[0].add("d")
    tree.children[0].add("e")
    tree.add("f")
    deep = tree.children[0]
    assert lines_of(tree) == [
        "root",
        "├── a",
        "│   ├── b",
        "│   ├── c",
        "│   └── … 2 more",
        "└── … 1 more",
    ]
    assert deep.max_children == 2
    hidden_root = Tree("root", hide_root=True, max_children=1)
    hidden_root.add("a")
    hidden_root.add("b")
    hidden_root.add("c")
    assert lines_of(hidden_root) == ["a", "… 2 more"]
    folded = Tree("root", max_children=1, expanded=False)
    folded.add("a")
    folded.add("b")
    assert lines_of(folded) == ["root"]
    with pytest.raises(ValueError):
        Tree("x", max_children=0)
    with pytest.raises(ValueError):
        Tree("x").add("y", max_children=-1)


def test_tree_max_children_measure_and_style():
    tree = Tree("root", max_children=1)
    tree.add("ab")
    tree.add("a very very long hidden child label")
    console = Console(width=60, file=io.StringIO())
    # "└── ab" / "└── … 1 more": 4 + len("… 1 more")
    assert Measurement.get(console, console.options, tree).maximum == 12
    ansi = Console(
        width=30,
        file=io.StringIO(),
        force_terminal=True,
        color_system="standard",
        legacy_windows=False,
    )
    ansi.print(tree)
    assert re.search(r"\x1b\[2m[^\x1b]*… 1 more", ansi.file.getvalue())
