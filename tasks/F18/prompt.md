Feature request for pytest-rerunfailures:

The `condition` argument of `@pytest.mark.flaky` decides whether a failing test is re-run, but it can't see what actually went wrong. I often want to re-run only for particular failures based on the exception's attributes, for example an HTTP error whose `status` is 429 or 503, and not for others of the same type. `only_rerun` matches on type or message, which isn't enough.

Please let a `condition` decide based on the exception that caused the failure. There are a few ways this could work and some corner cases I care about, so go through the design with me before building it. Add tests and keep the existing suite passing.
