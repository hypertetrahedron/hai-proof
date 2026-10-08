"""hai-proof command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


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

    rep = sub.add_parser("report", help="regenerate summary.json and report.html for a results dir")
    rep.add_argument("results_dir", type=Path)

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
    arms.add_argument("--no-control", action="store_true", help="single-arm run (no comparative verdict)")
    sp.add_argument("--mode", choices=["lightning", "quick", "full"], default="full")
    sp.add_argument("--reps", type=int, help="override repetitions (mode becomes 'custom')")
    sp.add_argument("--tasks", help="comma-separated task ids (default: all tasks for the mode)")
    sp.add_argument("--analysis", action="append", default=[], help="attach an analysis (repeatable)")
    sp.add_argument("--model", help="full model id (overrides hai-proof.toml)")
    sp.add_argument("--effort")
    sp.add_argument("--cli-version", help="Claude Code version to pin (default from hai-proof.toml)")
    sp.add_argument("--probe-runs", type=int, help="context-tax probe runs per arm (0 disables)")
    sp.add_argument("--no-warmup", action="store_true")
    sp.add_argument("--egress", choices=["proxy", "open"])
    sp.add_argument("--seed", type=int, default=0)


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

    if args.cmd == "report":
        from .report import load_run, write_report

        meta, trials = load_run(args.results_dir)
        s, h = write_report(args.results_dir, meta, trials)
        print(f"wrote {s}\nwrote {h}")
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
    from .runner import AuthError

    try:
        out = Runner(run, ex, auth).execute()
    except AuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(f"results: {out}")
    return 0


def _build_run_config(args: argparse.Namespace, cfg, root: Path):
    from .analyses_spec import load_analysis
    from .config import ConfigError, MODES, resolve_host, select_tasks_for_mode
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

    model = args.model or cfg.model
    if not model:
        raise ConfigError("no model configured: pass --model <full model id> or set model in hai-proof.toml")

    ids = [s.strip() for s in args.tasks.split(",")] if args.tasks else None
    tasks = load_suite(root / cfg.tasks_dir, ids)
    if not ids:
        tasks = select_tasks_for_mode(tasks, args.mode)
    if not tasks:
        raise ConfigError(f"no tasks found in {root / cfg.tasks_dir}")
    unbuilt = [t.id for t in tasks if not t.repo_dir.is_dir()]
    if unbuilt:
        raise ConfigError(f"tasks not built yet (no repo/): {', '.join(unbuilt)}; "
                          "run `hai-proof build-task <task dir>` first")
    reps = args.reps if args.reps else MODES[args.mode]["reps"]
    mode = "custom" if args.reps else args.mode

    names = list(dict.fromkeys([*cfg.analyses, *args.analysis]))
    analyses = [load_analysis(n, search_dirs=[root / cfg.analyses_dir]) for n in names]

    return RunConfig(
        run_id=new_run_id(), host=resolve_host(args.host, cfg), arms=arms, tasks=tasks, reps=reps,
        mode=mode, model=model, effort=args.effort or cfg.effort,
        cli_version=args.cli_version or cfg.cli_version, analyses=analyses,
        probe_runs=cfg.probe_runs if args.probe_runs is None else args.probe_runs,
        warmup=not args.no_warmup, egress=args.egress or cfg.egress,
        limits=Limits(cpus=cfg.limits.cpus, memory=cfg.limits.memory), seed=args.seed,
        results_dir=root / cfg.results_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
