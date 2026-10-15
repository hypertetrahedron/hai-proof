Our service re-reads a few settings on every request so that ops can change them without a restart. Shortly after start-up those settings start reading as missing.

Settings live in a `settings.toml` loaded through `LazySettings`/`Dynaconf`, e.g.

```toml
[foo]
bar = "baz"
```

and each request reads a nested value with a reload, for example `settings.get("foo.bar", fresh=True)` (in other places `settings.get_fresh("foo.bar")`).

The first read returns `"baz"`. Every read after that returns `None` (or the `default=` we pass), even though the file hasn't changed. Worse, once this has happened, *ordinary* reads of the same nested value elsewhere in the process start returning the default too, so the damage spreads beyond the code doing the reloads. Top-level keys reloaded the same way keep working, and restarting the process "fixes" it until the next reload.

We need nested values to be reloadable any number of times, and a reload must pick up a changed file. Please find the cause and fix it in the library, with a regression test. Keep the existing tests passing.
