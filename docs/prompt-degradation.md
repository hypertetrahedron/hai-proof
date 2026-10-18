# Prompt degradation: what happens when one piece of information is missing

Question: how much does each defect task's prompt depend on its diagnostic hints? For every defect task
(B1–B21) `prompts/degraded.md` is the original `prompt.md` with **one** piece of information removed.

Rules for writing a degraded prompt:

- Remove exactly one *diagnostic observation*: a hint that narrows where to look, such as a comparison
  that works, a traceback, or a condition under which the bug does or doesn't happen.
- Keep the observed symptom, any reproduction, and every stated requirement. The hidden tests check the
  requirements, so removing one would make the task unfair rather than harder.
- Add nothing. Only the minimum rewording needed to keep the remaining sentence grammatical, and no
  false or misleading information.
- If a prompt were so minimal that any removal left it meaningless, the task would be skipped and the
  limitation noted. None of B1–B21 needed this: every prompt had at least one removable hint. B1 (one
  symptom, a repro and expected values) comes closest; its only removable item is the note that closed
  bounds work.

How it ran: a treatment `treatments/degraded-prompt/` (manifest: `name = "degraded-prompt"`,
`prompt_variant = "degraded"`) made arm B use each task's `prompts/degraded.md`. Arm A was plain Claude Code
with the original prompt. Harness, model, CLI version, limits and host were identical, as in any A/B run:

```sh
uv run hai-proof run --treatment treatments/degraded-prompt --tasks B1,B2,...,B21 --reps 3
```

The exact removed text per task is in `docs/prompt-degradation/removed.json`.

**Outcome for the library (2026-10-10).** The degraded prompts that didn't change the result were dropped,
along with the treatment. The two that did became standalone tasks, kept separate from the standard
defect tasks:

| Task | Derived from | Prompt |
|---|---|---|
| B-DP-1 | B7 | B7's prompt without the `distributed.comm.core.connect` hint |
| B-DP-2 | B21 | B21's prompt without the "returned to pool after Pool disposed" log line |

B7 and B21 stay in the library unchanged. B19 also changed, but in the degraded prompt's favour (1/3 → 3/3,
noise), so it wasn't kept. The `prompt_variant` mechanism is still in the harness for future experiments.

## What was removed

| Task | Removed (summary) | What it told the agent |
|---|---|---|
| B1 | "Closed bounds with `clamp=True` still behave correctly." | Only the open-bound branch is wrong |
| B2 | Bug 1: "whether the bad quantity is caught depends on the other records in the batch" | The partial-load bug is per-batch state, not per-record |
| B3 | Problem 2: "a brand new `Layout` with the new numbers renders correctly" | Points at stale cached layout state |
| B4 | The list of public API functions the failures came through | Where to start (tokenizer, parser, serializer, nth, color modules) |
| B5 | The `KeyError` traceback into `dictionary.py`'s relative-string cache | The exact cache that races |
| B6 | "Index, slice and basic selectors all look fine" | Scopes the bugs to filters, functions and path output |
| B7 | The stuck coroutine was under `distributed.comm.core.connect` | Localises the hang to the connect handshake |
| B8 | The lookups "happen early in each request, before the database connection exists" | The cyclic garbage comes from lookups of missing attributes |
| B9 | "Turning logging down or off changes nothing" | Rules logging configuration out (the logger adapter itself is still a cause) |
| B10 | Raw `application/octet-stream` bodies are intact; only multipart loses a byte | Localises the bug to the multipart parser |
| B11 | Both keys survive "where the two flags have different values" | The bug depends on equal values |
| B12 | "Top-level keys reloaded the same way keep working" | The bug is in nested (dotted) key handling |
| B13 | The failing record follows one that goes through a helper which also uses `disabled()` | Nesting of `disabled()` blocks (the expectation paragraph still mentions nesting) |
| B14 | Affected plugins implement one hook twice via `@hookimpl(specname=...)` | The bug needs two implementations of one hook |
| B15 | Clients drop "while the server is still deciding", during a slow `process_request` | Where in the handshake the disconnect happens |
| B16 | "The same calls without `await` report the correct thread" | Only the async path is wrong |
| B17 | "It hangs with other test orders too" | There is more than one failure mode (the requirement still says "whatever position") |
| B18 | The `gen.with_timeout` symptom bullet | One of the hanging paths (`chain_future`); the requirement still covers it |
| B19 | The worst peer "accepts TCP but stalls during the TLS handshake" | The TLS hand-off leak paths |
| B20 | Growth stops without the index, or with a plain `Column` | Localises the leak to the index on a `MaskedColumn` |
| B21 | A connection is "returned to pool" *after* "Pool disposed" | The close carries on in the background after the task ends |

## Results

Run `20261010-085001-4eae` (2026-10-10). Setup:

- Arm A: plain Claude Code with the original prompt. Arm B: the same harness with `prompts/degraded.md`.
- 21 tasks × 3 reps per arm, 126 agent runs. Model claude-sonnet-5-5, CLI 2.1.296, host developmenthost1.
- The run took 6 h 05 min and cost $41.73.

Overall result, as graded during the run: A passed 55/63 and B passed 52/63. **After re-grading B9** with
the corrected grader (see "Harness observations" below), A passed **56/63** and B passed **55/63**. Removing one
hint made no measurable difference on 18 of the 21 tasks. The two losses (B7, B21) are both on tasks where
the cause is far from the symptom.

| Task | Pass A | Pass B | Median wall A / B (min) | Median cost A / B | Reading |
|---|---|---|---|---|---|
| B1 | 3/3 | 3/3 | 0.2 / 0.2 | $0.04 / $0.04 | No effect |
| B2 | 3/3 | 3/3 | 0.5 / 0.4 | $0.09 / $0.10 | No effect |
| B3 | 3/3 | 3/3 | 0.5 / 0.5 | $0.10 / $0.10 | No effect |
| B4 | 3/3 | 3/3 | 2.1 / 1.9 | $0.32 / $0.31 | No effect |
| B5 | 3/3 | 3/3 | 12.1 / 15.8 | $0.64 / $0.74 | Slower without the traceback (+31% wall), still solved |
| B6 | 1/3 | 1/3 | 2.6 / 2.7 | $0.50 / $0.56 | No effect. Both arms miss the same sub-bug (`test_compare_non_singular`) |
| B7 | 1/3 | 0/3 | 2.0 / 21.2 | $0.18 / $1.11 | **Strong effect.** Two B runs used all 60 turns. A is also weak on this run (two misses, one at max turns) |
| B8 | 3/3 | 3/3 | 0.7 / 0.6 | $0.08 / $0.07 | No effect |
| B9 | ~~2/3~~ 3/3 | ~~0/3~~ 3/3 | 16.7 / 13.5 | $1.40 / $1.62 | No effect. All four failures were grading artefacts; re-graded with the project's own runner, all six pass |
| B10 | 3/3 | 3/3 | 0.6 / 0.6 | $0.08 / $0.07 | No effect |
| B11 | 3/3 | 3/3 | 0.8 / 0.9 | $0.13 / $0.12 | No effect |
| B12 | 3/3 | 3/3 | 1.0 / 0.8 | $0.14 / $0.11 | No effect |
| B13 | 3/3 | 3/3 | 0.2 / 0.3 | $0.04 / $0.04 | No effect |
| B14 | 3/3 | 3/3 | 0.4 / 0.5 | $0.07 / $0.08 | No effect |
| B15 | 3/3 | 3/3 | 2.4 / 2.1 | $0.37 / $0.36 | No effect |
| B16 | 3/3 | 3/3 | 1.0 / 0.9 | $0.19 / $0.17 | No effect |
| B17 | 3/3 | 3/3 | 9.3 / 8.4 | $0.26 / $0.37 | No effect |
| B18 | 3/3 | 3/3 | 2.6 / 2.3 | $0.24 / $0.24 | No effect |
| B19 | 1/3 | 3/3 | 4.7 / 4.7 | $0.31 / $0.35 | Noise in B's favour: both A misses are the same `test_cancel` sub-bug the pilot also missed |
| B20 | 3/3 | 3/3 | 3.4 / 2.4 | $0.48 / $0.33 | No effect |
| B21 | 2/3 | 0/3 | 4.0 / 4.5 | $0.46 / $0.64 | **Likely effect.** All three B runs fail the cancellation acceptance test |

Findings:

- **Most hints were redundant.** On the 16 tasks that A always solved, B also passed every run, at about
  the same time and cost. On these tasks the symptom and the repro are enough for the model to locate the
  bug, and the extra diagnostic sentence doesn't matter.
- **Hints matter where the cause is far from the symptom.** For B7 the removed hint was the only pointer
  to `distributed.comm.core.connect`. Without it, median wall time rose from 2 to 21 min, and two runs
  used all 60 turns without finding the race in `comm/tcp.py`. For B21 the removed log line ("returned to
  pool" after "Pool disposed") is the evidence that the close continues after the task ends. Without it
  no run fixed both causes.
- **Hint removal changes the time more than the outcome on single-cause tasks.** B5 lost its traceback
  and still passed 3/3, taking 31% longer.
- **Noise is still large at 3 reps.** B19 went the other way (A 1/3, B 3/3). The two tasks with B losses
  (B7, B21) differ by one and two passes. No single task is significant (for B21, 2/3 vs 0/3 gives Fisher
  p = 0.4). The direction matches what the removed hints say, but 5–10 reps on B5, B7, B19 and B21 would
  be needed to confirm a per-task effect.

Failure classification (every failed run was inspected):

| Task | Failures | Classification |
|---|---|---|
| B6 | A×2, B×2 | Genuine: the same unfixed sub-bug (`test_compare_non_singular`) in both arms. One B run also broke `test_compile_time_recursion_error` |
| B7 | A×2, B×3 | Genuine: the hidden comm tests time out (`test_stop_listener_during_handle_stream`, `test_handshake_slow_comm`). Three runs hit max turns (A×1, B×2), and B rep2 left a broken `TCPListener` |
| B9 | A×1, B×3 | All four are **grading artefacts (verified by re-grading)**. In three (A rep1, B rep0, B rep1), hidden acceptance passed but the agent's *own* new `test_gc.py` / `test_refcount.py` failed in the regression step because of pytest's log capture (see below). In B rep2, acceptance failed on `test_close_waits_for_close_frame`, a timing flake: acceptance had no timeout factor. All six patches pass under the corrected grader |
| B19 | A×2 | Genuine: `ConnectorTest::test_cancel` not fixed (the same miss seen in the pilot) |
| B21 | A×1, B×3 | Genuine: `AsyncCancellationTest` fails. Each miss fixes only one of the two causes |

Two harness observations from this run:

- **B9 regression grades the agent's own tests under a different runner.** The regression command runs all
  of `tests/` with pytest, so new tests written by the agent are graded too. The agents wrote
  reference-counting tests that check a connection is freed once it closes, and they checked them with the
  project's own runner, `python -m unittest`. Under pytest, the logging plugin keeps every captured
  `LogRecord`. When a test path logs an exception ("connection handler failed", "keepalive ping failed"),
  the record's traceback keeps the connection's frames alive, so the agent's assertion fails.
  Checked 2026-10-10 by re-applying each of the three patches in a trial container. Results were
  deterministic across repeats:

  | Runner | Agent tests |
  |---|---|
  | pytest | Fail (6, 3 and 2 tests), with or without `WEBSOCKETS_TESTS_TIMEOUT_FACTOR=10` |
  | `pytest -p no:logging` | Pass |
  | `python -m unittest` | Pass |

  The timing factor is not the cause, contrary to the first guess. The other three B9 patches' tests pass
  under every runner.

  **Fixed 2026-10-10.** The grader gained `acceptance_cmd`, so a task can run its hidden tests with the
  project's own runner. B9 and B15 now use `python -m unittest` for both steps. B18 and B19 use
  `python -m tornado.test.runtests` for acceptance too; regression already used it, and B18's pytest-only
  conftest was removed. The websockets acceptance commands also set `WEBSOCKETS_TESTS_TIMEOUT_FACTOR=10`:
  without it, validation failed once on the reference fix (`test_keepalive` latency 1.16 ms > 1 ms).
  - Validation: all four tasks pass `validate-task` (fail at start, pass with the reference).
  - Re-grading B9: all six patches from this run pass.
  - Re-grading samples of the other three: results unchanged. B18 A/B rep0 and B15 A/B rep0 pass.
    B19 A rep0 and rep1 still fail `test_cancel`; B19 A rep2 and B rep0 still pass.

  Agent-added tests are still graded on purpose: an agent test that fails is a data point worth keeping.
