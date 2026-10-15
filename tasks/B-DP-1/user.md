I run the platform team that operates our autoscaling dask cluster. The scheduler and workers are separate processes on different machines and talk over plain `tcp://`. Workers are retired constantly while computations run.

What I know about the hang:
- A few times a week a `client.retire_workers(...)`, a rebalance, or sometimes a plain `client.gather` never returns. Nothing is logged at WARNING or above, the scheduler stays responsive, CPU is idle, and killing the stuck client process lets everything carry on.
- When we dumped the stuck task with `asyncio` debugging, the waiting coroutine was somewhere under `distributed.comm.core.connect`. We couldn't work out why it never finishes. The other side seemed to have moved on.
- `distributed/tests/test_active_memory_manager.py::test_RetireWorker_stress` shows the same thing when run in a loop: once in a while it times out instead of failing an assertion.

What I want:
- The root cause fixed in distributed itself, not a workaround in our code.
- No arbitrary timeout on something that is meant to wait. Slow networks are normal for us, so a handshake or connect that legitimately takes a long time must still succeed.
- A regression test that reproduces the hang deterministically, if possible, and the existing tests still passing.
- I don't mind how big the change is, but I'd rather it be small and targeted than a refactor of the comm layer.

I don't know which module the bug is in or how to fix it.
