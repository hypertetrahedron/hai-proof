Feature request for packaging:

I build tooling that rewrites requirements, for example swapping a name, pinning a different specifier, or dropping a marker, and today I have to take a `Requirement` apart and glue a string back together, or mutate attributes on a copy and hope nothing is left inconsistent. `Version` already has a way to make a modified copy of itself, and I'd like `Requirement` to have the same: a copy with some of its fields replaced, leaving the original alone. It should also work with `copy.replace()` on Python 3.13 and later.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
