Feature request for attrs:

I use `on_setattr` hooks to validate and normalise values, and I keep running into the same limitation: a hook only runs before the value is set, so anything I want to do afterwards (notify listeners, update a derived field, log the final state) has to go in a second mechanism. I'd like to write one hook that can do both, with code that runs before the assignment and code that runs after it, and I'm thinking a generator function is a natural way to express that.

Please add support for generator functions as `on_setattr` hooks, wherever `on_setattr` is accepted for an attribute or a class. Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing `on_setattr` tests and keep the suite passing.
