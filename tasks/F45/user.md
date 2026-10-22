I write tooling that rewrites requirements and I want a supported way to get a modified copy of a `Requirement`, like `Version` has.

The design I want:

- The method is `Requirement.__replace__`, so `copy.replace(req, ...)` works on Python 3.13+ and I can also call `req.__replace__(...)` directly. It must work with `copy.replace` on 3.13 and later (on older Pythons only the direct call matters).
- It takes keyword-only arguments, one per field: `name`, `url`, `extras`, `specifier`, `marker`. Any field I leave out is kept from the original.
- The original is never changed.
- Calling it with no arguments returns a copy that compares equal to the original but is a distinct object (not the same instance).
- `url=None` and `marker=None` clear those fields. A requirement with a URL can't also keep a version specifier, so replacing the url on a requirement that has a specifier means I also pass an empty `SpecifierSet()`; a url plus an empty specifier is accepted.
- The result is validated, and an invalid replacement raises `InvalidRequirement`, not some other error: a name that isn't a valid name (`"not a name!"`), and also any value that would smuggle in extra syntax and silently change another field, for example `name="foo[bar]"` (which would add an extra) or `extras={"a,b"}`. The check is that the new fields come back unchanged after being parsed again.
- Normalisation matches what parsing does: a replacement marker such as `extra == "Foo_Bar"` ends up as `extra == "foo-bar"` in the result's string form.
- An explicit prereleases setting on a replacement `SpecifierSet` (`SpecifierSet(">=2.0", prereleases=True)`), or on a specifier inside it, is preserved in the result. That also holds when I don't replace the specifier but the original's own specifier carries such a setting: the copy must still honour it when filtering versions.
- The copy does not share mutable specifier objects with the input: its `specifier` (and the individual specifiers inside it) must be different objects from the ones I passed in or from the original's.
- Subclasses are preserved: replacing on an instance of a subclass returns an instance of that same subclass, built through the subclass's own constructor so any state its `__init__` sets and its `__str__` uses carries over (a subclass whose `__str__` appends a tag keeps the tag in the new object).
- An unknown keyword argument raises `TypeError`.
- Add a short note to the class docstring (a `versionchanged` entry) and a docstring on the method.
