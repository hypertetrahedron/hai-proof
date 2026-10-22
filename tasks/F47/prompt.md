Feature request for click:

`click.style()` (and so `secho()`) is inconsistent about the colour values it accepts for `fg` and `bg`. Passing the 256-colour palette index for black seems to do nothing at all, some bad values raise one kind of exception, and others seem to be silently ignored or to produce garbage escape codes. I'd like colour handling in `style()` to be dependable: valid colours always produce the right escape code, and invalid ones fail loudly instead of quietly misbehaving.

Exactly what counts as valid and what should happen otherwise is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing `style()` tests and keep the suite passing.
