We load a large data dump into attrs classes. For speed, the loader runs with validators switched off (`with attr.validators.disabled(): ...`), because the dump has already been validated upstream. Since we refactored the loader into smaller helpers, imports crash part-way through with validator errors (`TypeError` / `ValueError` from `instance_of` and our own validators) on records that were never validated before, and shouldn't be.

What we see:

- The first few records load fine, then a later record fails validation, inside the same outer `with attr.validators.disabled():` block.
- Which record fails depends on the order of the dump. It always comes right after a record whose type goes through one particular helper. That helper also uses `with attr.validators.disabled():` around its own conversion step, because it's called from other places too.
- Validation stays on after that point for the rest of the outer block.

We expected `disabled()` to restore whatever state validation was in when the block was entered, so that it can be used from library code that may or may not already be running inside a `disabled()` block. Please find the cause and fix it in attrs, with a regression test. Keep the existing tests passing.
