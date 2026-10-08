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
| `--treatment X` | plain Claude Code (A) vs X (B) — full verdict |
| `--arm-a X --arm-b Y` | A/B between two configurations; `--arm-a plain --arm-b plain` is the A/A calibration |
| `--treatment X --no-control` | single arm, absolute metrics, no verdict |
| `--mode lightning \| quick \| full` | 1 / 3 / 5 repetitions (quick drops level-3 tasks); `--reps N` overrides |
| `--analysis NAME` | post-run analysis per trial or per arm (see `analyses/`) |

Results land in `results/<run-id>/`: `run.json`, `trials.jsonl`, per-trial artifacts (transcript, timing,
session patch, grade, analyses), `summary.json` and `report.html`. Regenerate with
`uv run hai-proof report results/<run-id>`.

## Commands

| Command | Purpose |
|---|---|
| `hosts list` / `hosts check [alias]` | discover execution hosts from `~/.ssh/config`; full preflight of one |
| `build-task <dir>` | materialise an open-repo task (`repo/`, `source.lock.json`) from its pinned `[source]` |
| `validate-task` | prove tasks are well-formed on the execution host (no API spend) |
| `build` | build base / treatment / trial images on the execution host |
| `run` | run an evaluation (`--dry-run` prints the plan; `-y` skips the spend confirmation) |
| `report <results-dir>` | regenerate `summary.json` and `report.html` |

## Repository layout

```
src/hai_proof/        controller: CLI, config, executor (local/SSH), images, trial lifecycle, stats, report
image/base/           trial image: Claude Code + in-container wrapper and grader
image/proxy/          egress allowlist sidecar
tasks/B1..B3, F1..F3  published 6-task suite (bug / feature tracks); repo/ snapshots are generated, not committed
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
