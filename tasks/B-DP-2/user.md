I maintain a Python service that uses SQLAlchemy's asyncio extension against PostgreSQL (asyncpg): `create_async_engine(...)`, `async with engine.connect() as conn: ...` and `async with AsyncSession(engine) as session: ...`. The service cancels in-flight work a lot: request timeouts cancel the handler's task, and on shutdown we cancel all outstanding tasks, wait for them to finish, and then `await engine.dispose()`.

What I know about the leak:
- After shutdown some connections are never closed: we get `ResourceWarning: unclosed ...` for the driver connection and its socket.
- With `logging.getLogger("sqlalchemy.pool").setLevel(logging.DEBUG)` we can see a connection being "returned to pool" after the "Pool disposed" message, that is, after every task that used the engine had already finished.
- During normal operation the pool slowly loses capacity after bursts of cancellations, as if some slots were checked out and never returned.
- It is intermittent and depends on exactly where the cancellation lands. A simple start-and-cancel loop almost never shows it locally; production, with real network latency and many cancellations, hits it regularly.

What I want:
- Once a task that used the engine has finished, cancelled or not, every connection it used is back in the pool or closed, so `dispose()` closes everything.
- A cancellation must never leave a connection open with nothing able to close it, or a pool slot checked out permanently.
- The fix in SQLAlchemy itself, with regression tests, and the existing tests still passing.
- Cancellation should still cancel: I don't want our tasks to keep running for a long time after they are cancelled, but finishing the cleanup of a connection first is fine.
- There is no PostgreSQL server in this environment; the asyncio tests run against aiosqlite with `--dburi sqlite+aiosqlite:///:memory:`.

I don't know where in SQLAlchemy the problem is.
