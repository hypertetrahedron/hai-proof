I want `Property.to_json()` to return a JSON string of the property settings, and `Property.from_json(data)` to be a classmethod that builds a new `Property` from one. A round trip must give a property with the same `as_dict()` and a fresh handle of its own (not the old handle), and it must work as `Index(properties=...)`.

How I want the odd cases to behave:

- The two callback keys, `custom_storage_callbacks` and `custom_storage_callbacks_size`, are left out of `to_json()`. They are process-local pointers and mean nothing in another process. Every other property key is included.
- `from_json` only accepts known property keys. An unknown key raises `ValueError`, and `handle` counts as unknown: it is not something a JSON document may set. The two callback keys are not accepted either.
- If the JSON is valid but not an object (a list, a number, a string), `from_json` raises `TypeError`, not `ValueError`.
- There is already a constant in `rtree.index`, `INDEX_JSON_SERIALIZATION_LIMIT_SIZE` (1024), that I want used as the size limit for this JSON. It counts UTF-8 bytes, not characters, so a string of 600 two-byte characters is over it.
- `from_json` checks the size before it parses anything, and does so for `str` and for `bytes` input alike. Over the limit raises `ValueError`. Exactly 1024 bytes is allowed; 1025 is not.
- `to_json` enforces the same limit: if the encoded result would be over 1024 bytes it raises `ValueError` rather than return something `from_json` would refuse.
- `from_json` accepts `bytes` as well as `str`.
