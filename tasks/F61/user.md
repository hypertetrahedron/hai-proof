I want to partially evaluate a marker against an environment I only partly know, and get back a simpler marker for the rest, instead of a yes or no.

The design I want:

- A method `apply(environment)` on every marker class (`AnyMarker`, `EmptyMarker`, single markers, `MultiMarker`, `MarkerUnion`, and the compact extra forms), taking a mapping of variable name to value, like the one `validate` takes.
- It returns a marker, never a bool.
- A single marker whose variable is in the environment is checked the way `validate` checks it, and is replaced by `AnyMarker` if it holds or `EmptyMarker` if it doesn't. For example `python_version >= '3.8'` with `python_version` `3.10` becomes the any marker, and with `3.7` becomes the empty marker.
- A variable that is not in the environment is kept as it is, unlike `validate`, which treats a missing variable as satisfied. `os_name == 'foo'` with an environment that only has `sys_platform` comes back as `os_name == 'foo'`.
- `AnyMarker` and `EmptyMarker` come back unchanged whatever the environment is.
- An empty environment returns the marker itself, unchanged.
- Composite markers are simplified as usual once their parts are applied. With `python_version >= '3.8' and sys_platform == 'linux'` and only `python_version` 3.10 known, the result is `sys_platform == 'linux'`. If one part of an "and" is false the whole thing is the empty marker. With an "or", a true part makes the whole thing the any marker, and a false part just drops out, leaving the other branch. Nested combinations work the same way, for example `(python_version >= '3.8' or sys_platform == 'win32') and extra == 'foo'` with `python_version` 3.7 gives `sys_platform == 'win32' and extra == 'foo'`.
- `extra` is different from the other variables: its value in the environment is a collection of the extras that are selected, such as `("a",)`, not a single string. `extra == 'a'` holds if `a` is in the collection. With an empty collection, `extra == 'a'` becomes the empty marker and `extra != 'a'` becomes the any marker. If `extra` is not in the environment at all, extra markers are kept like any other missing variable.
- The compact extra forms behave the same: `extra != 'a' and extra != 'b'` with extras `("c",)` becomes the any marker and with `("a",)` the empty marker; `extra == 'a' or extra == 'b'` with `("a",)` becomes the any marker and with `("c",)` the empty marker; with no `extra` in the environment they are kept as they are.
- Document it in the docstring of the base class method.
