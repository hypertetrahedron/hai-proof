Feature request for python-json-pointer:

I use `set_pointer` to fill in configuration documents, and it fails whenever part of the path doesn't exist yet: setting `/cat/name` on an empty dict raises, so I have to create each level by hand first. I'd like an option to make `set_pointer` (and `JsonPointer.set`, which it wraps) create the missing parts of the path for me, called `create`.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing set tests and keep the suite passing.
