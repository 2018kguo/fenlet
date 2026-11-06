import argparse
import json
import sys
import time
import getpass
import subprocess
from . import __version__
from .core import DEFAULT_INTENT, eligible_windows, snap_frame, screen_key, screen_for_window
from .operations import apply, read_plan, save_plan, summary, undo, audit_layout, revise_plan
from .runtime import decide, inventory, load_env, doctor, save_provider_key, install_cli, install_skill, run_json, native


def main():
    parser = argparse.ArgumentParser(prog="fenlet", description="Arrange your Mac windows into useful panes.")
    parser.add_argument("--version", action="version", version=f"fenlet {__version__}")
    parser.add_argument("--env-file", help="Explicit KEY=value file; never saved or uploaded")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Read current windows and displays, offline")
    sub.add_parser("check", help="Measure actual visible window overlaps, offline")
    snap = sub.add_parser("snap", help="Instantly snap the focused window, offline")
    snap.add_argument("zone", choices=["left", "right", "top", "bottom", "full"])
    tile = sub.add_parser("tile", help="Tile visible windows with size-aware panes, offline")
    tile.add_argument("--yes", action="store_true", help="Apply the layout immediately")
    for command in ("plan", "arrange"):
        plan = sub.add_parser(command, help="Preview a layout" if command == "plan" else "Plan and arrange windows in one command")
        plan.add_argument("intent", nargs="?", default=DEFAULT_INTENT)
        plan.add_argument("--model", choices=["nemotron", "beam", "jev", "hybrid"], default="jev")
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
    setup = sub.add_parser("setup", help="Set up window control, provider access, and the CLI")
    setup.add_argument("--provider", choices=["gateway", "openrouter"], default="gateway")
    setup.add_argument("--key-stdin", action="store_true", help="Read a key privately from stdin into Keychain")
    setup.add_argument("--permissions", action="store_true", help="Open macOS Accessibility settings")
    setup.add_argument("--install-cli", action="store_true", help="Install ~/.local/bin/fenlet and add it to zsh PATH")
    setup.add_argument("--install-skill", action="store_true", help="Install the bundled agent skill for Codex")
    args = parser.parse_args()
    started = time.monotonic()
    try:
        if args.env_file:
            load_env(args.env_file)
        if args.command == "check":
            result = audit_layout()
        elif args.command in ("snap", "tile"):
            inv = inventory()
            windows = eligible_windows(inv)
            if args.command == "tile":
                decisions = [{"id": w["id"], "role": screen_key(screen_for_window(w, inv["displays"]))} for w in windows]
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
        elif args.command in ("doctor", "setup"):
            if args.command == "setup":
                if args.key_stdin:
                    save_provider_key(args.provider, sys.stdin.read().strip())
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
            inv = inventory()
            if args.command in ("plan", "arrange"):
                inv["display_preferences"] = {"work": args.work_display, "chat": args.chat_display, "references": args.reference_display}
            if args.command == "scan":
                result = inv
            else:
                intent = args.intent
                decisions, model = decide(inv, intent, args.model, args.provider, use_cache=True)
                path, p = save_plan(inv, decisions, intent, model)
                result = summary(p, path)
                if args.command == "arrange":
                    if not args.yes:
                        counts = {kind: sum(a["kind"] == kind for a in p["actions"]) for kind in ("move", "minimize", "close")}
                        if not sys.stdin.isatty() or input(f"{counts}. Apply this layout? Type apply: ") != "apply":
                            raise ValueError(f"Nothing changed. Review {path}, then apply it or run arrange --yes when authorized.")
                    result = {"preview": result, "result": apply(path), "elapsed_ms": round((time.monotonic() - started) * 1000)}
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
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
