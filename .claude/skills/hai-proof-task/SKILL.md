---
name: hai-proof-task
description: Create a hai-proof task (a bug fix or feature both arms attempt) from a git repo, including the user's own private repos. Use when the user wants to add, build, validate or pilot a task, turn a past bug-fix commit into a task, or evaluate treatments on their own codebase.
---

# Create a hai-proof task

A task is one coding job that both arms of a run attempt, graded offline by hidden tests the agent never
sees. Read `docs/task-authoring.md` first: it is the authoritative schema and rules. This skill is the
procedure, with the extra care a private repo needs.

## 0. Ask before starting

Ask the user only what you can't find out yourself:
- **The repo:** a git URL the user's own `git` can clone (SSH or HTTPS with their credential helper) or a
  local path. The clone runs on this machine, with the user's credentials.
- **Where the task goes:** default `private/tasks/<ID>/`. `private/` is gitignored and searched
  automatically (`extra_tasks_dirs` in `hai-proof.toml`). **Never put a task from a private repo under
  `tasks/`.** That directory is published with this repo.
- **The id:** prefix it so it can't collide with the published `B*`/`F*` ids, e.g. `ACME-B1`, `ACME-F1`.
- **The kind:** bug or feature. Optionally the user may name a commit, issue or PR to base it on.

Tell the user, once, what leaves their machine:
- The task's repo snapshot is streamed to the execution host and baked into images there.
- The agent's transcripts go to the Anthropic API, like any Claude Code session.
- Results under `results/` contain code and transcripts. They are gitignored, but stay on disk.

## 1. Survey the repo

Clone it to a scratch directory (not into this repo), then find out:
- **Its test runner:** the command CI or the Makefile uses. Use the same command for grading.
- **How long the suite takes:** the target is under ~60 s for the part you'll run. Narrow `regression` to the
  relevant packages if the full suite is slower.
- **Services:** grading runs with **no network**. A database, queue or external API breaks this. Options:
  an in-memory or sqlite variant the project already supports (see B21's `acceptance_args`), a service
  started inside the container by the test command, or pick another area of the code.
- **The toolchain:** the base image has Python 3.12 (venv at `/opt/venv`), Node 22, git, gcc and uv. Anything
  else (Go, JDK, Rust, apt packages) goes in `task.Dockerfile` (step 3).
- **Private dependencies:** installs run during a Docker build on the execution host, with network but
  without the user's credentials. A dependency from a private registry won't install. Vendor it into the
  snapshot, or tell the user it isn't supported yet. Never put a token in any task file.

## 2. Choose the task's source (best first)

1. **A real past fix (`origin = "upstream-fix"`).** Find a commit (or a squashed PR) that fixed a genuine
   bug *and* added or changed a test that fails without it. In the `[source]` table:
   - set `base` to the full 40-hex SHA of the fix's parent, and `fix` to the fix's SHA;
   - `build-task` then derives `hidden_tests/` from the fix's test files and `reference.patch` from the rest;
   - use `exclude` for parts of the commit that belong to other changes.

   This gives the most realistic tasks. A bug task must test finding and fixing a genuine defect. Its
   difficulty should come from diagnosis (a symptom far from the cause, a vague report, a need to reproduce),
   not from a feature-sized fix. Long implementation work belongs in a feature task.
2. **An injected bug (`origin = "injected"`).** You write `inject.patch` on top of `base`, a small plausible
   mistake. `reference.patch` is its exact reverse. For L2/L3 the existing suite must still pass with the
   bug in, so pick an untested path.
3. **An authored feature (`origin = "authored"`).** There's no `inject.patch`. You write `reference.patch`,
   which implements the feature the way the project would, and the hidden tests.

Test-file detection, which decides what becomes a hidden test, covers Python (`tests/`, `test_*.py`,
`*_test.py`), Go `*_test.go`, JS/TS `*.test.*` / `*.spec.*` / `__tests__/`, JVM `src/test/`, Ruby `*_spec.rb`
and C# `*Tests.cs`. If the fix's tests don't match these patterns, write `hidden_tests/` by hand.

## 3. Write the task files in `private/tasks/<ID>/`

- **`task.toml`**: follow the schema in `docs/task-authoring.md`. Points that matter for private repos:
  - `[source] url` is the URL or local path you cloned, and `base`/`fix` are full SHAs.
  - `install` runs as the unprivileged `agent` user in `/work` at image build. Python projects use
    `uv pip install --python /opt/venv/bin/python -e .` plus test dependencies.
  - Test configuration:
    - `regression` is the project's own test command.
    - For a non-pytest runner, set `acceptance_cmd` to a shell command that runs only the hidden tests and
      exits 0 on pass (e.g. `go test ./pkg/foo -run TestHaiProof`).
    - Still list the hidden test files in `acceptance`.
    - A non-pytest `regression` also runs the hidden test files. That's expected.
  - Limits by level: L1 `timeout_s = 1200`, `budget_usd = 3`, `max_turns = 40`; L2 2400 / 5 / 60; L3 3600 / 8 or more / 80 or more.
  - Tag `suites = ["<team or repo name>"]`, never `"standard"`, so `run --suite <name>` selects the user's tasks.
- **`task.Dockerfile`**, optional: root build steps that run before the repo is copied in. Use only
  `RUN`/`ENV`/`ARG` lines, no `FROM` or `USER`. Pin versions, e.g.
  `RUN apt-get update && apt-get install -y --no-install-recommends golang-1.22 && rm -rf /var/lib/apt/lists/*`.
  It is identical for both arms and part of the task hash.
- **`prompt.md`**: what a colleague would type or an issue would say.
  - Give the symptom, and the traceback or failing call for L1.
  - Never mention hidden tests, `tests/hai_proof`, hai-proof, or how to fix it. Don't say "run the tests".
  - For an upstream fix, write it from the original issue, rephrased, and drop any hints the reporter
    couldn't have had.
- **`hidden_tests/`** mirrors repo paths.
  - Pytest default: `hidden_tests/tests/hai_proof/test_<id lower>.py`.
  - Test behaviour through the public API, so any correct fix passes.
  - Rewrite upstream assertions that pin one implementation (B17's notes in its `task.toml` show an example).
  - A hand edit to fix-derived tests is lost on `build-task --force`, so record it in a `task.toml` comment.
- **`user.md`**, optional: what the requester wants and knows, for `--user informative`. Never mention hidden tests.

If the repo itself ships a `CLAUDE.md` or `.claude/`, both arms see it, because it's part of the task. To
evaluate that file as a treatment instead, delete it in `inject.patch` and put it in the treatment's `project/`.

## 4. Build and validate (no API spend)

```sh
uv run hai-proof build-task private/tasks/<ID>          # --force to rebuild
uv run hai-proof validate-task --tasks <ID> --host <alias>
```

`validate-task` must print `[ok]`, which means:
- the acceptance tests fail at the start state;
- acceptance and regression pass with `reference.patch` applied;
- grading takes under 60 s (it warns otherwise).

Fix and repeat until it does. Never edit `repo/` or `source.lock.json`: they are generated.

If `regression` is a non-pytest command that covers the hidden test's package (e.g. `go test ./...`),
validate also prints "pre-existing suite fails at the start state". That warning comes from the hidden test,
not the suite, and is expected. Exclude the hidden test from `regression` if the runner allows it (e.g.
`go test ./... -skip TestHaiProof` on Go 1.20 or later).

## 5. Pilot (spends API credit: ask the user first)

```sh
uv run hai-proof run --arm-a plain --no-control --tasks <ID> --reps 3 --dry-run   # then without --dry-run
```

Plain Claude Code should solve it at least 2 out of 3 times. A task nobody solves only measures noise unless
the treatment targets exactly that. Set `level` and the limits from the median wall time and turns. If a limit
decided an outcome (`end_reason` in `tasks/.../baseline.json`, or the report), raise it.

## 6. Keep it

- **Record it:** add a row to the user's own catalog if they keep one. `docs/task-catalog.md` is for the
  published suite only.
- **Commit it:** if `private/` is its own git repo, commit the task there. Ignore `*/repo/` and
  `*/source.lock.json` in that repo too, because `build-task` regenerates them. Never stage `private/`
  files in the hai-proof repo.
- **Reference tasks:** the published tasks under `tasks/` are worked examples. B17 and B19 are upstream fixes
  (B17 has hand-edited hidden tests), B1 is an injected bug, F3 is an authored feature, and B21 is an
  upstream fix that grades against an in-memory database (`acceptance_args`).
