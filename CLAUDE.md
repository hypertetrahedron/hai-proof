# CLAUDE.md — hai-proof

A/B smoke test for Claude Code harness modifications: runs plain Claude Code and a modified one
through the same coding tasks in paired Docker containers and reports success, time, tokens and cost.
README.md is the user guide, DESIGN.md the spec (cite sections as `DESIGN §x.y`), ROADMAP.md the status.

## Commands

```sh
uv sync
uv run pytest -q                                   # unit tests; fake executors, no Docker/API needed
uv run hai-proof hosts check <alias>               # preflight an execution host
uv run hai-proof build-task tasks/<ID>             # regenerate a task's repo/ from its pinned SHA
uv run hai-proof validate-task --host <alias>      # no API spend
uv run hai-proof run ... --dry-run                 # always dry-run first; real runs spend API credit
```

## Layout

- `src/hai_proof/` — controller. `cli.py` entry; `config.py` (hai-proof.toml, host + auth resolution);
  `executor.py`/`hosts.py`/`sshconfig.py` (local or SSH Docker); `images.py`; `trial.py`/`runner.py`
  (trial lifecycle, scheduling); `streamjson.py` (transcript parsing); `stats.py`/`report.py` (verdict,
  summary.json, report.html); `tasks.py`/`validate.py`; `treatments.py`; `analyses*.py`, `diffbreakdown.py`.
- `image/base/` — trial image; `hai_proof_wrap.py` and `hai_proof_grade.py` run *inside* the container
  (stdlib only, no package imports).
- `image/proxy/` — egress allowlist sidecar.
- `tasks/<ID>/` — published suite. `repo/` and `source.lock.json` are generated and gitignored: never
  edit them; change `inject.patch` / `reference.patch` / `hidden_tests/` and rebuild. See docs/task-authoring.md.
- `examples/` — example task and treatment; `analyses/` — post-run analysis definitions.

## Rules

- Never commit or print credentials. They live in `.env` (gitignored; template `.env.example`) or the
  environment, and reach containers only via stdin, never argv or image layers.
- `hai-proof.toml` is per-user and gitignored; change defaults in `hai-proof.example.toml`.
- The controller has no runtime dependencies (`dependencies = []`); keep it stdlib-only.
- Prompts in `tasks/*/prompt.md` must never mention hidden tests.
- Keep both arms identical except for the treatment (same model pin, CLI version, limits, host).
- Mark ROADMAP rows Complete only after a real run or passing tests; say which in Notes.
