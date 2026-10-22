I want to empty a queue in one call and keep using it afterwards, instead of popping until `None` and leaving disk files behind. The method is `clear()`.

The design I want, starting with which queues get it:

- Every queue type gets `clear()`, not just some: the four leaf queues (the memory queues, `FifoDiskQueue` and `LifoDiskQueue`, and the SQLite queues) and also `PriorityQueue` and `RoundRobinQueue`. Everything below follows from that.
- After `clear()` the queue is empty (`len` is 0, `peek()` and `pop()` give `None`) and still open. Pushing and popping work as before, and calling `clear()` on an already empty queue is fine.
- `FifoDiskQueue`: the chunk files are deleted so the space is freed, and exactly one is left, `q00000`. The size, head and tail counters are reset as if the queue were new, and the queue stays usable (push, pop, then `close()` as usual).
- `LifoDiskQueue`: the file is truncated to an empty queue rather than deleted, and the queue stays usable.
- `PriorityQueue` and `RoundRobinQueue`: clear each inner queue, then close it, exactly as `pop()` does when an inner queue becomes empty, and drop all the inner queues. Also reset the bookkeeping: `curprio` goes back to `None` for the priority queue, and the key queue is emptied for the round-robin queue. Pushing afterwards creates fresh inner queues and works normally, and `close()` after a `clear()` returns nothing active and leaves nothing behind.
- An inner queue that has no `clear()` of its own, because it only implements `push`, `pop`, `peek`, `close` and `__len__`, must still work: the composite empties it by popping until it returns `None`, then closes it like the others.
- Mention `clear()` in the README, and note the two docstrings of the composite queues that inner queues may implement it.
