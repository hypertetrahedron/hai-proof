Feature request for platformdirs:

My app layers a user config file over site-wide defaults, the usual XDG arrangement. To find which `app.toml` applies I currently walk `iter_config_paths()` myself and test each candidate, and it turns out that walk has side effects in some configurations. Other libraries (pyxdg's `load_first_config` / `load_config_paths`) offer this lookup directly.

Please add a lookup like that to `PlatformDirs`. I have specific expectations about how it should behave, so work out the design with me before you implement it. Add tests and keep the existing suite passing.
