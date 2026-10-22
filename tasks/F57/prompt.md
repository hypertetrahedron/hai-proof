Feature request for Flask-Caching:

I cache expensive objects with `@cache.memoize` and also cache whole views with `@cache.cached`, and sometimes a cached value turns out to be out of date, but only by looking at the value itself (for instance when something it was built from has changed since). The existing `forced_update` hook can't help, since it has to decide before the cache is read and never sees the cached value. I'd like a way to say, per decorated function, that a cached value should be thrown away and recomputed when a check on that value says it's stale, as a new argument to both `cached` and `memoize` called `is_stale`.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing tests for `forced_update` and keep the suite passing.
