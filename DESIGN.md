# hai-proof — A/B smoke test for Claude Code harness modifications

*hai-proof: Harness for AI Plugin Rigorous Outcome and Overhead Framework (formerly toolproof).*

Status: proposed design · 2026-10-04 · Claude Code v2.1.289

## 1. Problem and goal

Developers add skills, hooks, CLAUDE.md files, MCP servers, subagents, plugins and output styles to Claude Code. They say these make it "feel better", but nobody measures it. hai-proof is a **smoke test**: it runs a few coding tasks through two arms, plain Claude Code (**control**) and Claude Code with one modification bundle (**treatment**), and reports whether the treatment changes:

1. **Success**: do the hidden acceptance tests pass?
2. **Wall-clock time**: from process start to exit.
3. **Tokens and cost**: the whole agent tree, subagents included.

The test is built to catch *large* differences (more than about 20–30%) cheaply. It is not a leaderboard or a fine-grained benchmark.

**Working hypothesis (the null the treatment must beat):** both arms solve the tasks, and the treatment costs more. One published study fits this. Gloaguen et al., ETH Zurich, arXiv 2602.11988, found that AGENTS.md-style context files did not generally improve task success and raised inference cost by more than 20% (we read the abstract only). Anthropic reports that large MCP tool sets can use tens of thousands of tokens before the first turn.

## 2. Design principles

- **The only difference between arms is the treatment bundle.** The CLI binary, model ID, effort, flags, task, container image, resources and auth mode are the same. "Plain" means a **fresh, empty config dir**. It does not mean `--bare` or `--safe-mode`, because both change Claude Code's behavior beyond removing customizations. `--bare` also drops tools and system reminders.
- **Install treatments the way developers install them.** A bundle is copied into the places Claude Code already reads: `~/.claude/` and the repo's `CLAUDE.md`, `.claude/` and `.mcp.json`. We do not translate it into flags. This tests what people actually run.
- **Verify isolation; do not assume it.** Every run records the `system/init` event. The run is rejected if the control loaded any plugin, MCP server, hook or non-bundled skill, or if the treatment failed to load what its bundle declares.
- **Hidden tests, graded outside the agent.** The agent never sees the acceptance tests.
- **Paired and interleaved runs.** Each control/treatment pair runs on the same task at the same time, so API latency drift and time-of-day effects cancel out.
- **Few tasks, repeated.** Six tasks with five repetitions each beats thirty tasks run once, because run-to-run variance is large. Published measurements show a geometric SD of about ×1.34 in token use across repeated runs of the same task, with occasional far larger outliers.

## 3. Architecture

```
hai-proof/
  image/Dockerfile           # pinned OS, Python 3.12 + uv, Node LTS (Claude Code runtime),
                             # git, claude CLI @ exact version. Control runs on this image.
  tasks/<task-id>/
    task.toml                # id, kind (bug|feature), level (1-3), timeout, budget
    prompt.md                # what the developer would type
    repo/                    # fixture source (no .git history containing the fix)
    hidden_tests/            # copied in only AFTER the agent exits
    grade.sh                 # runs hidden + existing tests, emits JSON
  treatments/<name>/
    manifest.toml            # declares expected skills/plugins/MCP/hooks (for init check),
                             # optional prompt_prefix (e.g. "/tdd "), extra env,
                             # external tool requirements + workspace setup (§3.4)
    Dockerfile               # optional: extra image layer FROM the base image (§3.4)
    user/                    # copied into CLAUDE_CONFIG_DIR  (≈ ~/.claude)
    project/                 # overlaid onto repo root (CLAUDE.md, .claude/, .mcp.json)
  hai-proof/                 # Python 3.11 runner package
    plan.py  run.py  grade.py  analyze.py  report.py
  hai-proof.toml             # default execution host, limits, model pin
  results/<timestamp>/       # raw JSONL per trial + summary.json + report.html
                             # (always local; copied back from the execution host)
```

### 3.1 Trial lifecycle (one arm, one task, one repetition)

1. **Provision.** On the execution host (§3.5), start a fresh container from the pinned image, capped at 4 CPU, 8 GB RAM and the task timeout. Stream `repo/` into `/work` as a tar archive. Use no bind mounts, so the same steps work locally or over SSH. Set `HOME=/home/agent` and `CLAUDE_CONFIG_DIR=/home/agent/.claude`, both empty.
2. **Apply the treatment** (treatment arm only).
   - The container is started from the treatment image (§3.4) instead of the base image.
   - Copy `user/` into the config dir and `project/` onto `/work`.
   - Run the manifest's `setup` commands in `/work`, untimed (§3.4).
   - Then, in both arms, `git init && git commit` the result, so the diff can be measured later.
3. **Run the agent.** Both arms get the same invocation:
   ```
   claude -p "$(cat prompt.md)" \
     --model <pinned full model id> --effort <pinned> \
     --permission-mode bypassPermissions \
     --max-turns 60 --max-budget-usd <task budget> \
     --no-session-persistence \
     --exclude-dynamic-system-prompt-sections \
     --output-format stream-json --verbose
   ```
   - Environment: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (no auto-update or feature-flag drift), `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and `CLAUDE_CODE_SUBAGENT_MODEL=<same pinned id>`.
   - Auth: `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`), the same one for both arms.
   - Permissions are bypassed **only inside the container**. That container is the sandbox.
4. **Capture.** A small wrapper inside the container records monotonic start and end times around the `claude` process. It writes the full stream-json transcript to a file inside the container. The runner copies both out afterwards. Timing is therefore taken next to the process, so SSH latency and dropped connections never touch the measurement.
5. **Grade.** Copy `hidden_tests/` in and run `grade.sh` with no network and no agent present. It produces:
   - `acceptance_pass`: the hidden tests.
   - `regression_pass`: the pre-existing suite.
   - `diff_stats`: files and lines changed.
6. **Analyze** (optional). Run any attached trial-scope analyses, using a neutral analyzer on a copy of the workspace (§3.7).
7. **Destroy** the container.

### 3.2 Scheduling

- For each repetition and each task, launch the control and treatment containers **at the same time**, so the concurrency is 2.
- Randomize which one starts first by a few milliseconds.
- Run repetitions in blocks, which spreads any drift evenly across tasks.
- Before the first block, run one **warm-up pair** that is not scored. It absorbs cold-start effects such as image pulls and the first cache writes.
- On HTTP 429 or a transient API error, the runner discards **both members of the pair** and reruns them. It logs every discard. A pair with a retry inside it is not comparable.

### 3.3 Context-tax probe (cheap and diagnostic)

Before the task runs, run each arm 5 times on the prompt `Reply with the single word OK.` and record:
- the input and cache-creation tokens of the first request,
- the total cost.

This isolates the treatment's **fixed per-session overhead**: CLAUDE.md, skill listings, MCP tool schemas and hook output. It costs almost nothing and often explains the whole result by itself. For example: "this bundle adds 31k tokens to every session before work starts".

### 3.4 Treatment dependencies (external tools such as OpenSpec and beads)

Some skills drive external CLIs, so a bundle may need extra tools that plain Claude Code never has. hai-proof installs those tools **only in that treatment's arm**. It keeps installation out of the measurements and checks that the tools were actually used.

**Declaring requirements.** The manifest declares what the bundle needs. The versions below are placeholders: pin the exact releases that were evaluated, never `@latest`.

```toml
# treatments/openspec-flow/manifest.toml
[[requires]]
name    = "openspec"
install = "npm install -g @fission-ai/openspec@<pinned version>"   # needs Node ≥ 20.19 (in base image)
check   = "openspec --version"

[[requires]]
name    = "bd"
install = "npm install -g @beads/bd@<pinned version>"              # alt: go install github.com/steveyegge/beads/cmd/bd@<tag>
check   = "bd --version"

[setup]                                   # run in /work after overlay, before the agent; untimed
commands = ["openspec init <non-interactive flags>", "bd init <non-interactive flags>"]
artifacts = ["openspec/", ".beads/"]      # excluded from diff_stats and from leakage scans

[network]
allow = []                                # extra egress hosts at *agent run time* (both tools work offline)
```

The setup commands need non-interactive flags. Each tool's interactive init prompts would hang a headless run. Confirm the exact flags against the pinned versions when the bundle is onboarded.

**How it runs.**
1. **Image layering.** `hai-proof build-treatment` produces `hai-proof-treat-<name>:<hash>` as an image layer `FROM` the pinned base image:
   - It runs every `install` line, or the treatment's own `Dockerfile` for anything more complex, such as building from source or adding apt packages.
   - It runs every `check` line, so a failed check fails the build.
   - Installation happens once at build time, with network access. It never happens inside a trial, so it adds nothing to wall-clock or tokens.
   - The image digest goes into the report and the treatment hash.
2. **Control stays clean.** The control arm always uses the bare base image. Preflight asserts that `command -v <name>` fails in the control container for every declared tool. That catches a base image that accidentally shipped one.
3. **Per-workspace init.** The `setup` commands run after the project overlay and before the clock starts, for example `openspec init` (which creates `openspec/`) or `bd init` (which creates `.beads/`).
   - They are part of the treatment's starting state, committed in the baseline git commit.
   - A bundle that expects these files committed in the repo can ship them in `project/` instead.
   - Either way, setup cost is excluded. It is a one-time per-repo cost, not a per-task one.
4. **Network.** Install-time network is unrestricted, at build only. Run-time egress is the API plus `network.allow`. Beads' optional git-remote sync stays off, because the workspace has no remote.
5. **Grading.** The paths in `artifacts` (spec files, issue databases) are excluded from `diff_stats`. That way a workflow that writes a spec proposal or files beads issues is not charged for "lines changed" in product code. Their size is reported separately as `treatment_artifact_lines`.
6. **Usage check.** The runner scans the transcript for Bash invocations of each declared tool and reports `dependency_used: {openspec: 4/5 runs, bd: 0/5 runs}`.
   - A dependency that never gets invoked means the skill didn't engage. Its cost then comes purely from context overhead, which is a finding in itself.
   - The report flags it so nobody mistakes "skill never fired" for "skill didn't help".
7. **Probe parity.** The context-tax probe (§3.3) also runs on the treatment image after setup. Any context injected by setup, such as hooks that read `.beads/` at session start, is counted as fixed overhead.

Treatments that need tools are therefore compared fairly. The control gets plain Claude Code on the plain image. The treatment gets everything its authors say it needs, pre-installed and initialized. Only the agent's work is timed.

### 3.5 Execution hosts (local or remote over SSH)

The machine running hai-proof, often a Windows laptop, may have no container engine. hai-proof therefore separates the **controller** from the **execution host**.
- The **controller** is local. It runs the CLI, plans the runs, analyzes results and writes the report.
- The **execution host** runs the containers. It is either the local machine or any machine reachable over SSH.

**Local requirements:** Python 3.11+ and an OpenSSH client. No Docker CLI or daemon is needed locally.

**Transport.** Every container operation goes through one small `Executor` interface with two implementations.
- `LocalExecutor` runs `docker …` directly.
- `SshExecutor` runs `ssh <alias> docker …`. File transfer is a tar archive streamed over SSH stdin and stdout:
  - Into a container: `tar c … | ssh <alias> docker cp - <ctr>:/work`.
  - Out of a container: `ssh <alias> docker cp <ctr>:/out - | tar x`.
  - Image builds: `tar c <context> | ssh <alias> docker build -t … -`. The build context is streamed, so nothing has to be pre-staged on the remote disk.
  - No bind mounts are used anywhere. A bind-mount path would refer to the *remote* filesystem.
  - The system `ssh` binary is called rather than a Python SSH library, so everything in the user's SSH setup works unchanged: `~/.ssh/config` aliases, `ProxyJump` bastions, `IdentityFile`, `ssh-agent` or Windows OpenSSH Agent, and hardware keys.
  - Every call uses `-o BatchMode=yes`, so a missing key fails fast instead of hanging on a password prompt.

**Discovering hosts from `~/.ssh/config`.**
- The config is found at `%USERPROFILE%\.ssh\config` on Windows and `~/.ssh/config` elsewhere.
- `hai-proof hosts list` reads it, follows `Include` directives, and collects the concrete `Host` aliases. It skips wildcard and negated patterns.
- It then runs `ssh -G <alias>` to get each host's *effective* settings (HostName, User, Port, ProxyJump), so `Match` blocks and defaults resolve exactly as OpenSSH resolves them.
- It then probes each host in parallel, with a 5-second timeout:
  ```
  ssh -o BatchMode=yes -o ConnectTimeout=5 <alias> \
    'docker version --format "{{.Server.Version}}" && docker info --format "{{.NCPU}} {{.MemTotal}} {{.Architecture}}" && df -Pk /var/lib/docker'
  ```
- It prints a table: alias, reachable (yes/no), auth OK, engine version, CPUs, RAM, architecture, free disk, and whether this user can use Docker without sudo.

**Choosing the host.** Precedence is `--host <alias>`, then `HAI_PROOF_HOST`, then `default_host` in `hai-proof.toml`, then `local`. `local` is allowed only if the local machine has a working container engine. `hai-proof hosts check <alias>` runs the full preflight:
- **Engine.** The engine is reachable, and the user can run it without sudo.
- **Capacity.** The host has at least 2 × the per-trial CPU and RAM limits, so a concurrent pair can run, plus at least 20 GB free disk for images.
- **Network.** The host can reach the Anthropic API.
- **Build.** The base image builds or pulls.

**Running over unreliable links.** Trials start detached (`docker run -d`), and the controller polls them. If the SSH connection drops, the trial keeps running on the host. The controller reconnects and collects the results, and the trial is not lost. Timing is taken inside the container (§3.1 step 4), so link latency is never measured.

**Credentials.**
- The API key or OAuth token is piped over SSH stdin into `docker run --env-file /dev/stdin …`.
  - It never appears in a remote command line, where `ps` would show it, and is never written to the remote disk.
  - The container is removed after each trial.
  - The runner MVP must verify that this `--env-file /dev/stdin` approach works on the target Docker versions. If it doesn't, the fallback is a `0600` temp file in a remote tmpfs that is deleted right after `docker run`.
- Trust boundary: anyone with root or Docker access on the execution host can read a running container's environment. Use hosts you would trust with that key. Better still, use a dedicated low-limit key for hai-proof.

**Egress allowlist, portable to any host.**
- The agent container joins an `--internal` Docker network, which has no route out.
- A small proxy sidecar on the same network has its own outbound access and allows only the Anthropic API plus the treatment's `network.allow` hosts.
- The agent container gets `HTTPS_PROXY` pointing at the sidecar.
- This needs no firewall changes or root on the remote host, beyond Docker access.

**Fairness across hosts.**
- Both arms of a pair always run on the **same host at the same time**. A report uses one host, and records its alias, CPU and RAM, architecture, engine version and image digests.
- Images are built on the execution host, for its native architecture, so x86-64 and arm64 hosts both work. Comparing reports from different hosts is flagged as a confound.
- Spreading one report's pairs across a pool of hosts is deferred.

**Engines.** Docker is the MVP engine. Podman is a later option, through the same CLI surface: `ssh <alias> podman …`, or a `podman system connection`.

**Windows note.** Windows OpenSSH does not support `ControlMaster` connection sharing, so each Executor call opens its own SSH connection, which costs about 0.2–1 s. That overhead falls only on setup and copying, never on timed work. On hosts that support `ControlMaster` (Linux and macOS controllers), the Executor turns it on automatically.

### 3.6 Arm configurations: comparative, A/B, single-arm

An **arm** is a label bound to a configuration: either `plain` (an empty config dir on the base image) or a treatment directory. A run has one or two arms. Three shapes are supported:

| Shape | CLI | Arm A (reference) | Arm B (candidate) | Output |
|---|---|---|---|---|
| **Comparative** (default) | `--treatment X` | `plain` | `X` | Full verdict, X ÷ plain |
| **A/B** | `--arm-a X --arm-b Y` | treatment `X` | treatment `Y` | Same statistics, Y ÷ X, with A/B verdict wording (§6) |
| **Single-arm** | `--treatment X --no-control` (or `--arm-a X` alone) | — | `X` (or `plain`) | Absolute metrics only, no verdict |

- **The plain control is just another arm.** The trial lifecycle, pairing, isolation checks, probe and analyses (§3.7) run identically per arm. `--arm-a plain --arm-b plain` is exactly the A/A calibration run (§6).
- **A/B.** Each arm is built and checked on its own:
  - Each arm gets its own image layer (§3.4).
  - Each arm's `init` snapshot must match *its own* manifest.
  - Each arm's container must not contain the *other* arm's declared tools.
  - Arm A is the reference for ratios, so pick the incumbent (for example, the team's current bundle) as A.
  - The report names both treatments and their hashes. It notes that "plain" was not part of the run, so the result says nothing about either bundle versus vanilla Claude Code.
- **Single-arm (`--no-control`).** This is for debugging a treatment, checking that a task suite is solvable, piloting task difficulty (§4 calibration), or exercising a new execution host.
  - Trials run one at a time instead of in pairs. The concurrency is 1.
  - The report shows per-task absolute metrics: success and pass^k, wall_s, cost, tokens, turns, `dependency_used` and analyses.
  - The report is stamped **SINGLE-ARM — NO COMPARATIVE VERDICT**. `summary.json` sets `"verdict": null`, so CI can't mistake it for a pass.
  - Comparing single-arm reports from different runs is not supported. Those runs are unpaired and happened at different times, which is exactly the drift pairing exists to remove. That comparison is deferred (see the roadmap).
- **Run modes combine with arm shapes.** Lightning, quick and full set reps and tasks. Arm shape sets what runs per rep. For example, `--lightning --no-control` gives 6 agent runs.

### 3.7 Post-run analyses (optional, per arm)

These help chase down unexpected agent behavior: files the agent touched beyond the task, documentation churn, test restructuring, and so on. A run can attach one or more **analyses**.

```toml
# analyses/non-code-changes.toml
name        = "non-code-changes"
scope       = "trial"            # "trial": after every trial; "arm": once per arm over all its trials
prompt_file = "non-code-changes.md"
budget_usd  = 1.00
```
```markdown
<!-- analyses/non-code-changes.md -->
Determine what changes were made during the previous session that did not directly
affect the product code — e.g. roadmap or documentation changes, test structure
changes, config/tooling files, or other items. Create a report outlining these
non-code changes, citing file paths and the transcript steps that produced them.
```
Attach analyses with `--analysis non-code-changes`, which can be repeated. A run can also list default analyses in `hai-proof.toml`.

**Trial-scope execution.** These run after grading and before the container is destroyed. They are lifecycle step 6 (§3.1).
1. The runner builds `/analysis/` inside the trial container:
   - `workspace/`: a *copy* of the final `/work`. It is a git repo whose baseline commit is the pre-agent state, so `git diff baseline` shows exactly what the session changed.
   - `transcript.jsonl`: the agent's full stream-json.
   - `task.md`: the task prompt.
   - `grade.json`: the grader output.
   - `diff_breakdown.json`: see §5.
2. It runs a **separate, neutral** Claude session:
   ```
   claude -p "$(cat prompt)" --safe-mode --model <pinned> \
     --permission-mode dontAsk \
     --allowedTools "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git status:*),Write(/analysis/out/**)" \
     --max-budget-usd <budget_usd> --no-session-persistence --output-format json
   ```
   - It runs in `/analysis` with a fresh, empty `CLAUDE_CONFIG_DIR`.
   - `--safe-mode` matters here. The treatment's project files (`CLAUDE.md`, `.claude/`) are present in the copied workspace, and without safe mode the analyzer would load the very harness it is analyzing. With it, every arm is analyzed by the same vanilla analyzer.
   - The exact `--allowedTools` rule syntax must be confirmed during the build.
3. **Blinding.** The analyzer is never told the arm label or the treatment name. The transcript and the files speak for themselves.
4. The output is `/analysis/out/report.md`. It is copied to `results/<ts>/<arm>/<task>/rep<n>/analysis-<name>.md`.

**Arm-scope execution.** This runs once per arm after all of that arm's trials, on the execution host, in a fresh container from the base image. Its inputs are every trial-scope analysis report from that arm, plus all transcripts and `diff_breakdown.json` files. Use it for prompts like "which non-code changes recur across runs?" The same safe-mode, blinding and budget rules apply.

**Isolation from the measurements.**
- Analyses run *after* grading, on a copy of the workspace, so they cannot change a result.
- Their tokens, cost and time are recorded as `analysis_*` fields. They are **never** added to an arm's metrics or used in a verdict.
- Analysis cost is shown separately in the report's cost summary. A trial-scope analysis in full mode adds up to 60 extra sessions, each capped by its `budget_usd`.
- A failed or over-budget analysis is logged and leaves the trial's result untouched.

**Deterministic companion.** The runner always computes `diff_breakdown` with no LLM. It sorts the session's changed files into categories by path rules, which can be overridden per task:
- `product_code`, `tests`, `docs` (`*.md`, `docs/`), `planning` (`ROADMAP.md`, `TODO*`, `openspec/`, `.beads/`), `config_tooling` (`pyproject.toml`, `.github/`, `.claude/`, …), `treatment_artifact`, `other`.

That gives a cheap, objective first answer to "what else did the agent change?" in every run. An LLM analysis is then for explaining *why*.

## 4. Task suite (6 tasks)

Tasks come from one of two sources, and each task declares which.
- **Open repos** (§4.1): the default for the suite whose results get published. Anyone can reproduce them.
- **A private synthetic fixture repo** written for hai-proof, in Python (the company's dominant language). It is a realistic small service of roughly 3–6k lines with a test suite. It cannot be in any training data, but only people with access to it can rerun its results.

| ID | Kind | Level | Shape |
|---|---|---|---|
| B1 | Bug | 1 | Wrong result in one function; the prompt includes the failing input and a traceback. |
| B2 | Bug | 2 | Symptom reported from the user's view ("totals are off for refunded orders"); the cause is one or two modules away. |
| B3 | Bug | 3 | Cross-cutting defect, such as a concurrency, caching or state-ordering issue, with a misleading symptom. |
| F1 | Feature | 1 | Add a parameter or flag to an existing endpoint or function. |
| F2 | Feature | 2 | New endpoint or command that touches model, service and API layers, following existing patterns. |
| F3 | Feature | 3 | Feature that needs a small refactor first, such as extracting an interface or adding a second storage backend. |

**Authoring rules.**
- Each bug is injected by reverting a known-good change. Its hidden tests fail before the fix and pass after.
- Every task ships a reference solution, which must pass `grade.sh`. That check is part of CI for the suite itself.
- Prompts are written the way a developer would actually write them. They do not tell the agent to "run the tests" or name a hidden test.
- **Calibrate** with a 3-run pilot of the control arm. Level 1 should take minutes, level 3 should take well under the timeout, and every task should pass at least 2 of 3. Replace any task the control cannot solve reliably: if it fails, it measures luck instead of overhead.

**Optional second fixture.** Use a frozen snapshot of a real internal repo, with 2–3 tasks recreated from historical bug-fix commits. This captures the treatment's home turf, because many CLAUDE.md files encode repo-specific knowledge, and that knowledge might genuinely help there.

### 4.1 Open-repo task sources (reproducibility)

Results are only persuasive if anyone in the company can rerun them. Not everyone can see the same internal repos, and a result nobody else can reproduce invites claims of bias. So hai-proof also supports tasks built on **public open-source repos**. The suite that gets published, the one results are quoted from, should be built this way.

**Task spec.** `task.toml` can point at a public repo instead of a local `repo/` directory:
```toml
[source]
kind   = "git"
url    = "https://github.com/<org>/<project>.git"
base   = "<full commit SHA>"   # the state the agent starts from
fix    = "<full commit SHA>"   # optional: upstream fix, used to derive hidden tests + reference solution
```

**How a task is built.**
1. `hai-proof build-task` clones the repo, checks out `base`, and **deletes `.git`**. It then re-initializes a single-commit repo, so the agent cannot find the fix in the history.
2. It installs dependencies into the task image. Graders and agents then run offline apart from the model API.
3. When `fix` is set, the hidden tests are the test-file changes from `fix`. The reference solution is the non-test part of that commit.
4. Everything is pinned by SHA. Anyone with the hai-proof repo can rebuild a byte-identical task and rerun it.

**Contamination tradeoff.** The model may have seen a public repo, or even the specific fix, in training. That is acceptable here, for three reasons:
- hai-proof measures the *difference* between arms, and both arms share the same model and therefore the same memorization.
- Mixed results still show up as success disagreements.
- Memorization makes tasks easier, which compresses the time and cost of both arms. This works against finding a difference, so any difference that does appear is if anything understated.

To limit memorization, prefer fix commits dated after the pinned model's training cutoff. Failing that, use **injected bugs**: a fresh mutation in a public repo, written by the task author, which cannot be in any training set. Each task records which kind it is, `upstream-fix` or `injected`, and the report shows it.

**Leakage from the open internet.** The agent has network access to reach the API, and the upstream fix is public.
- The container's egress allowlist permits only the Anthropic API, plus any hosts the treatment's `manifest.toml` declares for its MCP servers.
- The runner also scans each transcript for the upstream repo URL or the fix SHA. A run that reached either is flagged and excluded.

**Choosing open repos.** Use permissively licensed, actively maintained **Python** projects with fast, deterministic `pytest` suites (under a minute) and no services to stand up (no database, network or GPU). They need enough size (more than 10k lines) that navigating the code costs something. The default suite takes the six task slots in §4 from 2–3 such repos.

Candidates to vet, all pure-Python with pytest suites: `click`, `httpx`, `rich`, `attrs`, `marshmallow`. Each still has to pass two checks:
- The test suite runs in under a minute in the container.
- The project has enough fix commits after the model's training cutoff for `upstream-fix` tasks.

Dependencies are installed with `uv sync`, or `uv pip install -e .[test]`, at build time.

## 5. Metrics per trial

| Metric | Source |
|---|---|
| `success` | `acceptance_pass && regression_pass` |
| `wall_s` | In-container wrapper, monotonic, from `claude` process start to exit |
| `api_s` | `duration_api_ms` |
| `cost_usd` | `total_cost_usd`. Includes subagents. It is a client-side estimate, used only for relative comparison. |
| `tokens_{input,output,cache_read,cache_write}` | Summed over **`modelUsage`**. Includes subagents. The top-level `usage` field excludes them and would undercount. |
| `turns` | `num_turns` |
| `tool_calls`, `subagent_calls`, `skills_fired` | Counted from the stream-json transcript |
| `diff_lines` | `grade.sh` |
| `diff_breakdown` | Changed files and lines per category: product_code, tests, docs, planning, config_tooling, treatment_artifact, other (§3.7) |
| `analysis_*` | Tokens, cost and time of post-run analyses. Reported separately and **never** included in arm metrics or verdicts. |
| `terminal_reason`, `is_error` | Result event; distinguishes max-turns or budget exhaustion from completion |
| `init_snapshot` | `system/init`: tools, MCP servers, plugins, errors. Used for the isolation check. |

The run also records the CLI version, image digest, model ID, start time and treatment hash.

## 6. Analysis and verdict

- **Reliability.** For each task and arm, report pass^5: the fraction of task–arm cells where all five runs pass. A task where the arms disagree on success is listed explicitly. It is never averaged away.
- **Efficiency.** For cost, total tokens and wall_s, the headline is the **geometric-mean ratio, treatment ÷ control**, with a 95% **cluster bootstrap** CI. The bootstrap resamples tasks, then repetitions within each task, on log values. A Wilcoxon signed-rank test on per-task median log-ratios gives the p-value. Report each task's ratio as well, in a forest plot.
- **Verdict rules.** The margin is ±15%, which suits a smoke test.

| Verdict | Condition |
|---|---|
| **HARMFUL** | Treatment pass^k is lower on any task, or its overall success rate drops by 10 points or more. |
| **COSTS MORE THAN IT'S WORTH** | Success is the same, and the CI lower bound on the cost ratio *or* the wall ratio is above 1.15. |
| **PAYS FOR ITSELF** | Success is the same or better, and the CI upper bound on cost *and* wall is below 0.85, or success is strictly better. |
| **NO MEANINGFUL DIFFERENCE** | Both CIs fall inside [0.85, 1.15]. |
| **INCONCLUSIVE** | Anything else. Add repetitions, or check the per-task plots for one outlier task. |

**Calibration before first use: the A/A run.** Run control against control, using the same suite and procedure. Two things must hold:
1. The verdict is NO MEANINGFUL DIFFERENCE.
2. The measured within-task log-SD is used to confirm the suite's power. At log-SD ≈ 0.3, about 8 paired observations detect a 30% shift. Six tasks × 5 reps = 30 pairs, which leaves room for heavy tails.

If A/A reports a difference, the harness itself is broken. Repeat the A/A after any CLI or model upgrade.

**Other arm shapes (§3.6).**
- **A/B runs** use the same statistics and thresholds. Ratios are B ÷ A, and the verdicts are worded relative to A:
  - **B HARMFUL vs A**
  - **B COSTS MORE THAN A**
  - **B CHEAPER THAN A**
  - **NO MEANINGFUL DIFFERENCE**
  - **INCONCLUSIVE**

  The report states that neither arm was compared with plain Claude Code.
- **Single-arm runs** produce no verdict. They report per-task absolute metrics and pass^k only.

## 7. Cost and runtime envelope

- A full run is 6 tasks × 5 reps × 2 arms = **60 agent runs**, plus 10 probe runs and 1 warm-up pair.
- **Cost ceiling:** the per-task `--max-budget-usd` caps spend, for example at $3, $5 and $8 by difficulty level. Expected spend is far lower. The pilot will give real numbers.
- **Runtime:** pairs run concurrently. At an average of 6 minutes per run, that is about 30 pairs × 6 min ≈ **3 hours**.
- **Quick mode** (3 reps, no level-3 tasks) runs 24 agent runs in about 1 hour. It suits a first look at a new bundle.
- **Arm shape** changes these counts: single-arm runs halve them, and A/B runs match comparative ones. Trial-scope analyses add one capped session per trial, with cost reported separately.
- **Lightning mode** runs a single repetition of all 6 tasks. That is 12 agent runs plus the context-tax probe, in roughly 30–40 minutes.
  - One repetition gives no within-task variance, so lightning mode does not compute bootstrap CIs or Wilcoxon p-values.
  - It reports the per-task ratios, the overall geometric-mean ratio, any success disagreements, and the probe result.
  - The verdict is labelled **INDICATIVE**. It is one of LIKELY COSTLIER, LIKELY CHEAPER, LIKELY HARMFUL or NO OBVIOUS DIFFERENCE.
  - "Likely" requires the same direction on at least 5 of 6 tasks *and* a geometric-mean ratio beyond ×1.5 or ×0.67. A single run of the same task can vary by about 2× on its own, so anything narrower is noise.
  - Use it as a triage gate. A bundle that looks costlier in lightning mode is worth a quick or full run before anyone argues about it.

| Mode | Reps | Tasks | Agent runs | Statistics | Verdict |
|---|---|---|---|---|---|
| Lightning | 1 | 6 | 12 | per-task ratios only | INDICATIVE |
| Quick | 3 | 4 (levels 1–2) | 24 | bootstrap CI, Wilcoxon | full verdict, wider CIs |
| Full | 5 | 6 | 60 | bootstrap CI, Wilcoxon | full verdict |

## 8. Reporting

`report.html` is a single file, and `summary.json` holds the same content for CI. The report contains:
1. **The verdict line**, for example: "Treatment `team-superpowers@a1b2c3`: COSTS MORE THAN IT'S WORTH. Success 30/30 vs 30/30, cost ×1.62 [1.41, 1.88], wall ×1.37 [1.18, 1.60]."
2. **The context-tax probe**: fixed tokens added per session.
3. A per-task table and forest plot for the cost, token and wall ratios.
4. Success disagreements, with links to both transcripts.
5. Behavioral diffs: tool calls, subagent spawns, skills fired, and turns.
6. The isolation audit: the `init` snapshots of both arms.
7. **Change breakdown**: `diff_breakdown` per arm, highlighting non-code categories where the arms differ.
8. **Analyses**: arm-scope reports inline, with links to the per-trial reports and their separate cost.
9. A header stating the arm shape (comparative, A/B or single-arm) and each arm's configuration and hash.

## 9. Relationship to existing tools

- **`claude plugin eval --ablation with-without`** (checked locally in v2.1.289) runs a plugin's own eval cases with and without the plugin. It is the right tool for a plugin author asking "does my skill trigger and behave?". It does not fit here:
  - It covers only plugins. Bare CLAUDE.md files, settings-level hooks and MCP servers are out of scope.
  - It is built around graders on the plugin's own prompts, not a fixed coding suite.
  - Its reports emphasize scores, not cost or time.

  hai-proof can accept a plugin as a treatment, with the plugin placed in `user/`.
- **Inspect AI, Harbor / Terminal-Bench:** good models for the task and grader layout. hai-proof borrows their pattern of instruction + environment + hidden tests + oracle. A 6-task suite does not need their machinery. Revisit if the suite grows.
- **OpenTelemetry export** (`CLAUDE_CODE_ENABLE_TELEMETRY=1`): a possible secondary source, which emits `skill_activated` and per-request events. It is deferred because stream-json already holds what we need.

## 10. Threats to validity and mitigations

| Threat | Mitigation |
|---|---|
| Control secretly picks up the developer's `~/.claude`, managed policy or claude.ai connectors | Containers with an empty HOME and `CLAUDE_CONFIG_DIR`; the `init`-snapshot assertion; A/A calibration |
| Model or CLI drift during a run | Pin the full model ID and CLI version in the image; disable non-essential traffic; record versions; never compare across reports run on different versions |
| Prompt cache warmth favoring one arm | Concurrent pairs; warm-up pair; tokens reported by type (cache read and write separately) |
| Remote execution host skews timing (SSH latency, dropped links) | Timing is taken inside the container; trials run detached and survive disconnects; results are copied back afterwards |
| Different execution hosts (CPU, architecture, load) | Both arms of a pair always on the same host at the same time; host specs recorded; cross-host comparisons flagged |
| API key exposed on a shared remote host | Key passed over the SSH channel, never written to the remote disk or put in a command line; containers removed after each trial; a dedicated low-limit key is recommended |
| API latency or rate limits | Concurrent pairing; discard and rerun the whole pair on 429; log the discard count |
| Test leakage | Hidden tests are copied in only after the agent exits; the fixture has no fix in its git history; graders run offline |
| Treatment's external tools leak into control, or installing them inflates treatment time | Tools installed only in a per-treatment image layer at build time; control preflight asserts they are absent; setup runs before the clock starts |
| Skill's external tool never actually used | Transcript scan reports `dependency_used` per tool, and the report flags dependencies with zero use |
| Treatment needs a user-typed trigger (slash-command workflow) | `manifest.toml` `prompt_prefix` is part of the treatment, recorded in the report |
| The analyzer is biased by the harness it analyzes, or by knowing the arm | The analyzer runs with `--safe-mode`, in a fresh config dir, on a workspace copy; it is never told the arm or treatment name |
| Analysis cost or time leaks into arm metrics | Recorded as separate `analysis_*` fields and excluded from every verdict |
| A/B result misread as "better than vanilla" | A/B reports state that plain Claude Code was not an arm; a comparative run against `plain` is needed for that claim |
| Treatment claims quality, not speed | Out of scope for the smoke test; diff size and regression pass are recorded; a blinded LLM-judge quality rubric is deferred |
| The agent's choice of model or effort differs | Both pinned; `CLAUDE_CODE_SUBAGENT_MODEL` pinned; treatments that change the model are flagged in the report as a confound |
| Results generalize poorly beyond one fixture repo | Explicitly a smoke test; open-repo tasks span 2–3 projects; the optional internal-repo fixture covers repo-specific claims |
| Results can't be reproduced by colleagues without access to internal repos | The published suite uses public repos pinned by SHA (§4.1); reports embed the CLI version, model ID, image digest and treatment hash |
| Public repos are in the model's training data | Applies equally to both arms; prefer post-cutoff fixes or injected bugs; task kind shown in the report |
| Agent fetches the upstream fix from the internet | Egress allowlist; transcript scan flags runs that touch the upstream URL or the fix SHA |

## 11. Build plan

1. **Runner MVP.**
   - The `Executor` interface with local and SSH implementations, plus `hai-proof hosts list` and `hai-proof hosts check` driven by `~/.ssh/config` (§3.5).
   - The Docker image, trial lifecycle, stream-json parsing and init-snapshot assertion.
   - A single-trial command: `hai-proof run --host <alias> --treatment X --tasks B1 --reps 1`.
2. **Task suite.**
   - Build `hai-proof build-task` for open repos (§4.1).
   - Assemble the 6-task published suite from 2–3 public repos, plus reference solutions and the calibration pilot.
   - Add the private fixture if it is still wanted.
   - Add lightning mode alongside quick and full.
3. **Treatment dependencies** (§3.4).
   - Build `hai-proof build-treatment`: the image layer, the `check` lines, the `setup` step, and the control-absence preflight.
   - Build the transcript scan that reports `dependency_used`.
   - Prove it end to end with an OpenSpec bundle and a beads bundle.
4. **A/A calibration**, recording the measured σ.
5. **Analysis and report**: bootstrap, Wilcoxon, verdict rules, HTML report.
6. **Arm shapes and post-run analyses** (§3.6, §3.7):
   - `--no-control`, and `--arm-a` with `--arm-b`.
   - `diff_breakdown`.
   - The trial-scope and arm-scope analysis runner, with the `non-code-changes` analysis as the first built-in.
7. **First real treatments**: pick 2–3 bundles that are popular internally and publish the results.
8. *(Optional)* A CI job so a bundle author must attach a hai-proof report before the bundle goes into the shared marketplace.

## Sources

- Anthropic, "Demystifying evals for AI agents": https://anthropic.com/engineering/demystifying-evals-for-ai-agents
- Gloaguen et al., "Evaluating AGENTS.md" (abstract only): https://arxiv.org/pdf/2602.11988
- Anthropic, "Advanced tool use" (MCP tool-definition overhead): https://www.anthropic.com/engineering/advanced-tool-use
- "How Do AI Agents Spend Your Money?" (run-to-run token variance): https://arxiv.org/html/2604.22750v2
- Miller, "Adding Error Bars to Evals": https://arxiv.org/abs/2411.00640
- Contamination evidence on SWE-bench Verified: https://arxiv.org/abs/2506.12286
- Claude Code docs: https://code.claude.com/docs/en/headless, /cli-reference, /env-vars, /agent-sdk/cost-tracking, /monitoring-usage
