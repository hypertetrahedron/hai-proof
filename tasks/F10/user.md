I maintain a project that writes TOML config through tomlkit, and `Decimal` is the case that bit us, but I want a proper extension mechanism, not a Decimal special case.

The design I want:

- A global registry. `tomlkit.register_encoder(fn)` adds an encoder function and returns `fn` itself, so it works as a decorator (`@tomlkit.register_encoder`). `tomlkit.unregister_encoder(fn)` removes it, and does nothing if `fn` was never registered. Both are importable from the top-level `tomlkit` package (and live in `tomlkit.api` with the other helpers). I do not want a new keyword argument on `item()` or `dumps()`; the encoder has to apply everywhere tomlkit converts values, including nested ones.
- An encoder is a plain function that takes the value and returns a tomlkit item, for example `tomlkit.float_(str(value))` for a `Decimal`. If the encoder doesn't handle that value, it declines by raising `TypeError`, and tomlkit then tries the next registered encoder. Encoders only run for values tomlkit can't convert itself, so they can't change how built-in types are written.
- If no encoder handles a value, `tomlkit.item()` raises `TypeError`. Today it raises `ValueError` and some callers may catch that, so I'd accept an error that is both a `TypeError` and a `ValueError`, to stay compatible.
- If an encoder returns something that is not a tomlkit item, that is an error too, the same kind as above, and not silently accepted.
- `tomlkit.dumps()` has to use the registered encoders too, e.g. `tomlkit.dumps({"foo": Decimal("1.23")})` gives `foo = 1.23\n`.

Tests should cover the Decimal case through both `item()` and `dumps()`, the TypeError for an unsupported object, and unregistering. Make sure tests that register an encoder clean it up so they don't leak into other tests.
