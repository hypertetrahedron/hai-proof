Feature request for jsonpath-ng:

Slices and the `[*]` wildcard are surprisingly forgiving about what they are applied to: they quietly wrap values that are not arrays and match those. That makes some queries return nodes nobody asked for, and `..[*]` in particular gives odd results. I'd like these to behave the way RFC 9535 describes selectors for values that are not arrays, instead of coercing them.

Please change this. The exact behaviour is something I'd like to settle with you, so ask me before you lock it in. Update the existing tests that rely on the old behaviour, add tests for the new one, and keep the suite passing.
