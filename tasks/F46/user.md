I use attrs `on_setattr` hooks and want one hook to run code both before and after an attribute is set. The design I want:

- A generator function can be used as an `on_setattr` hook, anywhere a normal hook is accepted: per attribute (`attr.ib`/`attrs.field`) and class-level (`attr.s`/`attrs.define`). It has the same signature as a normal hook, `(instance, attribute, value)`.
- The value the hook yields is the value that gets set on the instance, the same role a normal hook's return value plays. If it yields the incoming value unchanged, the value is set as is.
- The code before the `yield` runs before the assignment, so `instance.x` still holds the old value there. The code after the `yield` runs after the assignment, so `instance.x` already holds the new value there.
- Like normal hooks, it does not run during `__init__`, only on later assignments.
- If the generator raises before it yields, the attribute is not set and keeps its old value; the exception propagates. If it raises after it yields, the new value stays set and the exception propagates.
- It must yield exactly once. If it yields a second time, the first yielded value is still set, the generator is closed (so its `finally` blocks run) and a `RuntimeError` is raised.
- Plain (non-generator) hooks keep working exactly as before.
- Generators do not have to work inside `attrs.setters.pipe(...)`; I don't need that, but please mention it in the `pipe` docs.
- Document it in the `on_setattr` docstrings and add a versionchanged note.
