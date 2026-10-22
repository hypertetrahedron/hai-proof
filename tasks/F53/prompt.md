Feature request for filelock:

I want to record who holds a lock (a pid, a hostname, a timestamp) inside the lock file itself, and I can't find a safe moment to write it. If I write before `acquire()` I race the other processes, and if I write after `acquire()` returns, a failed write leaves me holding a lock I never finished setting up. I'd like filelock to let me pass in a callback that it runs once the lock is held, so I can write my metadata there, as part of acquiring. Please call the option `on_acquired`.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
