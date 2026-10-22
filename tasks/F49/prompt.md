Feature request for pytest:

I write pytest plugins, and registering ini options with `Parser.addini(name, help, type="int")` and friends means picking from a list of string tags that I have to look up each time, and nothing lets me say that an option can be either a number or a word, or that it only accepts a few fixed strings. I'd like `addini`'s `type=` to accept real Python type expressions instead: the plain types such as `int`, a union such as `int | str`, and a `Literal` of strings such as `Literal["auto", "long"]`, with `config.getini()` returning a value that matches.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing `addini` tests and keep the suite passing.
