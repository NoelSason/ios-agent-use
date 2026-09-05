"""The `iosagent` command line."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import build, config, design, diff, driver, png, report, targets, tree
from .config import Config, ConfigError


class UsageError(Exception):
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load(args) -> Config:
    return config.load(Path(args.chdir) if args.chdir else None)


def _target(cfg: Config, name: str) -> targets.Target:
    return targets.make(cfg.target(name))


def _say(message: str = "") -> None:
    print(message, flush=True)


# ---------------------------------------------------------------------------
# the one-liner action grammar used by `iosagent do`
# ---------------------------------------------------------------------------

def parse_step(text: str) -> dict:
    """`tap library.new` · `type note.title Hello there` · `drag canvas @.2,.3 @.8,.7`"""
    parts = text.split()
    if not parts:
        raise UsageError("empty step")
    step: dict = {"action": parts[0]}
    rest = parts[1:]

    def selector(token: str) -> dict:
        if token.startswith("@"):
            x, _, y = token[1:].partition(",")
            return {"norm": [float(x), float(y)]}
        if ":" in token:
            kind, _, ident = token.partition(":")
            return {"type": kind, "id": ident} if ident else {"type": kind}
        return {"id": token}

    action = step["action"]
    if action in ("wait",):
        step["seconds"] = float(rest[0]) if rest else 1.0
    elif action in ("drag",):
        if len(rest) < 2:
            raise UsageError("drag needs two coordinates, e.g. drag @.2,.3 @.8,.7")
        anchor = selector(rest[0]) if not rest[0].startswith("@") else {}
        coords = [t for t in rest if t.startswith("@")]
        if len(coords) < 2:
            raise UsageError("drag needs two @x,y coordinates")
        step["from"] = {**anchor, **selector(coords[0])}
        step["to"] = {**anchor, **selector(coords[1])}
    elif action in ("type", "assertLabel"):
        if len(rest) < 2:
            raise UsageError(f"{action} needs a target and text")
        step.update(selector(rest[0]))
        step["text"] = " ".join(rest[1:])
    elif action in ("swipe", "scrollTo"):
        step.update(selector(rest[0]) if rest else {})
        if len(rest) > 1:
            step["direction"] = rest[1]
    elif rest:
        step.update(selector(rest[0]))
    return step


def build_plan(cfg: Config, steps: list[dict], *, mode: str,
               scenario_args: list[str], scenario_env: dict[str, str],
               tree_depth: int) -> dict:
    return {
        "launch": {
            "mode": mode,
            "args": scenario_args or cfg.launch_args,
            "env": scenario_env or cfg.launch_env,
        },
        "capture": {"after_every_step": True, "screenshot": True,
                    "tree": True, "tree_depth": tree_depth},
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    path = Path(args.chdir or ".") / config.CONFIG_NAME
    if path.exists() and not args.force:
        raise UsageError(f"{path} already exists; pass --force to overwrite")
    path.write_text(json.dumps(config.TEMPLATE, indent=2) + "\n")
    _say(f"wrote {path}")
    _say("Edit it, then copy driver/AgentDriverUITests.swift into your UI test target.")
    return 0


def cmd_doctor(args) -> int:
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        _say(f"  {'ok  ' if passed else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))

    _say("toolchain")
    xcode = shutil.which("xcodebuild")
    check("xcodebuild", bool(xcode), xcode or "not on PATH")
    try:
        version = subprocess.run(["xcodebuild", "-version"], capture_output=True,
                                 text=True, timeout=60).stdout.split("\n")[0]
    except Exception:                                          # noqa: BLE001
        version = ""
    check("Xcode version", bool(version), version)
    check("devicectl", subprocess.run(["xcrun", "devicectl", "--version"],
                                      capture_output=True).returncode == 0)
    check("sips (image resampling)", bool(shutil.which("sips")))

    _say("")
    _say("project")
    try:
        cfg = _load(args)
        check("config found", True, str(cfg.root / config.CONFIG_NAME))
        check("scheme", bool(cfg.scheme), cfg.scheme)
        check("bundle id", bool(cfg.bundle_id), cfg.bundle_id)
        check("ui test target", bool(cfg.ui_test_target),
              cfg.ui_test_target or "not set — `iosagent run` will not work")
        wrapper = cfg.wrapper_path()
        if cfg.build_wrapper:
            check("build wrapper", bool(wrapper),
                  str(wrapper) if wrapper else f"{cfg.build_wrapper} not found")
        if wrapper:
            _say(f"  note  DerivedData is managed by {cfg.build_wrapper}")
        else:
            try:
                derived = build.derived_data_path(cfg)
                check("DerivedData path", True, str(derived))
            except build.BuildError as exc:
                check("DerivedData path", False, str(exc).split("\n")[0])
        root = cfg.artifacts_root
        size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.exists() else 0
        _say(f"  note  artifacts at {root} ({size / 1e6:.0f} MB)")
    except ConfigError as exc:
        check("config", False, str(exc).split("\n")[0])
        cfg = None

    _say("")
    _say("targets")
    devices = targets.list_devices()
    if not devices:
        _say("  note  no physical device reachable — simulator targets still work")
    for dev in devices:
        _say(f"  {'ok  ' if dev.state == 'connected' else 'note'}  "
             f"{dev.name} ({dev.model}) — {dev.state or 'unknown'}")
    sims = [s for s in targets.list_simulators() if s.state == "Booted"]
    for sim in sims:
        _say(f"  ok    {sim.name} — Booted")
    if not sims:
        _say("  note  no booted simulator")

    _say("")
    _say("healthy" if ok else "problems found above")
    return 0 if ok else 1


def cmd_targets(args) -> int:
    _say(f"{'KIND':<10} {'STATE':<20} NAME")
    for dev in targets.list_devices():
        _say(f"{'device':<10} {dev.state or '?':<20} {dev.name}  [{dev.udid}]")
    for sim in targets.list_simulators():
        if args.all or sim.state == "Booted":
            _say(f"{'simulator':<10} {sim.state:<20} {sim.name}  [{sim.udid}]")
    if not args.all:
        _say("\n(only booted simulators shown; --all lists every installed one)")
    return 0


def cmd_build(args) -> int:
    cfg = _load(args)
    target = _target(cfg, args.target)
    if isinstance(target, targets.SimulatorTarget):
        target.boot()
    _say(f"building {cfg.scheme} for {target.describe()}")
    began = time.time()
    build.build(cfg, target.destination(), for_testing=not args.app_only,
                only_testing=cfg.ui_test_target if not args.app_only else "")
    _say(f"built in {time.time() - began:.0f}s")
    return 0


def cmd_install(args) -> int:
    cfg = _load(args)
    target = _target(cfg, args.target)
    app = build.app_path(cfg, target.destination())
    _say(f"installing {app.name} to {target.describe()}")
    target.install(app)
    _say("installed")
    return 0


def cmd_launch(args) -> int:
    cfg = _load(args)
    target = _target(cfg, args.target)
    target.launch(cfg.bundle_id, cfg.launch_args, cfg.launch_env, fresh=args.fresh)
    _say(f"launched {cfg.bundle_id} on {target.describe()}")
    return 0


def cmd_terminate(args) -> int:
    cfg = _load(args)
    _target(cfg, args.target).terminate(cfg.bundle_id)
    _say("terminated")
    return 0


def cmd_open(args) -> int:
    cfg = _load(args)
    _target(cfg, args.target).open_url(args.url)
    _say(f"opened {args.url}")
    return 0


def cmd_snap(args) -> int:
    cfg = _load(args)
    target = _target(cfg, args.target)
    run_dir = driver.new_run_dir(cfg, args.label or "snap")
    step_dir = run_dir / "steps" / "000"
    step_dir.mkdir(parents=True, exist_ok=True)
    full = target.screenshot(step_dir / "screen.png")
    view = png.downscale(full, step_dir / "view.png", driver.VIEW_MAX_DIM)
    _say(str(view))
    _say(f"(full resolution: {full})")
    return 0


def cmd_run(args) -> int:
    cfg = _load(args)
    target = _target(cfg, args.target)

    if args.plan:
        plan = json.loads(Path(args.plan).read_text())
    else:
        steps = [parse_step(text) for text in args.steps]
        if not steps:
            raise UsageError("give a plan file or at least one step")
        env = dict(cfg.launch_env)
        for pair in args.env:
            key, _, value = pair.partition("=")
            env[key] = value
        plan = build_plan(cfg, steps, mode=args.mode,
                          scenario_args=args.arg or cfg.launch_args,
                          scenario_env=env, tree_depth=args.tree_depth)

    _say(f"driving {target.describe()} — {len(plan['steps'])} step(s)")
    outcome = driver.run(cfg, target, plan, label=args.label,
                         keep_xcresult=args.keep_xcresult)
    path = report.write(outcome)
    _say("")
    _say(path.read_text() if args.print_report else f"report: {path}")
    if not args.print_report:
        _say(f"{'PASSED' if outcome.ok else 'FAILED'} in {outcome.seconds:.0f}s "
             f"({len(outcome.steps)} observations)")
    return 0 if outcome.ok else 1


def cmd_diff(args) -> int:
    before, after = Path(args.before), Path(args.after)
    if before.is_dir() and after.is_dir():
        before_shot, after_shot = before / "screen.png", after / "screen.png"
        before_tree, after_tree = before / "tree.json", after / "tree.json"
    else:
        before_shot, after_shot = before, after
        before_tree = after_tree = None

    pixel = None
    if before_shot.exists() and after_shot.exists():
        pixel = diff.pixels(before_shot, after_shot,
                            annotated=after_shot.parent / "diff.png")
    elements = None
    if before_tree and before_tree.exists() and after_tree and after_tree.exists():
        elements = tree.diff(tree.load(before_tree), tree.load(after_tree))

    _say(diff.report_step(0, f"{before.name} → {after.name}", ok=True, ms=0,
                          pixel=pixel, elements=elements))
    return 0


def cmd_pull(args) -> int:
    cfg = _load(args)
    dest = Path(args.dest or Path.cwd() / Path(args.remote).name)
    _target(cfg, args.target).pull(cfg.bundle_id, args.remote, dest)
    _say(str(dest))
    return 0


def cmd_push(args) -> int:
    cfg = _load(args)
    _target(cfg, args.target).push(cfg.bundle_id, Path(args.local), args.remote)
    _say(f"pushed to {args.remote}")
    return 0


def cmd_logs(args) -> int:
    cfg = _load(args)
    _say(_target(cfg, args.target).logs(cfg.bundle_id, args.seconds) or "(no log output)")
    return 0


def cmd_clean(args) -> int:
    cfg = _load(args)
    root = cfg.artifacts_root
    if not root.exists():
        _say("nothing to clean")
        return 0
    cutoff = time.time() - args.days * 86400
    removed = 0
    freed = 0
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        if entry.stat().st_mtime < cutoff:
            freed += sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    _say(f"removed {removed} run(s), freed {freed / 1e6:.0f} MB")
    return 0


def cmd_design_render(args) -> int:
    source = Path(args.source)
    out = Path(args.out) if args.out else source.with_suffix(".png")
    design.render(source, out, width=args.width, height=args.height, wait_ms=args.wait)
    _say(str(out))
    return 0


def cmd_compare(args) -> int:
    reference = Path(args.reference)
    if reference.suffix.lower() in (".html", ".htm"):
        rendered = Path(args.out or ".") / "reference.png"
        _say(f"rendering {reference.name}")
        reference = design.render(reference, rendered,
                                  width=args.width, height=args.height, wait_ms=args.wait)
        source = Path(args.reference)
    else:
        source = Path(args.design) if args.design else None

    actual = Path(args.actual)
    labels = None
    if actual.is_dir():
        tree_file = actual / "tree.json"
        if tree_file.exists():
            labels = [n.label for n in tree.load(tree_file) if n.label]
            labels += [n.value for n in tree.load(tree_file) if n.value]
        actual = actual / "screen.png"
    if not actual.exists():
        raise UsageError(f"{actual} does not exist")

    out_dir = Path(args.out) if args.out else actual.parent / "compare"
    result = design.compare(reference, actual, out_dir,
                            design_source=source, labels=labels)
    _say("")
    _say(result.render())
    _say("")
    _say(f"composite: {result.composite}")
    return 0


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iosagent",
        description="Drive a real iOS app on a device or simulator, then see what changed.",
    )
    parser.add_argument("-C", "--chdir", default="", help="project directory")
    parser.add_argument("-t", "--target", default="",
                        help="target name from .iosagent.json (default: default_target)")
    subs = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        sub = subs.add_parser(name, help=help_text)
        sub.set_defaults(func=func)
        return sub

    init = add("init", cmd_init, "write a starter .iosagent.json")
    init.add_argument("--force", action="store_true")

    add("doctor", cmd_doctor, "check the toolchain, project and targets")

    tgt = add("targets", cmd_targets, "list devices and simulators")
    tgt.add_argument("--all", action="store_true", help="include shut-down simulators")

    bld = add("build", cmd_build, "build the app (and the test bundle)")
    bld.add_argument("--app-only", action="store_true",
                     help="skip build-for-testing; you will not be able to run steps")

    add("install", cmd_install, "install the built app")
    lch = add("launch", cmd_launch, "launch the app")
    lch.add_argument("--fresh", action="store_true", help="terminate any running copy first")
    add("terminate", cmd_terminate, "terminate the app")

    opn = add("open", cmd_open, "open a URL (deep link) on the target")
    opn.add_argument("url")

    snp = add("snap", cmd_snap, "screenshot the target without running a test")
    snp.add_argument("--label", default="")

    run = add("run", cmd_run, "execute an action script and capture every step")
    run.add_argument("steps", nargs="*", help="inline steps, e.g. 'tap library.new'")
    run.add_argument("-f", "--plan", default="", help="a plan .json file instead")
    run.add_argument("--mode", default="activate",
                     choices=["activate", "launch", "none"],
                     help="activate keeps app state between batches (default)")
    run.add_argument("--arg", action="append", default=[], help="launch argument")
    run.add_argument("--env", action="append", default=[], help="KEY=VALUE launch env")
    run.add_argument("--label", default="")
    run.add_argument("--tree-depth", type=int, default=60)
    run.add_argument("--keep-xcresult", action="store_true")
    run.add_argument("--print-report", action="store_true",
                     help="print report.md instead of just its path")

    dif = add("diff", cmd_diff, "compare two steps or two PNGs")
    dif.add_argument("before")
    dif.add_argument("after")

    pll = add("pull", cmd_pull, "copy a file out of the app container")
    pll.add_argument("remote")
    pll.add_argument("dest", nargs="?", default="")

    psh = add("push", cmd_push, "copy a file into the app container")
    psh.add_argument("local")
    psh.add_argument("remote")

    log = add("logs", cmd_logs, "recent log output for the app")
    log.add_argument("--seconds", type=int, default=60)

    dsn = add("design", cmd_design_render, "render a design file (.dc.html, .html) to PNG")
    dsn.add_argument("source")
    dsn.add_argument("--out", default="")
    dsn.add_argument("--width", type=int, default=1600)
    dsn.add_argument("--height", type=int, default=1200)
    dsn.add_argument("--wait", type=int, default=2500, help="ms of virtual time before capture")

    cmp_ = add("compare", cmd_compare, "compare a design against a captured screen")
    cmp_.add_argument("reference", help="design .html/.dc.html, or a reference PNG")
    cmp_.add_argument("actual", help="a step directory from a run, or a PNG")
    cmp_.add_argument("--design", default="", help="design source for text checking, "
                                                   "when reference is already a PNG")
    cmp_.add_argument("--out", default="")
    cmp_.add_argument("--width", type=int, default=1600)
    cmp_.add_argument("--height", type=int, default=1200)
    cmp_.add_argument("--wait", type=int, default=2500)

    cln = add("clean", cmd_clean, "delete old run artifacts")
    cln.add_argument("--days", type=int, default=7)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, UsageError, build.BuildError, design.DesignError,
            driver.DriverError, targets.TargetError) as exc:
        print(f"iosagent: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
