I fill in configuration documents with `set_pointer` and want it to build the path as it goes.

The design I want:

- A new keyword argument `create`, default `False`, after `inplace`: `set_pointer(doc, pointer, value, inplace=True, create=False)` and the same on `JsonPointer.set(doc, value, inplace=True, create=False)`. With the default, behaviour is exactly as today: a missing member raises `JsonPointerException` and the document is unchanged.
- With `create=True`, missing members of a dict are created as dicts. `set_pointer({}, "/cat/name", "whiskers", create=True)` gives `{"cat": {"name": "whiskers"}}`. Existing members and siblings are kept, so a second call into the same branch adds to it.
- Created intermediates are always dicts, even when the next part looks like a number or a dash: `/a/0/b` on `{}` gives `{"a": {"0": {"b": ...}}}`, never a list.
- Lists can only grow at their end. A new list element can be created by naming the end, either as `-` or as an index equal to the list's current length, and the new element is a dict when more path follows, or the value itself when it is the last part. So `/foo/-/bar` on `{"foo": []}` gives `{"foo": [{"bar": 1}]}`, and `/foo/2` on a two-element list appends the value. An index beyond the end (`/foo/5/bar` on a one-element list) is not created: it raises `JsonPointerException`.
- Nothing can be created inside a string: it raises `JsonPointerException`.
- Tuples and other immutable sequences can't grow, so creating into one raises `JsonPointerException` ("Invalid assignment target" style). That includes plain `-` on a tuple without `create`, which must raise `JsonPointerException` too, not whatever error appending to a tuple raises.
- A call that fails must leave the document completely unchanged: no half-built branch left behind. So a path that would create two dicts and then hit a bad list index leaves the document as it was.
- `inplace=False` works with `create=True` on a deep copy; the original is untouched and the new document is returned.
- The return value is the document, as before. Setting the root pointer behaves as before.
