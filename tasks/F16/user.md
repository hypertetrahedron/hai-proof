I ship an app whose config is a user file layered over site-wide defaults (`$XDG_CONFIG_HOME` over `$XDG_CONFIG_DIRS`). I want platformdirs to find those files for me, safely.

The design I want:

- A pair of methods for every kind that has an `iter_*_paths` method (config, data, cache, state, log, runtime): `find_<kind>_file(name)` and `find_<kind>_files(name)`, on `PlatformDirsABC`. No existing signatures change.
- `find_<kind>_file` returns the first match as a `pathlib.Path`, or `None` when there is none. `find_<kind>_files` returns a list of every match, in precedence order (empty list when none).
- Precedence is the XDG rule, the same order as `iter_*_paths`: the user directory outranks every site directory, then site directories in order. Reuse that order rather than re-deriving it, so a directory that appears twice is only searched (and listed) once.
- A match must be a regular file. A directory that happens to have the name doesn't count and is skipped.
- `name` may be a `str` or any `os.PathLike` and may contain subdirectories (`"sub/app.toml"`).
- The lookup must only read the disk. Even when the instance has `ensure_exists=True` (under which the iterators create every directory they yield), a lookup must not create any directory. And it must not flip `ensure_exists` on my instance either, not even temporarily in a way I can observe; it stays as I set it.
- A name that escapes the directory (absolute, a drive, a leading slash or backslash, `..` anywhere) raises `ValueError` through the same check and message the library uses for `appname` ("name must stay inside the base directory, got ..."). Check before touching the disk.
- Docstrings, and a short how-to section in the docs.
