Our websocket gateway leaks memory under connection churn.

It holds about 450 concurrent client connections, and clients connect and disconnect all the time (mobile networks, reconnect loops). Resident memory grows by gigabytes over a day even though the number of *open* connections stays flat. A census of the live process with `gc.get_objects()` showed around 13,500 server connection objects alive while only about 450 were actually open. A forced `gc.collect()` freed roughly 1.75 GB, but it took 16 seconds. That stop-the-world pause was long enough for other clients to hit ping timeouts and disconnect, which made things worse.

So closed connections do get freed eventually, but only by the cyclic garbage collector, never by reference counting when the last reference goes away. With many connections the full collection runs far too rarely and is far too expensive.

Things we checked:
- It happens whether connections close cleanly or are aborted.
- Turning logging down or off (NullHandler, `propagate=False`, raising the level) changes nothing.
- We first saw it with the asyncio server, but a quick check suggests the threading (sync) and trio implementations behave the same way.

Please make a closed connection collectable by reference counting alone, in every implementation in the library (asyncio, sync, trio and the legacy one), and add tests that would catch this coming back. Keep the existing tests passing.
