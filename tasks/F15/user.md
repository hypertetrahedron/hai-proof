I'm a Werkzeug maintainer. The `int` and `float` converters accept and produce things nobody intended, and I want them tightened for 3.2 without breaking existing URLs. A one-to-one mapping between URLs and values is explicitly not a goal (leading zeros, `-0`, binary float rounding all stay).

The decisions:

- Only ASCII digits. Today the regexes use `\d`, which also matches other scripts' digits such as Arabic-Indic `١٢٣`; those URLs must not match (404). Use `[0-9]`.
- `int(fixed_digits=N)`: the minus sign does not count as a digit. With `fixed_digits=4, signed=True`, `-0123` matches and gives -123, and building -123 gives `-0123`. `-123` (3 digits) does not match.
- Building (`to_url`) validates too, for both converters: a negative value when `signed` is off, a value outside `min`/`max` (inclusive bounds), and for `int` a value with more digits than `fixed_digits` all fail the build (raise `ValidationError` from the converter, which the map turns into a `BuildError`). Building 12345 with `fixed_digits=4` must fail, not produce `12345`.
- `float` overflow: a value too large for a float becomes `inf` in Python; that must not match. Underflow (tiny values becoming `0.0`) is fine and allowed.
- `float` still requires both an integer and a fractional part: `.4` and `4.` stay rejected. No scientific notation in URLs, ever.
- Building a float: `inf` and `nan` fail the build. The output must never be scientific notation, but the current `%f` approach truncates small values; use `str(value)` and only when that contains an exponent, expand it into plain digits. So 1.23 builds as `1.23`, 5.0 as `5.0`, 0.00001 as `0.00001`, 1e16 as `10000000000000000.0`, and -0.0 as `-0.0`.
- Python's int-string length limit (`sys.get_int_max_str_digits()`) still means very long ints don't match, signed or not.
- The private `NumberConverter` base class can go; I'd rather have `IntegerConverter` and `FloatConverter` stand alone, each available as before (`int`, `float`), same parameters (`fixed_digits` only for int; `min`, `max`, `signed` for both).
- Document all this in the converter docstrings with `versionchanged:: 3.2` notes, including that the URL-to-value mapping isn't unique.
