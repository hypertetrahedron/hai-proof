I stamp holder metadata (pid, hostname, timestamp) into the lock file and want that to be part of acquiring, not a separate step afterwards.

The design I want:

- A new constructor option `on_acquired` on the lock classes, default `None`, and a read-only `on_acquired` property on the lock that returns exactly the callable that was passed (or `None`).
- The callback is called with one argument: the integer file descriptor of the locked lock file. I will read, write, seek and truncate through it with `os`; filelock keeps ownership, so I must not close or unlock it, and filelock doesn't need to fsync for me. It is a plain synchronous callable; coroutines are not supported.
- It runs while the lock is held (`lock.is_locked` is already true inside the callback) and before `acquire()` returns to the caller.
- It runs after filelock has finished its own setup of the file: any old content has already been truncated away (the callback sees size 0 on a file that had stale content) and the `mode` has already been applied. So what I write in the callback is what stays in the file.
- It runs once per physical acquisition. A recursive `acquire()` on a lock I already hold does not call it again, and a process that loses the race (its `acquire(timeout=...)` ends in `Timeout`) never calls it and must not truncate or otherwise disturb the file the holder has written to.
- If my callback raises, the acquisition is rolled back: the lock is released, `is_locked` is false, `lock_counter` is 0, another lock object can take the same path immediately, and the exception I raised comes out of `acquire()` unchanged (same type and message), not wrapped.
- `SoftFileLock` (and `AsyncSoftFileLock`) can't support it, because its marker file holds filelock's own protocol state. Passing `on_acquired` to them raises `ValueError` at construction. Only the native locks accept it.
- With `is_singleton=True`, asking for the same path again with the same callback object returns the same instance; asking with a different callback object raises `ValueError` ("differing arguments"). Callbacks are compared by identity, not equality, because two equal callables can close over different state.
- `AsyncFileLock` takes the same option and the same plain synchronous callable. It runs inside the lock's existing worker thread for the blocking acquire, so it executes off the event-loop thread, while the lock is held and before `await lock.acquire()` returns. If it raises, the async lock is released and not locked (`lock_counter` 0), and the exception propagates from `await lock.acquire()`.
