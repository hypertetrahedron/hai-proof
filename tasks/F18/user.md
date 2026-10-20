I maintain a test suite against flaky external services and use pytest-rerunfailures' `@pytest.mark.flaky` a lot. I want conditions that look at the actual exception.

The design I want:

- A callable `condition` that takes one argument receives the exception that caused a failed test phase, e.g. `condition=lambda error: error.status in {429, 503}`. Callables that take no arguments must keep working exactly as before. A callable whose signature takes neither zero nor one argument is an error in the condition (see below).
- A string `condition` can use the same exception through the reserved name `error`, e.g. `condition="error.status in {429, 503}"`. Its evaluation context stays as today (`os`, `sys`, `platform`, `config`, the test module's globals), but `error` always means the exception: a global called `error` in the test module must not shadow it.
- Boolean conditions are unchanged.
- Every failed phase counts, not just the call: an exception in setup or teardown is passed to the condition too, and so is a failing subtest's own exception (once per failing subtest).
- One decision per attempt: if several phases fail in the same attempt (say the call and then teardown), the test is re-run if the condition matches any of those failures.
- Each failure is evaluated at most once: a callable condition must not be called twice for the same exception.
- If the condition itself raises while being evaluated (a callable or a string), that must not crash or fail the run: emit a `UserWarning` that says the 'flaky' condition errored (reuse the existing "Error evaluating 'flaky' condition" wording) and includes the condition's exception, and do not re-run for that failure, so the test fails normally. This must stay a warning even when the user runs with `-W error` / `filterwarnings = error`.
- It must keep working with pytest-xdist (don't keep exception objects anywhere that has to cross to the controller).
- Document it in the `condition` section of the mark docs.
