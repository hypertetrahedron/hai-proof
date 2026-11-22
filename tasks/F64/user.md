I want `--reload-extra-file` / `reload_extra_files` to accept glob patterns as well as plain file paths, so that I can watch a whole directory of templates or specs with one entry. Plain paths keep working exactly as today.

If globs are supported, this is how I want them to behave:

- Patterns are expanded every time the reloader checks for changes, not once at startup. A file created after gunicorn started and matching the pattern must be watched from then on, without a restart. (The first edit to that file triggers the reload, not its creation; that is fine.)
- The config value keeps the pattern exactly as I wrote it. `reload_extra_files` must hold the unexpanded pattern, alongside any plain paths, in the order given. Do not replace it with the list of matches at validation time.
- Plain paths are still validated as today: a path that does not exist is a `ValueError`.
- A pattern that matches no files right now is not an error, because files may appear later. It must give a `RuntimeWarning` (stdlib `warnings`) and still be kept in the setting.
- `**` recurses into subdirectories, so `views/**/config.json` finds the file at any depth.
- `*` does not match dotfiles, the normal glob behaviour. I will list `.env` literally if I need it. Don't add special handling.
- What counts as a pattern: any entry containing `*`, `?` or `[`. So a literal path that happens to contain one of those characters is read as a pattern, not as a path: it warns if nothing matches instead of failing as a missing plain path would.
- Patterns are relative to the directory gunicorn was started from, not to `chdir`, which is applied later. No special handling for `chdir`.
- Mention the feature in the setting's description in the docs.
