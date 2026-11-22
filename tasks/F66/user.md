I want callable `choices` on the select fields (`SelectField`, `SelectMultipleField`, `RadioField`) and the callable on a `DataList` to be lazy. Same two callable shapes as today: `fn(form, field)` or a zero-argument `fn()`. These are the rules I want, case by case.

When it runs and how long it lives:
- The callable is not called when the form is constructed or processed, and not inside `post_process`. It is called the first time the field's `choices` are read: reading `field.choices`, rendering the field, or validating when there is submitted data to check against.
- The result is cached. Reading `choices`, rendering and validating again all reuse it; the callable runs once.
- Calling `post_process` again on the form (after I change some field data, passing the same formdata) throws the cache away, so the next read calls the callable again and sees the new data. Until that rerun, the cached value stays, even if the other fields' data changed.
- Validating a `SelectMultipleField` with no submitted data does not call the callable at all.
- If a form object is used without having been processed at all (a plain `BaseForm`), reading `choices` still calls the callable once; a later `process()` makes it refresh.
- A callable that reads its own `field.choices` must not recurse. It gets the previous value, which is `None` the first time, so `[*(field.choices or []), "x"]` yields `["x"]`.
- `post_process` on each field, including nested ones, still runs exactly once per processing cycle.

Assigning `choices` yourself:
- Assigning a list (or dict) replaces the constructor callable. It stays assigned, and a `post_process` rerun does not bring the callable back or overwrite it.
- Assigning `None` drops the callable. `choices` is `None` afterwards, also after a `post_process` rerun.
- Assigning a new callable replaces the old one and is lazy and cached in the same way: not called at assignment, called once on first read, and refreshed after the next `post_process`.

Nested forms:
- Rerunning `post_process` on the root form refreshes the callable choices of fields inside a `FormField` and inside every `FieldList` entry, so each of them sees the new data (for instance a callable reading `form._parent_form.tenant.data`).
- Entries added with `append_entry` / `insert_entry` still get working choices when they render.

Subclasses:
- A custom field subclass whose `__init__` calls `super().__init__(...)` and then extends the choices, e.g. `self.choices = [SelectChoice("", "---"), *(self.choices or [])]`, must keep working: that read resolves the callable once, and the resulting field validates and renders the callable's options after the blank one.

DataList:
- Same rule. The callable is not called at construction or in `post_process`. It runs the first time the datalist is rendered, and the result is cached across further renders. A `post_process` rerun refreshes it, so the next render calls it again with the new field value.
- A zero-argument callable is lazy and cached too: not called until the first render, called once across several renders.

Please also update the documentation of `choices` and `DataList` to describe the lazy behaviour.
