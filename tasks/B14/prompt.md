Our application hot-reloads plugins: on reload it calls `pm.unregister(old_plugin)` and then `pm.register(new_plugin)` on a pluggy `PluginManager`. After a reload, some hooks return results from both the old and the new version of a plugin, as if the old one were still loaded, and after several reloads the stale results pile up. Restarting the process clears it.

It only happens for some plugins. The affected ones implement the same hook more than once, using `@hookimpl(specname=...)` to register a second method for a hook they already implement. Plugins with one implementation per hook reload cleanly.

While debugging we also noticed that `pm.get_hookcallers(plugin)` lists the same hook caller twice for those plugins, which our admin page shows as duplicate rows.

After `unregister(plugin)`, none of that plugin's implementations should run any more, and `get_hookcallers(plugin)` should list each hook once. Please find the cause and fix it in pluggy, with regression tests. Keep the existing tests passing.
