# How hai-proof runs its test arms

This is a walk-through of a run from the command line to the report, written from the code
(`src/hai_proof/runner.py`, `trial.py`, `userloop.py`, `images.py` and the two in-container scripts in
`image/base/`). DESIGN.md is the spec and gives the reasons; this page says what happens, in order. Section
references are to DESIGN.md.

## Arms

An **arm** is a label (`a`, `b`) bound to a configuration:

- **`plain`**: vanilla Claude Code. The base image, an empty `~/.claude`, nothing added to the repo.
- **a treatment**: a directory under `treatments/` (or `extra_treatments_dirs`) with a `manifest.toml` and
  optionally `user/` (copied into `~/.claude`), `project/` (overlaid onto the repo), and a `Dockerfile` fragment.
  The manifest can set `prompt_prefix`, `prompt_variant`, `env`, `requires` (external tools, installed in the
  image), `setup.commands` (run in the workspace before the agent), `network.allow` (extra egress hosts),
  `expect` (plugins / MCP servers / skills that must load) and `workflow.turns` (scripted user messages).

Each arm also has a **user mode** (`--user`, per arm `--user-a/-b`) and an **ask-tool mode** (`--ask-tool`, per arm
`--ask-tool-a/-b`), described below under [User in the loop](#user-in-the-loop).

A run has one or two arms (§3.6):

| Shape | CLI | Arm A | Arm B | Results |
|---|---|---|---|---|
| Comparative (default) | `--treatment X` | `plain` | `X` | B ÷ A ratios, pass-rate differences |
| A/B | `--arm-a X --arm-b Y` | `X` | `Y` | the same statistics, Y ÷ X; nothing about plain |
| A/A calibration | `--arm-a plain --arm-b plain` | `plain` | `plain` | should show no difference |
| Single-arm | `--treatment X --no-control` | — | `X` | absolute metrics, no ratios |

Arm A is the reference for every ratio.

## What is held equal

Both arms of a pair get the same model (`model` in hai-proof.toml, also set as `CLAUDE_CODE_SUBAGENT_MODEL`),
effort, Claude Code version (resolved once at run start and baked into the base image), credentials, execution
host, CPU and memory caps, task limits and stand-in model. The only differences are the treatment (image layer,
config, repo overlay, setup, prompt prefix or variant, env, extra egress hosts) and, if you ask for it, the per-arm
user or ask-tool mode. A comparison should change one of those at a time.

## Before the first trial

`Runner._execute` does these once per run:

1. **Lock and record.** It takes `results/<run-id>/controller.lock` and writes `run.json`: shape, mode, reps,
   model, effort, CLI version, seed, egress, limits, each arm's treatment, content hash, user and ask-tool mode,
   each task's content hash, tier, order and brief hash, the stand-in settings and `limit_scale`.
2. **Build images**, all tagged by content hash, so they are reused across runs and never deleted:
   - **base** (`image/base/Dockerfile`): `python:3.12-slim-bookworm` with git, gcc, Node 22.12.0, uv 0.8.0 and
     `@anthropic-ai/claude-code@<version>`; a non-root `agent` user (Claude Code refuses bypassPermissions as root);
     an empty `/opt/venv`; `DISABLE_AUTOUPDATER=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`,
     `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`; the wrapper and grader scripts. Nothing treatment-specific.
   - **arm**: the base image itself for `plain`; for a treatment, the base plus each `requires` entry's `install`
     and `check` commands and the treatment's Dockerfile fragment (which may not contain `FROM`).
   - **trial**, one per (arm, task): the arm image plus the task's own root Dockerfile steps (if any), `repo/`
     copied to `/work`, and the task's `install` command. Hidden tests are never in any image.
3. **Check credentials.** With an API key, one `GET /v1/models` from the execution host; a 401/403 stops the run
   before any spend. (An OAuth token can't be checked this way.)
4. **Check tool absence.** Each arm's image must not contain a tool another arm declares in `requires`.
5. **Set up egress.** With `egress = "proxy"` (the default), each arm gets its own internal Docker network and an
   allowlist proxy sidecar (`image/proxy/`) that passes `api.anthropic.com` plus the arm's `network.allow` hosts.
   Trial containers on that network can reach nothing else.

Then, unless disabled:

- **Warm-up pair** (`--no-warmup` skips it): one unscored pair on the run's easiest task (lowest level, then id),
  to absorb image pulls and first cache writes.
- **Context-tax probe** (`[probe] runs`, default 5): each arm answers `Reply with the single word OK.` (300 s, 5
  turns, $1). The tokens and cost of that empty session are the treatment's fixed overhead per session (§3.3).

## Scheduling the scored pairs

- For each repetition the task order is shuffled with the run's seed, and every task runs once per rep. Reps run
  in blocks, so drift is spread across tasks.
- Within a (task, rep) **group**, the arm order is shuffled and both arms' trials start together on two threads,
  50 ms apart. Single-arm runs have one trial per group.
- Before each group: the `--max-spend` guard (spend so far plus the dearest pair so far must stay under the
  cap) and the resource gate (free memory on the controller and the host; this run's leaked containers are
  removed; a snapshot goes to `resources.jsonl`). Short memory waits up to 15 minutes, then stops the run cleanly.
- **Transient failures discard the whole pair.** If either trial was rate limited (HTTP 429/overloaded) or hit
  an infrastructure error, the other member is marked `discarded` too and the group is rerun as
  `<task>-r<rep>-retry<N>`, up to `max_pair_retries` (2) times. A pair with one retried member isn't comparable.
- **Account usage limit.** If a trial reports `usage_limit_reached`, the pair is discarded, the controller sleeps
  until the reported reset plus 2 minutes and reruns it as `-ulwait<N>`. More than 8 waits, a wait over 6 hours, or
  no reset time stops the run with `stopped_early`; the report is still written.
- A bad credential mid-run (401/403 in a transcript) stops the run.
- `--resume <results-dir>` picks up a run whose controller died, skipping groups where every arm already has an
  `ok` record (§3.2).

Several runs can share a host. Each run's containers and networks carry its run id, and teardown removes only those.

## One trial

`trial.run_trial` runs one arm on one task for one repetition. Every exception is turned into a recorded trial
with `status = "error"`, and the container is always removed.

1. **Start the container** from the (arm, task) trial image: `--cpus` and `--memory` from `[limits]` (default 4 and
   8g), the arm's network and proxy variables, a sysctl that restores the usual unprivileged-port floor (1024),
   and the credentials passed as secret env (never on a command line). It runs `sleep infinity`.
2. **Apply the treatment.** Copy `user/` into `/home/agent/.claude` and `project/` onto `/work`, then run
   `setup.commands` in `/work` (600 s each, untimed as far as the agent's time goes; a failure is a trial error).
   Plain does none of this.
3. **Mark the start state.** In both arms: `git init`, ignore build byproducts (`__pycache__`, `*.egg-info`, ...),
   commit everything, and point `refs/hai-proof/baseline` at it (a ref, not a tag, since setuptools-scm and the like
   read tags).
4. **Build the prompt.** `prompt_prefix` + the task's `prompt.md` (or `prompts/<variant>.md` if the treatment sets a
   `prompt_variant`). With `workflow.turns`, `{task_prompt}` in each scripted turn is replaced with it.
5. **Run the agent.** Each `claude` call is the same command line in every arm:
   ```
   claude -p <prompt> --model <model> [--effort <effort>] --permission-mode bypassPermissions
     --max-turns <n> --max-budget-usd <usd> --exclude-dynamic-system-prompt-sections
     --output-format stream-json --verbose
   ```
   The environment is the treatment's `env` plus `CLAUDE_CODE_SUBAGENT_MODEL=<model>` and a `CLAUDE_ENV_FILE`
   that unsets the proxy variables for the agent's own shell commands (only the `claude` process needs the
   proxy; tests that honour proxy variables would otherwise send local traffic to it).
   - The controller writes the spec to `/tp/agent.json` and starts `hai_proof_wrap.py` detached. The wrapper
     records monotonic start/end times next to the process, stops it at the time limit, and writes
     `transcript.jsonl`, `stderr.log`, `timing.json` and a `done` marker to `/out/agent`. Timing is taken inside the
     container, so SSH latency never touches it.
   - The controller polls for `done` every 5 s (surviving up to 12 failed polls). If the wrapper hasn't finished
     180 s past the time limit, the controller kills it and `claude`, writes a timed-out `timing.json`, and the trial
     is graded as a timed-out failure. It isn't retried.
   - Limits are the task's `timeout_s`, `max_turns` and `budget_usd`, times `--limit-scale` (both arms).
   - Multi-turn arms (user mode other than `conventional`, a workflow with several turns, or the ask tool on or
     hidden) go through the turn loop instead; see below.
6. **Collect.** Copy `/out/agent` back. Copy the container's `~/.claude` (session and subagent transcripts, file
   history, todos, debug logs) into `claude_home/`, drop `.credentials.json`, redact keys and scrub every known
   secret value. `claudedata.py` turns it into `claude_data.json` and `session.html`.
7. **Read the transcript** (`streamjson.py`): turns, tokens (input, output, cache read, cache write), cost, wall
   time, exit code, timed-out flag. If the session ended before its result event, cost comes from Claude Code's own
   records. Then four checks:
   - **isolation**: the `system/init` event must match the arm. Plain must have no non-builtin plugins and no MCP
     servers. A treatment's `expect`ed plugins, MCP servers and skills must be present and healthy. A failure marks
     the trial `excluded`.
   - **leakage**: a network request to the upstream repo's URL, or the upstream fix's commit SHA anywhere in the
     transcript, marks it `excluded` ("agent reached the upstream fix").
   - **rate limit / usage limit / auth failure**: as described under scheduling.
   - **dependency use**: whether the agent called the treatment's `requires` tools.
8. **Diff.** `git add -A && git diff --cached refs/hai-proof/baseline`, taken before the hidden tests arrive, saved as
   `session.patch` and broken down into categories in `diff_breakdown.json` (source, tests, docs, treatment
   artifacts...).
9. **Grade, offline.** The container is disconnected from its network and any remaining `claude` process is
   killed. `hidden_tests/` is copied onto `/work` and `hai_proof_grade.py` runs two steps (600 s each), compiling
   bytecode into a fresh directory so stale `.pyc` files can't grade old code:
   - **acceptance**: `python -m pytest -q -p no:cacheprovider [acceptance_args] <acceptance ids>`, or the task's
     `acceptance_cmd` (exit 0 = pass).
   - **regression**: the task's `regression` command, with `--ignore` for the acceptance files when it is pytest.
     Tests the agent wrote run here too, on purpose. Exit 5 (nothing collected) gives `None`, not a failure.
   - A task with its own `grade.sh` replaces both steps.
   - The trial **succeeds** when acceptance and regression both pass.
10. **Analyses** (optional, `--analysis NAME`): reconnect the network and run each trial-scope analysis on a copy of
    the workspace with a neutral analyzer (§3.7). Analyses never change the metrics.
11. **Record.** `trial.json` in the trial directory, one line in `trials.jsonl`, and remove the container.

Trial directories are `results/<run-id>/trials/<arm>/<task>/rep<N>[-retryN|-ulwaitN]`, plus `warmup` and
`probe-<i>`.

## User in the loop

Most published tasks run `conventional`: one `claude -p` session, nobody answers, and a question from the agent
simply ends the session. The interview suite and some treatments need a user between turns (§3.8).

**The turn loop** (`userloop.run_loop`). Each agent turn is a `claude -p` call on one session (`--session-id` on the
first call, `--resume` after), with the same flags as above, writing to `/out/turns/NN`. The task's time, turn and
budget limits cover the whole trial; each call gets what's left. After each call:

1. An abnormal end (error, max turns, budget, time limit, rate or usage limit) stops the loop.
2. In `conventional` mode the next scripted turn is sent, or the loop stops.
3. Otherwise the stand-in classifies the agent's last message as WAITING (a question, a choice, an approval
   request) or DONE. WAITING with replies left: the stand-in's reply is the next message. WAITING with no replies
   left (`--max-user-replies`, default 5): the next scripted turn, or stop. DONE: the next scripted turn, or stop.

Afterwards the per-call files are concatenated into `agent/transcript.jsonl`, `timing.json` (wall time summed)
and `stderr.log`, so the rest of the trial reads them like one session. Every exchange is in `user_loop.json`.

**User modes:**

| Mode | Reply when the agent is waiting |
|---|---|
| `conventional` | none |
| `uninformative` | always "I don't have anything to add. Use your best judgement and continue." |
| `informative` | from the task's `user.md` brief, correcting plans against the whole brief |
| `reticent` | from the same brief, but only on points the agent's message asks about or states; never volunteers the rest |

**The stand-in** is a separate `claude -p --safe-mode --tools '' --max-turns 1` call on `stand_in_model` (default
`claude-sonnet-5-5`), in its own container from the plain base image on the arm's network. The agent's container
never holds the brief. The WAITING/DONE decision never sees the brief either. Stand-in cost is reported separately
and never added to an arm's cost. Two reticent-mode settings change what it says:

- `reticence`: `standard`, or `strict`, where each text reply goes through a second call that deletes points
  the agent didn't raise (the unfiltered reply is kept as `draft`).
- `tool_answers`: `brief` (one sentence per question from the ask tool) or `full` (everything the brief says on that
  point, as a text reply would give).

A task can fix both in its task.toml. The interview suite sets `strict` and `full`, and a contradicting flag is refused.

**The ask tool.** `claude -p` alone never offers AskUserQuestion. With `--ask-tool on`, each call runs with
`--input-format stream-json --permission-prompt-tool stdio`, the Agent SDK's mode, which offers AskUserQuestion and
the plan-mode tools. The wrapper sends the prompt on stdin, allows every other tool, and writes each question to
`/out/turns/NN/ask/NNN.json`. The controller polls every 2 s, gets an answer from the stand-in (from the brief in
informative/reticent mode, otherwise the fixed reply), and writes `NNN.answer.json` for the wrapper to return. A
question unanswered after 10 minutes is denied with "make a reasonable assumption". Time spent waiting for answers
counts toward the call's wall time and is recorded as `ask_wait_s`. `--ask-tool hidden` is the same input mode with
`--disallowedTools AskUserQuestion`, the control for `on`.

Interview-suite tasks declare `user = "reticent"` and `ask_tool = "on"`. `run` refuses `--user conventional` for them
and warns on other mismatches. Arms with a stand-in or the ask tool don't feed `baseline.json`.

## After the last pair

- **Arm-scope analyses**, if any are attached.
- **Teardown**: remove this run's containers, proxies and networks, then a final resource snapshot (anything left is
  a leak).
- **Report** (`stats.py`, `report.py`): `summary.json` and `report.html`. For each arm, pass@1 and pass@k (each
  task weighted equally). For B vs A, the pass-rate difference with a two-level bootstrap CI, the ratio, the per-task
  win/loss counts and a sign-test p; for cost, total tokens and wall time, the geometric-mean ratio of paired runs
  with a cluster-bootstrap CI and a Wilcoxon p. Per-task tables are grouped by `cost_tier` in `report_order`, and
  tasks where pass counts differ are listed separately (§6). Plain-arm conventional trials are also added to each
  task's `baseline.json`.

Only `status = "ok"` trials with rep ≥ 0 are scored. `discarded` (rate/usage limits, a failed partner), `excluded`
(isolation or leakage) and `error` trials are kept in `trials.jsonl` and their directories for inspection.

## Suites and modes

`--suite` picks the tasks (task.toml `suites`; default `standard`; `all` for everything) and `--tasks A,B` picks ids
instead. `--mode` then sets reps and drops tasks above a level: `lightning` 1 rep, `quick` 3 reps without level-3
tasks, `full` 5 reps. `--reps N` overrides. The tasks in each suite are described in
[suites.md](suites.md).

Always `--dry-run` first. It prints the plan: agent, probe and warm-up runs, and the spend ceiling, which is the sum of
every call's `--max-budget-usd` cap.
