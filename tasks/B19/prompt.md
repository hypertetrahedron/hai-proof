Our service makes a lot of outbound connections with Tornado: HTTP calls through `SimpleAsyncHTTPClient`, raw connections through `TCPClient.connect(...)` (some with `ssl_options`), and a protocol that upgrades an existing `IOStream` with `start_tls`.

The process slowly leaks sockets. The open file descriptor count keeps growing until we hit `Too many open files`, and some of our peers complain that we leave connections open to them indefinitely. The requests themselves fail the way we expect (e.g. `HTTPTimeoutError` / 599 for a fetch); it is only the sockets behind them that are never closed.

What we have noticed:

- It correlates with timeouts and with code that gives up on a connection attempt. We set `connect_timeout` / `timeout`, and in several places we wrap connects in `asyncio.wait_for(...)` or cancel the waiting task on shutdown.
- The worst offender is a partner endpoint that accepts the TCP connection but then stalls during the TLS handshake. Every attempt against it leaves a socket behind.
- Hosts that resolve to several addresses seem to make it worse.

Please fix the library so that a connection attempt that times out, fails, or is abandoned/cancelled by the caller never leaves a socket open, whichever of these APIs it came through. Add regression tests and keep the existing tests passing.
