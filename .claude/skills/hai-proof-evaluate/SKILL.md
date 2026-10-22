---
name: hai-proof-evaluate
description: Plan, run and read a hai-proof evaluation (a treatment vs plain Claude Code, two treatments, or an A/A calibration) on the published suite or the user's own tasks. Use when the user wants to test a treatment, check whether results are significant, resume a run, or interpret report.html / summary.json.
---

# Run and read an evaluation

Every real run spends API credit or subscription usage. Always dry-run first, and get the user's go-ahead
on the plan (tasks, reps, spend ceiling, expected hours) before starting.

## 0. One-time setup (check, don't redo)

- **Install:** `uv sync`.
- **Config:** copy `hai-proof.example.toml` to `hai-proof.toml`, then set `model` (full id) and `default_host`.
- **Credentials:** copy `.env.example` to `.env`. The user fills in **one** of `ANTHROPIC_API_KEY` or
  `CLAUDE_CODE_OAUTH_TOKEN` themselves. Never read, print or commit it.
- **Execution host:** `uv run hai-proof hosts list` and `uv run hai-proof hosts check <alias>`. The host
  needs Docker without sudo, and the user should trust it with the key.
- **Tasks:** build every task the run uses with `uv run hai-proof build-task <dir>`. For the published suite:
  `for t in tasks/*/; do uv run hai-proof build-task "$t"; done`.

## 1. Pick the run

| Question | Command shape |
|---|---|
| Does treatment X beat plain Claude Code? | `run --treatment X` |
| Is Y better than our current setup X? | `run --arm-a X --arm-b Y` (A is the reference) |
| How noisy is this host, suite and model? | `run --arm-a plain --arm-b plain` (A/A calibration) |
| Does X work at all on these tasks? | `run --treatment X --no-control` |

Common options:
- **Tasks:** `--suite standard` is the published 13-task default. Use `--suite <name>` for the user's own
  tasks (their `suites` tag) or `--tasks A,B`.
- **Reps:** `--mode lightning|quick|full` (1/3/5 reps), or `--reps N`. Small effects need full mode.
  The A/A run on the standard suite (Sonnet, 5 reps) showed what this suite can detect: about a 15-point
  pass@1 gap, or a cost/time ratio outside about [0.85, 1.2]. A new suite needs its own A/A run before
  "no difference" means anything.
- **Limits:** `--limit-scale 3` for treatments that are slower than plain. The limits then only stop
  runaways and don't decide outcomes. It applies to both arms.
- **Spend:** `--max-spend USD` is a hard stop; keep it on.
- **User modes:** `--user uninformative|informative|reticent` puts a stand-in user in the loop (Sonnet, answering
  from each task's `user.md`), applied to both arms unless `--user-a`/`--user-b` say otherwise. Without it nobody
  answers, as in a headless run.
- **Interview suite:** for treatments that ask the user before building (interviewing, brainstorming, spec-first),
  `--suite interview` is the 10-task set whose prompts leave decisions open. Its tasks declare their setup, so pass
  `--user reticent --ask-tool on --limit-scale 3 --max-user-replies 15`; the run refuses `--suite interview` with
  nobody answering. Check the stand-in on the host first with `--suite interview-smoke --mode lightning` (one
  task, cheap). One rep costs about $2.8 per arm on Sonnet and takes about 33 min serially. Plain Claude Code
  passes about 26% here (Sonnet, 2026-10-21) and interview-guide about 94%, so it separates "interviews" from
  "doesn't", but it is near ceiling for comparing two good interviewers. Also run the treatment on
  `--suite standard` with no user, to check it doesn't stall or lose passes when nobody answers.
- **Pin the CLI:** `--cli-version <x.y.z>` keeps the version fixed across runs you'll compare.
  `latest` drifts.

## 2. Dry-run, confirm, launch

```sh
uv run hai-proof run --treatment X --suite standard --mode full --limit-scale 3 --max-spend 500 --cli-version 2.1.301 --dry-run
```

Show the user the plan:
- the arms and the task list;
- the number of agent runs and the spend ceiling;
- a time estimate: about 15 h for the standard suite in full mode on one host.

Then launch it without `--dry-run`, with `-y`, in the background, and redirect output to a log under
`results/`. The log fills in late because output is buffered. Watch `results/<run-id>/trials.jsonl` instead.
- **One host:** run one evaluation per host at a time. Runs on the same host disturb each other's timing.
- **Subscription tokens:** these share the 5-hour usage window. The runner waits out
  `usage_limit_reached` by itself; a long run may pause.
- **Interrupted runs:** `run --resume results/<run-id>` with the original arguments continues one.

## 3. Read the result

`uv run hai-proof report results/<run-id>` regenerates `summary.json` and `report.html`.

- **Pass rate:** `results.relative["pass@1"]` holds `diff` (B − A), `ci_low`/`ci_high` (a two-level
  bootstrap over tasks, then runs) and `sign_p` (an exact sign test over tasks where the arms differ).
  - It's a real difference only if the CI excludes 0 *and* the gap is larger than the A/A noise.
  - Otherwise report "no detectable difference at this size", not "no effect".
- **Cost, tokens, time:** `ratios.<metric>` gives the geometric-mean ratio B ÷ A with a CI, a Wilcoxon p
  and per-task ratios. Use the CI and the A/A band, not one task.
- **Check before trusting anything:**
  - every trial has status `ok`; `excluded` means the treatment didn't load as declared;
  - timeouts and `end_reason`: a limit deciding outcomes calls for `--limit-scale`;
  - `dependency_used`, skills and subagent calls show whether the treatment acted at all. A treatment
    that never acted only measured its context cost, and the write-up must say so;
  - `init_snapshot` model use: a treatment whose subagents pin another model is a model confound;
    name it.
- **Per-task differences:** a task where B lost runs that A passed is worth one look. Re-grade with the
  treatment's edits reverted, or read the transcript, before calling it harm (flaky tests exist).
  `uv run hai-proof regrade results/<run-id>` re-grades with no API spend. `uv run hai-proof sessions` compares
  session timelines.

Write the result up with: the run id, settings (model, CLI, mode, limit scale, user mode), pass@1 A vs B
with CI and sign p, the cost, token and wall ratios with CIs, the confounds, and what the treatment did
or didn't do in the transcripts. Update ROADMAP.md (or the user's tracker) with the run id.
