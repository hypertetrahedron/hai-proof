I maintain code that queries JSON documents with jsonpath-ng and I want slices and `[*]` to follow RFC 9535 for values that are not arrays. I am happy to break the old coercion; it was documented as a feature in the docstring, but I want it gone, and the docstring updated to describe the new behaviour.

The behaviour I want:

- `[*]` applied to an array matches each element, as today, with `[0]`, `[1]`, ... paths.
- `[*]` applied to an object matches each member value, in the object's order, and the match's path is the field name (so `$.o[*]` on `{"o": {"x": 1, "y": 2}}` gives 1 and 2 with full paths `o.x` and `o.y`). An empty object matches nothing.
- `[*]` applied to a scalar (number, float, string, `True`/`False`) matches nothing, and so does `None`. It must no longer wrap the value in a one-element list, so `[*]` on `1` is `[]`, not `[1]`.
- A slice with any parameter (`[0:2]`, `[1:]`, `[::-2]`, ...) matches nothing unless it is applied to an array: nothing from an object, a string or a number. On arrays it works as it does today, including steps and negative steps.
- Only lists need to work as arrays; other iterables such as `range` are not arrays, so the old test that sliced a `range` should pass a real list instead.
- So `[*].foo` on `{"foo": 1}` matches nothing, while on `{"a": {"foo": 1}, "b": {"foo": 2}}` it gives 1 and 2 with paths `a.foo` and `b.foo`.
- `$..[*]` must stop producing phantom nodes (the root object again, or a second copy of each string). It should select exactly the children of every object and array in the document: for `{"a": ["foo", "bar"]}` that is three matches, `a`, `a.[0]` and `a.[1]`, and on a scalar document it is empty. This applies to both `jsonpath_ng.parse` and `jsonpath_ng.ext.parse`. Descendant slices such as `$..[0:2]` only match inside arrays and ignore objects and scalars.
- The full path of every match must round-trip: parsing `str(match.full_path)` and finding it in the same data gives that same value.
- `update` follows `find`: `$.o[*]` with a value sets every member of the object `o`, and `$.n[*]` or `$.s[0:2]` on a scalar leaves the data unchanged. `filter` likewise: `$.o[*]` can remove object members.
- Same behaviour for `jsonpath_ng.parse` and `jsonpath_ng.ext.parse`.
