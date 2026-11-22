Bug report / feature request for bidict:

Mutating an `OrderedBidict` while iterating over it goes wrong, and goes wrong differently depending on what you do. Adding an item inside a `for key in ob:` loop can loop forever, calling `clear()` blows up with a confusing error, and deleting an item quietly skips others. A plain `dict` or `OrderedDict` doesn't behave like this: it notices and fails loudly. I'd like ordered bidicts to do the same, so these bugs show up immediately instead of corrupting a loop.

Exactly what should count as a mutation, and what should happen in the less obvious cases, is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
