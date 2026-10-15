Right now `tabulate()` lines up each header with its column: a left-aligned text column gets a
left-aligned header, a column of numbers gets a right-aligned header, and so on. That is not always
what I want. In reports I often need the headers centered, or one header aligned differently from the
data underneath it.

Could you make alignment in `tabulate()` more flexible?

- Let users align headers independently of the column alignment: one alignment for all the headers,
  with a way to override it for individual headers.
- Do the same for the data columns: one alignment for every column, with the existing per-column
  `colalign` still able to override individual columns.
- Per-column or per-header alignment lists that are longer than the table shouldn't crash.
- Passing a single string where a per-column sequence is expected is an easy mistake, and today it is
  silently treated as one letter per column. Warn when that happens.

Existing calls that don't use the new options must produce exactly the same output as today, and I'd
like tests for the new behaviour added to the test suite.
