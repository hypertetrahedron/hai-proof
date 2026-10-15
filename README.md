# hai-proof

**H**arness for **AI** **P**lugin **R**igorous **O**utcome and **O**verhead **F**ramework.

A/B smoke test for Claude Code harness modifications (skills, hooks, CLAUDE.md, MCP servers, plugins).
Runs plain Claude Code and a modified Claude Code through the same coding tasks in paired containers
and reports success, wall-clock time, tokens and cost. Design: [DESIGN.md](DESIGN.md). Status: [ROADMAP.md](ROADMAP.md).

## Requirements

- Controller (this machine): Python 3.11+, [uv](https://docs.astral.sh/uv/), an OpenSSH client.
- Execution host: Docker, usable without sudo — either this machine or any host in `~/.ssh/config`
  reachable with key/agent auth.
- Credentials: copy `.env.example` to `.env` (gitignored) and set **one** of:
  - `ANTHROPIC_API_KEY` — a Console API key (`sk-ant-api…`). Preferred: hai-proof checks it for free
    before any trial runs. A dedicated low-limit key is recommended (DESIGN §3.5).
  - `CLAUDE_CODE_OAUTH_TOKEN` — a subscription token from `claude setup-token` (`sk-ant-oat…`).
    Usage counts against the subscription, whose tighter rate limits can add wall-clock noise.

  A variable already set in the environment overrides `.env`. Don't put credentials in
  `.claude/settings.json`: it is the shared project settings file, and Claude Code doesn't pass its
  `env` credentials on to the commands hai-proof runs.

## Quick start

```sh
uv sync
cp hai-proof.example.toml hai-proof.toml        # set model and default_host

uv run hai-proof hosts list                     # hosts from ~/.ssh/config, probed
uv run hai-proof hosts check <alias>            # full preflight

# tasks live in tasks/<id>/ (see examples/tasks/example-bug); open-repo tasks are built from a pinned SHA:
for t in tasks/*/; do uv run hai-proof build-task "$t"; done
uv run hai-proof validate-task --host <alias>   # reference solutions pass, start states fail; no API spend

# treatments live in treatments/<name>/ (see examples/treatments/openspec-beads)
uv run hai-proof run --host <alias> --treatment <name> --mode lightning --dry-run
uv run hai-proof run --host <alias> --treatment <name> --mode lightning
```

## Run shapes and modes

| | |
|---|---|
| `--treatment X` | plain Claude Code (A) vs X (B) — pass@1, pass@k and B ÷ A ratios |
| `--arm-a X --arm-b Y` | A/B between two configurations; `--arm-a plain --arm-b plain` is the A/A calibration |
| `--treatment X --no-control` | single arm, pass@1/pass@k and absolute metrics, no ratios |
| `--mode lightning \| quick \| full` | 1 / 3 / 5 repetitions (quick drops level-3 tasks); `--reps N` overrides |
| `--suite standard \| smoke \| diagnosis \| all` | which tasks run (default `standard`, 13 tasks; see [docs/task-catalog.md](docs/task-catalog.md#suites)); `--tasks A,B` picks ids instead |
| `--analysis NAME` | post-run analysis per trial or per arm (see `analyses/`) |
| `--user conventional \| uninformative \| informative` | who answers the agent between turns. The default `conventional` is the single-session test. The two stand-in modes run each trial as several `claude -p` calls on one session, with a user stand-in that replies to questions: always "use your best judgement" (`uninformative`), or from the task's `user.md` (`informative`). `--user-a` / `--user-b` set one arm. Treatment `[workflow] turns` script multi-step workflows such as plan → apply (DESIGN §3.8) |
| `--ask-tool off \| on \| hidden` | offer the agent AskUserQuestion, which `claude -p` alone never does. `on` runs each call in the SDK's stream-json stdio mode and answers the tool's questions like `--user` does (from `user.md` when informative, otherwise "use your best judgement"). `hidden` is the same mode without the tool, the control for `on`. `--ask-tool-a` / `--ask-tool-b` set one arm (DESIGN §3.8) |
| treatment `prompt_variant = "<name>"` | same harness in both arms; B gets each task's `prompts/<name>.md` (prompt-quality experiments, see [docs/prompt-degradation.md](docs/prompt-degradation.md)) |

Results land in `results/<run-id>/`: `run.json`, `trials.jsonl`, per-trial artifacts (transcript, timing,
session patch, grade, analyses, Claude Code's own records in `claude_home/` with `claude_data.json` and
`session.html`), `resources.jsonl`, `summary.json` and `report.html`. Regenerate with
`uv run hai-proof report results/<run-id>`.

Before every pair the runner checks resources and logs a snapshot to `resources.jsonl`:
- **Memory:** free memory on the controller machine (at least 2 GB) and on the execution host (both arms'
  memory limits + 2 GB).
- **Leaks:** this run's leftover trial containers are removed, and containers from other runs are reported.
- **Controller memory:** growth of the controller's own memory is tracked.

While memory is short it waits, polling for up to 15 minutes, and then stops the run cleanly with teardown and
a report. A final snapshot after teardown shows anything still left behind.

## Commands

| Command | Purpose |
|---|---|
| `hosts list` / `hosts check [alias]` | discover execution hosts from `~/.ssh/config`; full preflight of one |
| `build-task <dir>` | materialise an open-repo task (`repo/`, `source.lock.json`) from its pinned `[source]` |
| `validate-task` | prove tasks are well-formed on the execution host (no API spend) |
| `build` | build base / treatment / trial images on the execution host |
| `run` | run an evaluation (`--dry-run` prints the plan; `-y` skips the spend confirmation; `--max-spend USD` stops cleanly before a pair that could pass USD; `--resume <results-dir>` with the original arguments continues an interrupted run, keeping finished pairs) |
| `report <results-dir>` | regenerate `summary.json` and `report.html` |
| `regrade <results-dir> [--trials A/B7/0,...] [--all] [--write]` | re-grade trials' `session.patch` in fresh offline containers with the current grader (no API spend; default: failed trials only); `--write` records changed results. Check each change before writing: a randomized test (e.g. Hypothesis) can pass on a re-grade by chance |
| `baseline update [results-dirs] \| show` | long-run plain-arm aggregates per task and model / CLI version (`tasks/<ID>/baseline.json`; `run` updates them automatically; see docs/task-authoring.md#baselines-baselinejson) |
| `sessions [results-dirs] [--task ID]` | compare Claude Code sessions across trials and runs: phases, first edit, test/reproduction runs, timelines (`results/sessions.html`; see docs/session-analysis.md) |

## Repository layout

```
src/hai_proof/        controller: CLI, config, executor (local/SSH), images, trial lifecycle, stats, report
image/base/           trial image: Claude Code + in-container wrapper and grader
image/proxy/          egress allowlist sidecar
tasks/                task library (B* bugs, B-DP-* degraded-prompt bugs, F* features), tagged into suites and
                      cost tiers; baseline.json holds plain-arm aggregates; repo/ snapshots are generated, not committed
examples/             example task and treatment (openspec-beads) to copy from
analyses/             post-run analysis definitions
docs/                 task-authoring guide and calibration notes
tests/                pytest suite (stream-json fixtures under tests/fixtures/)
```

Not committed: `.env` (credentials), `hai-proof.toml` (your host and model choices), `results/`, and
generated task snapshots.

## Status

Runner, SSH execution hosts, the 6-task suite, the context-tax probe and the HTML report are verified on
real runs. Treatment dependencies, post-run analyses and quick/full modes are implemented and unit-tested
but not yet exercised end-to-end with a real treatment. See [ROADMAP.md](ROADMAP.md).

## Development

```sh
uv sync
uv run pytest -q          # 235 tests; no Docker or API access needed
```

## License

MIT — see [LICENSE](LICENSE).
