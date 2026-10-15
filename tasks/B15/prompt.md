Our websocket servers (we run all three flavours: asyncio for the main gateway, the threading `sync` server for an admin tool, and trio for an internal service) log scary `ERROR` entries every few minutes:

```
ERROR websockets.server: unexpected internal error
Traceback (most recent call last):
  ...
```

with a traceback from deep inside the library. Our on-call alerts fire on `ERROR` logs, so this pages people for nothing.

What we've worked out:

- It happens when a client gives up while the server is still deciding whether to accept the connection. Our `process_request` hook does an authentication lookup that can take a while, and impatient mobile clients drop the TCP connection in the meantime.
- From the client's side everything is as expected: the connection fails with an `InvalidHandshake`.
- A client disconnecting during the handshake is normal and should be handled quietly, not logged as an internal error.
- We see the same thing on all three server implementations.

Please fix the library so that a peer that closes the TCP connection before the server sends its handshake response is handled quietly (no `ERROR` log, no attempt to write to the closed connection) in every server implementation, and add regression tests. Keep the existing tests passing.
