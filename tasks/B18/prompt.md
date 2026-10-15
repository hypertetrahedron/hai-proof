We run a Tornado web service that mixes native `async def` code, older `@gen.coroutine` code and plain asyncio libraries. Whenever something gets cancelled, parts of the service hang forever instead of failing.

Things we have seen:

- A request handler awaits an asyncio task or future that another part of the code cancels (we cancel outstanding work on shutdown and when a downstream call is abandoned). The client never gets a response and the connection stays open until the client times out. Nothing is logged. Some of our handlers are `async def` and some are still `@gen.coroutine`, and it happens with both, including in `prepare()` of `@stream_request_body` handlers.
- A `@gen.coroutine` that yields a future which is cancelled never completes, so whatever is waiting on it hangs too. The same happens when the coroutine raises `asyncio.CancelledError` itself.
- `gen.multi([...])` over a list that contains a cancelled future never completes, and asyncio logs "Exception in callback" errors.
- `gen.with_timeout(...)` wrapping a future that is cancelled waits for the full timeout instead of reacting to the cancellation.
- When our shutdown code cancels the asyncio task that is running a request handler, the client is left hanging as well.

What we expect is asyncio's behaviour:

- `asyncio.CancelledError` coming from something that was awaited propagates like any other exception and can be caught.
- A `@gen.coroutine` that ends with `CancelledError` behaves like an `asyncio.Task` that was cancelled: its future ends up cancelled.
- `gen.multi` behaves like `asyncio.gather` (raises `CancelledError` when a child is cancelled, without cancelling its own future, and without spurious error logs).
- Anything that wraps or forwards a future that gets cancelled ends up cancelled too.
- A handler whose awaited work was cancelled gets the normal error handling for an uncaught exception: a 500 response and the usual error log.
- When the handler's own task is cancelled, the client should still get a 500 response so the connection is not left hanging. This is a deliberate shutdown, not an application error, so it should not be logged as an uncaught exception, and the task itself should still end up cancelled.

`KeyboardInterrupt` and `SystemExit` must keep propagating as they do today.

Please fix this in the library, add regression tests, and keep the existing tests passing.
