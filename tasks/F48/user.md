I want a `count` property on `vRecur` for the COUNT part of a recurrence rule. The design:

- Reading `rule.count` returns an `int`, e.g. `vRecur.from_ical("FREQ=DAILY;COUNT=10").count == 10`.
- If COUNT is absent, it returns `None`. If COUNT is present but an empty list, it also returns `None`.
- `0` is a valid COUNT (the RFC grammar is just digits) and is returned as `0`, never confused with "missing". Setting `rule.count = 0` stores it: `"COUNT" in rule` and the rule serialises as `FREQ=DAILY;COUNT=0`.
- If several values are stored (e.g. `COUNT=[10, 20]`), reading returns the first.
- Setting `rule.count = 5` stores it so that `to_ical()` gives `FREQ=DAILY;COUNT=5`, and a rule serialised and parsed again gives the same count (also for 0).
- Setting `rule.count = None` removes COUNT from the rule, same as `del rule.count`. Deleting when COUNT is not set is a no-op, not an error.
- Setting something that is not an `int` raises `TypeError`, e.g. the string `"10"`. `bool` counts as not an int, so `True` raises `TypeError` too.
- Setting a negative number raises `icalendar.error.InvalidCalendar` (a `ValueError` subclass), not a plain `ValueError` and not a `TypeError`.
- If the stored value cannot be read as an int, which can only happen when someone assigned it directly with `rule["COUNT"] = "abc"` (or `""`, or `["abc"]`) past the parser, reading `rule.count` raises `InvalidCalendar` rather than letting a bare `int()` error through. Parsing a non-numeric COUNT keeps failing in the parser as it does today.
- COUNT and UNTIL are mutually exclusive in the RFC, but the accessor does not enforce that.
- Add a docstring with an example, and a news entry.
