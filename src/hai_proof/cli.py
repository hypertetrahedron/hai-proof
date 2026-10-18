"""hai-proof command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .models import ASK_TOOL_MODES, USER_MODES


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hai-proof", description="A/B smoke test for Claude Code harness modifications")
    p.add_argument("--version", action="version", version=f"hai-proof {__version__}")
    p.add_argument("--root", type=Path, default=Path.cwd(), help="project root containing hai-proof.toml")
    sub = p.add_subparsers(dest="cmd", required=True)

    hosts = sub.add_parser("hosts", help="discover and check execution hosts")
    hsub = hosts.add_subparsers(dest="hosts_cmd", required=True)
    hl = hsub.add_parser("list", help="list hosts from ~/.ssh/config and probe them")
    hl.add_argument("--no-probe", action="store_true")
    hl.add_argument("--config", type=Path, help="ssh config path (default ~/.ssh/config)")
    hc = hsub.add_parser("check", help="full preflight of one host")
    hc.add_argument("host", nargs="?", help="ssh alias or 'local' (default: configured host)")

    bt = sub.add_parser("build-task", help="materialise an open-repo task from its [source] (DESIGN §4.1)")
    bt.add_argument("task_dir", type=Path)
    bt.add_argument("--force", action="store_true")

    vt = sub.add_parser("validate-task", help="prove tasks are well-formed on the execution host (no API spend)")
    vt.add_argument("--host", help="ssh alias or 'local'")
    vt.add_argument("--tasks", help="comma-separated task ids (default: all)")
    vt.add_argument("--cli-version", help="Claude Code version for the base image")

    b = sub.add_parser("build", help="build base/treatment/trial images on the execution host")
    _run_args(b)

    r = sub.add_parser("run", help="run an evaluation")
    _run_args(r)
    r.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    r.add_argument("-y", "--yes", action="store_true", help="skip the spend confirmation")

    rg = sub.add_parser("regrade", help="re-grade trials' session.patch in fresh containers (no API spend)")
    rg.add_argument("results_dir", type=Path)
    rg.add_argument("--host", help="execution host alias (default: the run's host)")
    rg.add_argument("--all", action="store_true", help="regrade passing trials too (default: failed only)")
    rg.add_argument("--trials", help="comma-separated ARM/TASK/REP, e.g. A/B7/0,B/B1/0")
    rg.add_argument("--write", action="store_true",
                    help="record changed results in trials.jsonl (+ regrade.json) and regenerate the report")

    rep = sub.add_parser("report", help="regenerate summary.json and report.html for a results dir")
    rep.add_argument("results_dir", type=Path)

    bl = sub.add_parser("baseline", help="long-run plain-arm aggregates per task (tasks/<ID>/baseline.json)")
    blsub = bl.add_subparsers(dest="baseline_cmd", required=True)
    blu = blsub.add_parser("update", help="fold runs' plain-arm trials into each task's baseline.json")
    blu.add_argument("results_dirs", type=Path, nargs="*",
                     help="results dirs to fold in (default: every run under the configured results dir)")
    blu.add_argument("--legacy", action="store_true",
                     help="accept runs recorded before task hashes existed, assuming the current task content")
    blu.add_argument("--skip", action="append", default=[], metavar="TASK:RUN_ID",
                     help="leave out one task of one run (e.g. graded before a task fix); repeatable")
    bls = blsub.add_parser("show", help="print the baselines for the current task content")
    bls.add_argument("--tasks", help="comma-separated task ids (default: all)")

    ses = sub.add_parser("sessions", help="compare Claude Code sessions across trials and runs")
    ses.add_argument("results_dirs", type=Path, nargs="*",
                     help="results dirs to include (default: every run under the configured results dir)")
    ses.add_argument("--task", help="only this task id")
    ses.add_argument("--out", type=Path, help="output HTML path (default: <results dir>/sessions.html)")
    ses.add_argument("--refresh", action="store_true",
                     help="also rewrite each trial's claude_data.json and session.html with the current parser")

    args = p.parse_args(argv)
    # Task output (grader tails, rendered text) can contain non-ASCII; never crash a Windows cp1252 console.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001
        from .config import ConfigError

        if isinstance(e, ConfigError):
            print(f"error: {e}", file=sys.stderr)
            return 2
        raise


def _run_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--host", help="ssh alias or 'local'")
    arms = sp.add_argument_group("arms (DESIGN §3.6)")
    arms.add_argument("--treatment", help="treatment to compare against plain Claude Code")
    arms.add_argument("--arm-a", help="reference arm for A/B runs (treatment name, path, or 'plain')")
    arms.add_argument("--arm-b", help="candidate arm for A/B runs")
    arms.add_argument("--no-control", action="store_true", help="single-arm run (no comparison)")
    ul = sp.add_argument_group("user in the loop (DESIGN §3.8)")
    ul.add_argument("--user", choices=USER_MODES, default="conventional",
                    help="who answers the agent between turns, both arms: conventional = nobody (one session, the "
                         "classic test); uninformative = a stand-in that always says 'use your best judgement'; "
                         "informative = a stand-in that answers from each task's user.md")
    ul.add_argument("--user-a", choices=USER_MODES, help="override --user for arm A")
    ul.add_argument("--user-b", choices=USER_MODES, help="override --user for arm B")
    ul.add_argument("--ask-tool", choices=ASK_TOOL_MODES, default="off",
                    help="offer the agent AskUserQuestion, both arms (`claude -p` alone never does): on = stream-json "
                         "input with stdio permission prompts, questions answered like --user (fixed reply unless "
                         "informative); hidden = the same input mode without the tool (the control for on)")
    ul.add_argument("--ask-tool-a", choices=ASK_TOOL_MODES, help="override --ask-tool for arm A")
    ul.add_argument("--ask-tool-b", choices=ASK_TOOL_MODES, help="override --ask-tool for arm B")
    ul.add_argument("--stand-in-model", help="model of the user stand-in (default from hai-proof.toml)")
    ul.add_argument("--max-user-replies", type=int, default=5, metavar="N",
                    help="stand-in replies per trial (default 5); then the script moves on or the trial ends")
    sp.add_argument("--mode", choices=["lightning", "quick", "full"], default="full")
    sp.add_argument("--reps", type=int, help="override repetitions (mode becomes 'custom')")
    sp.add_argument("--tasks", help="comma-separated task ids (default: the suite's tasks for the mode)")
    sp.add_argument("--suite", help="task suite from task.toml `suites` (default: standard; 'all' for every task)")
    sp.add_argument("--analysis", action="append", default=[], help="attach an analysis (repeatable)")
    sp.add_argument("--model", help="full model id (overrides hai-proof.toml)")
    sp.add_argument("--effort")
    sp.add_argument("--cli-version", help="Claude Code version to pin (default from hai-proof.toml)")
    sp.add_argument("--probe-runs", type=int, help="context-tax probe runs per arm (0 disables)")
    sp.add_argument("--no-warmup", action="store_true")
    sp.add_argument("--egress", choices=["proxy", "open"])
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--max-spend", type=float, metavar="USD",
                    help="stop cleanly before any pair that could take the run's agent cost past USD "
                         "(reserve = most expensive pair so far)")
    sp.add_argument("--limit-scale", type=float, default=1.0, metavar="N",
                    help="multiply every task's time limit, turn limit and budget by N for both arms "
                         "(e.g. 3 for treatments slower than plain; the limits then only stop runaways)")
    sp.add_argument("--resume", type=Path, metavar="RESULTS_DIR",
                    help="continue an interrupted run in RESULTS_DIR: pass the same arguments as the original run; "
                         "finished pairs are kept, the rest run (--max-spend counts the whole run)")


def _dispatch(args: argparse.Namespace) -> int:
    from .config import load_project_config, resolve_host

    root: Path = args.root
    cfg = load_project_config(root)

    if args.cmd == "hosts":
        from . import hosts, sshconfig

        if args.hosts_cmd == "list":
            aliases = sshconfig.list_host_aliases(args.config)
            if args.no_probe:
                print("\n".join(aliases) or "(no hosts found)")
                return 0
            infos = hosts.probe_all(["local", *aliases], ssh_binary=cfg.ssh_binary)
            print(hosts.format_table(infos))
            return 0
        from .executor import make_executor

        host = resolve_host(args.host, cfg)
        info = hosts.probe(host, ssh_binary=cfg.ssh_binary)
        results = hosts.check_host(make_executor(host, ssh_binary=cfg.ssh_binary), info,
                                   cpus=cfg.limits.cpus, memory=cfg.limits.memory)
        for c in results:
            print(f"[{'ok' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
        return 0 if all(c.ok for c in results) else 1

    if args.cmd == "build-task":
        from .tasks import build_task

        build_task(args.task_dir, force=args.force)
        return 0

    if args.cmd == "validate-task":
        from . import images
        from .executor import make_executor
        from .tasks import load_suite
        from .validate import format_validation, validate_task

        ids = [s.strip() for s in args.tasks.split(",")] if args.tasks else None
        tasks = load_suite(root / cfg.tasks_dir, ids)
        ex = make_executor(resolve_host(args.host, cfg), ssh_binary=cfg.ssh_binary)
        base = images.build_base(ex, images.resolve_cli_version(ex, args.cli_version or cfg.cli_version))
        results = []
        for t in tasks:
            if not t.repo_dir.is_dir():
                print(f"[FAIL] {t.id}\n    problem: not built yet; run `hai-proof build-task {t.path}`")
                continue
            v = validate_task(ex, base, t, cpus=cfg.limits.cpus, memory=cfg.limits.memory)
            results.append(v)
            print(format_validation(v), flush=True)
        ok = sum(v.ok for v in results)
        print(f"\n{ok}/{len(tasks)} tasks valid")
        return 0 if ok == len(tasks) else 1

    if args.cmd == "regrade":
        from . import images
        from .config import ConfigError
        from .executor import make_executor
        from .regrade import regrade_run
        from .report import load_run, write_report
        from .tasks import load_suite

        meta, trials = load_run(args.results_dir)
        only = None
        if args.trials:
            only = set()
            for item in args.trials.split(","):
                parts = item.strip().split("/")
                if len(parts) != 3 or not parts[2].isdigit():
                    raise ConfigError(f"--trials wants ARM/TASK/REP, got {item!r}")
                only.add((parts[0], parts[1], int(parts[2])))
        tasks = {t.id: t for t in load_suite(root / cfg.tasks_dir)}
        ex = make_executor(resolve_host(args.host or meta.get("host"), cfg), ssh_binary=cfg.ssh_binary)
        base = images.build_base(ex, str(meta.get("cli_version")))
        lim = meta.get("limits") or {}
        res = regrade_run(ex, base, args.results_dir, meta, trials, tasks, failed_only=not args.all and only is None,
                          only=only, write=args.write, cpus=float(lim.get("cpus", 4)), memory=str(lim.get("memory", "8g")))
        changed = [r for r in res if r.changed]
        print(f"{len(res)} regraded, {len(changed)} changed" + ("" if args.write or not changed else
                                                                 " (pass --write to record)"))
        if args.write and changed:
            meta, trials = load_run(args.results_dir)
            write_report(args.results_dir, meta, trials)
        return 0

    if args.cmd == "report":
        from .config import ConfigError
        from .report import apply_task_order, load_run, write_report
        from .tasks import load_suite

        meta, trials = load_run(args.results_dir)
        try:
            apply_task_order(meta, load_suite(root / cfg.tasks_dir, [t["id"] for t in meta.get("tasks", [])]))
        except ConfigError:
            pass  # a task since removed or renamed: keep the run's own order data
        s, h = write_report(args.results_dir, meta, trials)
        print(f"wrote {s}\nwrote {h}")
        return 0

    if args.cmd == "baseline":
        from . import baselines
        from .config import ConfigError
        from .report import load_run, task_sort_key
        from .tasks import load_suite

        if args.baseline_cmd == "update":
            tasks = load_suite(root / cfg.tasks_dir)
            dirs = args.results_dirs or sorted(p.parent for p in (root / cfg.results_dir).glob("*/run.json"))
            skip = []
            for item in args.skip:
                tid, sep, rid = item.partition(":")
                if not sep or not tid or not rid:
                    raise ConfigError(f"--skip wants TASK:RUN_ID, got {item!r}")
                skip.append((tid, rid))
            added, notes = baselines.update(tasks, ((*load_run(d), d) for d in dirs), legacy=args.legacy,
                                            skip=skip)
            for n in notes:
                print(f"note: {n}")
            for tid, n in added.items():
                print(f"{tid}: +{n} samples")
            print(f"{sum(added.values())} samples added from {len(dirs)} run(s)")
            return 0
        ids = [x.strip() for x in args.tasks.split(",")] if args.tasks else None
        tasks = sorted(load_suite(root / cfg.tasks_dir, ids),
                       key=lambda t: task_sort_key({"id": t.id, "cost_tier": t.cost_tier, "report_order": t.report_order}))
        cols = [("cost_usd", "cost $", 2), ("tokens_output", "out tokens", 0), ("tokens_total", "tokens", 0),
                ("wall_s", "wall s", 0)]
        print(f"{'task':7}{'tier':8}{'model':20}{'cli':9}{'effort':9}{'pass':>7}"
              + "".join(f"{label + ' mean':>17}{'sd':>12}" for _, label, _ in cols))
        for t in tasks:
            for e in baselines.current_entries(t):
                sm = e["summary"]
                row = (f"{t.id:7}{t.cost_tier or '-':8}{e['model']:20}{e['cli_version']:9}{e['effort']:9}"
                       f"{str(sm['passes']) + '/' + str(sm['trials']):>7}")
                for name, _, nd in cols:
                    x = sm["metrics"].get(name)
                    row += f"{x['mean']:>17,.{nd}f}" if x else f"{'-':>17}"
                    row += f"{x['sd']:>12,.{nd}f}" if x and x["sd"] is not None else f"{'-':>12}"
                print(row)
        return 0

    if args.cmd == "sessions":
        from .sessions_compare import compare, write

        base = root / cfg.results_dir
        dirs = args.results_dirs or sorted(d for d in base.iterdir() if d.is_dir())
        rows = compare(dirs, task=args.task, refresh=args.refresh)
        if not rows:
            print("no trials with collected Claude Code data found")
            return 1
        out = args.out or base / ("sessions" + (f"-{args.task}" if args.task else "") + ".html")
        h, j = write(rows, out)
        print(f"{len(rows)} trial(s)\nwrote {h}\nwrote {j}")
        return 0

    # build / run
    from .config import ConfigError, auth_env
    from .executor import make_executor
    from .runner import Runner, make_plan

    run = _build_run_config(args, cfg, root)
    ex = make_executor(run.host, ssh_binary=cfg.ssh_binary)

    if args.cmd == "build":
        from . import images

        version = images.resolve_cli_version(ex, run.cli_version)
        base = images.build_base(ex, version)
        print(f"base: {base}")
        for arm in run.arms:
            arm_img = images.build_treatment(ex, base, arm.treatment)
            print(f"arm {arm.label} ({arm.treatment.name}): {arm_img}")
            for t in run.tasks:
                print(f"  {t.id}: {images.build_trial(ex, arm_img, t)}")
        if run.egress == "proxy":
            print(f"proxy: {images.build_proxy(ex)}")
        return 0

    plan = make_plan(run)
    print("\n".join(plan.lines))
    if args.dry_run:
        return 0
    try:
        auth = auth_env(root)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not args.yes:
        if not sys.stdin.isatty():
            print("refusing to spend without confirmation; pass --yes", file=sys.stderr)
            return 2
        if input("proceed? [y/N] ").strip().lower() not in {"y", "yes"}:
            return 1
    from .resources import ResourceError
    from .runner import AuthError, ResumeMismatch

    try:
        out = Runner(run, ex, auth).execute()
    except (AuthError, ResourceError, ResumeMismatch) as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(f"results: {out}")
    try:  # fold plain-arm trials into tasks/<ID>/baseline.json; never fails the run
        from . import baselines
        from .report import load_run

        added, _ = baselines.update(run.tasks, [(*load_run(out), out)])
        if any(added.values()):
            print(f"baseline: +{sum(added.values())} plain-arm samples in tasks/*/baseline.json")
    except Exception as e:  # noqa: BLE001
        print(f"warning: baseline update failed: {e}", file=sys.stderr)
    return 0


def _build_run_config(args: argparse.Namespace, cfg, root: Path):
    from .analyses_spec import load_analysis
    from .harness import harness_info
    from .config import ConfigError, MODES, resolve_host, select_tasks_for_mode, select_tasks_for_suite
    from .models import PLAIN, ArmSpec, Limits, RunConfig
    from .runner import new_run_id
    from .tasks import load_suite
    from .treatments import resolve_treatment

    tdirs = [root / cfg.treatments_dir]
    if args.arm_a or args.arm_b:
        if args.treatment:
            raise ConfigError("use either --treatment or --arm-a/--arm-b, not both")
        arms = [ArmSpec("A", resolve_treatment(args.arm_a or "plain", search_dirs=tdirs))]
        if args.arm_b:
            arms.append(ArmSpec("B", resolve_treatment(args.arm_b, search_dirs=tdirs)))
        if args.no_control and len(arms) == 2:
            raise ConfigError("--no-control cannot be combined with --arm-b")
    elif args.treatment:
        t = resolve_treatment(args.treatment, search_dirs=tdirs)
        arms = [ArmSpec("A", t)] if args.no_control else [ArmSpec("A", PLAIN), ArmSpec("B", t)]
    elif args.no_control:
        arms = [ArmSpec("A", PLAIN)]
    else:
        raise ConfigError("choose arms: --treatment X, --arm-a X --arm-b Y, or --no-control")

    users = {"A": args.user_a or args.user, "B": args.user_b or args.user}
    if args.user_b and len(arms) == 1:
        raise ConfigError("--user-b needs a second arm")
    asks = {"A": args.ask_tool_a or args.ask_tool, "B": args.ask_tool_b or args.ask_tool}
    if args.ask_tool_b and len(arms) == 1:
        raise ConfigError("--ask-tool-b needs a second arm")
    arms = [ArmSpec(a.label, a.treatment, users[a.label], asks[a.label]) for a in arms]
    if args.max_user_replies < 0:
        raise ConfigError("--max-user-replies must be >= 0")
    if args.limit_scale <= 0:
        raise ConfigError("--limit-scale must be > 0")

    model = args.model or cfg.model
    if not model:
        raise ConfigError("no model configured: pass --model <full model id> or set model in hai-proof.toml")

    ids = [s.strip() for s in args.tasks.split(",")] if args.tasks else None
    tasks = load_suite(root / cfg.tasks_dir, ids)
    if ids and args.suite:
        raise ConfigError("use either --tasks or --suite, not both")
    if not ids:
        tasks = select_tasks_for_mode(select_tasks_for_suite(tasks, args.suite), args.mode)
    if not tasks:
        raise ConfigError(f"no tasks found in {root / cfg.tasks_dir}")
    unbuilt = [t.id for t in tasks if not t.repo_dir.is_dir()]
    if unbuilt:
        raise ConfigError(f"tasks not built yet (no repo/): {', '.join(unbuilt)}; "
                          "run `hai-proof build-task <task dir>` first")
    for arm in arms:
        v = arm.treatment.prompt_variant
        missing = [t.id for t in tasks if v and v not in t.prompt_variants]
        if missing:
            raise ConfigError(f"arm {arm.label} ({arm.treatment.name}) uses prompt variant '{v}', "
                              f"which these tasks lack (prompts/{v}.md): {', '.join(missing)}")
    if any(a.user == "informative" for a in arms):
        missing = [t.id for t in tasks if not t.user_brief]
        if missing:
            raise ConfigError("the informative stand-in answers from each task's user.md, which these tasks lack: "
                              + ", ".join(missing))
    reps = args.reps if args.reps else MODES[args.mode]["reps"]
    mode = "custom" if args.reps else args.mode

    names = list(dict.fromkeys([*cfg.analyses, *args.analysis]))
    analyses = [load_analysis(n, search_dirs=[root / cfg.analyses_dir]) for n in names]

    run_id, results_dir = new_run_id(), root / cfg.results_dir
    if getattr(args, "resume", None):
        rd = Path(args.resume)
        if not (rd / "run.json").is_file():
            raise ConfigError(f"--resume: no run.json in {rd}")
        run_id, results_dir = rd.name, rd.parent

    return RunConfig(
        run_id=run_id, host=resolve_host(args.host, cfg), arms=arms, tasks=tasks, reps=reps,
        mode=mode, model=model, effort=args.effort or cfg.effort,
        cli_version=args.cli_version or cfg.cli_version, analyses=analyses,
        probe_runs=cfg.probe_runs if args.probe_runs is None else args.probe_runs,
        warmup=not args.no_warmup, egress=args.egress or cfg.egress,
        limits=Limits(cpus=cfg.limits.cpus, memory=cfg.limits.memory), seed=args.seed,
        results_dir=results_dir, harness=harness_info(root), max_spend_usd=args.max_spend,
        resume=bool(getattr(args, "resume", None)),
        stand_in_model=args.stand_in_model or cfg.stand_in_model, max_user_replies=args.max_user_replies,
        limit_scale=args.limit_scale,
    )


if __name__ == "__main__":
    raise SystemExit(main())
