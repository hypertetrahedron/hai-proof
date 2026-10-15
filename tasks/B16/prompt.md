We add callsite information to every log entry with `structlog.processors.CallsiteParameterAdder`, including `CallsiteParameter.THREAD` and `CallsiteParameter.THREAD_NAME`, so we can match log lines to the thread that produced them.

In our async services the thread fields are useless. Every entry logged with the async methods (`await log.ainfo(...)`, `await log.awarning(...)`, ...) reports some worker thread, `asyncio_0`, `asyncio_1` and so on, with its id, instead of the thread that actually made the call (usually `MainThread`). The other callsite fields (function name, line number, module) look right. The same calls without `await` (`log.info(...)`) report the correct thread.

We see this both with structlog's own bound loggers (`structlog.make_filtering_bound_logger(...)`) and with the stdlib integration (`structlog.stdlib.BoundLogger` and `structlog.stdlib.AsyncBoundLogger`).

Please fix it so that callsite thread information always describes the caller, for every logger flavour that has async log methods, and add regression tests. Keep the existing tests passing.
