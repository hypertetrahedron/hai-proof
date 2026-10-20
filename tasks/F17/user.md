I maintain a service that locks its dependencies with PDM's `exclude-newer`. I need per-package exceptions to that cutoff.

The design I want:

- In pyproject: a table `[tool.pdm.resolution.exclude-newer-override]` mapping package name to a value, next to the existing `exclude-newer` key.
- On the command line: `pdm lock --exclude-newer-override PACKAGE=DATE`. It takes one or more `PACKAGE=DATE` values per flag (`nargs="+"`), and the flag can also be repeated; all values accumulate.
- A value is a cutoff in the same formats `exclude-newer` already accepts (a date/datetime, or a relative time like `3d`), and it replaces the global cutoff for that package, in either direction: later (let a newer release in) or earlier (hold it further back).
- To remove the cutoff entirely for one package, the value is `false`: TOML `false` in the table, the string `false` on the CLI. Not `0`: `0` (and `1`, `true`, a list, or any other non-date) is invalid and must make `pdm lock` fail with a usage error that mentions the `exclude-newer-override` setting; an invalid CLI value fails with an argument error mentioning exclude-newer.
- Package names are normalized, so `Zipp` in the table applies to `zipp`.
- An override works even when there is no global `exclude-newer` at all (it then only restricts that one package).
- CLI and pyproject combine per package: the CLI value wins for a package present in both, and packages in only one of them keep their value.
- Overrides alone count as "exclude-newer is set" for the existing rule that forces `--update-all` when locking with a cutoff.
- The uv resolver must get the same overrides, as `--exclude-newer-package PACKAGE=<isoformat or false>` arguments after the global `--exclude-newer`.
- Document it in the lockfile docs.
