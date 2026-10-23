Feature request for subliminal:

`subliminal download --name NAME` lets me give a file a different name for guessing its metadata, but it passes the same fixed name to every file. When I download subtitles for a whole folder of badly named episodes I end up writing a shell loop with one call per file. I'd like `--name` to also accept a sed-like substitution, `s/pattern/replacement/flags`, applied to each file individually, so the name is derived from the file's own path.

The exact behaviour, including the odd cases, is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
