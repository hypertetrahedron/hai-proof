We use Lark to parse small structured snippets (dates, JSON payloads, `${...}` placeholders) that are embedded in much larger free text: log lines, prose, templates. Today we have to guess where each snippet starts and call `parse()` on a substring, which is slow and fragile. Please add a way to scan a whole text for every place the grammar matches.

## API

Add `Lark.scan(text, start=None)`. It returns an iterator of `ScanMatch` objects. `ScanMatch` must be importable from the top-level `lark` package. Make it a small named-tuple-like class with two fields, in this order:

- `range`: a `(start, end)` tuple of offsets into the input;
- `value`: the parse result for that span, a `Tree` by default, or whatever the parser's `transformer` returns.

So `ScanMatch((1, 3), Tree('expr', []))` is a valid construction, and two matches compare equal when both fields do.

## Matching rules

- Walk the input from left to right and yield **non-overlapping** matches. Text that doesn't match the grammar is skipped silently, never raised.
- Where several end positions are valid for a match that starts at the same place, take the **longest**. Prefer the longest valid prefix even if the parse fails further on: in `(a)(b) || (c)(d(e)` with `start: expr+`, the matches are `(a)(b)`, `(c)`, then `(e)`.
- Matches may be adjacent. The next search resumes exactly at the end of the previous match.
- A match never starts or ends with an ignored terminal (`%ignore`), and its `range` covers only the non-ignored part. Zero-length matches are never produced, even when the start rule can match the empty string. A grammar that can only match the empty string yields nothing, and doesn't loop forever.
- The result has to be what `parse()` would return for that span. This includes tree options such as `keep_all_tokens` and `maybe_placeholders`, and `propagate_positions` metadata (`meta.line`, `meta.column`, `meta.start_pos`, and so on) relative to the whole input.
- The contextual lexer has to work as it does for `parse()`. For example, a keyword string may lex as a `NAME` where the parser state requires it. The basic lexer has to work too, including grammars where a keyword terminal is folded into a broader terminal.
- Input can be `str`, `bytes` (with `use_bytes=True`, so ranges are byte offsets), or a `lark.utils.TextSlice`. For a `TextSlice`, only the slice is scanned, but ranges and line/column metadata refer to positions in the underlying full text.
- With several start symbols, `start` must be given (as with `parse()`), and the scan then looks only for that rule.

## Configuration and errors

- `scan()` is only supported for `parser='lalr'` without a `postlex` and without a custom lexer class. Otherwise raise `lark.exceptions.ConfigurationError`. For the postlex case, the message must mention `postlex`. A lexer-only `Lark(..., parser=None)` must also give `ConfigurationError`, not an `AttributeError`.
- Validate the configuration when `scan()` is called, before the caller starts iterating.
- `lexer_callbacks` may run while candidate positions are explored:
  - If a callback raises `ValueError`, treat it as "this candidate doesn't lex": skip it and keep scanning.
  - `ConfigurationError` subclasses `ValueError`, but it must still propagate.
  - Any other exception propagates too.
- A callback that returns a `Token` without source positions (a fresh `Token(type, value)` instead of `token.update(...)`) makes `scan()` raise `lark.exceptions.LexError` whose message contains `did not preserve token positions`. This applies even if it is not the last token of the match.
- The transformer is applied only to the matches actually returned. A transformer whose values can't be deep-copied must still work, as with `parse()`.

## Standalone parsers

Parsers generated with `python -m lark.tools.standalone` must support `scan()` too.

Keep `parse()` behaviour and performance unchanged.
