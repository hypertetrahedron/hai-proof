# Task catalog

A record of every task that has been built or piloted, every candidate still being looked at, and
the ideas that were rejected. Use it to see what has been tried before authoring something new.
How to write a task is in [task-authoring.md](task-authoring.md).

Target (2026-10-08): one rep of the whole suite should take about **1 hour per arm**, so treatments
have room to make a difference. Level-3 tasks are aimed at **about 30 min** of agent time each.

Decision 2026-10-10: the ~30 min target is relaxed for defect tasks (natural defects top out around
10–15 min for the current model). All built tasks B1–B21, B-DP-1, B-DP-2 and F1–F8 are in the library (Active).

Decision 2026-10-09: tasks are never deleted when a longer one arrives. F3 and F4 stay, and the catalog
is kept as a pool of calibrated tasks for future suite shapes and features.

Status: `Active` (in the published suite) · `Piloting` (built and validated, not yet in the suite)
· `Candidate` (researched, not built) · `Retired` · `Rejected`

## Built tasks

All pilots: plain arm only (single-arm runs), `claude-sonnet-5-5`, on `developmenthost1`. Times are
wall-clock per agent run. The run ID is the `results/<run>` directory, which is local and gitignored.

| ID | Kind · level | Repo @ tag | Summary | Status | Pilot runs (pass) | Wall time, median (range) | Tokens, median | Cost / run | Run IDs |
|---|---|---|---|---|---|---|---|---|---|
| B1 | bug · L1 | click 8.5.0 | Clamping on an open-bounded `IntRange` goes the wrong way | Active | 3/3 + 1 | 11 s (8–12) | 82k (3-run pilot) | $0.05 | 20261007-193151-34c4, 20261007-214151-fcbe |
| B2 | bug · L2 | marshmallow 4.3.1 | Regression report: three related defects in an order import | Active | 3/3 (final version) | 38 s (25–68) | 125k | $0.10 | 20261007-211025-c0aa |
| B3 | bug · L3 | rich 15.0.0 | Regression report: `Layout` panels misplaced, live updates missing | Active | 3/3 (final version) | 48 s (28–65) | 159k | $0.12 | 20261007-211025-c0aa |
| B4 | bug · L2 | tinycss2 1.5.0 | Conformance regression report: 16 injected bugs (tokenizer 7, parser 2, An+B 1, serializer 2, colors 4+1) with 16 listed symptoms | Active (L2, calibrated 2026-10-09) | 3/3 | 147 s (107–169) | — | $0.31–0.44 | 20261009-161628-0cf7, 20261009-231624-c4b4 |
| B5 | bug · L3 | dateparser @ de7b986f | Real upstream bug: not thread-safe (#441, #1291). Fix PR #1346 (2026-08-24) reworks caches and shared settings across 8 modules | Active (L3, calibrated 2026-10-09) | 3/3 | 485 s (237–510) | — | $0.41–0.57 | 20261009-175117-cf62, 20261009-231624-c4b4 |
| B6 | bug · L2 | python-jsonpath-rfc9535 2.0.1 | Long bug: a "simplification refactor" breaks RFC 9535 semantics in five places (comparison/existence rules, well-typedness checks, function-argument nodelist→value conversion in both resolvers, I-Regexp handling, normalized-path escaping); 134/706 compliance cases fail | Active (L2, calibrated 2026-10-09) | 0/1 as graded; 1/1 after excluding the 2 `^`/`$` cases | 212 s (1 run) | 1.4M | $0.73 | 20261009-192311-e2a2 |
| B7 | bug · L2 | dask/distributed @ 2d43f7f6 | Concurrency, symptom far from cause: retire/rebalance under churn hangs forever with nothing logged. Cause: listener `stop()` vs accepted-stream race in `comm/tcp.py`. Fix is an 8-line guard (PR #9315, 2026-07-02) | Active (L2, calibrated 2026-10-09) | 3/3 after prompt fix (0/1 before) | 174 s (111–775) | — | $0.15–0.54 | 20261009-195010-5746, 20261009-205034-8594 |
| B8 | bug · L1 | asgiref @ ec6f6666 | Memory leak, hidden cause: thread-critical `Local` lookups leave exception/traceback/frame cycles (a caught `RuntimeError` inside a `@contextmanager` generator). Fix +3 lines (issue #487, PR #508, 2025-06-30) | Active (L1, calibrated 2026-10-10) | 3/3 | 45 s (36–53) | — | $0.07–0.08 | 20261009-235014-4ff7 |
| B9 | bug · L3 | websockets @ 803abd96 | Memory leak across components: closed connections are only freed by the cyclic GC (logger-adapter extra dict and keepalive task / trio assembler cycles), across asyncio, sync, trio and legacy implementations (issue #1749, PR #1752, 2026-08-25) | Active (L3 limits, calibrated 2026-10-10; ~14 min, 78–102 turns) | 3/3 (run 2392) | 829 s (762–850) | — | $1.34–2.18 | 20261010-012729-5d2e, 20261010-024512-e100, 20261010-044729-2392 |
| B10 | bug · L1 | werkzeug @ b48878cf | Data-dependent: multipart uploads lose exactly 1 byte when a part ends in CR at a particular buffer offset; the reporter lost a day to decoys (issue #3077, PR #3081, 2026-01-02) | Active (L1, calibrated 2026-10-10) | 3/3 after grading fix (graded 0/3) | 39 s (32–39) | — | $0.07–0.09 | 20261009-235014-4ff7 |
| B11 | bug · L1 | dynaconf @ b56a831c | Interaction: after `validators.validate()` on `foo.bar.value`, the sibling `foo.value` vanishes when both hold the same value (merge guard applied at every recursion level). Fix +1 line (issue #974, PR #1434, 2026-07-29) | Active (L1, calibrated 2026-10-10) | 3/3 | 47 s (46–53) | — | $0.11–0.14 | 20261010-012729-5d2e |
| B12 | bug · L1 | dynaconf @ 833533d1 | Hidden persistent state: `get("foo.bar", fresh=True)` returns the default after the first call, and poisons ordinary reads (child segment recorded as deleted). Fix +10/−2 (issue #1187, PR #1423, 2026-08-03) | Active (L1, calibrated 2026-10-10) | 3/3 | 62 s (48–68) | — | $0.11–0.18 | 20261010-012729-5d2e |
| B13 | bug · L1 | attrs @ ab7f8b2f | Interaction: nested `validators.disabled()` re-enables validators for the rest of the outer block (context manager always restores True). Fix +3/−1 (PR #1513, 2026-03-14) | Active (L1, calibrated 2026-10-10) | 3/3 | 13 s (13–15) | — | $0.04 | 20261010-024512-e100 |
| B14 | bug · L1 | pluggy @ 6e1d0f13 | Interaction: a plugin with two impls of one hook (`specname=`) keeps one firing after `unregister()`; `get_hookcallers` lists duplicates. Fix +7/−8 in 2 files (issue #431, PR #646, 2026-02-25) | Active (L1, calibrated 2026-10-10) | 3/3 | 25 s (23–60) | — | $0.08–0.15 | 20261010-024512-e100 |
| B15 | bug · L1 | websockets @ 02653c73 | Same defect in 3 parallel implementations: servers log an "unexpected internal error" when the peer drops TCP during `process_request` (asyncio, sync, trio servers + clients). PR #1744, 2026-07-28 | Active (L1, calibrated 2026-10-10) | 3/3 (1 grading flake, re-graded) | 156 s (117–183) | — | $0.31–0.36 | 20261010-044729-2392 |
| B16 | bug · L1 | structlog @ c6e7cad1 | Same defect across logger flavours: callsite THREAD/THREAD_NAME report the executor thread for async log methods (native and stdlib bound loggers). Issue #710, PR #805, 2026-05-10. `inject.patch` imports multiprocessing in tests/conftest.py (environment shim) | Active (L1, calibrated 2026-10-10) | 3/3 | 51 s (45–62) | — | $0.16–0.20 | 20261010-044729-2392 |
| B17 | bug · L2 | pytest-xdist @ dd198c35 | One hang, two causes, second found after the first fix: `--dist=loadgroup` never finishes after a crashed worker is replaced (issues #1323/#1327, PRs #1324/#1328, 2026-08/09) | Active (L2, calibrated 2026-10-10) | 3/3 (rep 0 re-graded after the hidden-test fix) | 442 s (389–606) | — | $0.25–0.31 | 20261010-062840-da87 |
| B18 | bug · L1 | tornado @ 89afbd1d | Incomplete first fix: awaiting a cancelled future hangs request handlers, `@gen.coroutine`, `multi`, `with_timeout` (issues #2990/#3537, PRs #3695/#3749, 2026-09). `[source] exclude` drops #3749's unrelated hardening | Active (L1, calibrated 2026-10-10) | 2/3 | 144 s (139–362) | — | $0.21–0.27 | 20261010-073922-d475 |
| B19 | bug · L2 | tornado @ 76460597 | Multi-cause socket leak after connect timeouts / abandoned connects: start_tls, TCPClient timeout and cancel, simple_httpclient (issues #2785/#3614, PRs #3735/#3745, 2026-09-25) | Active (L2, calibrated 2026-10-10) | 2/3 (reps 1–2 re-graded after the port fix) | 532 s (210–720) | — | $0.26–0.49 | 20261010-062840-da87 |
| B20 | bug · L1 | astropy @ 1c0d7ec0 | Long-investigation leak: `t[t["idx"] == v]` on a Table indexed on a `MaskedColumn` grows memory without bound (issue #16089, 27 comments, 2 failed PRs; fix PR #20456, 2026-09-22) | Active (L1, calibrated 2026-10-10) | 3/3 | 126 s (96–258) | — | $0.22–0.52 | 20261010-075703-3c6a |
| B21 | bug · L2 | sqlalchemy @ bc898286 | Concurrency in a large system: cancelling a task while an async context manager closes lets the close continue in the background, so connections return into a disposed pool and leak; pool slots lost on cancel during reset (issue #12710, 30 comments; fix 6f899879, 2026-09-30). Hand-assembled hidden tests (sweep harness overlaid at grading) | Active (L2, calibrated 2026-10-10) | 1/3 | 276 s (192–288) | — | $0.36–0.47 | 20261010-081428-1abe |
| B-DP-1 | bug · L2 | dask/distributed @ 2d43f7f6 | Degraded-prompt task: B7 without the `distributed.comm.core.connect` hint (docs/prompt-degradation.md) | Active (degraded prompt) | 0/3 | 1273 s (492–1645) | — | $0.23–1.24 | 20261010-085001-4eae |
| B-DP-2 | bug · L2 | sqlalchemy @ bc898286 | Degraded-prompt task: B21 without the "returned to pool after Pool disposed" log line (docs/prompt-degradation.md) | Active (degraded prompt) | 0/3 | 270 s (264–353) | — | $0.50–0.79 | 20261010-085001-4eae |
| F1 | feature · L1 | click 8.5.0 | `suffixes` option for `click.Path` | Active | 3/3 | 43 s (38–116) | 118k | $0.09 | 20261007-193151-34c4 |
| F2 | feature · L2 | marshmallow 4.3.1 | List validator that rejects repeated items | Active | 3/3 | 62 s (58–87) | 237k | $0.16 | 20261007-193151-34c4 |
| F3 | feature · L3 | rich 15.0.0 | Line, row and child limits across `Table`, `Panel` and `Tree` | Active | 3/3 (final version) | 161 s (148–244) | 642k | $0.51 | 20261007-211025-c0aa |
| F4 | feature · L3 | Jinja2 3.1.6 | `{% match %}` statement (Python-style pattern matching): parser, AST, compiler, scoping, `meta`, async, sandbox | Active (L3 limits, ~9 min, calibrated 2026-10-08) | 3/3 | 520 s (442–740) | 2.65M | $1.53–2.57 | 20261008-205320-c606 |
| F5 | feature · L3 | jsonpath-ng 1.9.1 | Strict RFC 9535 module (`jsonpath_ng.rfc9535`): parser, evaluator, function type system, I-Regexp, normalized paths, user function extensions, `--rfc9535` CLI mode. RFC 9535/9485 texts are added under `docs/rfc/` by `inject.patch` | Active (calibrated 2026-10-09) | 3/3 with the fixed tests (first run graded 0/1 by the original tests) | 1617 s (670–1859) | 8.6M | $2.20–4.72 | 20261008-215805-3ddb, 20261009-064858-f773 |
| F6 | feature · L3 | lark @ c169b26 (upstream PR #1592) | `Lark.scan()`: find every non-overlapping grammar match in free text (`ScanMatch`, longest-prefix, contextual lexer, `TextSlice`, standalone parser) | Active (pilot 2026-10-10) | 3/3 | 230 s (213–250) | 0.89M | $0.46–0.59 | 20261010-194554-c904 |
| F7 | feature · L3 | sqlglot @ b4c9ad5 (upstream PR #8190) | Python executor evaluates subqueries: `EXISTS`, scalar, `IN`/`NOT IN`, `ANY`/`ALL`, correlation, CTEs, NULL semantics; plan not mutated | Active (pilot 2026-10-10) | 2/3 (one genuine miss: correlated `EXISTS` over an aggregating outer CTE) | 1072 s (870–1753) | 1.62M | $0.68–1.72 | 20261010-194554-c904 |
| F8 | feature · L3 | tornado @ 9598807 (upstream PR #3762) | Opt-in `cross_origin_protection` via `Sec-Fetch-Site`/`Origin`, `trusted_origins`, `check_origin` moved to `RequestHandler` | Active (pilot 2026-10-10) | 3/3 | 130 s (105–149) | 0.32M | $0.17–0.22 | 20261010-194554-c904 |
| F9 | feature · L2 | python-tabulate @ 83fd4fb (upstream PR #221, issue #59) | User-in-the-loop, deliberately ambiguous: header alignment independent of column alignment, a global column alignment, over-long lists, a warning for a bare string (the prompt asks for each behaviour since 2026-10-14; before that it asked only for headers and the hidden tests checked more, 0/6 in run 20261014-215059-aef8). `user.md` holds the API (`headersglobalalign`, `headersalign`, `colglobalalign`, "same"/"global"), over-long lists ignored, the "As a string" `UserWarning` and the signature order | Piloting (2026-10-14): the agent never asks | 0/14 informative | 31–66 s | — | $0.10–0.22 | 20261014-215059-aef8, 20261014-224001-e71f |
| F10 | feature · L2 | tomlkit @ 5f0e954 (upstream PR #296, issue #288) | User-in-the-loop, deliberately ambiguous: a way to serialize unsupported types (Decimal). `user.md` fixes the design: global `register_encoder`/`unregister_encoder`, encoders decline with `TypeError`, `item()` raises an error that is both `TypeError` and `ValueError`. The prompt invites design questions | Piloting (2026-10-14); contaminated (2026-10-15): the agent knows the upstream design and says so in 4/10 trials | 14/14 informative; 4/5 informative, 4/5 uninformative (ask tool on) | 56–95 s | — | $0.13–0.21 | 20261014-215059-aef8, 20261014-224001-e71f, 20261015-074833-5aee |
| F11 | feature · L2 | copier @ 38f9bb0 (upstream PR #2849, issue #2763; both after the model cutoff) | User-in-the-loop, deliberately ambiguous: advanced questions hidden by default. `user.md` fixes the design: a templatable `ask` key separate from `when`; `ask: false` records the `--data`/previous/default value without prompting, even without `--defaults`, and keeps the previous answer on update; `--ask` globs override it; `when: false` wins and discards. Hidden tests: the upstream 30-row pexpect truth table plus hand-written API tests | Validated 2026-10-19 (`[ok]`, grading 57 s with 4 xdist workers). Pilot 8fcc (plain, ask tool on, x3): uninformative 0/3, informative 3/3, 4 questions per trial; uninformative runs chose an `advanced` key (8/36 acceptance tests fail) | ~10 min, ~$0.30
| F12 | feature · L1 | towncrier @ b3a363e (upstream PR #740, merged 2026-08-15) | User-in-the-loop, deliberately ambiguous: configurable changelog wrap width. `user.md` fixes the design: `wrap` itself takes an integer (no second key), `true` stays 79, an integer <= 0 falls back to 79 rather than disabling. Hidden tests: upstream `render_fragments` cases plus hand-written `towncrier build --draft` tests. A 2024 issue comment suggested "accept an integer", so that half may be recalled | Validated 2026-10-19 (`[ok]`, grading 4 s). Pilot 8fcc (plain, ask tool on, x3): uninformative 0/3, informative 3/3, 2-3 questions per trial; uninformative runs added a separate `wrap_width` key, so the 2024 suggestion was not recalled | ~1 min, ~$0.13
| F13 | feature · L2 | platformdirs @ 46843f1 (upstream PR #585, merged 2026-09-26) | User-in-the-loop, decision-dense: `place_*_file` methods. `user.md`: six methods; every directory created gets 0o700 level by level; existing ones untouched; independent of `ensure_exists`; bad names raise `ValueError` and create nothing; unknown home raises `RuntimeError`. Hidden tests are upstream's; the empty-name message is relaxed to "mentions the name" (hand edit) | Validated 2026-10-20. Pilot cc5a: uninformative 0/5 (no `place_*` names), informative 2/5 (all 3 failures were message wording, then relaxed). The escape message is still pinned (reuse of the existing check) |
| F14 | feature · L2 | RxPY @ b5dc66c (upstream PR #711, final design 2026-10-16) | User-in-the-loop, decision-dense: `zip_latest`. `user.md`: three entry points; a pending value from a completed source forms one final tuple; complete as soon as no further tuple is possible; an empty source skips later subscriptions; zero sources raise `ValueError`; `None` is a value; futures accepted | Validated 2026-10-20. Pilot cc5a: uninformative 0/5, informative 5/5. Misses are real design points (subscription skipping, zero sources) |
| F15 | feature · L2 | werkzeug @ ef518e4 (upstream PR #3243, issue #3242, merged 2026-08-19) | User-in-the-loop, decision-dense: tighten the `int`/`float` URL converters. `user.md`: ASCII digits only; sign not counted by `fixed_digits`; build validates; overflow rejected, underflow allowed; `str()` float formatting without exponents. Hidden test hand-fixed: upstream's failing-match rows called `match()` without the path (vacuous), plus an overflow row with a fraction | Validated 2026-10-20 |
| F16 | feature · L2 | platformdirs @ ba1cc1e (upstream PR #586, merged 2026-09-26) | User-in-the-loop, decision-dense: a `find_<kind>_file(s)` pair. `user.md`: every kind with `iter_*_paths`; user directory first, then site; regular files only; de-duplicated; never creates directories even under `ensure_exists`, and leaves the instance flag alone; existing escape check | Validated 2026-10-20. Run 9189 (reticent, plain vs superpowers, x5): 5/5 both, so no headroom. F13's `place_*` code in this base already shows the copy-with-`ensure_exists`-off pattern |
| F17 | feature · L2 | pdm @ 4abfe39 (upstream PR #3875, issue #3809, merged 2026-09-03) | User-in-the-loop, decision-dense: `exclude-newer-override`. `user.md`: table and CLI forms; `false` not `0` (the issue proposed 0); normalised names; CLI over pyproject per package; overrides alone force `--update-all`; uv `--exclude-newer-package`. Hand edits: message assertions relaxed; the uv argv test (internal state attribute) excluded | Validated 2026-10-20 (13 s grading). Run bfdc (reticent, x5): plain 2/5, superpowers 3/5; superpowers trials cost about 2x |
| F18 | feature · L2 | pytest-rerunfailures @ 78561a5 (upstream PR #365, merged 2026-09-09) | User-in-the-loop, decision-dense: rerun conditions with error inspection (catalog H5). Pins `pytest>=9.1,<9.2`. Hand edits: the private-attribute test removed, a warning pattern's " as a callable" suffix dropped. The hidden tests are the project's own test file, so `regression` names it explicitly (the grader's `--ignore` otherwise left nothing to collect) and equals acceptance | Validated 2026-10-20 (16.5 s grading). Runs 1dca (interview-guide) and 91ef (superpowers), reticent x5: 0/5 every arm, because `test_condition_uses_one_decision_for_call_and_teardown_failures` fails for all 20 trials (the first attempt's teardown error stays reported, exit 1): a pytest report-protocol detail, not a design point. Without it: plain 3/5 and 3/5, guide 5/5, superpowers 5/5. 2026-10-20: that test removed from the hidden tests (note 3 in `task.toml`), revalidated [ok] (15.6 s); 1dca/91ef stay pilot data on the old hash |
| F19 | feature · L2 | bidict @ 77ade42 (upstream PR #393, merged 2026-08-23) | User-in-the-loop, decision-dense: `RuntimeError` when an `OrderedBidict` is mutated during iteration (catalog D5). `user.md`: forward and reverse; insert, delete, `clear`, `move_to_end`, collapsing `forceput` and mutation via `.inverse` all count; the last item raises (unlike `OrderedDict`); value-only update allowed; an unadvanced iterator raises. Regression needs `--hypothesis-profile=default` | Validated 2026-10-20 (29 s grading); not run |
| F20 | feature · L2 | packaging @ 7464e38 (upstream PR #1377, merged 2026-10-20) | User-in-the-loop, decision-dense: `Requirement.__replace__` (D2). `user.md`: keyword-only fields; no-op returns an equal distinct copy; re-parse validation (`InvalidRequirement` for `name="foo[bar]"`, `extras={"a,b"}`); marker extras normalised; specifiers deep-copied with `prereleases` kept; subclasses preserved; unknown keyword `TypeError`. `copy.replace` test skips on 3.12 | Validated 2026-10-20 (11 s grading); not run |
| F21 | feature · L2 | jsonpath-ng @ ccb9533 (upstream PR #289, merged 2026-10-16) | User-in-the-loop, decision-dense: RFC 9535 slices and `[*]` on non-arrays (D10). `user.md`: coercion dropped; `[*]` on objects gives member values with field paths, on scalars nothing; parameterised slices only on lists; `..[*]` without phantom nodes; `update`/`filter` follow `find`; both parsers. Guessable direction from the RFC | Validated 2026-10-20 (4.6 s grading); not run |
| F22 | feature · L2 | packaging @ 189a76d (upstream PR #1313, merged 2026-07-21) | User-in-the-loop, decision-dense: `SpecifierSet.is_subset/is_superset/is_disjoint` (D6). `user.md`: plain bools; unsatisfiable set subset of and disjoint from everything; `""` accepts everything; differing `prereleases` `ValueError`; `===` `ValueError`; non-`SpecifierSet` `TypeError`. Hand edit: three `match=` strings dropped | Validated 2026-10-20 (15 s grading); not run |
| F23 | feature · L2 | attrs @ d3a98cf (upstream PR #1592, merged 2026-08-01) | User-in-the-loop, decision-dense: Generator `on_setattr` hooks (D4). `user.md`: yielded value is set; post-yield code sees the new value; not in `__init__`; exception before yield keeps the old value, after keeps the new; second yield `RuntimeError` with the generator closed. Hand edits: private `test_compat` tests excluded, yield-twice message unpinned. Issue #1437 (2025) settles the headline | Validated 2026-10-20 (16 s grading); not run |
| F24 | feature · L2 | click @ 8dd4d60 (upstream PR #3677, merged 2026-07-08) | User-in-the-loop, decision-dense: `style()` colour validation (D9). `user.md`: index 0 honoured; names case-sensitive; 0..255; RGB exactly three ints, list accepted; bools rejected; every invalid value `ValueError`. Hand edit: `match="Unknown color"` dropped; pager tests ignored in regression (no `less`). Risk: the rule fits in one sentence | Validated 2026-10-20 (7.7 s grading); not run |
| F25 | feature · L2 | icalendar @ 8e80304 (upstream PR #1852, merged 2026-09-30) | User-in-the-loop, decision-dense: `vRecur.count` (D1). `user.md`: int reads; absent or empty list `None`; 0 valid; first of several; `None`/`del` remove, `del` unset no-op; non-int and bool `TypeError`; negative `InvalidCalendar`; unreadable stored value `InvalidCalendar` on read. Hand edits: message unpinned, a parser-text test removed. Installed with pip and a throwaway git repo (uv workspace source, hatch-vcs) | Validated 2026-10-20 (4.1 s grading); not run |

Notes:

- **F6–F8** (2026-10-10): the first feature tasks taken from upstream PRs, not authored. The search
  (web/async, data/parsing, dev tools/CLI) found 14 verified feature PRs merged 2026-07..10. Each prompt is a
  detailed spec written from the PR. All three are graded with the project's own runner (`acceptance_cmd`).
  F6 excludes `tests/test_trees.py`, which checks Token deepcopy, an upstream implementation detail. F7's hidden
  `test_subquery_memoization` was removed because it reads the private `_subquery_plans` cache, and F7
  regression runs the full `python -m unittest` (SKIP_INTEGRATION would skip the executor tests). The F7 failure
  is genuine: the case `WITH w AS (SELECT b, COUNT(*) ...) SELECT a FROM x WHERE EXISTS (SELECT 1 FROM w WHERE
  w.b = x.a OR w.k = 2)` crashes with `KeyError: None` inside the aggregate, and the prompt requires subqueries over
  outer CTEs. Only F7 runs long (~18 min median); F6 and F8 finish in under 5 min, even with a full spec.
  Reserves: cyclopts #921, anyio #1173, babel #1161, websockets #1730, pluggy #732, falcon #2731.
- **B2, B3, F3** were tuned over several single-task runs on 2026-10-07 (runs 203828 to 210531).
  Those runs used earlier, smaller versions of the tasks and are not counted above. B2 and B3 became
  three-defect regression reports because a single subtle bug was found in under a minute however
  misleading its symptom was.
- **F4** (2026-10-08): reference solution is 614 added lines in 7 files, with 82 hidden tests. It is
  reliable (3/3), but at about 9 min it is a third of the 30-min target. It shows that a
  parser-plus-compiler feature takes 3 to 4 times as long as F3, but spec size alone does not reach 30 min.
  Limits: `timeout_s 3600`, `budget_usd 40`, `max_turns 300`. CLI 2.1.295.
- **F5** (2026-10-08): reference is about 830 added lines (`rfc9535.py` plus CLI and README). The 735 hidden
  tests are the full JSONPath Compliance Test Suite (706 cases; `cts.json` vendored with its BSD-2
  license) plus 29 API, function-extension, CLI and edge-case tests. The container has no internet, so the
  RFC texts go into the repo; the agent cannot fetch them or the compliance suite. `validate-task`
  [ok] on developmenthost1 (grading 12.4 s).
- **F5 pilot, 1 run** (2026-10-08, CLI 2.1.295): **31 min**, which is the first task to reach the target. It
  failed only 2 of 735 hidden tests, the compliance-suite cases "functions, match, explicit caret" and
  "explicit dollar", which expect `^`/`$` to be anchors. RFC 9485's grammar makes them literal
  characters (`NormalChar` includes `%x5E` and `%x00-27`), and the agent followed the RFC as the prompt
  told it to. Those 2 cases are now excluded from the hidden tests (733 remain). The run's own
  `session.patch` passes all 733, and `validate-task` is [ok] again.
- **F5 calibration** (2026-10-09, run 20261009-064858-f773): 2 more runs, both passed: 1617 s ($4.38) and
  670 s ($2.20). Over 3 runs the median is **27 min**, but the spread is wide (11–31 min). The two long
  runs started a background subagent and then used `ScheduleWakeup`, so their transcripts contain
  several `result` events. Turns are now summed across them (59, 53 and 36); before the fix the
  report showed 1. Expect high variance in wall time on this task.
- **B4** (2026-10-09): candidate D1 built. tinycss2 v1.5.0 pulls in the css-parsing-tests corpus as a
  submodule, which `build-task` does not clone. `inject.patch` plants 16 one-line bugs and adds a
  *reduced* corpus, with the 1,567 cases the bugs break removed, so the repo's own 13,683 tests pass at
  the start state and the agent has no oracle for the broken cases. Each kept bug breaks between 1 and
  1,035 corpus cases (4 other candidates broke none and were dropped). Hidden tests run a copy of the
  upstream test file against the full corpus (16,968 tests, public domain). `reference.patch` reverts
  only the code. `validate-task` [ok] on developmenthost1 (grading 25 s).
- **B4 pilot, 1 run** (2026-10-09): passed all 16,968 hidden tests in **2.5 min** (15 turns, 14 tool calls,
  peak context 74k, $0.44). Listing one concrete symptom per bug turns the task into a checklist, and the
  model fixed all 16 one-liners from the symptoms alone. As it stands, B4 is level 2 in length. Ways to
  lengthen it: describe fewer, vaguer symptoms; make the bugs interact; or require work that cannot be
  read straight off the symptoms. Decision 2026-10-09: keep it as a level-2 bug task (limits moved to the
  L2 values: $5, 60 turns, 2400 s). It still needs 2 more pilot runs to count as calibrated.
- **B5** (2026-10-09): candidate D6 built from the real fix (`origin = "upstream-fix"`, `fix` pinned so
  `build-task` derives the hidden tests and `reference.patch`). The default regression collection from the
  repo root picked up `dateparser_scripts/` and `fuzzing/`, so `regression` is set to `tests`. The 3 hidden
  race tests failed 10/10 at the start state and passed 10/10 with the fix. Grading takes 65 s (24k
  tests). Two of the tests check that shared `Settings` are never mutated while parsing, so the prompt
  states that as an observed symptom. It also rules out a single global lock, which the tests do not check.
- **B5 pilot, 1 run** (2026-10-09): **passed in 8.5 min** (23 turns, 22 tool calls, no subagents, peak
  context 68k, $0.50). The agent changed 6 of the 8 files the upstream fix touched (≈290 changed lines)
  and wrote its own `tests/test_thread_safety.py`, which the hidden file of the same name overwrites at
  grading. Like F4, a real multi-module fix lands at about 9 min. Of the tasks so far, only F5's
  write-and-verify-against-a-large-spec shape has reached ~30 min.
- **Session stats caveat:** this agent (like the B1 and B4 runs) edited files through Bash (heredocs,
  `python -c`), not Edit/Write, so `session.html` reports 0 edits. `session.patch` and
  `diff_breakdown.json` are the reliable record of what changed.
- **B6** (2026-10-09): option 2 from the B5 discussion, a bug with F5's shape. The library is
  jg-rp/python-jsonpath-rfc9535 (MIT), tag v2.0.1, released 2026-10-09. `inject.patch` replaces about 196
  lines of correct code with about 30 simplified ones across 6 files, adds the RFC 9535/9485 texts under
  `docs/rfc/`, and moves the 8 test files that would expose the breaks out of the repo. Those 8 files plus
  the vendored compliance suite (`tests/cts/cts.json`, BSD-2) are the hidden acceptance tests, which
  makes 1,491 tests at grading. The agent keeps 155 passing tests. The prompt gives per-area failure
  counts and examples without naming the suite. `validate-task` [ok] (grading 1.8 s).
- **B6 pilot, 1 run** (2026-10-09): **3.5 min**, $0.73, 24 turns. It restored all five areas (≈600 changed
  lines including its own new test file) and failed only the 2 compliance cases where `^`/`$` conflict with
  RFC 9485. Those are now excluded, as in F5, and the run's patch passes all 1,604 tests. So repairing broken
  semantics inside a well-structured library is fast: the surrounding correct code shows what the missing
  logic should look like. What made F5 long was writing the implementation from scratch, with no existing
  structure to follow. B6 is collected as a level-2 bug.
- **B7** (2026-10-09): candidate D12, built from the real fix. Build issues and fixes:
  - `setuptools-scm` needs git metadata, so `install` sets `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_DISTRIBUTED`.
  - The offline container makes `get_ip()` warn and the repo's `filterwarnings = error` breaks collection,
    so a 2-line `inject.patch` adds an ignore next to the existing IPv6 one.
  - The IPv6 tests in `test_comms.py` cannot pass without IPv6. So `acceptance` is two node IDs: the
    regression test, plus `test_handshake_slow_comm`, the guard that rejects "add a handshake timeout".
  - `regression` is `distributed/comm/tests` (about 5 s).
  - The hidden test fails 10/10 (5 s hang) at the start state and passes 10/10 with the fix (0.05 s).
  - The prompt gives only the symptom, the flaky stress test, and that the stuck coroutine sits under
    `comm.core.connect` (client side). The cause is on the server/listener side.
- **B7 pilot, 1 run** (2026-10-09): **failed after 2.5 min**. The agent read `tcp.py`'s `_handle_stream` region
  but settled on a similar-looking listener-stop race in the `inproc://` transport. It fixed that, added its
  own test, and stopped without looping the stress test. Its summary admitted the fix "only explains hangs on
  inproc:// … if your production workers talk over tcp://, this isn't the cause". Changes after the run:
  - The prompt now says production uses `tcp://` between processes (a reporter would know this).
  - `--runslow` was added to `acceptance`, because the anti-timeout guard `test_handshake_slow_comm` had been
    silently skipped (marked slow).
  - Revalidated [ok] (grading 8 s).
  This is the first task that produced a plausible but wrong diagnosis rather than running long. Whether
  it reaches ~30 min, or is just unreliable, needs more runs.
- **B7 re-pilot, 3 runs** (2026-10-09, run 20261009-205034-8594): **3/3 pass**, all fixing `comm/tcp.py`, in
  111 s, 174 s and 775 s ($0.15–0.54). Once the report says `tcp://`, the client-side `connect` hint plus the
  transport narrow the search to the TCP listener, and the 8-line guard follows quickly. Median about 3 min,
  so B7 is collected as a level-2 bug (limits moved to the L2 values). Without the transport the agent
  misdiagnosed (first run). The hard version is one where the report does not narrow the transport and the
  agent has to *reproduce* the hang with the stress test, but that version failed rather than ran long.
- **B8–B10 pilot, 3 runs each** (2026-10-10, run 20261009-235014-4ff7):
  - **B8** (asgiref leak) passed 3/3 in about 45 s, so it is L1. Once `gc.garbage` is inspected, the
    contextmanager/except cycle is found immediately.
  - **B10** (werkzeug 1-byte loss) failed 3/3 in about 35 s, but only on upstream's changed *internal*
    chunking expectations in `tests/sansio/test_multipart.py`. All three patches pass the user-visible
    regression test. Grading was fixed: acceptance is `tests/test_formparser.py` only, the hidden sansio file
    is the repo's own copy, and the implementation-specific parametrized test is deselected. Collected as L1.
  - **B9** (websockets leak) failed 3/3 after about 27 min each, and the runs are **invalid**. The trial
    tagged its start commit `baseline`; websockets derives its version from `git describe --tags`, could
    not parse `baseline-0-g…`, and raised on import. Every test failed for the agent and at grading.
    `validate-task` missed it because its container had no git repo.
  - **Harness fixes:** the start commit is now marked with `refs/hai-proof/baseline` (not a tag), and
    `validate-task` runs the same git baseline step as a trial. B9 is being re-piloted.
- **B9/B11/B12 pilot, 3 runs each** (2026-10-10, run 20261010-012729-5d2e):
  - **B11** and **B12** (dynaconf) passed 3/3 in about 50–60 s, so they are L1.
  - **B9** was graded 0/3 after 27, 28 and 7 min. The failures were environmental: trial containers
    carry the egress-proxy variables, and websockets routes even local test connections (e.g.
    `ws://overridden/` with an explicit host) through a proxy when they are set. The unmodified start
    state fails 14 tests with them set and none without; validation had no proxy variables.
  - Re-graded without proxy variables: reps 0 and 1 **pass** (all 1,012 acceptance and 1,410 regression
    tests), and rep 2 fails one trio test. So B9 is **2/3 with a median of about 27 min**, but the agents
    also lost time to the same spurious failures.
  - **Harness fixes:** the grader strips proxy variables (grading is offline anyway); trials add lowercase
    `no_proxy`; the agent's Bash environment drops proxy variables via `CLAUDE_ENV_FILE` (only the
    `claude` process needs the proxy). B9 is being re-piloted to measure its length without the noise.
- **B9/B13/B14 pilot, 3 runs each** (2026-10-10, run 20261010-024512-e100):
  - **B13** (attrs) passed 3/3 in about 13 s and **B14** (pluggy) 3/3 in about 25 s, so both are L1.
  - **B9** passed **2/3 at 34–38 min**. The session data showed most of that time was spent in test runs
    (1,250–1,930 s per run): the agents ran the full suite, which hangs offline on the upstream
    `test_reconnect`, and waited out 500–600 s timeouts and `sleep` loops. That is environment friction,
    not diagnosis.
  - **Fix:** `inject.patch` for B9 and B15 now skips `test_reconnect` (hangs offline) and
    `test_close_keeps_handlers_running` (timing-flaky), each with a stated reason. B9 is being
    re-piloted to measure its honest length.
- **B9/B15/B16 pilot, 3 runs each** (2026-10-10, run 20261010-044729-2392), environment clean (no
  calls over 120 s in any trial):
  - **B9** passed **3/3 in 13–14 min** (78–102 turns, $1.34–2.18). With the hang gone, it is about half the
    earlier length. First edit at 9–26 s; the time goes into 28–39 test runs and 15–35 reproduction runs
    while the agents check each implementation for remaining reference cycles. It needs L3 limits (more
    than 60 turns) but is not a 30-min task.
  - **B15** passed 2/3 in 2–3 min. The failure was one trio *client* test (`test_aclose_waits_for_close_frame`,
    1006 vs 1000) in code the patch does not touch; re-running regression with that patch passed 6/6. The
    websockets suite flakes about once in 15 full runs at its default 1 ms timing unit, and a different
    timing test flaked during re-validation. **Fix:** B9 and B15 regression set upstream's
    `WEBSOCKETS_TESTS_TIMEOUT_FACTOR=10` (15/15 clean). Counted as 3/3; collected as L1.
  - **B16** (structlog) passed 3/3 in under 1 min: L1.
- **B17/B19 pilot, 3 runs each** (2026-10-10, run 20261010-062840-da87):
  - **B17** (xdist hang, two causes) **3/3 in 6.5–10 min**. Rep 0 was graded a fail: its fix reports
    "1 failed, 1 passed", the same as `--dist=load`, but upstream's tests assert "*5 failed*", a count
    specific to upstream's fix (the crashed test re-runs on each replacement worker). The hidden tests now
    assert the behaviour (the run finishes, the crash is a failure, the other test still runs); rep 0's
    patch passes them. Both 120 s calls were the agents reproducing the hang (part of the bug).
  - **B19** (tornado socket leaks) **2/3 in 9–12 min**; the miss (3.5 min) fixed the TLS paths but not the
    cancelled multi-address connect (`ConnectorTest.test_cancel`). All three regression runs failed only
    `test_source_port_fail`. That is environmental: Docker sets `ip_unprivileged_port_start=0`, so the
    first bind to port 1 in a fresh container succeeds. **Fix:** trial and validation containers now set
    it to 1024; the three patches pass that test 3/3 with it.
  - Both are genuine multi-cause defects, but at 6–12 min they are L2, not 30-min tasks.
- **B18 pilot, 3 runs** (2026-10-10, run 20261010-073922-d475): tornado cancellation hang, **2/3 in
  2.3–6 min**, so L1 in practice. Every fix passed all 13 acceptance tests. The miss added a new test
  module without registering it in `tornado/test/runtests.py`, which tornado's own suite checks: a genuine
  regression failure. The incomplete-first-fix shape did not slow the agent; it traced `CancelledError`
  through all the paths from the report in one pass. (The session classifier now also counts project
  runners such as `python -m tornado.test.runtests` as test runs.)
- **B20 pilot, 3 runs** (2026-10-10, run 20261010-075703-3c6a): astropy masked-index leak, **3/3 in
  1.6–4.3 min**. A bug that resisted maintainers for 2.5 years (27 comments, two failed PRs) took the model
  about two minutes; upstream's own fix PR says an AI assistant found the cause. Human difficulty does not
  predict model difficulty. Collected as L1.
- **B21 pilot, 3 runs** (2026-10-10, run 20261010-081428-1abe): sqlalchemy async cancellation leak,
  **1/3 in 3–5 min**. Both failures are genuine partial fixes of a two-cause defect. Rep 1 made the context
  managers wait for their close but missed the pool path (a cancellation during reset on return loses the
  slot). Rep 2 fixed the pool path but not the background close. Neither built a deterministic
  cancellation sweep; each tested only the cause it had found. Short, but it discriminates, which suits
  treatments that push for verification. Kept at L2 limits.
- **Scaling seen so far:** wall time grows with how much code has to be written and checked
  (reference patch size: F3 ~230 added lines → 2.7 min; F4 ~615 → 9 min). The model does not slow down on a bug that has a
  "misleading symptom". For about 30 min, expect a reference of roughly 1,500 to 2,000 lines, or work
  whose correctness the agent has to establish against a large external spec.

## Suites

Decided 2026-10-10. The goal is a sample of bugs and features that shows **large** effects between arms; the
generated per-task data (time, tokens, cost, transcripts) matters more than the headline results. Levels set limits
(time / budget / turns), not a difficulty tier: `--mode quick` simply drops the L3 (long-limit) tasks.

| Suite | Tasks | Why | Est. per arm per rep |
|---|---|---|---|
| `standard` (default) | B5, B6, B7, B9, B17, B19, B20, B21, F3, F4, F5, F6, F7 | One task per project. Mixed pass rates (B6, B7, B19, B21, F7) carry the success signal; steady multi-minute tasks (B5, B9, B17, F4, F5) carry the time/cost signal. Covers 2–27 min. | ~$12, ~1.9 h serial |
| `smoke` | B1, B13, F1 | Always pass in under a minute; checks the harness works before a real run. | ~$0.20 |
| `diagnosis` | B-DP-1, B-DP-2 | 0/3 for plain Claude Code; only informative for treatments aimed at diagnosis. Run alongside `standard`. | ~$1.30 |
| `userloop` | F9–F25 | Feature requests with the decisive API detail moved from the prompt to `user.md`; meaningful only with `--user informative` (the prompt alone underdetermines the hidden tests). | F11/F12 piloted 2026-10-19 (run 8fcc): ~$0.45 per rep for both |

### Cost tiers and report order

Decided 2026-10-11 from plain-arm trials (Sonnet 5.5, CLI 2.1.293–2.1.296, default effort; runs before each task's
last change left out). Reports group the standard tasks into three cost tiers and list them in this fixed order,
cheapest first, set once in each task.toml (`cost_tier`, `report_order`) and never re-ranked per run.

The sort key is median **output tokens**. Total tokens are dominated by cache reads, which grow with turn count
rather than work done, and rank the tasks differently (B9 and B5 move up); output tokens track cost almost
exactly (Spearman 0.98). Near-ties were ordered by mean bootstrap rank (2,000 resamples), which is noted where it
decided the order; within a tier the order is not statistically stable.

| Order | Task | Tier | Median output tokens | Median cost | Plain pass | Note |
|---|---|---|---|---|---|---|
| 1 | B17 | low | 9.0k | $0.29 | 8/8 | |
| 2 | B20 | low | 10.4k | $0.30 | 11/11 | |
| 3 | B7 | low | 13.2k | $0.39 | 4/10 | B7 before B19 on mean bootstrap rank (3.4 vs 3.6) |
| 4 | B19 | low | 12.8k | $0.36 | 4/8 | |
| 5 | B21 | low | 14.7k | $0.45 | 6/11 | |
| 6 | F3 | low | 18.9k | $0.43 | 8/8 | on the low/medium border by tokens; low by cost |
| 7 | B5 | medium | 19.0k | $0.57 | 11/11 | |
| 8 | F6 | medium | 22.8k | $0.54 | 8/8 | |
| 9 | B6 | medium | 23.2k | $0.60 | 3/8 | |
| 10 | F7 | high | 46.3k | $1.04 | 5/8 | F7 before B9: medians within 2%, tied mean rank; F7 is cheaper |
| 11 | B9 | high | 47.2k | $1.40 | 7/8 | |
| 12 | F4 | high | 74.3k | $1.59 | 8/8 | |
| 13 | F5 | high | 148.6k | $2.86 | 7/7 | always last |

Tasks outside `standard` have no tier and are listed after the tiers, by id. Pass counts are from the
`baseline.json` backfill (below), which leaves out these runs, each made before a later change to the task:
B2, B3 and F3 before 20261007-211025 (final versions); B4 20261009-161628 (limits); B6 20261009-192311 (two
compliance cases excluded); B7 20261009-195010 (prompt fix); B9 and B15 before 20261010-085001 (inject patch,
timeout factor); B10 20261009-235014 (grading fix); B17 and B19 20261010-062840 (re-grades never written back
to trials.jsonl); F5 20261008-215805 (two compliance cases excluded).

Untagged tasks stay in the library and run with `--suite all` or `--tasks`: B15, B18, F8 and B12 repeat a
project already in `standard`; B2–B4, B8, B10, B11, B14, B16 and F2 are too quick to show a time difference
(B4 is first in line if the standard set needs to grow). Typical standard A/B: `--treatment X --reps 3`
(78 agent runs, about $75).

## Candidates

Ranked by how likely they are to reach about 30 min, while meeting the rules in task-authoring.md
(permissive license, test suite under about 60 s, no services).

| # | Kind | Repo (license) | Idea | Why it might reach ~30 min | Risks / open checks |
|---|---|---|---|---|---|
| 1 | feature | jsonpath-ng (Apache-2.0) | **Built as F5 (2026-10-08).** **RFC 9535 compliant mode**: a `jsonpath_ng.rfc9535` parser and evaluator. Hidden tests are the JSONPath Compliance Test Suite (`cts.json`, BSD-2, several hundred cases). | Full grammar, filter expressions with RFC comparison semantics, the function type system (`length`, `count`, `match`, `search`, `value`), I-Regexp, slices, normalized paths, rejecting invalid queries. Upstream issue #223 says jsonpath-ng is not compliant. Scope can be adjusted by choosing which CTS sections to include. | Standalone RFC 9535 libraries exist (`jsonpath-rfc9535` on PyPI), so a model may recall them. The reference is a large authoring job. Check that the CTS runs in under 60 s (it should). |
| 2 | feature | Jinja2 3.1.6 (BSD-3) | **F4 expanded**: add class patterns (`Point(x=0, y=y)` with `__match_args__`), a pattern-test registry on `Environment`, and match in `{% set %}` blocks. | F4 already takes 9 min. Three more subsystems might triple it. | Making the prompt longer gives diminishing returns. It is still one well-known language feature that a model can copy from Python. |
| 3 | bug | sqlglot (MIT) | **Multi-defect regression report** across tokenizer, parser, optimizer and generator (transpilation gives wrong SQL). | Much larger codebase. Optimizer bugs show up far from their cause. | Test suite runtime not yet checked against the 60 s limit. Earlier experience: bugs get found fast, so it needs 5 or more defects. |
| 4 | feature | sqlglot (MIT) | **New dialect** for an engine sqlglot does not cover yet. Hidden tests are transpilation round trips. | Tokenizer, parser and generator overrides, plus many function mappings. | First confirm the engine is really absent and its syntax is public. The model may know the engine poorly. |
| 5 | feature | tomlkit (MIT) | **TOML 1.1 support** (multi-line inline tables, trailing commas, `\e` and `\xHH` escapes, optional seconds), round-trip preserving. Pin a tag from before upstream supported it. | Style-preserving round trip makes every change touch both the parser and the writer. | tomlkit may already support 1.1, in which case the upstream fix is public and likely in training data. Probably 10–15 min, not 30. |

### Defect candidates (researched 2026-10-09)

The lesson from B2/B3 is that single bugs, even three of them, are found in under a minute. So each
candidate below is a conformance regression: a library fails many cases of a public corpus, for
10–15 independent reasons spread over a large module. Hide part of the corpus from the agent, or it
can use the shipped copy as an oracle.

| # | Repo (license) | Idea | Hidden tests | Risks |
|---|---|---|---|---|
| D1 | **Built as F25.** tinycss2 (BSD-3, Kozea) — **built as B4** | About 12–15 injected bugs across `tokenizer`, `parser`, `serializer`, `nth` (An+B) and `color3/4/5`. The issue reads "after upgrading, many CSS Syntax / Color results differ from browsers". | css-parsing-tests (public domain): stylesheet, rule/declaration lists, An+B and the color_* suites | The repo vendors the corpus, so held-out files must be removed from `repo/`. Bugs that are too local would finish in 5–10 min. |
| D2 | **Built as F20.** tomli (MIT) | About 12 injected bugs in `_parser.py`/`_re.py`: datetimes, string escapes, multiline trimming, table redefinition, inline-table immutability, number formats, invalid-input rejection. | toml-test (MIT), valid and invalid cases | Shipped test data gives a partial oracle. A well-known codebase. TOML 1.0 vs 1.1 ambiguity. |
| D3 | markdown-it-py (MIT) | About 12–15 bugs in block rules (lists, blockquote, fences, HTML blocks) and inline rules (emphasis balancing, links, entities). | CommonMark spec examples (CC-BY-SA, needs attribution) | A port of a well-known JS algorithm. The shipped spec tests are an oracle. |
| D4 | **Built as F23.** jsonschema (MIT) | Injected bugs in keyword and draft handling (`unevaluated*`, `$dynamicRef`, `multipleOf`, `uniqueItems` 1 vs true). | JSON-Schema-Test-Suite (MIT) | The suite may exceed 60 s. Native `rpds-py` dependency. Corpus very well known. |
| D5 | **Built as F19.** PyYAML (MIT) | Mutated scanner, parser and composer. | yaml-test-suite (MIT) | Real conformance gaps are architectural, so it would need injected bugs only. |

### Large-fix defect candidates (researched 2026-10-09)

B4 showed that a list of symptoms makes even 16 bugs a 2.5-minute checklist. So these are **real
upstream bugs whose fix is large**: about 150+ non-test lines and a redesign rather than a one-liner.
They were merged in 2025–2026, which lowers the chance the model has seen the fix. Hidden tests come
from the fix PR. PR numbers, dates and sizes were checked with `gh api`; nothing has been built.

| # | Repo (license) | Bug / fix | Merged | Fix size | Hidden tests | Risks |
|---|---|---|---|---|---|---|
| D6 | **Built as F22.** dateparser (BSD-3), **built as B5** | Not thread-safe (issues #441, #1291): concurrent `parse()` hits check-then-read races in the size-limited dictionary/locale caches → random `KeyError`. PR #1346 reworks caching and shared state across the language pipeline. Base `de7b986f`, fix `cd9bb13e`. | 2026-08-24 | 9 files, +383/−173 (≈ +255/−173 code) | new `tests/test_thread_safety.py` (+128): `setswitchinterval(1e-7)`, `CACHE_SIZE_LIMIT=1`, concurrent parse/search | Race tests are probabilistic (repeat in grading). The suite (~24k tests, ~27 s) needs extra deps and Linux (`time.tzset`). Issue is from 2018, fix is recent. |
| D7 | click (BSD-3) | Flag options: envvar / `default` / `flag_value` / `type` reconciliation wrong (#2952: flag always true when any envvar set). PR #2956. Base `5c1239b0`, fix `565f36d5`. | 2025-07-01 | 8 files, +421/−89 (≈ 160 code lines in core.py, types.py) | parametrized `tests/test_options.py` (+239) | Expected semantics are upstream's choices, so the prompt must state them. 2025 merge, so some contamination risk. |
| D8 | icalendar (license NOASSERTION, check LICENSE) | Date-only PERIOD parses but `to_ical()` raises; needs date→midnight datetime conversion and timezone propagation (#1633). PR #1645. Base `58310758`, fix `30ec6eef`. | 2026-08-12 | 11 files, +352/−58 | `test_issue_1633.py` (+197) + .ics fixtures | Mostly one file. The "accept, not reject" decision must be stated in the prompt. |
| D9 | **Built as F24.** sqlglot (MIT) | OFFSET/ORDER/TOP/FETCH attached to the wrong scope in set operations for ClickHouse/T-SQL. PR #8385. | 2026-09-21 | 7 files, ≈ 130 lines | dialect tests asserting exact SQL | Exact-string expectations leave the right answer under-determined. |
| D10 | **Built as F21.** werkzeug (BSD-3) | `parse_options_header` ambiguities. PR #3231. | 2026-08-10 | ≈ 190 lines | ≈ 20 test lines | Part bug fix, part performance work, and thin tests. Weak. |

| D11 | python-markdown2 (MIT; API says NOASSERTION, LICENSE.txt says MIT) | Emphasis/strong mis-parsing (#632 `**A_1** through **A_2**` → crossed `<em>`; #645, #652, #653, #654). PR #665 rewrites emphasis to GFM delimiter-run (left/right-flanking) rules. Base `a30892f6`, fix `c87a78c0`. | 2025-12-17 | 1 file, +451/−50 | `gfm_emphasis` case (≈268 lines of GFM spec snippets) + `middle_word_em_escaped_char` | One file, about 400 lines (estimate 10–15 min). One large case file gives all-or-nothing feedback. The PR body describes the algorithm, so keep it out of the prompt. |

Third search (2026-10-09), looking for real fixes of 500+ non-test lines: **none found** in about 90 permissive
pure-Python repos. Large "fix" PRs were mostly test data or features. D11 was the closest. The others
(fonttools #4169, pydicom #2265, networkx #8616) change fewer than 200 lines of code. Conclusion: at this
size, real upstream bug fixes top out around B5's length (about 9 min). The ~30-min bug slot needs B6's
shape: a bug whose fix is feature-sized and checked against a spec.

### Concurrency candidates (fourth search, 2026-10-09)

The shape here is a multi-component concurrency defect with a **small fix but a symptom far from the
cause** (no traceback into the faulty code), so the time goes into diagnosis. PRs were checked with `gh api`.
Nothing has been cloned or run yet.

| # | Repo (license) | Symptom → cause | Merged | Fix | Regression test | Risks |
|---|---|---|---|---|---|---|
| D12 | dask/distributed (BSD-3), **built as B7** | Retiring/rebalancing workers under churn occasionally **hangs forever**; no error logged (seen as flaky `test_RetireWorker_stress`). Cause: in the TCP comm layer, `listener.stop()` runs between accept and `_handle_stream`, `abort_handshaking_comms()` never sees that stream, and the client waits in a handshake that has no timeout. Symptom in AMM/scheduler, cause in `comm/tcp.py`. PR #9315, base `2d43f7f6`, fix `4db4e05c`. | 2026-07-02 | `comm/tcp.py` +8 | `test_stop_listener_during_handle_stream`: forced interleaving (monkeypatched `handle_stream` calls `stop()` first), deterministic, ~5 s | Heavy dependencies (dask, tornado, msgpack, …). The full suite is far over 60 s, so `regression` needs a subset (e.g. `distributed/comm/tests`). The hidden test names the failure, so the prompt must give only the hang. |
| D13 | anyio (MIT) | After cancelling a task waiting on `Lock`/`Semaphore`, a later task hangs (asyncio backend only, timing-dependent). A cancelled head waiter stays queued. PR #1145, base `d517ee1d`, fix `f8b9f011`. | 2026-06-15 | `_backends/_asyncio.py` +30/−17 | 2 deterministic tests | Small, single-module library, so the cause is near the symptom. |
| D14 | dask/distributed (BSD-3) | Worker startup failure with a bad kwarg sometimes reports a bare "Nanny failed to start worker process" and loses the real exception (process-exit vs queue-poll race). PR #9327, base `90e1a846`, fix `0f72f8f2`. | 2026-07-09 | `nanny.py` +19/−6 | deterministic forced race, spawns a subprocess | Has a traceback; fix clustered in one place. |
| D15 | anyio (MIT) | `CapacityLimiter(1)` silently lets 2 tasks in (`available_tokens` < 0). Borrower registered only after the woken waiter resumes. PR #1172, base `6f82b253`, fix `6bbc6c33`. | 2026-07-12 | +6/−5 | deterministic | Local cause; follow-up PRs leave hints in history. |

**Concurrency pick: D12** (dask/distributed #9315). The hang appears in the scheduler/worker retirement
path, the cause is an 8-line guard in the TCP listener of a codebase with thousands of files, and the
hidden test forces the interleaving deterministically. Before building: confirm the dependency footprint
installs in the image, pick a regression subset under ~90 s, and run the hidden test 10× before and after
the fix.

**Recommendation: D6 (dateparser thread safety).** It is a clean, reproducible user report with a
multi-module fix and a ready-made test file, merged in the last two months. The open question is
whether the race tests are deterministic enough to grade. Validate it by running the hidden tests
about 10 times against both the start state and the reference.

### Leak / perf and hard-to-diagnose candidates (fifth and sixth searches, 2026-10-09)

Built: asgiref #508 (B8), websockets #1752 (B9), werkzeug #3081 (B10). Not built, kept as backups:
- **Markdown #1631** (ReDoS in the reference processor, `'[id]:' + ' ' * 50000` takes about 8 s). The fix is a one-token regex change, and a profiler would find it immediately.
- **structlog #807** (module-level `WRITE_LOCKS` dict pins file objects). The issue names the dict.
- **Markdown #1621** (inline processor rescans from 0). The upstream test asserts the mechanism, not behaviour.
- **werkzeug #2939** (a 2024 ReDoS fix that also changes behaviour).
- **pyparsing #618** (`Word.copy()` loses its regex when the chars include a space). Its traceback narrows the search.
- **anyio #1111** (100% CPU spin after cancel). The issue body states the cause, so a custom report would be needed.

**Seventh search (interaction bugs, 2026-10-09):** built dynaconf #1434 (B11) and #1423 (B12). Backups:
attrs #1513 (nested `validators.disabled()` re-enables validators globally; fix +3/−1) and pluggy #646
(`unregister` leaves a second hookimpl of the same plugin firing).

### Eighth search: incomplete first fixes, multi-cause leaks, large-system concurrency (2026-10-10)

Shape sought: one user-visible symptom with several independent causes, or an upstream fix that was
incomplete, so the obvious fix fails the hidden tests (B9 at 14 min is the model: several reference
cycles across implementations, each confirmed by experiment).

Built:
- **B17** pytest-xdist #1324 + #1328: `--dist=loadgroup` hangs after a crashed worker is replaced; two
  root causes, the second found after the first fix shipped. Fix ~16 lines in one scheduler module.
- **B18** tornado #3695 + #3749: awaiting a cancelled future hangs handlers, `@gen.coroutine`, `multi`,
  `with_timeout`, `chain_future`. The first fix covered only `RequestHandler._execute`. Built with the new
  `[source] exclude` to leave out #3749's separate websocket/HTTP1Connection/tcpclient hardening.
- **B19** tornado #3735 + #3745: sockets leak after connect timeouts or abandoned connects via four paths
  (start_tls ownership hand-off, TLS timeout, cancelled multi-address connect, simple_httpclient's own
  connect timer). The PR's synchronous-connect-error tests are left out of acceptance.

Harness changes made while building B17–B19:
- `[source] exclude` (DESIGN §4.1) leaves parts of a multi-defect upstream fix out of the hidden tests and
  the reference.
- The grader adds its `--ignore <acceptance file>` flags only to pytest regression commands. Tornado's
  suite must run under `python -m tornado.test.runtests`; under pytest about 360 tests fail on its logging
  and warning setup. So B18/B19's regression also runs the hidden test files. For B19 the separate
  defect's tests were removed by hand from the hidden `tcpclient_test.py` (noted in task.toml).
- B17's and B18's start states hang (that is the bug). Each grading step is now capped at 600 s and the
  grader exec gets room for both steps (before, a hang in both overran the 1,200 s exec timeout and crashed
  validation).
- Trial and validation containers set `net.ipv4.ip_unprivileged_port_start=1024` (see the B19 pilot).
- B18's acceptance first ran single tests under pytest, with a grading-only `conftest.py` that silenced
  `tornado.access`. Since 2026-10-10, B9, B15, B18 and B19 run both grading steps with the project's own
  runner via `acceptance_cmd`, and the conftest is gone. Under pytest, B9's grading failed correct work
  (docs/prompt-degradation.md).

Backups (verified SHAs in the search reports; not built):
- uvicorn #3048 → #3050 → #3053 (BSD-3): server-initiated WebSocket close gives clients 1006 / truncated
  data, three layered fixes across the sansio and wsproto implementations. Partly adds flow control (a
  feature-like piece), so check fairness before building.
- anyio #1304 → #1314 → #1318: cleanup skipped when a cancelled task closes temp dirs / files / streams;
  three ~5-line sites. Probably L1–L2.
- aiohttp #13504 (Apache-2.0): two flow-control stalls (upgrade + pipelining); touches the Cython parser,
  so check that the pure-Python parser exercises it.
- celery #10716 + #10715 (BSD-3): GC-triggered re-entrant redis pubsub deadlock; hidden tests are tied to
  internal names and would need rewriting to behaviour.
- jupyter_server #1619 (BSD-3): three FD leaks in one file; kernel start-up may be slow in a container.
- scrapy #8245, networkx #8892, fsspec #2069 / #2154 + #2163, filelock #745 + #810, kombu #2694,
  prefect #23089, urllib3 #5260, pyparsing #643 + #645, packaging #1248 → #1411: smaller or single-module.

### Ninth search: bugs that were hard for maintainers (2026-10-10)

Shape: closed issues with long investigation threads (15+ comments, wrong hypotheses, failed fix PRs) and
a cause far from the symptom. Difficulty for humans is the best remaining proxy for diagnosis time.

Built:
- **B20** astropy #16089 → PR #20456: indexed `MaskedColumn` lookups grow memory without bound. Open 2.5
  years, 27 comments, two failed fix PRs; the cause is numpy's `MaskedArray._optinfo` carrying `indices`
  into derived arrays. 14-line fix. Acceptance is the upstream tracemalloc test only (the PR's other test
  inspects `_optinfo`). Needs a C compiler: `gcc` was added to the base image.

Backups:
- gevent #1865 → PR #2191 (MIT; bundled libev is BSD/GPL dual): `patch_thread` + `ThreadPoolExecutor` +
  subprocess hangs at fork, because `concurrent.futures`' at-fork lock was imported before patching. Tests
  must run as monkey-patched scripts through gevent's runner; one asserts the lock type.
- sqlalchemy #12710 (fix 6f899879, 2026-09-30): async connections leak from the pool under task
  cancellation. Hidden tests depend on new test infrastructure in `lib/` and a new private symbol.
- pytest-asyncio #724 → PR #1430 (Apache-2.0): "unclosed event loop" ResourceWarning in a later sync test;
  4-line fix, probably L1.
- xarray #11629 (netCDF thread safety; probabilistic tests), poetry #10944 (solver; feature-like).

**Harness fixes found while building B8–B12:**
- The grader now kills the whole process group on timeout. Before, a timed-out `shell=True` regression
  left pytest running into the next step.
- `build-task` forces `core.eol=lf`, because a `* text=auto` `.gitattributes` produced CRLF checkouts on
  Windows (werkzeug).
- The trial-image hash no longer normalises CRLF, so a CRLF→LF rebuild gets a fresh image instead of a
  stale one.

### Tenth search: ambiguous features merged after the model cutoff (2026-10-19)

For the `userloop` suite, after F9 (agent never asks) and F10 (contaminated). Criteria: merged on or after
2026-07-01, several plausible designs with the merged one non-default on at least two test-visible points,
pure Python, 50–600 changed lines. Two searches, one from merged PRs and one from debated issues. Merge
dates and base SHAs were checked with `gh`. Nothing has been cloned, built or run yet.

| # | Upstream | Merged | Size | Decisions an agent would likely get wrong | Risks |
|---|---|---|---|---|---|
| U1 | **Built as F11.** copier #2849 (issue #2763), base `38f9bb0` | 2026-10-06 | +236/-13 | A separate templatable `ask` key, not `hide` and not `_ask` inside `when`; `when: false` beats `--ask` and discards the answer; an `ask: false` question keeps its previous answer on update, else records its default; `--ask` takes globs. 14-row truth table in the tests | Heavy install (jinja2, questionary, plumbum, pydantic) and needs `git`; the prompt tests use pexpect, so hidden tests should call `run_copy`/`run_update` |
| U2 | mashumaro #339 (issue #176), base `71cd4d9` | 2026-09-17 | +235/-52 | Multiple aliases per field: the first is canonical for dump and schema; on load they are tried in order and the first key present wins; precedence field option > annotation > config, with no merging; the field name is tried after the aliases | Follow-up fixes landed upstream; codegen-heavy library; test dependencies (orjson, msgpack) |
| U3 | **Built as F12.** towncrier #740, base `b3a363e` | 2026-08-15 | +77/-14 | `wrap` takes an int instead of gaining a second option (maintainer's request); `True` means 79; `wrap <= 0` falls back to 79, not "off"; `True` is not the int 1 | Small, so few decisions; tests run under `trial` |
| U4 | pytest-rerunfailures #365 (issue #230) | 2026-09-09 | +547/-26 | `condition` callables take the exception; string conditions see it as `error`; every failed phase counts, each evaluated once; a condition that raises gives a warning, even under `filterwarnings=error` | Large; the xdist and subtests parts may need cutting |
| U5 | stamina #160 (issue #151), base `22e52e0` | 2026-10-19 | +281/-6, mostly docs | `set_/get_process_details` setter pair, not an argument on `set_on_retry_hooks` (the maintainer's first idea); runs once per retry for every hook; `None` clears | The API names can only come from the brief |
| U6 | pdm #3875 (issue #3809) | 2026-09-03 | ~172 | `exclude-newer-override`: `false` disables and `0` is rejected (the issue proposed 0); CLI `PKG=DATE` beats pyproject; names normalised | Heavy fixtures; famous repo |
| U7 | dateparser #1443 (issues #701, #868), base `260fe0c` | 2026-10-02 | +513/-19 | `STRICT_DATE_ORDER` became an opt-in enum `none`/`year`/`all`, not a bool; raises without an explicit `DATE_ORDER`; a rejection returns `None` with no day/month swap | Near the size limit; large reject set |
| U8 | starlette #3431 (issue #2155), base `c41236c` | 2026-08-08 | +619/-9 | Counts bytes received, with `Content-Length` used only to fail fast; nested routes can raise or lower the limit; multipart files count | Too large unless scoped down |

Weaker: bump-my-version #430 (`--to`; no debate in the thread), towncrier #735 (`--sub-issue`; mostly a name),
parsel #351 (decided in review, not debated), rerunfailures #336 (guessable), hatch #2306 (heavy, needs the
internet). Near-misses include pydantic-settings #949, RxPY #711, multidict #1288, black #5433, tox #4020,
whenever #403 (side branch), jsonpickle #609 and loguru #1413.

Fallback, synthetic features if none of these work out. These are unverified sketches:
- schedule: blackout windows, where a blocked run is deferred rather than skipped.
- parse: `{name?}` optional fields that are absent from `.named` rather than `None`.
- cachetools: `TTLCache.touch()` that returns `False` for a missing key and resets the expiry from now.

### Eleventh search: decision-dense features (2026-10-19)

Pilot 8fcc showed F11 and F12 have no headroom: plain Claude Code's own 2–4 questions covered every decisive
point (informative 6/6). A task that can separate a better interviewer needs many test-visible decisions,
several of them second-order. Second-order means edge cases, error types, precedence, interaction with existing
options, or update/round-trip behaviour that an agent wouldn't think to ask about. Counts are decisions/second-order,
read from the PR tests (not run). All were merged after 2026-07-01.

| # | Upstream, base | Merged | Size | Decisions | Notes |
|---|---|---|---|---|---|
| H1 | **Built as F13.** platformdirs #585 `place_*_file`, `46843f1` | 2026-09-26 | +222/-5 | 11 / 8 | Each created directory gets 0o700 one level at a time; existing directories are untouched; applies with or without `ensure_exists`; rejected names create nothing; no-home `RuntimeError`; runtime-dir `PermissionError` propagates. Error messages are pinned by regex, so the brief must carry them. Fast, pure Python, Linux modes |
| H2 | **Built as F14.** RxPY #711 `zip_latest`, `b5dc66c` | 2026-10-16 | ~110 src | 12 / 8 | Completion semantics: a pending value contributes one final tuple; completes as soon as no further tuple is possible; empty source stops later subscriptions; zero sources `ValueError`. Black-box TestScheduler tests |
| H3 | **Built as F15.** werkzeug #3243 strict int/float converters, `ef518e4` | 2026-08-19 | +217/-95 | 10 / 8 | Non-ASCII digits rejected; validation on build too; `fixed_digits` ignores the sign; overflow to inf gives 404; no scientific notation on build. Framed as tightening, not a new feature |
| H4 | **Built as F17.** pdm #3875 `exclude-newer-override`, `4abfe39` | 2026-09-03 | ~60 src | 12 / 9 | The issue's `0` became `false`; CLI beats pyproject per package; overrides alone force update-all; uv argv pinned. Tests set the internal `core.state.exclude_newer_overrides`; heavy fixtures; famous repo |
| H5 | **Built as F18.** pytest-rerunfailures #365, `78561a5` | 2026-09-09 | ~150 src | 13 / 11 | Densest, but 40–60+ min of tangled rerun-protocol work, so failures may come from coding rather than missed questions. Drop the xdist and private-attribute tests |
| H6 | **Built as F16.** platformdirs #586 `find_*_file(s)`, `ba1cc1e` | 2026-09-26 | +212 | 8 / 6 | Overlaps H1 on name validation; don't use both in one comparison |
| H7 | pytest #14824 plugin import exit codes, `59e7f3a` | 2026-08-30 | +268/-33 | 10 / 8 | Unit tests import internals (`PluginImportFailure`); keep only the acceptance tests |

Rejected for this purpose: dateparser #1443 (about 100 edge-case strings no interview can cover), starlette #3431
(implementation traps and pinned constants), stamina #160 and mashumaro #339 (second-order points are guessable).
Near-misses: werkzeug #3288 (not fully read), pytest #15153, cattrs #788, syrupy #1222, filelock #803.


### Twelfth search: more decision-dense features (2026-10-20)

After the overnight runs, only F13–F15 separated an interviewing treatment from plain, so the effect rests on three
tasks. Same criteria as the eleventh search, plus: no decisions that hinge on message wording, no private-internal
tests, no protocol plumbing (F18's lesson). About 200 repos swept by merge date. Merge dates and first-parent base
SHAs verified with `gh`; for several PRs `baseRefOid` is not the first parent, so use these. Nothing cloned or run.

| # | Upstream, base | Merged | Size | Decisions | Notes |
|---|---|---|---|---|---|
| D1 | icalendar #1852 `vRecur.count`, `8e80304` | 2026-09-30 | +69 src | 12 / 7 | 0 is valid and stored; bool `TypeError`; negative raises `InvalidCalendar`, not plain `ValueError`; first of several values; empty list reads `None`; `del` when unset is a no-op, setting `None` deletes; unreadable stored values raise on read. The PR body says "ValueError if <1" but the code allows 0: brief follows the code. One message-pinned test to drop. Sibling #1861 `wkst` (`d68d728`): use one |
| D2 | packaging #1377 `Requirement.__replace__`, `7464e38` | 2026-10-20 | +54 src | 10 / 7 | No-op replace returns an equal, distinct instance; validated by re-parsing (`InvalidRequirement`); specifier deep-copied; marker extras normalised; subclasses preserved; unknown keyword `TypeError`. `copy.replace` tests need Python 3.13 (skip on 3.12). Don't pair with D7 |
| D3 | tldextract #374 `TLDEXTRACT_PUBLIC_SUFFIX_LIST_URLS`, `9f86422` | 2026-09-29 | +40 src | 9 / 6 | Newline-delimited, blanks skipped; empty string means no fetch; local file paths become `file://`; explicit argument wins, `()`/`None` still disables; read at construction, not import. Check the suite runs offline |
| D4 | attrs #1592 generator `on_setattr` hooks, `d3a98cf` | 2026-08-01 | ~70 src | 9 / 6 | Yielded value is what gets set; not run in `__init__`; exception before yield keeps the old value, after yield keeps the new one; second yield `RuntimeError` with the generator closed; not allowed in `setters.pipe`. Exclude the private `test_compat` additions; one message pin |
| D5 | bidict #393 mutation during `OrderedBidict` iteration, `77ade42` | 2026-08-23 | +61/-17 src | 8 / 6 | Every mutation kind raises in both directions; mutation through `.inverse` counts; mutating on the last item raises (unlike `OrderedDict`); value-only update allowed; an unadvanced iterator also raises. Framed as a fix, but tests are behavioural |
| D6 | packaging #1313 `SpecifierSet.is_subset/is_superset/is_disjoint`, `189a76d` | 2026-07-21 | +64 src | 8 / 5 | Unsatisfiable set is a subset of and disjoint from everything; `""` is not a subset of `>=3.12`; differing `prereleases` (unset vs `False`) `ValueError`; `===` `ValueError`; wrong type `TypeError`. Messages matched: disclose or relax |
| D7 | packaging #1457 `Specifier/SpecifierSet.__replace__`, `fc61337` | 2026-10-20 | +75 src | 9 / 6 | Unchanged replace returns `self` (the opposite of D2); `prereleases=None` restores auto-detection; validated; subclasses preserved. Python 3.13 for `copy.replace` |
| D8 | pluggy #732 hookspec argument defaults, `6e836fd` | 2026-09-22 | ~18 src | 8 / 5 | Spec default fills an omitted argument, also for historic replay and `call_extra`; falsy defaults honoured; missing arg without default `PluginValidationError`; spec added after registration still works. Follow-up #738 (`f51e3a7`) flips the precedence: a precedence task on its own |
| D9 | click #3677 `style()` colour validation, `8dd4d60` | 2026-07-08 | +27 src | 10 / 5 | `ValueError` not `TypeError`; `fg=0` honoured; bool rejected; 0..255; names case-sensitive; RGB exactly three ints, list accepted. Message "Unknown color" matched |
| D10 | jsonpath-ng #289 RFC 9535 slices and `[*]`, `ccb9533` | 2026-10-16 | +22/-43 src | 10 / 5 | `[*]` on objects yields values, on scalars nothing; slices on non-arrays yield nothing; no phantom copies under `..`. An agent that knows RFC 9535 needs little interviewing |

**Vetting (2026-10-20).** Each candidate was cloned and its tests run locally (Windows, Python 3.12, HTTP proxy
blocked; not yet in the Linux container). "Fails at base" = the fix's test files on the base checkout. No API spend.

| # | Verdict | Fails at base | Grading | Decisions (2nd-order) | Edits needed / notes |
|---|---|---|---|---|---|
| D5 | build | 14 of 16 | ~5 s | 7 (7) | None (exclude CHANGELOG). No prior discussion; a size-change check misses `move_to_end`/`forceput`, a per-bidict counter misses `.inv` |
| D2 | build | 6 (+1 skips on 3.12) | ~3 s | 13 (11) | None; brief says it must also serve `copy.replace` on 3.13. `Version.__replace__` at base hints the sentinel and `TypeError` |
| D10 | build | 58 of 347 | ~1 s | 12 (9) | None (exclude changelog, pyproject). The base docstring defends coercion, so the user must decide to break it; RFC 9535 makes the direction guessable |
| D6 | build with edits | 37 | ~3 s | 9 (6) | Drop three `match=` strings. `===` rejection and `TypeError` are the unguessable points; issue #947 (2025) had other names |
| D4 | build with edits | 8 of 8 | <1 s | 8 (6) | Drop private `test_compat.py` tests; loosen the yield-twice message. Issue #1437 (2025) settles the headline design |
| D9 | build with edits | 38 of 100 | <1 s | 8 (6) | Drop `match="Unknown color"`. Risk: the user can state the invalid-value rule in one line |
| D1 | build with edits | 18 of 19 | <1 s | 14 (9) | Loosen "COUNT must be an int"; drop the old parser-text test; grade only the recur directory (full suite fails on Windows, unchecked on Linux). Issue #1851 (post-cutoff) spells out many decisions |
| D7 | build with edits | 7 (2 skip on 3.12) | ~3 s | 9 (7) | Identity/aliasing assertions ("returns `self`") must be stated by the user; don't pair with D2 |
| D8 | build with edits, low | 8 | <1 s | 8 (5) | Drop `test_does_not_override_hookimpl_default` (pins behaviour the PR calls provisional). Requested since 2018, so guessable. #738 is not a good standalone task |
| D3 | build with edits, low | 5 of 10 | <1 s | 9 (8) | Contaminated: issue #233 (2024 maintainer comments) gives the name, format and empty-string rule |

Build order: D5, D2, D10, D6, D4, then D9 and D1. Skip D7 (overlaps D2), D8 and D3.

Near-misses: packaging #1376, dj-database-url
#288. Rejected: private-internal tests (pydantic-settings #952, responses #809, itemloaders #120, click #3681),
plumbing (toolz #634, jsonpath-ng #292, icalendar #1672), fixes not features (json-patch, bidict #392/#401/#403,
tomlkit #567, cattrs #765/#778, more-itertools #1248/#1253/#1260), too few decisions (more-itertools #1116,
wcwidth #250, packaging #1334/#1346, cssselect #178, fsspec #2272).

## Rejected

| Idea | Why |
|---|---|
| SWE-bench Pro public tasks | Built for long tasks (hours of engineer time), but the public set comes only from GPL (copyleft) repos, and task-authoring.md allows only BSD/MIT/Apache. |
| FeatBench / FEA-Bench tasks | Upstream PRs, so solutions are likely in training data. Not calibrated by agent time, and repo test suites are often slow. |
| Commit0 (re-implement stubbed libraries) | Length is easy to adjust, but the work is unrealistic, which invites the same "toy task" criticism. |
| One subtle bug in a small library | Found in under a minute regardless of the symptom (B2/B3 tuning, 2026-10-07). |
