#!/usr/bin/env python3
"""Render synthetic display setups and verify pinned controls through real AX."""
import argparse
import os
import json
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fenlet.core import build_actions


def snapshot(window):
    result = subprocess.run(["peekaboo", "see", "--window-id", str(window), "--tree", "--no-screenshot", "--json"], capture_output=True, text=True)
    response = json.loads(result.stdout)
    if not response.get("success"):
        raise RuntimeError(response.get("error"))
    return response["data"]


def controls(data):
    elements = data["ui_elements"]
    found = {name: next(e for e in elements if e.get("label") == name) for name in ("Confirm arrangement", "Layout instructions")}
    root = next(e["bounds"] for e in elements if e.get("ax_role") == "AXWindow")
    for element in found.values():
        b = element["bounds"]
        assert element.get("is_enabled"), element
        assert root["x"] <= b["x"] and root["y"] <= b["y"]
        assert b["x"] + b["width"] <= root["x"] + root["width"] + 1
        assert b["y"] + b["height"] <= root["y"] + root["height"] + 1
    return {name: value["bounds"] for name, value in found.items()}


def fixture(count, allow_portrait=True):
    screens, windows, decisions = [], [], []
    for index in range(count):
        portrait = allow_portrait and index % 2 == 1
        bounds = dict(x=index * 2600, y=0, width=1200 if portrait else 2560, height=1920 if portrait else 1440)
        screen = dict(id=f"screen-{index}", name=f"Display {index + 1}", built_in=count == 1, bounds=bounds,
                      usable={**bounds, "y": 30, "height": bounds["height"] - 60},
                      physical_size_mm=dict(width=336 if portrait else 598, height=598 if portrait else 336))
        screens.append(screen)
        for position, app in enumerate(("Terminal", "Safari", "Notes")):
            w = dict(id=f"w-{index}-{position}", app_name=app, title=f"Example {position + 1}", pid=100,
                     process_instance="synthetic", accessible=True, minimized=False, is_focused=index == position == 0,
                     bounds=dict(x=bounds["x"] + 20, y=50, width=800, height=600))
            windows.append(w); decisions.append(dict(id=w["id"], role="display_" + screen["id"]))
    inventory = dict(displays=screens, windows=windows, scan_ms=0, created_at=time.time(), coverage=dict(complete=True, errors=[]))
    actions = build_actions(inventory, decisions)
    return dict(plan_path="synthetic", plan=dict(inventory=inventory, actions=actions), window_count=len(windows),
                action_count=len(actions), model=None, coverage=dict(errors=[]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional directory for synthetic PNGs and AX evidence")
    parser.add_argument("--counts", type=int, nargs="+", default=[1, 2, 4, 6], choices=range(1, 13))
    args = parser.parse_args()
    if not shutil.which("peekaboo"):
        raise SystemExit("Install Peekaboo to run native widget verification.")
    report, pinned = [], None
    with tempfile.TemporaryDirectory(prefix="fenlet-widget-") as directory:
        directory = Path(directory)
        executable = directory / "FenletWidgetFixture"
        (directory / "bin").mkdir()
        (directory / "bin/fenlet").symlink_to(ROOT / "bin/fenlet")
        subprocess.run(["xcrun", "swiftc", "-O", "-D", "FENLET_UI_TEST", "-parse-as-library",
                        *[str(ROOT / "native" / file) for file in ("MenuBar.swift", "WindowPreviews.swift", "DraftEditing.swift", "Brand.swift", "WidgetFixture.swift")],
                        "-o", str(executable), "-framework", "SwiftUI", "-framework", "Security", "-framework", "ScreenCaptureKit"], check=True)
        cases = [(count, True) for count in args.counts]
        if 2 in args.counts: cases.append((2, False))
        for count, allow_portrait in cases:
            path = directory / "input.json"
            preview = fixture(count, allow_portrait)
            plan = dict(version=1, id=uuid.uuid4().hex, intent="Synthetic widget test", model=None, **preview["plan"])
            plan_path = directory / "plan.json"; plan_path.write_text(json.dumps(plan))
            preview["plan_path"] = str(plan_path); path.write_text(json.dumps(preview))
            environment = {**os.environ, "FENLET_STATE": str(directory / "state"), "FENLET_CONFIG": str(directory / "config.json")}
            process = subprocess.Popen([str(executable), str(path)], stdout=subprocess.PIPE, text=True, env=environment)
            try:
                if not select.select([process.stdout], [], [], 10)[0]:
                    raise TimeoutError("Widget fixture did not create a window.")
                window = int(process.stdout.readline())
                data = snapshot(window)
                before = controls(data)
                if pinned is None: pinned = before
                assert before == pinned, "Instructions or confirmation moved with display count."
                gallery = next(e for e in data["ui_elements"] if e.get("ax_role") == "AXScrollArea")
                field = before["Layout instructions"]
                assert gallery["bounds"]["y"] + gallery["bounds"]["height"] <= field["y"], "Gallery overlaps instructions."
                if count == 1:
                    source = next(e for e in data["ui_elements"] if e.get("label") == "Preview Terminal: Example 1")
                    target = next(e for e in data["ui_elements"] if e.get("label") == "Preview Safari: Example 2")
                    drag = subprocess.run(["peekaboo", "drag", "--from", source["id"], "--to", target["id"],
                                           "--snapshot", data["snapshot_id"], "--duration", "400ms", "--steps", "20", "--json"], capture_output=True, text=True)
                    receipt = json.loads(drag.stdout)
                    assert receipt.get("success"), receipt.get("error")
                    deadline = time.monotonic() + 3
                    while True:
                        data = snapshot(window)
                        changed = next(e for e in data["ui_elements"] if e.get("label") == source["label"])
                        plans = list((directory / "state/plans").glob("*.json"))
                        if changed["bounds"] == target["bounds"] and len(plans) == 1: break
                        if time.monotonic() >= deadline: raise AssertionError("Tile drag did not save and render the swapped draft.")
                        time.sleep(.1)
                    saved = json.loads(plans[0].read_text())
                    assert saved["actions"][0]["window"]["id"] == "w-0-1"
                    assert json.loads(plan_path.read_text()) == plan, "Drag changed the original plan."
                    assert controls(data) == before, "Dragging moved the main controls."
                if count > 2:
                    receipt = subprocess.run(["peekaboo", "scroll", "--on", gallery["id"], "--snapshot", data["snapshot_id"],
                                              "--direction", "down", "--amount", "10", "--json"], capture_output=True, text=True)
                    scroll = json.loads(receipt.stdout)
                    assert scroll.get("success"), scroll.get("error")
                    # Scroll delivery may finish before SwiftUI's animation. Observe,
                    # without sending another event, until the last row is visible.
                    deadline = time.monotonic() + 3
                    while True:
                        data = snapshot(window)
                        assert controls(data) == before, "Scrolling moved the main controls."
                        last = next((e for e in data["ui_elements"] if e.get("label") == f"Display {count}"), None)
                        g = gallery["bounds"]
                        if last and g["y"] <= last["bounds"]["y"] < g["y"] + g["height"]: break
                        if time.monotonic() >= deadline:
                            raise AssertionError(f"Last display cannot be reached: {count}, gallery={g}, last={last}")
                        time.sleep(.1)
                if args.output:
                    args.output.mkdir(parents=True, exist_ok=True)
                    name = f"widget-{count}" + ("-landscape" if not allow_portrait else "")
                    (args.output / f"{name}.json").write_text(json.dumps(data, indent=2))
                    capture = subprocess.run(["peekaboo", "see", "--window-id", str(window), "--path", str(args.output / f"{name}.png"), "--json"], capture_output=True, text=True)
                    assert json.loads(capture.stdout).get("success"), capture.stdout
                report.append(dict(displays=count, portrait_included=allow_portrait and count > 1, controls_visible=True, controls_pinned=True, last_display_reachable=True, drag_swap_saved=True if count == 1 else None))
            finally:
                if process.poll() is None: process.terminate()
                process.wait(timeout=3); process.stdout.close()
    print(json.dumps(dict(synthetic=True, results=report)))


if __name__ == "__main__":
    main()
