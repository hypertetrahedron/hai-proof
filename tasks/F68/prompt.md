Feature request for rtree:

We keep our index settings in a config store and rebuild indexes from them at startup. `rtree.index.Property` already pickles, but we would like a plain JSON form instead: I'd like to serialise an index's `Property` to JSON and read it back, with methods named `to_json` and `from_json`, so that a stored string can be turned into a `Property` we can pass to `Index(properties=...)`.

Exactly how it should behave, including the odd cases, is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
