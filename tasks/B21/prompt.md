We use SQLAlchemy's asyncio extension in a service backed by PostgreSQL (asyncpg): `create_async_engine(...)`, `async with engine.connect() as conn: ...` and `async with AsyncSession(engine) as session: ...`. The service cancels in-flight work a lot: request timeouts cancel the handler's task, and on shutdown we cancel all outstanding tasks, wait for them to finish, and then call `await engine.dispose()`.

We are leaking database connections:

- After shutdown, some connections are never closed. We get `ResourceWarning: unclosed ...` for the driver connection and its socket, and with `logging.getLogger("sqlalchemy.pool").setLevel(logging.DEBUG)` we can see a connection being "returned to pool" *after* the "Pool disposed" message, i.e. after every task that used the engine had already finished.
- During normal operation the pool slowly loses capacity after bursts of cancellations, as if some slots were checked out and never returned.

It is intermittent. A simple loop that starts tasks and cancels them after a short sleep almost never shows it locally; it seems to depend on exactly where the cancellation lands, and production (real network latency, lots of cancellations) hits it regularly.

What we expect: once a task that used the engine has finished, cancelled or not, every connection it used is back in the pool or closed, so that `dispose()` closes everything. A cancellation should never leave a connection open with nothing able to close it, and should never leave a pool slot checked out permanently.

Please find the cause and fix it in SQLAlchemy, add regression tests, and keep the existing tests passing. There is no PostgreSQL server here; the asyncio tests run against aiosqlite with `--dburi sqlite+aiosqlite:///:memory:`.
