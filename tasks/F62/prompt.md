Feature request for watchdog:

We watch a directory on a network share with `PollingObserver`. When the share drops for a few seconds, the observer goes quiet and never recovers, even after the share is back, and we only notice much later. I'd like the polling observer to handle that kind of outage properly instead of silently going quiet, but I haven't decided what "properly" means yet: failing loudly so we can restart it, or carrying on by itself.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
