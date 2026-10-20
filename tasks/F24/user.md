I want `click.style()` (and `secho()`) to treat `fg` and `bg` consistently. The rules I want:

- `None` (the default) means no colour, as now.
- A palette index of `0` (black in the 256-colour palette) is a real colour and must be honoured for both `fg` and `bg`; today it is dropped because the code tests truthiness.
- Valid colours are exactly these: one of the existing colour names (the eight basic names, the `bright_` variants and `reset`); an integer palette index from 0 to 255 inclusive; or an RGB triple of exactly three integers, each 0 to 255 inclusive, given either as a tuple or as a list.
- Colour names are case-sensitive: `"BLACK"` is not valid. The empty string and unknown names are not valid.
- `True` and `False` are not valid colours even though bools are ints in Python, so they must not turn into palette indices 1 and 0.
- Anything else is invalid: integers below 0 or above 255, floats, bytes, empty or wrong-length tuples and lists, RGB components that are not ints (strings, floats, bools) or are out of range.
- Every invalid colour, for `fg` and for `bg`, raises `ValueError`. Today some of these raise `TypeError` and some are ignored; I want one exception type for all of them. The message should say the colour is unknown and show the offending value.
- The escape codes for valid colours stay as they are: `fg=0` gives `\x1b[38;5;0m`, `bg=0` gives `\x1b[48;5;0m`, an RGB triple gives `\x1b[38;2;r;g;bm` (48 for `bg`), a name keeps its existing code.
- Document the change in the `style()` docstring with a versionchanged note, and add a changelog line.
