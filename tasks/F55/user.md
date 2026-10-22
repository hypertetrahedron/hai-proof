This is how I want `max_scan` to work, the same for `get_base_url` and `get_meta_refresh`:

- It is a keyword-only argument, `max_scan=None` by default. `None` means no limit, which is today's behaviour.
- It is a count of characters when the text is a `str` and of bytes when the text is `bytes`. So the same limit can reach a tag in a string and fall short of it in the equivalent bytes when the text has multi-byte characters.
- `max_scan=0` looks at nothing, so you get the usual "not found" result (the given `baseurl` for `get_base_url`, `(None, None)` for `get_meta_refresh`). A negative value raises `ValueError`. A limit longer than the text is just the whole text.
- The limit bounds the work, not the results: a tag that starts before the limit is read to its end, even if its end is past the limit, wherever in the tag the limit falls, and even when a quoted attribute value contains a `>`. I never want a half tag to be parsed, because a cut off URL would be worse than none. A tag that starts at or after the limit is not seen.
- A `<` that does not open a tag (such as `1 < 2` in text) does not make the scan run on past the limit.
- Reading on to the end of a tag that the limit falls inside stops at the next `<`: if the tag has no `>` before another `<` begins, I read only up to that `<`, so a `<base>` or `<meta>` that comes after it is still past the limit and is not seen.
- A tag that is not closed but is entirely inside the limit (the text ends before its `>`) still counts, as it does without a limit.
- With bytes, a cut can land in the middle of a multi-byte character. That must not raise; the broken character is decoded with a replacement character and the rest is scanned as usual.
