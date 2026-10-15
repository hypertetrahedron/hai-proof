Our CI runs the test suite with `pytest -n auto --dist=loadgroup` (we group a few tests with `@pytest.mark.xdist_group`). Some of our tests exercise native extensions, and occasionally one of them takes the whole worker process down (segfault, or `os._exit` in a misbehaving fixture).

When that happens, xdist prints `replacing crashed worker gw0` and starts a replacement worker, as expected. But then the run never finishes: no more progress, no summary, and CI kills the job at its timeout. We lose the report of which test crashed.

It does not depend on the machine: it reproduces with a single worker and a two-test file in which one test kills its worker:

```python
import os

def test_a():
    pass

def test_b():
    os._exit(1)
```

```
pytest -n1 --dist=loadgroup test_crash.py
```

It hangs with other test orders too, not only this one. With `--dist=load` and the other distribution modes the same crash is reported and the run finishes normally.

Please fix it so that a run with `--dist=loadgroup` (and `--dist=loadscope`, which shares the scheduler) always finishes after a worker crashes and is replaced, reporting the crash as a failure, whatever position the crashing test has. Add regression tests and keep the existing tests passing.
