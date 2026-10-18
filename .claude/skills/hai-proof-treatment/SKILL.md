---
name: hai-proof-treatment
description: Package a Claude Code setup (the user's own CLAUDE.md, skills, agents, commands, hooks, plugins, MCP servers or CLI tools, or a third-party plugin) as a hai-proof treatment, so it can be A/B tested against plain Claude Code. Use when the user wants to evaluate their configuration, a team setup, or a plugin with hai-proof.
---

# Package a treatment

A treatment is the one thing that differs between the arms. Arm A is plain Claude Code. Arm B is the
same model, CLI version, limits, task and host, plus the treatment. Read DESIGN §3.4 and §3.6 for the
mechanics. `treatments/code-simplifier` is a minimal plugin treatment, `treatments/spartan` a large one with a
scripted workflow, and `treatments/openspec` a CLI tool plus setup commands.

## Layout (`private/treatments/<name>/` for anything private; `treatments/<name>/` only for public, permissively licensed bundles)

```
manifest.toml   name, prompt_prefix, [workflow], [env], [[requires]], [setup], [network], [expect]
user/           copied to the agent's ~/.claude   (CLAUDE.md, skills/, agents/, commands/, hooks/, settings.json, plugins)
project/        copied into the repo root /work before the baseline commit (CLAUDE.md, .claude/, .mcp.json)
Dockerfile      optional root build steps appended to the base image (no FROM); arm B only
NOTICE          licence and provenance notes when needed
```

`private/treatments` is searched automatically (`extra_treatments_dirs`), so `--treatment <name>` finds it.
A path also works (`--treatment private/treatments/<name>`).

## 1. Find out what is being tested

Ask the user which parts of their setup the treatment should include. Don't assume "everything":
- each extra piece adds context cost;
- a mixed bundle can't say which part helped.

Then inventory only what they named:
- **User-level** (`~/.claude/`; `%USERPROFILE%\.claude\` on Windows): `CLAUDE.md`, `skills/`, `agents/`,
  `commands/`, `settings.json` (hooks, env, enabledPlugins), and installed plugins under
  `plugins/cache/<marketplace>/<plugin>/<version>/`.
- **Project-level** (in the repo they work in): `CLAUDE.md`, `.claude/` (skills, agents, commands,
  settings.json), `.mcp.json`.
- **MCP servers configured with `claude mcp add`**: these live in `~/.claude.json` (user scope), which the
  treatment can't carry. Move them to `project/.mcp.json`.

**Never copy:**
- `projects/`, `history.jsonl`, `todos/`, `shell-snapshots/`, `statsig/`, `ide/`;
- `.credentials.json`, `settings.local.json`, `~/.claude.json`;
- memory files;
- anything holding a token.

Before writing any file, scan what you are about to copy for secrets (`sk-ant-`, `ghp_`, `xox`, `AKIA`,
`Bearer`, `password`, `token`). Stop and ask if you find one. Treatments have no secret channel: `[env]` values
are written into the trial's files. An MCP server or hook that needs a credential can't be evaluated yet. Say
so rather than embedding it.

## 2. Build the bundle

- **CLAUDE.md, skills, agents, commands:** copy them into `user/` or `project/` where they were scoped.
  Remove references to the user's machine (absolute paths, private hostnames) or point them at
  `/home/agent/.claude/...`.
- **settings.json:** keep only the keys that are part of the treatment: `hooks`, `env`, `enabledPlugins`,
  `extraKnownMarketplaces`, `outputStyle`, `enableAllProjectMcpServers`.
  - Drop `model`, effort and `permissions`. Both arms pin the model and run with bypassPermissions, so a model
    setting would be a confound, not a treatment.
  - Drop `statusLine` and `apiKeyHelper`.
- **Hooks:** copy each hook script into `user/hooks/` and rewrite its command to
  `/home/agent/.claude/hooks/<script>`.
  - The base image has bash, Python 3.12, Node 22, git and curl. Anything else (`jq`, a linter) is a
    `[[requires]]` entry.
  - A hook that calls a network service needs that host in `[network] allow`.
- **Plugins:** vendor the exact installed version. Never let the trial fetch one.
  - Copy the code from the plugin cache, or clone the plugin's repo at the commit it was installed from.
  - Record the source, version, commit and licence at the top of `manifest.toml`. Add a `NOTICE` if the
    licence file is missing or unusual.
  - Reproduce the local-marketplace layout exactly as in `treatments/code-simplifier/user/`:
    - `user/hai-proof-mkt/.claude-plugin/marketplace.json` names marketplace `hai-proof-pinned`, with one entry per plugin (`"source": "./<plugin>"`);
    - `user/hai-proof-mkt/<plugin>/` holds the plugin;
    - `user/plugins/cache/hai-proof-pinned/<plugin>/<version>/` holds a second copy of it;
    - `user/plugins/installed_plugins.json` and `user/plugins/known_marketplaces.json` follow the existing files, with paths under `/home/agent/.claude/`;
    - `user/settings.json` has `extraKnownMarketplaces.hai-proof-pinned` (directory source) and `enabledPlugins: {"<plugin>@hai-proof-pinned": true}`.
  - For a plugin the user didn't write, read its hooks, `.mcp.json` and scripts before vendoring. Note in the
    manifest anything that runs at load or uses the network.
- **MCP servers:** declare them in `project/.mcp.json`, and set `"enableAllProjectMcpServers": true` in `user/settings.json`.
  - A stdio server installs as a pinned `[[requires]]` (e.g. `npm install -g <pkg>@<exact version>`, with a `check`).
  - A remote server's host goes in `[network] allow`.
- **CLI tools and per-repo init:** see `treatments/openspec/manifest.toml`.
  - `[[requires]]` install lines run once at image build, with exact versions.
  - `[setup] commands` run non-interactively in `/work` before the clock starts.
  - `artifacts` lists files the workflow writes that shouldn't count as code changes.
- **`[expect]`:** list each plugin name, MCP server name and key skill or command the treatment must load.
  The run checks them against Claude Code's init event and excludes trials where they're missing. That
  catches a treatment that silently didn't load.

## 3. Decide how it gets used

Plain prompts often never trigger a treatment. code-simplifier was never delegated to unprompted, and
spartan's router never reached its debug or build workflows. If real users invoke the treatment
explicitly, script that:
- `prompt_prefix = "..."` goes in front of every task prompt.
- `[workflow] turns = ["/plugin:command {task_prompt}", "follow-up message"]` sends user turns in order.
  One of them must contain `{task_prompt}`.
- A workflow that stops to ask questions needs `run --user uninformative` (or `informative` with `user.md` briefs).

Write down in a manifest comment why the turns are what they are. Keep both arms honest: the scripted
text is part of the treatment, and arm A only ever gets the task prompt.

## 4. Verify

1. **Check the manifest loads:** run `uv run hai-proof run --treatment <name> --suite smoke --mode lightning --dry-run`.
2. **Smoke run:** run the same command without `--dry-run`, after asking the user, since it spends roughly $1–3. Then check that:
   - both arms pass the three smoke tasks;
   - no trial is `excluded` (an isolation failure means `[expect]` didn't match what loaded);
   - `init_snapshot` in `trials.jsonl` lists the plugins, MCP servers and skills;
   - the transcripts show the treatment actually acting: skill calls, subagent runs, hook output.

   If it never acts, fix the workflow before spending on a full run.
3. **Record it:** add a ROADMAP row (or the user's own tracker) with the smoke run id. Then hand over to the
   `hai-proof-evaluate` skill for the real run.
