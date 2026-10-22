Feature request for platformdirs:

Writing a file such as `sub/app.toml` under the user config directory takes a manual `mkdir` every time, and getting it right is fiddlier than it looks. The XDG base directory spec has requirements about the directories you create before writing, and the obvious `Path.mkdir(parents=True, mode=...)` doesn't quite do what people expect. Other ecosystems already have a helper for this (Rust's `xdg` crate, Go's `adrg/xdg`).

Please add something to `PlatformDirs` that gives me the path for a file in a user directory with the directories on the way created properly. I care about the details here, so talk the design through with me before building it. Add tests and keep the existing suite passing.
