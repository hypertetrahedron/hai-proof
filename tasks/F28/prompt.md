Feature request for httpx2:

I consume server-sent events with `client.sse(url)`, and an event is buffered until its terminating blank line arrives. A misbehaving or hostile server can keep sending data without ever finishing an event, and my process just keeps growing. I'd like a way to cap how much gets buffered for one event, as an argument to `sse()` called `max_event_size`, on both `Client` and `AsyncClient`, and I'd like the stream to fail with `SSEError` when the cap is exceeded.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing SSE tests and keep the suite passing.
