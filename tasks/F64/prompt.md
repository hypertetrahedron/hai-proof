Feature request for gunicorn:

We run gunicorn with `--reload` and list the files that should also trigger a restart with `--reload-extra-file` (`reload_extra_files` in the config). That works for a handful of named files, but our templates and JSON specs live in directories that change all the time, and listing every file by hand is not workable. I'd like to be able to give glob patterns there instead of only exact file paths.

Exactly how it should behave, including the odd cases, is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
