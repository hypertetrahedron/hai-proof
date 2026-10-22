Feature request for RxPY:

I have several sources that emit at very different rates (a fast sensor feed, a slow configuration stream, and so on), and I want to process them in rounds: one tuple per round, holding the most recent value from each source, emitted once every source has produced something new since the last tuple. `zip` queues up every value from the fast source and falls further and further behind; `combine_latest` emits on every single change and reuses stale values. I want something in between, where a fast source's newer value simply replaces its older pending one.

Please add this as a new operator. Its exact behaviour is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing operator tests and keep the suite passing.
