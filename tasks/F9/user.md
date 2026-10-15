I maintain a reporting tool built on `tabulate()`, and I want header alignment to be configurable without touching how the data columns are aligned.

What I want:
- Two new keyword arguments to `tabulate()`: `headersglobalalign` sets one alignment for every header, and `headersalign` is a sequence that overrides it header by header, starting from the leftmost header.
- Both default to `None`, which means headers keep following their column's alignment, exactly as now.
- Values for the headers: "left", "right" and "center". In `headersalign` I also want "same", meaning this header follows its column's alignment, and "global", meaning use `headersglobalalign` for this header (no override).
- I want the same pair of ideas for the data columns: a new `colglobalalign` keyword that sets the alignment of every column before any `colalign` override is applied (None means the usual per-type alignment), and "global" accepted as an entry in `colalign` meaning no override for that column.
- A `colalign` or `headersalign` that is longer than the table (more entries than columns or headers) must not crash or misalign anything. The extra entries are just ignored.
- If someone passes a bare string to `colalign` or `headersalign`, such as `colalign="center"`, it currently gets treated as a sequence of single letters. I want a `UserWarning` whose message contains the text "As a string" and says what the string was interpreted as and suggests the right keyword, such as `colglobalalign="center"` or `colalign=("center",)`. One warning per offending argument.
- Parameter order in the signature: put `colglobalalign` immediately before `colalign`, and `headersglobalalign` and `headersalign` right after `maxcolwidths` and before `rowalign`. Existing parameters keep their order, so positional callers don't break.
- Document the new options in the `tabulate()` docstring. If there is no table data, column alignment is ignored, so a header can't follow it; that is fine.
- Examples I have in mind: with `colglobalalign="center"` and `colalign=("global", "left", "right")` the first column is centered, the second left and the third right. With `headersglobalalign="right"` and `headersalign=("same", "same", "left", "global", "center")`, the first two headers follow their columns, the third is left, the fourth is right and the fifth is centered.
