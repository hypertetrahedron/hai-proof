After we added validators to our settings, a feature flag started disappearing in production, and we can't see why.

Simplified, our settings look like this (loaded from YAML in reality; the same happens when we build them in code):

```yaml
foo:
  value: true          # a feature flag, read all over the codebase
  bar:
    value: true        # a sub-feature flag
```

and at startup we register validators and run them:

```python
settings.validators.register(Validator("foo.bar.value", must_exist=True, is_type_of=bool))
settings.validators.validate()
```

Validation passes and raises nothing. But afterwards `settings.foo.value` no longer exists: reading it raises an attribute/key error, and `settings.as_dict()` doesn't contain it any more. `settings.foo.bar.value` is still fine. Before `validate()` both are there. If we remove the validator, or validate only `foo.bar` instead of the leaf, both flags survive. It also seems to depend on the data: in another service, where the two flags have different values, both keys survive. That made us suspect our own config loading for a long time.

Validation must never remove or change settings it isn't validating. Please find the cause and fix it in the library, with a regression test. Keep the existing tests passing.
