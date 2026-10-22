This is how I want `is_stale` to work:

- It is a keyword argument of `cache.cached(...)` (functions and views) and `cache.memoize(...)`, default `None`, meaning no check.
- It is a callable that is asked about a cached value after the value has been found in the cache. If it says the value is stale, the cached value is ignored, the decorated function runs again and its result is stored as usual (replacing the old one).
- It is called only on a cache hit. On a miss (nothing cached yet) it is not called at all, and it is called again on every later hit.
- If `forced_update` is also given and says to refresh, the refresh already happens and the cache isn't read, so `is_stale` is not called in that case. The two can be combined.
- The first argument is the cached value (for a cached view, the cached response). If the callable accepts only that one argument, it gets just the value. If it accepts more than one positional argument (not counting keyword-only ones), it also gets the arguments of the current call after the value: `is_stale(value, *args, **kwargs)`, so `is_stale(value, param)` for a function `f(param)` and `is_stale(value, a, b)` for `memoize` on `f(a, b)`.
- Only a result that is exactly `True` counts as stale, the same way `forced_update` works. A truthy value such as `1` or a non-empty list does not.
- When the check says the value is stale, it counts as a miss for the cache signals: a miss signal is sent for that call (for `memoize`, `cache_memoize_miss`) and the hit signal that would have fired for that lookup is not sent. A hit that is not stale sends the hit signal as it does today.
- A stale value is just recomputed: it needs no special handling for views, and it doesn't change how `unless`, `response_filter` or timeouts behave.
