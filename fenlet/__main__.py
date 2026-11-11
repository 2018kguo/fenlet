import argparse
import json
import sys
import time
import getpass
import subprocess
from . import __version__
from .core import DEFAULT_INTENT, eligible_windows, snap_frame, screen_key, screen_for_window, guard_cleanup_decisions
from .operations import reconcile_plan, apply, read_plan, save_plan, summary, undo, audit_layout, revise_plan
from .runtime import decide, inventory, load_env, doctor, save_provider_key, install_cli, install_skill, run_json, native, native_json


def resolve_display(inventory, selector):
    screen = next((s for s in inventory["displays"] if s["id"] == selector
                   or selector == "laptop" and s.get("built_in")), None)
    if screen is None:
        raise ValueError("Display not found. Run fenlet scan for connected display IDs, or use --display laptop.")
    return screen


def arguments(argv=None):
    parser = argparse.ArgumentParser(prog="fenlet", description="Arrange your Mac windows into useful panes.")
    parser.add_argument("--version", action="version", version=f"fenlet {__version__}")
    parser.add_argument("--env-file", help="Explicit KEY=value file; never saved or uploaded")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Read current windows and displays, offline")
    scan.add_argument("--all-spaces", action="store_true", help="Include windows on other Spaces and fullscreen apps")
    sub.add_parser("check", help="Measure actual visible window overlaps, offline")
    snap = sub.add_parser("snap", help="Instantly snap the focused window, offline")
    snap.add_argument("zone", choices=["left", "right", "top", "bottom", "full"])
    tile = sub.add_parser("tile", help="Tile visible windows with size-aware panes, offline")
    tile.add_argument("--all-spaces", action="store_true", help="Gather windows from other Spaces, leaving fullscreen on confirmation")
    tile.add_argument("--display", help="Gather onto this display ID, or laptop")
    tile.add_argument("--yes", action="store_true", help="Apply the layout immediately")
    for command in ("plan", "arrange"):
        plan = sub.add_parser(command, help="Preview a layout" if command == "plan" else "Plan and arrange windows in one command")
        plan.add_argument("intent", nargs="?", default=DEFAULT_INTENT)
        plan.add_argument("--all-spaces", action="store_true", help="Include other Spaces; fullscreen windows leave fullscreen only on confirmation")
        plan.add_argument("--display", help="Gather all roles onto this display ID, or laptop")
        plan.add_argument("--model", choices=["auto", "local", "nemotron", "beam", "jev", "hybrid"], default="auto")
        plan.add_argument("--preferred-model", choices=["jev", "hybrid", "nemotron", "beam"], default="jev", help=argparse.SUPPRESS)
        plan.add_argument("--provider", choices=["gateway", "openrouter"], default="gateway")
        for purpose in ("work", "chat", "reference"):
            plan.add_argument(f"--{purpose}-display", default="auto", help="Display ID from scan, or auto")
        if command == "arrange":
            plan.add_argument("--yes", action="store_true", help="Authorize moves, minimizes, and closing idle clutter")
    execute = sub.add_parser("apply", help="Apply a previewed window layout once")
    execute.add_argument("plan_path")
    execute.add_argument("--yes", action="store_true", help="Use after reviewing and authorizing the preview")
    edit = sub.add_parser("edit", help="Adjust a draft locally without moving windows or calling a model")
    edit.add_argument("plan_path")
    changes = edit.add_mutually_exclusive_group(required=True)
    changes.add_argument("--swap", nargs=2, metavar=("WINDOW", "OTHER_WINDOW"))
    changes.add_argument("--move", nargs=2, metavar=("WINDOW", "DISPLAY"))
    changes.add_argument("--minimize", metavar="WINDOW")
    changes.add_argument("--close", metavar="WINDOW")
    restore = sub.add_parser("undo", help="Undo window moves and minimizations")
    restore.add_argument("journal_path")
    health = sub.add_parser("doctor", help="Check runtime, macOS permission, and provider setup")
    health.add_argument("--provider", choices=["gateway", "openrouter"], default="gateway")
    health.add_argument("--permissions-only", action="store_true", help="Read window-control permission without accessing provider credentials")
    setup = sub.add_parser("setup", help="Set up window control, provider access, and the CLI")
    setup.add_argument("--provider", choices=["gateway", "openrouter"], default="gateway")
    setup.add_argument("--key-stdin", action="store_true", help="Read a key privately from stdin into Keychain")
    setup.add_argument("--permissions", action="store_true", help="Open macOS Accessibility settings")
    setup.add_argument("--install-cli", action="store_true", help="Install ~/.local/bin/fenlet and add it to zsh PATH")
    setup.add_argument("--install-skill", action="store_true", help="Install the bundled agent skill for Codex")
    sub.add_parser("serve", help="Keep the shared engine warm using JSON requests on stdin")
    rebase = sub.add_parser("rebase", help="Refresh a draft without discarding reviewed choices")
    rebase.add_argument("plan_path")
    rebase.add_argument("--all-spaces", action="store_true")
    return parser.parse_args(argv)


def execute(args, input_text=None):
    started = time.monotonic()
    if (args.env_file and args.command in ("plan", "arrange", "setup", "doctor")
        and not (args.command == "doctor" and args.permissions_only)
        and not (args.command in ("plan", "arrange") and args.model == "local")):
        load_env(args.env_file)
    if args.command == "check":
        result = audit_layout()
    elif args.command in ("snap", "tile"):
        inv = inventory(all_spaces=True) if args.command == "tile" and args.all_spaces else inventory()
        destination = resolve_display(inv, args.display) if args.command == "tile" and args.display else None
        windows = eligible_windows(inv)
        if args.command == "tile":
            decisions = [{"id": w["id"], "role": screen_key(destination or screen_for_window(w, inv["displays"]))} for w in windows]
            path, p = save_plan(inv, decisions, "Tile visible windows.", None)
            result = apply(path) if args.yes else summary(p, path)
        else:
            w = next((w for w in windows if w.get("is_focused")), None)
            if not w:
                raise ValueError("Focus the window you want to snap, then run this command again.")
            screen = screen_for_window(w, inv["displays"])
            actions = [{"kind": "move", "window": w, "target": snap_frame(args.zone, screen["usable"]), "display": screen["id"], "display_name": screen["name"]}]
            path, p = save_plan(inv, None, "Snap focused window.", None, actions=actions)
            result = apply(path)
    elif args.command == "doctor" and args.permissions_only:
        result = native_json("permissions")
    elif args.command in ("doctor", "setup"):
        if args.command == "setup":
            if args.key_stdin:
                save_provider_key(args.provider, (sys.stdin.read() if input_text is None else input_text).strip())
            elif sys.stdin.isatty() and not args.permissions and not args.install_cli and not args.install_skill and not doctor(args.provider)["key_configured"]:
                save_provider_key(args.provider, getpass.getpass("Provider API key (saved in Keychain): "))
            if args.permissions:
                subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"], check=True)
            if args.install_cli:
                install_cli()
            if args.install_skill:
                install_skill()
        result = doctor(args.provider)
    elif args.command in ("scan", "plan", "arrange"):
        inv = inventory(all_spaces=True) if args.all_spaces else inventory()
        if args.command in ("plan", "arrange"):
            destination = resolve_display(inv, args.display)["id"] if args.display else None
            inv["display_preferences"] = {"work": destination or args.work_display, "chat": destination or args.chat_display, "references": destination or args.reference_display}
        if args.command == "scan":
            result = inv
        else:
            intent = args.intent
            if args.model in ("auto", "local"):
                from .runtime import automatic_decisions
                decisions, model = automatic_decisions(inv, intent, args.preferred_model, args.provider, local_only=args.model == "local")
            else:
                decisions, model = decide(inv, intent, args.model, args.provider, use_cache=True)
            decisions = guard_cleanup_decisions(inv, decisions)
            path, p = save_plan(inv, decisions, intent, model)
            result = summary(p, path)
            if args.command == "arrange":
                if not args.yes:
                    counts = {kind: sum(a["kind"] == kind for a in p["actions"]) for kind in ("move", "minimize", "close")}
                    if not sys.stdin.isatty() or input(f"{counts}. Apply this layout? Type apply: ") != "apply":
                        raise ValueError(f"Nothing changed. Review {path}, then apply it or run arrange --yes when authorized.")
                result = {"preview": result, "result": apply(path), "elapsed_ms": round((time.monotonic() - started) * 1000)}
    elif args.command == "rebase":
        result = reconcile_plan(args.plan_path, inventory(all_spaces=args.all_spaces))
    elif args.command == "edit":
        if args.swap:
            result = revise_plan(args.plan_path, "swap", *args.swap)
        elif args.move:
            result = revise_plan(args.plan_path, "move", *args.move)
        else:
            result = revise_plan(args.plan_path, "minimize" if args.minimize else "close", args.minimize or args.close)
    elif args.command == "apply":
        if not args.yes:
            if not sys.stdin.isatty() or input("Apply this layout? Type apply: ") != "apply":
                raise ValueError("Nothing changed. Review the plan and confirm, or use --yes when authorized.")
        result = apply(args.plan_path)
    else:
        result = undo(args.journal_path)
    return result


def main(argv=None):
    args = arguments(argv)
    if args.command == "serve":
        from .worker import serve
        serve(sys.stdin, sys.stdout)
        return
    try:
        print(json.dumps({"ok": True, "data": execute(args)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
