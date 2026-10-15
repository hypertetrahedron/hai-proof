# Session analysis: how the agent spends a trial

`hai-proof sessions [results dirs] [--task ID] [--refresh]` compares Claude Code's own session records
across trials and runs. It writes `results/sessions.html` and `results/sessions.json`. Each tool call is put
in a phase:

- **explore**: Read/Grep/Glob, and Bash commands that only inspect.
- **edit**: Edit/Write, and Bash commands that change files (`sed -i`, heredoc writes, `open(..., 'w')`, `git apply`, …).
- **test**: pytest and similar.
- **run**: scripts and loops, i.e. reproductions and experiments.
- **delegate**: subagents.

Time from one call to the next is charged to the earlier call's phase, so it includes the model thinking
about the result. An edit that also runs tests or code counts as test/run time. Per trial it reports:
time to first edit, exploration before it, edits, test runs, code runs, edit→test cycles, and whether the
agent re-tested after its last edit. It also draws a phase timeline on a common scale.

Note: agents in these runs edited mostly through Bash, not the Edit tool. That is why the phase
classifier exists; the plain "files edited" count under-reports.

## First findings (2026-10-09, 9 trials with session data, plain arm, claude-sonnet-5-5)

| Task · run · rep | Result | Wall | First edit | Explore before edit | Test runs | Code runs | Re-tested after last edit | Where the time went |
|---|---|---|---|---|---|---|---|---|
| B4 · 0cf7 · 0 | pass | 147 s | 77 s | 9 | 4 | 0 | yes | explore 83 s, test 62 s |
| B5 · cf62 · 0 | pass | 510 s | 74 s | 10 | 9 | 0 | yes | **test 411 s** (thread-safety tests) |
| B6 · e2a2 · 0 | fail* | 212 s | 90 s | 5 | 6 | 2 | **no** | evenly spread |
| B7 · 5746 · 0 | **fail** | 148 s | 57 s | 12 | 4 | **0** | yes | explore 58 s, test 81 s |
| B7 · 8594 · 0 | pass | 111 s | 25 s | 5 | 3 | 0 | yes | test 78 s |
| B7 · 8594 · 1 | pass | 174 s | 37 s | 8 | 4 | 1 | yes | test 112 s |
| B7 · 8594 · 2 | pass | 775 s | 63 s | 12 | 7 | 5 | yes | **run 498 s** (a stress-reproduction script) |

\* B6 failed only on the two `^`/`$` compliance cases that were later excluded. The patch passes the corrected tests.

What this shows so far:

1. **Diagnosis is short in every run.** The first edit comes 25–90 s in, after 5–12 exploration calls. No
   task made the agent explore for long. The bug searches found the same thing: reading code is cheap for
   this model.
2. **Long runs are long because they execute things, not because they think.** B5's 8.5 min is mostly its
   thread-safety tests running. B7 rep 2's 13 min is mostly a stress-reproduction script the agent wrote
   and ran 5 times. Model "thinking" between calls is a small share in every run.
3. **Reproducing first was the only difference between the long and short B7 passes.** Rep 2 built a
   reproduction of the hang before fixing. Reps 0 and 1 reasoned from the code and wrote a unit test.
   All three passed, so with the corrected prompt the extra 10 minutes bought no extra success.
4. **The B7 failure skipped reproduction.** The misdiagnosed run (inproc instead of tcp) had the most
   exploration of any B7 run (12 calls) but **ran no reproduction at all** (0 code runs). It tested only its
   own new unit test. Re-testing alone is not enough: the agent can verify the wrong thing.
5. **The other failure did not re-test after its last edit** (B6). This run's failure was a grading
   artefact, but "re-tested after last edit = no" is cheap to watch for.

## Environment friction (added 2026-10-10)

The comparison page also shows **calls over 120 s** and the **longest call**. These are the first things
to check when a task runs long. B9's first valid-looking long runs (34–38 min) turned out to be mostly
the agents waiting on an upstream test that hangs without a network, not diagnosis. They showed up as
500–600 s commands and `sleep` loops. A long run with several slow calls means "fix the environment",
not "the task is hard". After the fix, B9 runs 13–14 min with no call over 120 s (run 20261010-044729-2392), so
about half of its first measured length was friction.

## Implications

- **For treatments:** these per-trial numbers are where a harness change should show up, even when
  pass/fail and cost don't move much: first-edit time, reproduction before fixing (code runs > 0), re-test
  after the last edit, and edit→test cycles. A planning or spec framework, for example, should shift time
  into explore before the first edit. A verification framework should raise re-tests and reproductions.
  The report's per-arm behaviour table can grow these columns once more runs exist.
- **For task design:** a defect task gets long mainly when the agent must *run* something slow or
  repeatedly (a reproduction, a flaky test). To make diagnosis itself take longer, the report must not
  narrow the search, and confirming the cause must require a reproduction. For a hidden test to reward
  the right diagnosis (not a lucky one), it should fail for every plausible wrong fix (B7's
  `test_handshake_slow_comm` guard is an example).
- **Caveat:** 9 trials, one model, one arm. These are hypotheses for the next runs, not conclusions.
