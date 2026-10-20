I write CLI tools that keep config, caches and sockets in the user's directories, and I want platformdirs to do the "make the directories, give me the path" step safely, the way the XDG spec says.

The design I want:

- Six methods on `PlatformDirsABC` (so every platform gets them): `place_config_file`, `place_data_file`, `place_cache_file`, `place_state_file`, `place_log_file` and `place_runtime_file`. Each takes a relative file name (a `str` or any `os.PathLike`, may contain subdirectories such as `"sub/app.toml"`) and returns a `pathlib.Path` under the matching `user_*_dir`.
- It creates the missing directories on the way, including the user directory itself, but never the file. I write the file myself.
- Every directory it creates gets mode `0o700`, each level, not just the last one. (`Path.mkdir(parents=True, mode=0o700)` only applies the mode to the last directory; intermediates get the default.) The process umask still applies on top, that's fine.
- Directories that already exist are left alone: never chmod them.
- This happens whether or not the instance has `ensure_exists=True`. Careful: with `ensure_exists=True`, merely reading `user_config_dir` creates the directory with the default mode, which would defeat the point; the result must not depend on that flag.
- Bad names raise `ValueError` and create nothing at all:
  - a name that is absolute, has a drive, starts with a slash or backslash, or climbs out with `..` (also `..\` and nested ones like `sub/../../evil`): use the same check and message the library already uses for `appname`, i.e. `name must stay inside the base directory, got '<name>'`;
  - an empty name or `"."`, which don't name a file: `name must point to a file, got '<name>'`.
- If the home directory is unknown (the user directory comes back starting with `~`), raise the same `RuntimeError` the library already raises for that under `ensure_exists` ("could not determine the home directory, refusing to create '~/...'"), and create nothing. Never create a literal `~` directory.
- `place_runtime_file` should simply let the existing `PermissionError` from the Unix temporary runtime-dir owner check propagate; document it.
- Docstrings on the methods, and a short how-to section in the docs.
