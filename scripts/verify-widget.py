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


def build_fixture(executable):
    subprocess.run(["xcrun", "swiftc", "-O", "-D", "FENLET_UI_TEST", "-parse-as-library",
                    *[str(ROOT / "native" / file) for file in ("Engine.swift", "Updater.swift", "MenuBar.swift", "WindowPreviews.swift", "DraftEditing.swift", "Brand.swift", "DemoWindows.swift", "WidgetFixture.swift")],
                    "-o", str(executable), "-framework", "SwiftUI", "-framework", "Security", "-framework", "ScreenCaptureKit"], check=True)


def snapshot(window):
    # SwiftUI can settle its AX receipt while a new fixture is opening. These
    # retries only observe; a delivered gesture is never repeated here.
    for attempt in range(3):
        result = subprocess.run(["peekaboo", "see", "--window-id", str(window), "--tree", "--no-screenshot", "--json"], capture_output=True, text=True)
        response = json.loads(result.stdout)
        if response.get("success"): return response["data"]
        if attempt < 2: time.sleep(.1)
    raise RuntimeError(response.get("error"))


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


def fixture(count, allow_portrait=True, mode="tiles"):
    screens, windows, decisions = [], [], []
    for index in range(count):
        portrait = allow_portrait and index % 2 == 1
        bounds = dict(x=index * 2600, y=0, width=1200 if portrait else 2560, height=1920 if portrait else 1440)
        screen = dict(id=f"screen-{index}", name=f"Display {index + 1}", built_in=count == 1, bounds=bounds,
                      usable={**bounds, "y": 30, "height": bounds["height"] - 60},
                      physical_size_mm=dict(width=336 if portrait else 598, height=598 if portrait else 336))
        if mode == "spaces": screen["gather_space"] = 100 + index
        screens.append(screen)
        if mode in ("background", "spaces") and index > 0: continue
        for position, app in enumerate(("Terminal", "Safari", "Notes")):
            w = dict(id=f"w-{index}-{position}", app_name=app, title=f"Example {position + 1}", pid=100,
                     process_instance="synthetic", accessible=True, minimized=False, is_focused=index == position == 0,
                     bounds=dict(x=bounds["x"] + 20, y=50, width=800, height=600))
            role = "minimize" if mode == "background" and position == 2 else "display_" + screen["id"]
            if mode == "spaces": w.update(space_ids=[200 + position], fullscreen=position > 0)
            windows.append(w); decisions.append(dict(id=w["id"], role=role))
    if mode == "tiles":
        for app, title, role in (("Music", "Background example", "minimize"), ("Calendar", "Old example", "close")):
            w = {**windows[-1], "id": role, "app_name": app, "title": title, "is_focused": False}
            if mode == "spaces": w.update(space_ids=[200 + position], fullscreen=position > 0)
            windows.append(w); decisions.append(dict(id=w["id"], role=role))
    inventory = dict(displays=screens, windows=windows, scan_ms=0, created_at=time.time(), coverage=dict(complete=True, errors=[]))
    if mode == "spaces": inventory["all_spaces"] = True
    actions = build_actions(inventory, decisions)
    return dict(plan_path="synthetic", plan=dict(inventory=inventory, actions=actions), window_count=len(windows),
                action_count=len(actions), model=None, coverage=dict(errors=[]))


def drag(window, data, source, target):
    for attempt in range(2):
        receipt = subprocess.run(["peekaboo", "drag", "--from", source["id"], "--to", target["id"],
                                  "--snapshot", data["snapshot_id"], "--duration", "400ms", "--steps", "20", "--json"], capture_output=True, text=True)
        response = json.loads(receipt.stdout)
        if response.get("success"): return
        error = response.get("error", {})
        # A tooltip can change window inventory between observation and delivery.
        # Re-observe only when Peekaboo proves no gesture was dispatched.
        if attempt or error.get("code") != "SNAPSHOT_STALE" or error.get("mutation_dispatched") is not False:
            raise AssertionError(error)
        data = snapshot(window)
        source = next(e for e in data["ui_elements"] if e.get("label") == source["label"])
        target = next(e for e in data["ui_elements"] if e.get("label") == target["label"])


def restore_background_window(window, directory, data, before):
    """Reproduce the three-window report through real gestures and the shared CLI."""
    source_label = "Preview Notes: Example 3"
    assert any(e.get("label") == source_label for e in data["ui_elements"]), "Background window vanished from the draft."
    for source_label, target_label, kind, display, source_id in (
            (source_label, "Drop a window here", "move", "screen-1", "w-0-2"),
            (source_label, "To close after confirmation", "close", None, "w-0-2"),
            ("Preview Safari: Example 2", source_label, "close", None, "w-0-1"),
            (source_label, "Preview Terminal: Example 1", "move", "screen-0", "w-0-2"),
            ("Preview Safari: Example 2", source_label, "move", "screen-0", "w-0-1")):
        source = next(e for e in data["ui_elements"] if e.get("label") == source_label)
        target = next(e for e in data["ui_elements"] if e.get("label") == target_label)
        existing = set((directory / "state/plans").glob("*.json"))
        drag(window, data, source, target)
        deadline = time.monotonic() + 4
        while True:
            data = snapshot(window)
            files = set((directory / "state/plans").glob("*.json")) - existing
            if files:
                assert len(files) == 1
                plan = json.loads(next(iter(files)).read_text())
                action = next(a for a in plan["actions"] if a["window"]["id"] == source_id)
                assert action["kind"] == kind and action.get("display") == display, action
                if any(e.get("label") == "Confirm arrangement" and e.get("is_enabled") for e in data["ui_elements"]): break
            if time.monotonic() >= deadline: raise AssertionError("Background window could not be restored through the draft.")
            time.sleep(.1)
        assert controls(data) == before, "Dragging moved the main controls."
        assert sum(e.get("label", "").startswith("Preview ") for e in data["ui_elements"]) == 3, "A window disappeared while changing its disposition."
    return data


def cancel_draft(window, data):
    cancel = next(e for e in data["ui_elements"] if e.get("label") == "Cancel preview")
    result = subprocess.run(["peekaboo", "click", "--on", cancel["id"], "--snapshot", data["snapshot_id"],
                             "--input-strategy", "actionOnly", "--json"], capture_output=True, text=True)
    assert json.loads(result.stdout).get("success")
    deadline = time.monotonic() + 3
    while True:
        current = snapshot(window)
        elements = current["ui_elements"]
        if any(e.get("label") == "Arrange windows" for e in elements):
            assert not any(e.get("label") == "Confirm arrangement" for e in elements)
            assert sum(e.get("label", "").startswith("Preview ") for e in elements) == 3
            field = next(e["bounds"] for e in elements if e.get("label") == "Layout instructions")
            button = next(e["bounds"] for e in elements if e.get("label") == "Arrange windows")
            assert field["y"] + field["height"] <= button["y"]
            return
        if time.monotonic() > deadline: raise AssertionError("Cancel did not return every window to the live preview.")
        time.sleep(.1)


def verify_onboarding(executable, directory, environment, output):
    path = directory / "setup-preview.json"
    path.write_text(json.dumps(fixture(1)))
    permission = directory / "permissions.json"
    process = subprocess.Popen([str(executable), str(path), "--onboarding", "--permission-file", str(permission)],
                               stdout=subprocess.PIPE, text=True, env=environment)
    try:
        assert select.select([process.stdout], [], [], 10)[0], "Onboarding did not open."
        window = int(process.stdout.readline())
        data = snapshot(window)
        root = next(e["bounds"] for e in data["ui_elements"] if e.get("ax_role") == "AXWindow")
        for name in ("Allow window control", "Allow window previews"):
            button = next(e for e in data["ui_elements"] if e.get("label") == name)
            bounds = button["bounds"]
            assert bounds["height"] >= 40 and bounds["width"] >= 300, button
            assert root["y"] <= bounds["y"] and bounds["y"] + bounds["height"] <= root["y"] + root["height"]
        if output:
            capture = subprocess.run(["peekaboo", "see", "--window-id", str(window), "--path", str(output / "onboarding.png"), "--json"], capture_output=True, text=True)
            assert json.loads(capture.stdout).get("success"), capture.stdout
        for accessibility, recording, absent, present in (
                (True, False, "Allow window control", "Allow window previews"),
                (True, True, "Allow window previews", "Confirm arrangement")):
            permission.write_text(json.dumps(dict(accessibility=accessibility, screen_recording=recording)))
            deadline = time.monotonic() + 3
            while True:
                labels = {e.get("label") for e in snapshot(window)["ui_elements"]}
                if absent not in labels and present in labels: break
                assert time.monotonic() < deadline, "A new permission did not update onboarding automatically."
                time.sleep(.1)
        return dict(onboarding_permissions_visible=True, large_permission_buttons=True, permission_grants_auto_refresh=True)
    finally:
        if process.poll() is None: process.terminate()
        process.wait(timeout=3); process.stdout.close()


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
        # Legacy choices must not pin the new automatic widget to a laptop or
        # restrict it to one Desktop when a monitor is attached.
        (directory / "config.json").write_text(json.dumps(dict(model="beam", provider="gateway", allSpaces=False, gatherScreen="laptop", workScreen="laptop", chatScreen="laptop")))
        (directory / "bin").mkdir()
        (directory / "bin/fenlet").symlink_to(ROOT / "bin/fenlet")
        build_fixture(executable)
        cases = [(count, True, "tiles") for count in args.counts]
        if 2 in args.counts: cases += [(2, False, "tiles"), (2, False, "background"), (2, False, "spaces")]
        for count, allow_portrait, mode in cases:
            path = directory / "input.json"
            preview = fixture(count, allow_portrait, mode)
            plan = dict(version=1, id=uuid.uuid4().hex, intent="Synthetic widget test", model=None, **preview["plan"])
            plan_path = directory / "plan.json"; plan_path.write_text(json.dumps(plan))
            preview["plan_path"] = str(plan_path); path.write_text(json.dumps(preview))
            environment = {**os.environ, "FENLET_STATE": str(directory / "state"), "FENLET_CONFIG": str(directory / "config.json")}
            process = subprocess.Popen([str(executable), str(path), "--verify-state"], stdout=subprocess.PIPE, text=True, env=environment)
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
                if mode == "tiles":
                    for label in ("Preview Music: Background example", "Preview Calendar: Old example"):
                        item = next((e for e in data["ui_elements"] if e.get("label") == label), None)
                        assert item, "A non-display action is hidden instead of shown as a thumbnail."
                        assert item["bounds"]["y"] + item["bounds"]["height"] <= field["y"], "Disposition preview overlaps instructions."
                if count == 1:
                    source = next(e for e in data["ui_elements"] if e.get("label") == "Preview Terminal: Example 1")
                    target = next(e for e in data["ui_elements"] if e.get("label") == "Preview Safari: Example 2")
                    drag(window, data, source, target)
                    deadline = time.monotonic() + 3
                    while True:
                        data = snapshot(window)
                        changed = next(e for e in data["ui_elements"] if e.get("label") == source["label"])
                        plans = list((directory / "state/plans").glob("*.json"))
                        a, b = changed["bounds"], target["bounds"]
                        centered = abs(a["x"] + a["width"] / 2 - b["x"] - b["width"] / 2) < 2 and abs(a["y"] + a["height"] / 2 - b["y"] - b["height"] / 2) < 2
                        ready = any(e.get("label") == "Confirm arrangement" and e.get("is_enabled") for e in data["ui_elements"])
                        if centered and len(plans) == 1 and ready: break
                        if time.monotonic() >= deadline: raise AssertionError(f"Tile drag did not save and render the swapped draft: source={a}, target={b}, plans={len(plans)}, ready={ready}")
                        time.sleep(.1)
                    saved = json.loads(plans[0].read_text())
                    assert next(a for a in saved["actions"] if a["kind"] == "move")["window"]["id"] == "w-0-1"
                    assert json.loads(plan_path.read_text()) == plan, "Drag changed the original plan."
                    assert controls(data) == before, "Dragging moved the main controls."
                if mode == "background":
                    data = restore_background_window(window, directory, data, before)
                    assert json.loads(plan_path.read_text()) == plan, "Drag changed the original plan."
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
                    name = f"widget-{count}" + ("-landscape" if not allow_portrait else "") + ("-"+mode if mode != "tiles" else "")
                    (args.output / f"{name}.json").write_text(json.dumps(data, indent=2))
                    capture = subprocess.run(["peekaboo", "see", "--window-id", str(window), "--path", str(args.output / f"{name}.png"), "--json"], capture_output=True, text=True)
                    assert json.loads(capture.stdout).get("success"), capture.stdout
                if mode in ("background", "spaces"): cancel_draft(window, data)
                if mode == "spaces":
                    data = snapshot(window)
                    assert not any(e.get("label", "").startswith(("Gather destination", "Window scope")) for e in data["ui_elements"]), "A display or Desktop mode is required before arranging."
                    panes = [e["bounds"] for e in data["ui_elements"] if e.get("label", "").startswith("Preview ")]
                    assert len(panes) == 3
                    for i, a in enumerate(panes):
                        for b in panes[i+1:]:
                            assert min(a["x"]+a["width"], b["x"]+b["width"]) <= max(a["x"], b["x"]) or min(a["y"]+a["height"], b["y"]+b["height"]) <= max(a["y"], b["y"]), f"Other-Space thumbnails cover one another: {a}, {b}"
                report.append(dict(displays=count, portrait_included=allow_portrait and count > 1, controls_visible=True, controls_pinned=True,
                                   dispositions_visible=True, background_drag_restored=mode == "background", cancel_keeps_windows=True if mode in ("background", "spaces") else None,
                                   all_spaces_overview=mode == "spaces",
                                   last_display_reachable=True, drag_swap_saved=True if count == 1 else None))
            finally:
                if process.poll() is None: process.terminate()
                process.wait(timeout=3); process.stdout.close()
        report.append(verify_onboarding(executable, directory, environment, args.output))
    print(json.dumps(dict(synthetic=True, results=report)))


if __name__ == "__main__":
    main()
