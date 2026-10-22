Feature request for cmd2's `@with_annotated` (cmd2/annotated.py):

Two things I keep running into with `Enum` parameters.

First, my enums define the standard `_missing_` hook so they accept aliases and special keywords (`auto`, `default`, a legacy spelling), but a command-line token never reaches it: the converter only knows member values and member names, so those tokens get rejected as invalid. I'd like a way to let `_missing_` have a say.

Second, a parameter that can be one of several enums, e.g. `Color | Shade`, is refused as ambiguous. I'd like that to work.

Exactly how these should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
