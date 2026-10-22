Feature request for watchdog:

We watch a directory on a network share with `PollingObserver`. When the share drops for a few seconds, the observer goes quiet and never recovers, even after the share is back, and we only notice much later. I'd like the polling observer to keep going through that kind of outage instead of giving up. I'm not sure whether it should survive every kind of failure, or what it should report along the way.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
