Our Django service runs on sync WSGI workers. Under load its memory climbs steadily between garbage-collection passes, and we see periodic latency spikes when the cyclic collector finally runs. We tried to find what produces the cyclic garbage:

- With `gc.disable()` and `gc.set_debug(gc.DEBUG_SAVEALL)` around a batch of requests, then `gc.collect()`, `gc.garbage` fills with exception objects, tracebacks, frames and generator objects. Thousands of each after a few hundred requests.
- The exceptions are all handled. Nothing fails, nothing is logged, and responses are correct.
- It only happens in the sync code path. Our async views don't produce this garbage.
- The garbage seems related to connection and request-local state lookups that happen early in each request, before things like the database connection exist yet. Django keeps that state in `asgiref.local.Local(thread_critical=True)`, which is why we're reporting it here.

Objects that need the cyclic collector should not be created on every lookup in a normal request path. Please find out why asgiref creates them, fix it in the library so these code paths free everything by reference counting alone, and add a test that catches it. Keep the existing tests passing.
