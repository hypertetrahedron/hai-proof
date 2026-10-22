Feature request for icalendar:

I work with recurrence rules a lot, and reading or changing the COUNT part of a `vRecur` means poking at the underlying dict, where the value is a list that may hold ints, strings or nothing at all. Other parts of the library have proper property accessors for this kind of thing. Please add a `count` property to `vRecur` that I can read, assign and delete (`rule.count`, `rule.count = 5`, `del rule.count`) so I don't have to touch the dict.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing property tests and keep the suite passing.
