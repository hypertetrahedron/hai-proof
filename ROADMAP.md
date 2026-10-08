# Roadmap

Status legend: Not Started · In Progress · Complete · Deferred
Last updated: 2026-10-07

| Feature | Status | Notes |
|---|---|---|
| Initial public commit (gitignore audit, `.env.example`, CLAUDE.md, MIT license) | Complete | 2026-10-07: secrets and local config verified gitignored, 235 tests pass, wheel builds; pushed to github.com/hypertetrahedron/hai-proof (main) |
| Design proposal (DESIGN.md) | Complete | Approved 2026-10-04 |
| Rename toolproof → hai-proof | Complete | 2026-10-07: package `hai_proof`, CLI `hai-proof`, `hai-proof.toml`, image tags/labels; 235 tests pass; validated + real trial on developmenthost1. Project folder on disk not renamed |
| Runner MVP (Docker trial lifecycle, stream-json capture, init isolation check) | Complete | Real trials on developmenthost1 2026-10-06: A/A lightning run (verdict NO OBVIOUS DIFFERENCE) and single-arm run; grading, diff, cleanup verified |
| Execution hosts: local or remote over SSH (`Executor`, host discovery from `~/.ssh/config`, preflight, egress proxy sidecar) | Complete | Verified 2026-10-06 on developmenthost1: host list/check, remote image builds over SSH, secret delivery (key fingerprint matches in-container), proxy allows api.anthropic.com and blocks other hosts |
| Open-repo task builder (`build-task`: clone @ SHA, strip history, derive hidden tests) | Complete | Tested against a local git repo with base + fix commits |
| 6-task published suite (B1–B3, F1–F3) from 2–3 public repos, with reference solutions | Complete | click 8.5.0 / marshmallow 4.3.1 / rich 15.0.0; 6/6 validate; calibrated 2026-10-07 (27 pilot runs, all pass, levels ordered: bugs 11→38→48 s, features 43→62→161 s). See docs/task-authoring.md |
| Private synthetic fixture repo | Not Started | Optional complement; contamination-free but not reproducible company-wide |
| Run modes: lightning (1 rep) / quick (3 reps) / full (5 reps) | In Progress | Lightning verified for real 2026-10-06; quick/full share the code path but await the 6-task suite |
| Treatment dependencies (per-treatment image layer, setup step, control-absence check, usage scan) | In Progress | Implemented + unit-tested; image layer not yet built on Docker. Example manifest has version/flag placeholders |
| Arm configurations: comparative, A/B, single-arm | In Progress | A/B (plain vs plain) and single-arm verified for real 2026-10-06; comparative with a real treatment not yet run |
| Post-run analyses (trial/arm scope, neutral `--safe-mode` analyzer, blinded) + deterministic `diff_breakdown` | In Progress | Implemented; tested with fake executor. Analyzer `--allowedTools` rule syntax unverified against real CLI |
| Context-tax probe | Complete | Verified 2026-10-06: plain Claude Code 2.1.292 first request = 14,816 input tokens, identical across arms |
| A/A calibration run | In Progress | Lightning A/A on the example task passed 2026-10-06; the real calibration (full mode) needs the 6-task suite |
| Analysis + HTML report (bootstrap CI, Wilcoxon, verdict rules) | Complete | summary.json verified on real runs; HTML visually confirmed 2026-10-07 |
| First real treatment evaluations | Not Started | 2–3 popular internal bundles |

## Deferred
- **Harder level-3 tasks (5–15 min)** — the model solves small-library tasks in under ~3 min; L3 is calibrated on ordering, not absolute time. Unblock with a larger repo or longer multi-part features if treatments only differ on long tasks.
- **LLM-judge code-quality rubric** — the smoke test only scores tests passing and cost/time. Unblock if treatments claim quality gains that tests can't detect.
- **OpenTelemetry secondary telemetry** — stream-json already has the needed data. Unblock if skill-activation or per-request timing is needed.
- **Multi-host pools** — spreading one report's pairs across several execution hosts. Deferred for comparability (one host per report); unblock if runs are too slow on a single host.
- **Podman engine** — Docker is the MVP engine. Unblock when a team's execution hosts run Podman only.
- **Comparing single-arm runs across time** — unpaired runs at different times reintroduce the drift that pairing removes. Unblock if a stored-baseline mode with explicit drift warnings is wanted.
- **Three-arm runs (plain + two treatments)** — the design caps a run at two arms. Unblock if A/B runs routinely need a vanilla reference at the same time; it needs concurrency 3 per block.
- **Internal-repo fixture** — optional second suite for repo-specific CLAUDE.md claims. Unblock once the synthetic suite is calibrated.
