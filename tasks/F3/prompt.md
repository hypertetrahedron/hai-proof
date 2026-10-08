I'd like to be able to cap how tall things get in Rich. We print tables, panels and trees full of log messages and descriptions, and one chatty entry blows the whole output up to 30 lines. I want to say "show at most N lines of this and mark that there is more", consistently across `Table`, `Panel` and `Tree`: limits on the number of lines of a cell / panel / label, plus limits on the number of rows of a table and children of a tree node.

## Line limits

### The building block

A new public renderable, `rich.linelimit.LineLimit(renderable, max_lines, more_marker="…")`, which renders `renderable` and truncates it to `max_lines` lines. `max_lines=None` means unlimited. `max_lines` must be `None` or an integer of at least 1, otherwise `ValueError` (everywhere in this request that a `max_lines` is accepted). A `rich.linelimit.validate_max_lines` helper is not required, but all the places below should share one implementation of the truncation rule rather than each growing their own copy.

"Lines" means the lines of the renderable after it has been rendered and wrapped at the width it is given, so this works for strings with markup, `Text`, `Panel`, a nested `Table`, and so on. If the content has no more than `max_lines` lines nothing changes. Otherwise only the first `max_lines` lines are kept and the last kept line is changed like this, in order:

1. Trailing whitespace on that line is removed.
2. If the line (without the marker) is wider than `width - marker width`, it is cropped to `width - marker width` cells. No further whitespace stripping happens after cropping.
3. The marker is appended directly after the text, in the style of the last character that was kept on that line (no style if the line is blank). A blank kept line just becomes the marker. If the marker is wider than the available width it is cut down to that width and replaces the whole line. An empty marker `""` is allowed, and means the content is simply cut off.

The text `{hidden}` anywhere in a marker is replaced (before measuring the marker) by the number of lines that were removed, e.g. `more_marker=" (+{hidden})"` gives `a (+3)`. Nothing else in the marker is interpreted (no `str.format`, no markup).

For example, at width 10, `"alpha beta gamma delta"` with `max_lines=2` is `alpha beta` / `gamma…`, and with `max_lines=1` it is `alpha bet…` (the kept line is exactly 10 wide, so it loses its last character to make room). At width 8 with `more_marker=">>"` and `max_lines=1`, `"aa bb cc dd ee"` is `aa bb >>`.

Measuring a `LineLimit` gives the measurement of the wrapped renderable, i.e. the limit never changes widths, only heights. Style inside the kept text is preserved, and a `height` imposed from outside (for example `Panel(height=...)`) is applied afterwards, as it is today, and not before the limit.

### Table

```python
table = Table(max_lines=3, more_marker="…")      # table-wide default
table.add_column("Message", max_lines=2)         # per-column override
table.add_column("Level", more_marker="[+]")     # per-column marker override
table.add_row("...", "...", max_lines=1)         # per-row override
```

- `Table(max_lines=None, more_marker="…")`, `Table.add_column(..., max_lines=None, more_marker=None)`, `Table.add_row(..., max_lines=None)`. The `Column` dataclass gets matching `max_lines` / `more_marker` fields (both default `None`), and `Table.max_lines` / `Table.more_marker` are plain attributes that can be changed after rows and columns have been added (the table is resolved when it renders).
- Precedence, most specific first: the row's `max_lines`, then the column's, then the table's. Likewise a column's `more_marker` (if not `None`) beats the table's. A row-level `max_lines` applies to every cell in that row.
- The limit also applies to header and footer cells (using the column's, then the table's, setting; there is no row setting for those).
- Cell padding is not part of the content, so with `padding=(1, 2)` you still get the blank padding lines above and below the (at most `max_lines`) content lines.
- Column widths are decided from the full, untruncated content exactly as today: setting `max_lines` must not make columns narrower, and the table's measurement must not change. Only row heights change. Row heights, vertical alignment in neighbouring cells, borders, `show_lines`, `row_styles` and so on all work from the truncated height, so a row is as tall as its tallest *truncated* cell.
- A failed `add_row` (invalid `max_lines`) must not leave a partial row behind.

### Panel

`Panel(..., max_lines=None, more_marker="…")`, and `Panel.fit(...)` accepts the same. The limit applies to the panel's content, not including its padding, border, title or subtitle. The panel's width (including `Panel.fit` sizing to its content) is still computed from the full content. If `height` is also given, the content is limited first and then padded or cropped to the height as today, so a `height` smaller than the limited content crops it with no marker.

### Tree

`Tree(label, ..., max_lines=None, more_marker="…")` limits the label of that node, and `Tree.add(label, ..., max_lines=None, more_marker=None)` too. A child that is given `None` inherits the value its parent has at the moment `add` is called (the same way `style` and `guide_style` already work), and an explicit value overrides it for that node and for its own later children. Guide lines continue to work as they do now for the lines that remain, and the width available to a label (after the guide prefix) is what gets wrapped before limiting.

## Row and child limits

### `Table(max_rows=None, rows_marker="… {hidden} more")`

If the table has more than `max_rows` body rows (`max_rows` is `None` or an integer of at least 1, `ValueError` otherwise), only the first `max_rows` rows are shown, followed by one extra *marker row*. The marker row has the `rows_marker` text (with `{hidden}` replaced by the number of hidden rows, no other interpretation beyond what a plain string cell already gets) in the first column and empty cells in the others, and the style `"dim"`. `Table.max_rows` and `Table.rows_marker` are plain attributes that can be changed at any time; the table's own `rows` and `columns` data is never modified by rendering, and `row_count` still reports the real number of rows.

- The marker row is an ordinary row for everything else: it takes part in `row_styles` alternation (it is the row at index `max_rows`), its first-column text wraps if the column is narrow and is subject to the column / table `max_lines`, `show_lines` / `leading` separators are drawn around it like around any other row, and the header and (if enabled) footer are still shown, the footer after the marker row.
- `end_section` of a hidden row is ignored; `end_section` on the last shown row works as usual. The marker row itself never ends a section.
- Layout is computed as if the table only contained the shown rows plus the marker row: hidden rows do not influence column widths or the table's measurement.
- If the number of rows is `max_rows` or fewer, the table renders exactly as it does without the option.

### `Tree(max_children=None, children_marker="… {hidden} more")`

If an expanded node has more than `max_children` children, only the first `max_children` are displayed, followed by one extra leaf, the *marker leaf*, which is the last child of the node (so it gets the closing `└──` guide) and whose label is `children_marker` with `{hidden}` replaced by the number of hidden children. The marker leaf is rendered in the tree's style with `"dim"` added, is never itself limited by `max_lines`/`max_children`, and takes part in everything else (guide lines and styles, `hide_root`, width wrapping) as an ordinary leaf. Hidden children and their descendants are not rendered and do not contribute to the tree's measurement, while the marker leaf does. A collapsed node (`expanded=False`) shows nothing and so shows no marker.

`Tree.add(..., max_children=None, children_marker=None)` follows the same inheritance rule as `max_lines` above: `None` inherits the parent's current value when `add` is called, and an explicit value applies to that node (and, by inheritance, its later children). Changing `max_children` / `children_marker` on an existing node affects that node only. `ValueError` for invalid values, in `Tree(...)` and `Tree.add(...)`.

## Compatibility

A table, panel or tree that never uses these options must render exactly as it does now, and existing public classes and method signatures should stay backward compatible (new parameters are keyword-only additions with the defaults above).
