I process telemetry with RxPY. Several sources emit at very different rates, and I want rounds: each round's tuple has the latest value from every source, and a new round starts only when every source has emitted again. A fast source's newer value replaces its older pending one; nothing queues up.

The design I want:

- The operator is called `zip_latest`, available three ways like the other combination operators: `reactivex.zip_latest(*sources)`, `reactivex.operators.zip_latest(*others)` for `pipe`, and the fluent `Observable.zip_latest(*others)`. Add it to the relevant `__all__` lists.
- Each emission is a tuple, in source order, of the latest pending value from each source. After a tuple is emitted, every source must emit again before the next one. With one source, emit 1-tuples: `zip_latest(of(1, 2))` gives `(1,)`, `(2,)`.
- Completion, which is where I care most:
  - When a source completes and it has a pending value that hasn't gone into a tuple yet, that value can still go into one final tuple once the other sources have caught up. The result completes right after emitting that tuple, at the same moment.
  - When a source completes with nothing pending, no further tuple is possible, so the result completes immediately, even if the other sources are still running. Equally, right after any tuple is emitted, if some source has already completed, complete then and there.
  - So with synchronous sources `of(1, 2)` and `of("a", "b")` the result is exactly `[(2, "a")]` and then completion: the first source has run to completion (its 1 replaced by 2) before the second starts.
  - An empty source makes the result complete straight away; sources after it in the list are then never subscribed to at all.
  - Never-ending sources with nothing to pair give a result that never emits and never completes.
- Errors from any source propagate immediately, and everything else is disposed. Only the first error is delivered.
- `None` is an ordinary value, not "no value yet".
- Futures are accepted as sources, like elsewhere in the library.
- Calling it with no sources at all raises `ValueError` whose message says it needs "at least one source".
- Thread-safe like the other combination operators. Docstrings with a marble diagram, and add it to the operator list in the docs.
