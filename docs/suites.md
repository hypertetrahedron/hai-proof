# The standard and interview suites

What each task in the two main suites asks for, what the real cause or upstream design is, how it is graded, its
limits, and how plain Claude Code does on it. It is a reference for reading a report; the history of how each task
was found, built and calibrated is in [task-catalog.md](task-catalog.md), how to write one is in
[task-authoring.md](task-authoring.md), and how a run uses them is in [how-arms-run.md](how-arms-run.md).

A task's suites are listed in its `task.toml` (`suites`). `run --suite NAME` selects them; `standard` is the default.

| Suite | Tasks | Run with |
|---|---|---|
| `standard` | B17, B20, B7, B19, B21, F3, B5, F6, B6, F7, B9, F4, F5 (13, report order) | `--suite standard` (default) |
| `interview` | F52, F42, F54, F45, F56, F49, F41, F43, F53, F50, then F58, F59, F65 (13, report order) | `--suite interview --user reticent --ask-tool on` |

The other suites are `smoke` (B1, B13, F1), `diagnosis` (B-DP-1, B-DP-2), `interview-smoke` (F12), and the
superseded `interview-v1` (F13, F14, F15, F20, F26, F27, F29, F30, F31, F33) and `interview-v2-candidates`. They
are described in [task-catalog.md#suites](task-catalog.md#suites).

**Grading in brief.** After the agent exits, the hidden tests are copied in and two steps run offline: acceptance
(the task's `acceptance` pytest ids, or its `acceptance_cmd`) and regression (the task's `regression` command,
default `python -m pytest -q -p no:cacheprovider` over the whole repo, with the acceptance files ignored). A trial
succeeds when both pass. Tests the agent wrote run in the regression step too.

**Calibration figures** are for the plain arm on `claude-sonnet-5-5`. *Plain pass* for the standard suite is from the
`baseline.json` backfill behind the cost tiers (task-catalog.md, "Cost tiers and report order"); *wall* is the
pilot median from the catalog's Built tasks table. Median output tokens and cost are from the tier table.

## Standard suite

One task per project, chosen 2026-10-10 to show **large** effects between arms. Tasks with mixed plain pass rates
(B6, B7, B19, B21, F7) carry the success signal. Steady multi-minute tasks (B5, B9, B17, F4, F5) carry the time and
cost signal. Together they cover 2–27 minutes per run, about $12 and 1.9 h per arm per rep. Level sets the limits,
not the difficulty: `--mode quick` drops the level-3 tasks (F3, B5, F6, F7, B9, F4, F5).

| Order | Task | Kind · level | Tier | Project | Limits (s / $ / turns) | Plain pass | Wall, median | Output tokens | Cost |
|---|---|---|---|---|---|---|---|---|---|
| 1 | B17 | bug · L2 | low | pytest-xdist | 2400 / 5 / 60 | 8/8 | 442 s | 9.0k | $0.29 |
| 2 | B20 | bug · L1 | low | astropy | 1200 / 3 / 40 | 11/11 | 126 s | 10.4k | $0.30 |
| 3 | B7 | bug · L2 | low | dask/distributed | 2400 / 5 / 60 | 4/10 | 174 s | 13.2k | $0.39 |
| 4 | B19 | bug · L2 | low | tornado | 2400 / 5 / 60 | 4/8 | 532 s | 12.8k | $0.36 |
| 5 | B21 | bug · L2 | low | SQLAlchemy | 2400 / 5 / 60 | 6/11 | 276 s | 14.7k | $0.45 |
| 6 | F3 | feature · L3 | low | rich | 2400 / 8 / 80 | 8/8 | 161 s | 18.9k | $0.43 |
| 7 | B5 | bug · L3 | medium | dateparser | 3600 / 40 / 300 | 11/11 | 485 s | 19.0k | $0.57 |
| 8 | F6 | feature · L3 | medium | lark | 3600 / 40 / 300 | 8/8 | 230 s | 22.8k | $0.54 |
| 9 | B6 | bug · L2 | medium | python-jsonpath-rfc9535 | 2400 / 5 / 60 | 3/8 | 212 s | 23.2k | $0.60 |
| 10 | F7 | feature · L3 | high | sqlglot | 3600 / 40 / 300 | 5/8 | 1072 s | 46.3k | $1.04 |
| 11 | B9 | bug · L3 | high | websockets | 3600 / 40 / 300 | 7/8 | 829 s | 47.2k | $1.40 |
| 12 | F4 | feature · L3 | high | Jinja2 | 3600 / 40 / 300 | 8/8 | 520 s | 74.3k | $1.59 |
| 13 | F5 | feature · L3 | high | jsonpath-ng | 3600 / 40 / 300 | 7/7 | 1617 s | 148.6k | $2.86 |

Tiers and order are by median output tokens, set once and never re-ranked per run. Within a tier the order is not
statistically stable.

Origins: *upstream-fix* tasks start at the parent of a real fix and take their hidden tests from it; *injected* (B6)
breaks a released version on purpose; *authored* (F3, F4, F5) are features written for hai-proof, graded by
hand-written tests.

### B17 — pytest-xdist: `--dist=loadgroup` hangs after a worker crash

- **Source:** [pytest-dev/pytest-xdist](https://github.com/pytest-dev/pytest-xdist) at `dd198c35`; issues #1323 and
  #1327, fixed by PRs #1324 and #1328 (2026-08/09).
- **Prompt:** `pytest -n auto --dist=loadgroup` never finishes after a worker crashes (segfault or `os._exit`) and is
  replaced. A two-test repro is given (`test_b` calls `os._exit(1)`, run with `-n1`); `--dist=load` is fine. Both
  `loadgroup` and `loadscope`, which share the scheduler, must finish and report the crash as a failure.
- **Cause:** one hang with two independent causes in the scheduler's handling of a replaced worker. Upstream found
  the second only after the first fix shipped.
- **Grading:** acceptance `testing/acceptance_test.py::TestNodeFailure::test_loadgroup_does_not_hang_after_restart`
  and `…_restart2`; regression `pytest --timeout=120 testing`. The hidden acceptance file is hand-edited to assert
  behaviour (the run finishes, the crash counts as a failure) instead of upstream's exact failure count.

### B20 — astropy: indexed `MaskedColumn` slicing leaks memory

- **Source:** [astropy/astropy](https://github.com/astropy/astropy) at `1c0d7ec0`; issue #16089 (27 comments, two
  failed PRs), fixed by PR #20456 (2026-09-22).
- **Prompt:** a long-running service selects rows with `t[t["idx"] == key]` from a Table indexed on a
  `MaskedColumn` of timestamp strings, and memory grows without bound (18 GB). `gc.collect()` doesn't help; a plain
  `Column` or no index doesn't leak; a 200k-row repro is given.
- **Cause:** numpy's `MaskedArray._optinfo` carries the column's `indices` into derived arrays, so each slice of a
  slice deep-copies the whole index.
- **Grading:** acceptance is the behavioural leak test
  `astropy/table/tests/test_index.py::test_indexed_masked_column_slicing_does_not_leak_memory` (the PR's test that
  inspects `_optinfo` is left out); regression `astropy/table/tests`.

### B7 — dask/distributed: retire/rebalance hangs with nothing logged

- **Source:** [dask/distributed](https://github.com/dask/distributed) at `2d43f7f6`; PR #9315 (2026-07-02).
- **Prompt:** an autoscaling cluster that retires workers constantly sees `retire_workers`, rebalance or gather hang
  forever a few times a week. The scheduler stays responsive and nothing is logged. It points at
  `test_RetireWorker_stress` (which times out occasionally) and says the stuck coroutine is under
  `distributed.comm.core.connect`. It asks for a root-cause fix, not a timeout.
- **Cause:** a race between a listener's `stop()` and an accepted stream in `comm/tcp.py` leaves the client hanging in
  the handshake. The fix is an 8-line guard.
- **Grading:** acceptance `distributed/comm/tests/test_comms.py::test_stop_listener_during_handle_stream` plus
  `::test_handshake_slow_comm` with `--runslow`. The second one fails an "add a handshake timeout" fix. Regression
  `distributed/comm/tests`.
- **Note:** B-DP-1 (`diagnosis` suite) is this task without the `comm.core.connect` hint.

### B19 — tornado: sockets leak after connect timeouts and abandoned connects

- **Source:** [tornadoweb/tornado](https://github.com/tornadoweb/tornado) at `76460597`; issues #2785 and #3614,
  PRs #3735 and #3745 (2026-09-25).
- **Prompt:** the open-file count grows until "Too many open files". Sockets leak from `SimpleAsyncHTTPClient`,
  `TCPClient.connect` (some with `ssl_options`) and `IOStream.start_tls`, even though the requests fail as they
  should. The leaks correlate with timeouts and cancelled waits; the worst case is a peer that accepts TCP and then
  stalls the TLS handshake. No timed-out, failed or abandoned attempt may leave a socket open.
- **Cause:** several independent paths. `start_tls` hands the socket to a stream the caller never sees;
  `TCPClient.connect` leaves the handshake or other address attempts open on timeout or cancel;
  `simple_httpclient` enforced its connect timeout outside `TCPClient`.
- **Grading:** `acceptance_cmd` with tornado's runner: `TestIOStreamStartTLS.test_start_tls_cancellation`,
  `TLSHandshakeTimeoutTestCase`, three `TCPClientTest` close-on-timeout/cancel tests and `ConnectorTest.test_cancel`.
  Regression `python -m tornado.test.runtests` (pytest isn't usable on this suite). The same PR's fix for a separate
  synchronous-connect defect is removed from the hidden tests by hand.

### B21 — SQLAlchemy: cancelled async close leaks connections

- **Source:** [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) at `bc898286`; issue #12710 (30
  comments), fix `6f899879` (2026-09-30).
- **Prompt:** an asyncio service on asyncpg cancels tasks often. It sees ResourceWarnings for unclosed driver
  connections, a pool log line "returned to pool" after "Pool disposed", and pool capacity that shrinks after bursts
  of cancellations. Once a task is done, every connection it used must be back in the pool or closed. Tests run on
  aiosqlite.
- **Cause:** cancelling a task while an `AsyncConnection` or `AsyncSession` context manager closes lets the task
  finish while the close carries on in the background, so the connection returns into an already-disposed pool.
  Related pool paths lose slots when cancelled during reset.
- **Grading:** acceptance `test/ext/asyncio/test_cancellation.py` with `--dburi sqlite+aiosqlite:///:memory:`;
  regression `test/engine/test_pool.py` and `test/ext/asyncio`. The hidden tests are hand-assembled: they overlay the
  fix's cancellation sweep harness, which is excluded from the reference patch because its docstrings describe the
  cause.
- **Note:** B-DP-2 (`diagnosis`) is this task without the "returned to pool after Pool disposed" log line.

### F3 — rich: line, row and child limits

- **Source:** [Textualize/rich](https://github.com/Textualize/rich) v15.0.0 (`6ac483cb`); authored.
- **Prompt:** a detailed spec with examples. It asks for a `rich.linelimit.LineLimit(renderable, max_lines,
  more_marker="…")` renderable with an exact truncation rule; `max_lines` and `more_marker` on `Table` (with
  table/column/row precedence), `Panel` (including `Panel.fit` and `height`) and `Tree` (inherited on `add`);
  `Table(max_rows, rows_marker)`; `Tree(max_children, children_marker)`; `ValueError` validation; and full backward
  compatibility.
- **Grading:** acceptance `tests/hai_proof/test_f3.py`; regression is the default whole suite. The install pins
  `pygments==2.19.2`, because newer releases change token colours.

### B5 — dateparser: not thread-safe

- **Source:** [scrapinghub/dateparser](https://github.com/scrapinghub/dateparser) at `de7b986f`; issues #441 and
  #1291, PR #1346 (2026-08-24), which touches 8 modules.
- **Prompt:** in a thread pool, parsing raises intermittent `KeyError`s from the relative-strings cache (a 16-thread
  repro is given). Two more problems are reported: `PREFER_LOCALE_DATE_ORDER` temporarily writes the locale's date
  order into shared settings, and `search_dates()` mutates `RELATIVE_BASE` on the shared defaults. Results must match
  sequential parsing, visible settings must never change, caches must keep respecting `CACHE_SIZE_LIMIT`, and no
  global lock is allowed.
- **Cause:** shared per-settings caches are evicted and mutated concurrently, and settings objects are mutated
  during parsing.
- **Grading:** acceptance `tests/test_thread_safety.py`; regression `pytest tests`.

### F6 — lark: `Lark.scan()`

- **Source:** [lark-parser/lark](https://github.com/lark-parser/lark) at `c169b26a`; PR #1592 (2026-07-18).
- **Prompt:** add `Lark.scan(text, start=None)`, which yields `ScanMatch((start, end), value)` for every
  non-overlapping, longest-prefix grammar match in free text. Matches skip non-matching text, never start or end on
  `%ignore` terminals and are never zero-length. Each result is identical to `parse()`, with positions relative to the
  whole input. It must work with the contextual and basic lexers, `str`/`bytes`/`TextSlice` input, several start
  symbols and standalone parsers. Only LALR is supported, with the configuration errors listed.
- **Grading:** `acceptance_cmd` `python -m unittest -k scan tests.test_scan tests.test_parser tests.test_tools`;
  regression `python -m tests` (lark's own runner).

### B6 — python-jsonpath-rfc9535: a refactor broke RFC 9535 compliance

- **Source:** [jg-rp/python-jsonpath-rfc9535](https://github.com/jg-rp/python-jsonpath-rfc9535) v2.0.1
  (`8393f7c6`); injected defect.
- **Prompt:** about 130 of 700 conformance checks fail, and the prompt lists them by area: filters (~55), function
  extensions (~50), whitespace in function calls (~15) and normalized paths (~12). The RFC texts are in `docs/rfc/`.
  Both `find()`/`finditer()` and `findall()` must be fixed.
- **Cause:** a "simplification refactor" breaks the semantics in connected places: comparison and existence rules,
  well-typedness checks, nodelist-to-value conversion of function arguments in both resolvers, I-Regexp handling,
  and normalized-path escaping. Fixing it means re-deriving them from the RFC.
- **Grading:** acceptance is the compliance suite (vendored `cts.json`) plus the well-typedness, IETF example,
  canonical-path, CLI, error, issue and regex-cache tests; regression is the default whole suite.

### F7 — sqlglot: the Python executor evaluates subqueries

- **Source:** [tobymao/sqlglot](https://github.com/tobymao/sqlglot) at `b4c9ad5a`; PR #8190 (2026-08-16).
- **Prompt:** `sqlglot.executor.execute` fails on subqueries the optimizer can't rewrite into joins. It must evaluate
  `EXISTS`/`NOT EXISTS`, scalar subqueries (no rows gives NULL; more than one row or column raises `ExecuteError`,
  detected statically for columns), `IN`/`NOT IN` with three-valued NULL logic, and `ANY`/`SOME`/`ALL`. It must handle
  correlation two levels deep, set operations and CTEs. The `Plan` must not be mutated, identical correlated values
  must not re-execute, and results must match DuckDB/Postgres.
- **Grading:** `acceptance_cmd` runs `TestExecutor.test_subqueries`, `test_subquery_cardinality` and
  `test_subquery_execution_does_not_mutate_the_plan`; regression `python -m unittest`. Upstream's
  `test_subquery_memoization` is removed, since it inspects a private attribute.

### B9 — websockets: closed connections are freed only by the cyclic GC

- **Source:** [python-websockets/websockets](https://github.com/python-websockets/websockets) at `803abd96`; issue
  #1749, PR #1752 (2026-08-25).
- **Prompt:** a gateway with 450 concurrent connections and heavy churn holds about 13,500 live connection objects.
  `gc.collect()` frees 1.75 GB but takes 16 s, which causes ping timeouts. A closed connection must be collectable by
  reference counting alone in all four implementations: asyncio, sync, trio and legacy.
- **Cause:** reference cycles through the logger adapter's `extra` dict and the keepalive task / trio assembler.
- **Grading:** `acceptance_cmd` runs the four implementations' connection/protocol tests under `unittest` with
  `WEBSOCKETS_TESTS_TIMEOUT_FACTOR=10`. Regression is the full `unittest` suite. It isn't pytest because pytest's log
  capture keeps tracebacks alive and breaks the refcount tests. `inject.patch` skips two offline-flaky upstream
  tests.

### F4 — Jinja2: a `{% match %}` statement

- **Source:** [pallets/jinja](https://github.com/pallets/jinja) 3.1.6 (`15206881`); authored.
- **Prompt:** add core `{% match %}` / `{% case pattern [if guard] %}` / `{% endmatch %}`, modelled on Python's
  structural pattern matching. The spec covers wildcard, capture, literal, value, sequence (with star), mapping
  (with `**rest`), `|`, `as` and `is test` patterns; compile-time errors; per-case scoping; `meta`; async, the sandbox
  and `NativeEnvironment`; `match`/`case` staying usable as names; and docs in `templates.rst`.
- **Grading:** acceptance `tests/hai_proof/test_f4.py`; regression is the default whole suite.

### F5 — jsonpath-ng: a strict RFC 9535 module

- **Source:** [jsonpath-ng/jsonpath-ng](https://github.com/jsonpath-ng/jsonpath-ng) v1.9.1 (`fe6c7891`); authored.
  `inject.patch` only adds the RFC 9535 and 9485 texts under `docs/rfc/`.
- **Prompt:** a new `jsonpath_ng.rfc9535` module that leaves the existing parsers unchanged. It needs `parse(query,
  functions=None)` with `find()` in RFC nodelist order, `normalized_path()`, and `JsonPathParserError` for invalid or
  ill-typed queries. It needs the five built-in functions, user `FunctionExtension`s with the RFC type system, and
  I-Regexp semantics. Deep `..` must recurse past Python's recursion limit. It also adds `--rfc9535`/`--paths` CLI
  flags and a README section.
- **Grading:** acceptance `tests/hai_proof/test_f5.py`, including the vendored compliance suite; regression is the
  default whole suite. F5 is always last in reports.

## Interview suite

User-in-the-loop feature requests, frozen 2026-10-23 as `interview` (the v2 set, also tagged `interview-v2`). Each
prompt is deliberately underspecified and asks the agent to settle the behaviour by asking. The decisive rules live
in the task's `user.md`, which only the user stand-in sees, and the hidden tests pin them. An agent that doesn't
ask, or doesn't ask about the right points, guesses and usually fails. The suite measures whether a treatment
makes the agent interview well. It isn't informative with nobody answering, so `run` refuses
`--user conventional` for these tasks. Check the plumbing first with `--suite interview-smoke --user reticent
--ask-tool on --mode lightning`.

**What every task shares.** All 13 are feature · L2, upstream-fix, with limits of 2400 s / $5 / 60 turns, and
they declare the stand-in themselves:

- `user = "reticent"`: the stand-in answers from the brief, but only on points the agent's message asks about or
  states. It never volunteers the rest.
- `ask_tool = "on"`: the agent is offered AskUserQuestion.
- `reticence = "strict"`: asking "does this plan look right?" doesn't count as an open question. Each text reply
  also goes through a filter call that deletes sentences raising a separate point the agent didn't raise. Answers to
  genuinely open questions ("anything else?") are kept whole.
- `tool_answers = "full"`: an AskUserQuestion answer gives everything the brief says on that question's point, as a
  text reply would, so the channel doesn't decide how much the agent hears.

The stand-in settings are part of the task, so a contradicting `--reticence` or `--tool-answers` flag is refused.
Twelve of the tasks are copies of earlier tasks (F13–F36) under this stand-in, with the same prompt, brief and
tests. F65 was built new for v2. Every upstream feature was merged in 2026.

**Tiers** come from the x5 confirmation on Sonnet 5.5. *Easy* tasks are ones plain often passes. *Middle* means
plain mostly fails and a good interviewer passes. *Hard* means even good interviewers miss. *Floor checks* are tasks
plain passes, kept to catch a treatment that makes things worse. Only F50 separates the strong interviewers (the
catch-all from the guide). Finding a fuller hard tier is deferred in ROADMAP.md.

Results are passes per arm in the format plain / interview-catchall / interview-guide / superpowers. The x3
calibration is runs 20261022-115440-c3a7 and -115504-db21, and the x5 confirmation is runs 20261022-200817-6b1c and
-200842-3078 (seed 351). F65's figures come from its own pilot (seed 361, x3) and confirmation (seed 371, x5).
Over the 13 tasks at x5, plain passed 37/65, catchall 60/65, guide 59/65 and superpowers 40/65. Plain costs about
$4.3 per rep.

| Order | Task | Base | Tier | Project | x3 | x5 |
|---|---|---|---|---|---|---|
| 14 | F52 | F29 | easy | python-json-pointer | 2 / 1 / 3 / 2 | 3 / 5 / 5 / 4 |
| 15 | F42 | F14 | easy | RxPY | 2 / 3 / 3 / 1 | 3 / 4 / 5 / 5 |
| 16 | F54 | F31 | floor check | Scrapy | 2 / 2 / 3 / 2 | 5 / 5 / 5 / 3 |
| 17 | F45 | F20 | middle | packaging | 0 / 3 / 3 / 1 | 1 / 5 / 4 / 1 |
| 18 | F56 | F33 | middle | dnspython | 2 / 3 / 3 / 1 | 1 / 5 / 5 / 5 |
| 19 | F49 | F26 | floor check | pytest | 3 / 1 / 3 / 3 | 5 / 5 / 4 / 3 |
| 20 | F41 | F13 | easy | platformdirs | 2 / 3 / 3 / 2 | 4 / 5 / 5 / 4 |
| 21 | F43 | F15 | easy-middle | werkzeug | 3 / 3 / 3 / 1 | 2 / 5 / 4 / 1 |
| 22 | F53 | F30 | easy | filelock | 2 / 3 / 3 / 3 | 4 / 5 / 5 / 5 |
| 23 | F50 | F27 | hard | cyclopts | 0 / 1 / 1 / 0 | 1 / 1 / 4 / 0 |
| — | F58 | F35 | floor check | cmd2 | 3 / 3 / 3 / 2 | 5 / 5 / 3 / 3 |
| — | F59 | F36 | easy-middle | dateparser | 2 / 3 / 3 / 3 | 2 / 5 / 5 / 5 |
| — | F65 | new | middle | xknx | 0 / 3 / 2 / 0 | 1 / 5 / 5 / 1 |

F58, F59 and F65 have no `report_order` in task.toml (F58 and F59 have no `cost_tier` either), so reports list them
after the ordered tasks, by id.

### F52 — python-json-pointer: `create` for `set_pointer`

- **Source:** [stefankoegl/python-json-pointer](https://github.com/stefankoegl/python-json-pointer) at `57a8e8d`;
  PR #84 (2026-10-19), first requested in 2013 (#41).
- **Prompt:** add a `create` option to `set_pointer` and `JsonPointer.set` that creates missing parts of the path.
- **Brief:**
  - The keyword is `create=False`, placed after `inplace`, and the default behaviour is unchanged.
  - Intermediates are always dicts, even for numeric or `-` parts.
  - Lists grow only at the end (`-` or index equal to the length); an index past the end raises
    `JsonPointerException`.
  - Nothing is created inside a string or a tuple.
  - A failed call leaves the document completely unchanged.
  - `inplace=False` works on a deep copy.
- **Grading:** acceptance `tests.py` (copied by hand from the fix, since build-task doesn't detect a top-level
  `tests.py`); regression `python -m doctest jsonpointer.py`.

### F42 — RxPY: `zip_latest`

- **Source:** [ReactiveX/RxPY](https://github.com/ReactiveX/RxPY) at `b5dc66c`; PR #711, opened 2024 as
  `combine_throttle` and merged 2026-10-16 with different completion semantics, so recalling the draft doesn't help.
- **Prompt:** an operator that emits one tuple per "round" with the latest value from each source, once every source
  has produced something new. It sits between `zip` and `combine_latest`.
- **Brief:**
  - Three entry points: `reactivex.zip_latest`, `operators.zip_latest` and the fluent `Observable.zip_latest`.
  - Tuples come in source order.
  - Completion: a completed source with a pending value contributes one last tuple; one with nothing pending
    completes the result at once. Synchronous `of(1, 2)` with `of("a", "b")` gives exactly `[(2, "a")]`.
  - An empty source completes immediately, and later sources are never subscribed.
  - The first error wins.
  - `None` is an ordinary value, and futures are accepted as sources.
  - No sources raises `ValueError`.
  - It must be thread-safe.
- **Grading:** acceptance `tests/test_observable/test_ziplatest.py` and `test_combination_fluent.py`; regression
  `tests/test_observable`, `tests/test_core` and `tests/test_subject`.

### F54 — Scrapy: `Request.id` and `Request.parent_id`

- **Source:** [scrapy/scrapy](https://github.com/scrapy/scrapy) at `b87415d`; PR #8225 (2026-10-04).
- **Prompt:** every request should carry its own identifier and the id of the request it came from.
- **Brief:**
  - `id` is a read-only integer that is unique across processes.
  - `parent_id` defaults to `None`, is settable, and is a constructor keyword.
  - `copy()` and `replace()` give a new `id`, with `parent_id` set to the copied request's `id`; an explicit value
    wins, even `None`.
  - `Response.follow` and `follow_all` set `parent_id` from the response's request.
  - The scraper fills in `parent_id` for yielded requests that have none, for sync and async generators and
    errbacks, and never overwrites an explicit value.
  - `to_dict()` and `request_from_dict` round-trip both ids.
  - The same rules hold for every `Request` subclass.
- **Grading:** acceptance `test_request_dict.py`, `test_request_lineage.py`, `test_http_request.py` and
  `test_http_response.py`; regression five neighbouring test files.

### F45 — packaging: `Requirement.__replace__`

- **Source:** [pypa/packaging](https://github.com/pypa/packaging) at `7464e38`; PR #1377 (2026-10-19/20).
- **Prompt:** a supported way to make a modified copy of a `Requirement`, as `Version` has, that also works with
  `copy.replace()` on 3.13+.
- **Brief:**
  - `__replace__` takes the keyword-only fields `name`, `url`, `extras`, `specifier` and `marker`. A call with no
    arguments gives an equal but distinct object.
  - `url=None` and `marker=None` clear the field. Replacing the url on a requirement that has a specifier also
    needs an empty `SpecifierSet()`.
  - Replacements are validated by re-parsing and raise `InvalidRequirement`, including values that would smuggle in
    extra syntax.
  - Marker extras are normalised.
  - The specifier is deep-copied, and its `prereleases` override is kept.
  - Subclasses are built through their own constructor.
  - An unknown keyword raises `TypeError`.
- **Grading:** acceptance `tests/test_requirements.py`, unedited (`test_copy_replace` skips on the container's
  3.12); regression `test_markers.py` and `test_specifiers.py`.

### F56 — dnspython: BIND substitution rules in `$GENERATE`

- **Source:** [rthalley/dnspython](https://github.com/rthalley/dnspython) at `0ccb9cf`; PR #1363 (2026-10-18).
- **Prompt:** dnspython's `$GENERATE` expansion should match BIND's.
- **Brief:**
  - Every `$` is handled independently, left to right: `$`, `${offset}`, `${offset,width}` and
    `${offset,width,base}` with bases `d o x X n N`.
  - `$$` is a literal `$`, and `\$` stays `\$`.
  - The nibble bases write hex digits dot-separated, least significant first and never truncated. Width only pads
    with zero nibbles and counts the dots, so `${0,3,n}` for 427 gives `b.a.1`. Width 0 is allowed.
  - Malformed modifiers raise `dns.exception.SyntaxError`, and so does a negative value in a nibble base.
  - Someone who knows BIND's `genname()` needs fewer questions.
- **Grading:** acceptance `tests/test_generate.py`; regression ten neighbouring test files.

### F49 — pytest: type expressions in `Parser.addini(type=...)`

- **Source:** [pytest-dev/pytest](https://github.com/pytest-dev/pytest) at `ef052d0`; PR #14751 (2026-07-24).
- **Prompt:** `addini(type=...)` should accept `int`, unions such as `int | str`, and `Literal[...]`, and
  `getini()` should return matching values.
- **Brief:**
  - The existing string tags keep working, and plain types are aliases of them.
  - Unions of those types and string `Literal`s are allowed; anything else raises `ValueError` at `addini`.
  - A union or Literal needs an explicit `default=`.
  - Reading a union: TOML values keep their native type and the first accepting member wins; string sources are
    coerced to the first member that accepts them.
  - No accepting member raises `TypeError`. A Literal checks a string against its choices without coercion.
  - Error messages name the config file and the option.
  - `--help` shows the type.
- **Grading:** acceptance `testing/test_config.py`, with eight message pins removed and the exact `--help`
  rendering test dropped; regression `test_parseopt.py`, `test_findpaths.py` and `test_helpconfig.py`.

### F41 — platformdirs: `place_*_file` methods

- **Source:** [tox-dev/platformdirs](https://github.com/tox-dev/platformdirs) at `46843f1`; PR #585 (2026-09-26).
- **Prompt:** a way to get a file path in a user directory with the directories on the way created properly, per
  the XDG spec. It says `Path.mkdir(parents=True, mode=...)` is not enough.
- **Brief:**
  - Six methods, `place_config_file` through `place_runtime_file`, each returning a `Path` under the matching
    `user_*_dir`.
  - They create missing directories, including the user dir itself, but never the file. Every created level gets
    0o700, and existing directories are never chmod-ed.
  - They are independent of `ensure_exists`.
  - Escaping names (absolute paths, `..`) and empty names raise `ValueError` with the library's existing messages
    and create nothing.
  - An unknown home raises the existing `RuntimeError` and never creates a literal `~` directory.
  - The runtime owner check's `PermissionError` propagates.
- **Grading:** acceptance `tests/test_api.py` and `tests/test_unix.py`; regression `tests`.

### F43 — werkzeug: conservative cleanup of the `int` and `float` converters

- **Source:** [pallets/werkzeug](https://github.com/pallets/werkzeug) at `ef518e4`; issue #3242, PR #3243
  (2026-08-19).
- **Prompt:** a maintainer with firm opinions wants unintended matching and building behaviour cleaned up before
  3.2. It notes that a recent scientific-notation fix went too far.
- **Brief:**
  - Only ASCII digits match.
  - The minus sign doesn't count toward `fixed_digits`.
  - `to_url` validates `signed`, `min`, `max` and `fixed_digits`.
  - A float that overflows to inf doesn't match. A float needs both integer and fractional parts, with no exponent.
  - Building a float uses `str(value)`, with an exponent expanded into plain digits.
  - Ints longer than `sys.get_int_max_str_digits()` don't match.
  - `NumberConverter` may go.
  - Document the changes with `versionchanged:: 3.2`.
- **Grading:** acceptance `tests/test_routing.py`, with two hand fixes to vacuous or ill-formed rows; regression
  routing, urls and wrappers tests. Plain often regresses an existing converter behaviour here.

### F53 — filelock: an `on_acquired` hook

- **Source:** [tox-dev/filelock](https://github.com/tox-dev/filelock) at `0b9adaa`; issue #607, PR #625
  (2026-07-13).
- **Prompt:** a callback that runs once the lock is held, so holder metadata can be written as part of acquiring.
- **Brief:**
  - It is a constructor option with a read-only property, called with the locked file's fd.
  - It runs while the lock is held, after truncation and `mode` are applied, and before `acquire()` returns.
  - It runs once per physical acquisition: not on a recursive acquire, and never for a contender that times out.
  - If the callback raises, the lock is released and the original exception propagates.
  - The soft locks reject the option.
  - Singletons with a different callback raise `ValueError`.
  - With `AsyncFileLock`, the callback runs in the lock's worker thread.
- **Grading:** acceptance `tests/test_filelock.py` and `tests/test_async_filelock.py` with `-k "not threaded"`,
  plus an autouse `gc.collect()` fixture added after leaked locks broke caplog checks; regression `tests`, minus
  three slow or unrelated parts.

### F50 — cyclopts: reject a config `null` for types that don't allow None

- **Source:** [BrianPugh/cyclopts](https://github.com/BrianPugh/cyclopts) at `6feee65`; PR #1004 (2026-10-12).
- **Prompt:** a `null` from a config source should be checked against the parameter's type.
- **Brief:**
  - A type that doesn't allow None raises `CoercionError`, and so does a null inside a `dict` or `list` of such
    types. Types that do allow None bind `None`; these include `Any`, `X | None` and Literals containing None.
  - Unannotated parameters are typed by their default, so `x=0` rejects null.
  - A `None` default binds as if the key were absent.
  - Classes (dataclasses, pydantic models) follow the same rule.
  - A keyed null inside an optional dict is an error, not "the whole dict is None".
  - Validators still see `None`.
- **Grading:** acceptance `tests/config/test_dict.py` and `tests/test_pydantic.py`, with one message pin dropped and
  four top-level rows removed after they failed 23 of 25 trials in every arm; regression five config and binding
  test files. This is the one task where the guide beats the catch-all.

### F58 — cmd2: Enum `_missing_` and Enum unions in `@with_annotated`

- **Source:** [python-cmd2/cmd2](https://github.com/python-cmd2/cmd2) at `ec22b82`; PR #1694 (2026-06-16).
- **Prompt:** let an Enum's `_missing_` hook resolve command-line tokens, and make `Color | Shade` work instead of
  being refused as ambiguous.
- **Brief:**
  - `_missing_` is used only with the opt-in `allow_unknown_entry` on `Argument`/`Option`, and only as a fallback
    after value and name matching. The flag reaches collections and union members.
  - For a single Enum, an exception from `_missing_` propagates. In a union it counts as declining.
  - Union members are tried in the order written, and if all decline the error is the merged "invalid choice".
  - A union with a non-Enum member is still a `TypeError`.
  - Completion choices are merged and de-duplicated.
  - `A | B | None` becomes an optional positional, or a `--flag` when it has a `None` default.
- **Grading:** acceptance `tests/test_annotated.py`, with one private-API test removed and message pins dropped;
  regression the same file plus `test_argparse_utils.py`, with the new classes deselected.

### F59 — dateparser: a `TIMEZONE_ABBREVIATIONS` setting

- **Source:** [scrapinghub/dateparser](https://github.com/scrapinghub/dateparser) at `dda8b21`; issues #683 and
  #580, PR #1415 (2026-10-21).
- **Prompt:** "IST" parses as Israel time (+02:00) but the data means India (+05:30). The user wants a way to say
  what an abbreviation means.
- **Brief:**
  - The setting maps abbreviations to `timedelta`, defaulting to `{}`. Unlisted abbreviations keep their built-in
    offsets.
  - It applies to absolute dates, freshness dates and strings with a numeric offset as well, including
    `RETURN_AS_TIMEZONE_AWARE`, and works without `languages`.
  - Keys are case-sensitive and must exist. An unknown key or a non-`timedelta` value raises
    `SettingValidationError`.
  - It doesn't affect `TIMEZONE` or `TO_TIMEZONE`.
- **Grading:** acceptance `tests/hai_proof/test_f36.py` (hand-written: case sensitivity, TIMEZONE/TO_TIMEZONE,
  detected language, bad values), `test_settings.py` and `test_timezone_parser.py`; regression five parser test
  files.

### F65 — xknx: the cause of a device update in `Device.last_update`

- **Source:** [XKNX/xknx](https://github.com/XKNX/xknx) at `b549ef8`; PR #1952 (2026-10-13).
- **Prompt:** devices should record what caused their latest update. It fixes the API names: `Device.last_update`
  (a `DeviceUpdate` with `telegram` and `context`), `Telegram.context` and the `telegram_context` context manager.
  Every behavioural rule is left to the conversation.
- **Brief:**
  - `DeviceUpdate` is immutable, and starts as `DeviceUpdate()`. It is set before callbacks run, and the callback
    signature is unchanged.
  - `telegram_context` tags outgoing telegrams created inside the block, nests, and restores the outer value on
    exit. An explicit context wins, and tasks inherit it. Incoming telegrams never pick up the context.
  - A cause that comes from a later task is kept: cover travel updates, debounced light colour channels and binary
    sensor counters.
  - The current telegram is cleared while callbacks run, so work they schedule doesn't inherit it.
  - `context` is left out of equality and `repr`.
- **Grading:** acceptance `test/hai_proof/test_f65.py`, written by hand from the PR's three test files; regression
  the devices, telegram, cemi and remote-value tests. The task.toml comment still calls it hard-tier, but at x5 it
  is middle.
