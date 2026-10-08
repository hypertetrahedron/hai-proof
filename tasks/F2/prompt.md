It would be really useful to be able to say that a list field must not contain repeats. Today we hand-roll a `validate=` function for every "tags" / "ids" / "emails" list, and each one gets the unhashable-items case wrong (a list of nested objects blows up on `set()`).

Desired usage:

```python
from marshmallow import Schema, fields, validate

class ArticleSchema(Schema):
    tags = fields.List(fields.String(), unique=True)

ArticleSchema().load({"tags": ["a", "b", "a"]})
# ValidationError: {'tags': ['Items must be unique.']}

ArticleSchema().load({"tags": ["a", "b"]})
# {'tags': ['a', 'b']}
```

Please also expose the check on its own as a validator so it can be used with any field that produces a collection, e.g. `fields.Raw(validate=validate.Unique())` or `validate.Unique(error="no repeats")`.

Behaviour I'd expect:

- `unique` defaults to `False`; existing lists behave exactly as before. Dumping is never affected.
- Duplicates are judged by equality of the *deserialized* items, not the raw input, so `fields.List(fields.Int(), unique=True)` rejects `[1, "1"]`.
- Items don't have to be hashable: `fields.List(fields.Nested(PointSchema), unique=True)` must work and reject two equal nested dicts.
- Empty and single-item lists are fine.
- The error is a field-level error on the list (a list of messages, like other validators). The default message is `"Items must be unique."`. It should be customisable the way other fields do it, with `error_messages={"duplicate": "..."}` on the field, and `error=` on the validator.
- If individual items fail to deserialize, report only those item errors (no extra duplicate error on top).
- It should combine with other validators on the same field: if `validate=` validators also fail, all the messages are reported together, the way `fields.Url` and `fields.Email` do it.
- Works inside `many=True` schemas with the usual error indexing.
