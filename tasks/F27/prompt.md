Feature request for cyclopts:

My apps load their settings from config files (I use the `cyclopts.config` sources, and the same goes for a plain `Dict`), and some of those files set a key to `null`. Today a `null` doesn't get checked against what the parameter's type is, so I can end up with `None` in a parameter that was never meant to hold it, or with a confusing error far from the cause. I'd like a config `null` to be checked against the parameter's type: a parameter whose type doesn't allow `None` should reject it with a clear conversion error, and one that does allow it should take it.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing config tests and keep the suite passing.
