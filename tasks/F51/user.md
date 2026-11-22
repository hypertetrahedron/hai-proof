This is how I want `max_event_size` to work:

- It is a keyword argument of `client.sse(...)` on both `Client` and `AsyncClient`, and also of `EventSource(response, max_event_size=...)`. It is a number of bytes.
- The limit is on by default: if I don't pass it, events are capped at 1 MiB (1024 * 1024 bytes). Passing `max_event_size=None` turns the limit off, so an event of any size is buffered (a 2 MiB event then comes through intact). Documentation should say the default is 1 MiB.
- When an event goes over the limit, iterating the event source raises `httpx2.SSEError`. The message says "Server-sent event exceeded the N byte limit." with the configured number. Entering the `with client.sse(...)` block does not raise; the error comes while iterating.
- The size is measured in UTF-8 bytes, not characters, so 50 four-byte emoji count as 200.
- Every field line of the event counts, not only `data:` lines: `id:`, `event:`, `retry:` and a bare `data` line with no colon all use up budget, as does the field name itself. A thousand `data: chunk` lines or a thousand bare `data` lines are an oversized event. The line terminator itself is not counted. A line that is longer than the limit on its own is an error even when its blank line has arrived.
- Comment lines (starting with `:`, used as keep-alives) are not counted: a thousand `: keepalive` comments followed by one small event is fine under a small limit.
- The size is of the event in progress. The count starts again after each blank line, so many small events in a row are fine even if their total is larger than the limit, and an event that follows another event in the same network chunk is not charged for the previous one.
- A partial line counts as soon as it arrives. If the server sends `data: ` followed by a long run of bytes and never sends a newline, the stream fails once the pending bytes exceed the limit, without waiting for the line to end. The pending, not yet terminated, part of the last line is added to the lines of the same event already received, even if they came in separate chunks (60 bytes plus 60 pending bytes goes over a limit of 100).
- An event under the limit is delivered normally.
- The `SSEError` raised for the limit carries the request, so `exc.request.url` is the URL that was requested. The existing error for a wrong content type should do the same.
