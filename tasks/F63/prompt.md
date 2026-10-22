Feature request for queuelib:

We sometimes need to throw away everything waiting in a queue and carry on using it, and today the only way is to pop in a loop until it returns None, which is slow on the disk-backed queues and leaves their files behind. I'd like a way to empty a queue in one call. Please name the method `clear()`.

Which queues should get it and exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
