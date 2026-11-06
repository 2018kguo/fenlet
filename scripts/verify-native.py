#!/usr/bin/env python3
"""Exercise the real window adapter using only windows owned by a disposable fixture."""
import json
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fenlet import runtime, operations
from fenlet.core import same_bounds, frames_overlap


def verify_spaces(fixture, references, directory):
    """Three owned windows across a Desktop and two fullscreen app Spaces."""
    normal_id = references("state")[0]["id"]
    normal = next(w for w in runtime.inventory(all_spaces=True)["windows"] if w["id"] == normal_id and w["pid"] == fixture.pid)
    closed = runtime.native_window_batch([{"kind": "close", "window": normal}])
    assert closed.results[normal["id"]].get("closed"), closed.results
    references("renew")
    references("fullscreen")
    ids = {w["id"] for w in references("state")}
    second = subprocess.Popen([str(directory / "FenletFixture")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def second_refs(command=None):
        if command:
            second.stdin.write(command+"\n"); second.stdin.flush()
        if not select.select([second.stdout], [], [], 6)[0]:
            raise TimeoutError("Second fullscreen fixture did not respond.")
        return json.loads(second.stdout.readline())
    try:
        other = second_refs()
        ids.add(other[0]["id"])
        second_refs("fullscreen")
        deadline = time.monotonic() + 6
        while True:
            inv = runtime.inventory(all_spaces=True)
            originals = [w for w in inv["windows"] if w["id"] in ids and w["pid"] in (fixture.pid, second.pid)]
            if len(originals) == 3 and sum(w.get("fullscreen", False) for w in originals) == 2: break
            if time.monotonic() >= deadline: raise AssertionError("Owned fullscreen windows were not discovered.")
            time.sleep(.05)
        assert len({s for w in originals for s in w["space_ids"]}) == 3
        screen = next(s for s in inv["displays"] if s.get("built_in"))
        area = screen["usable"]
        width = (area["width"] - 18) / 2
        height = (area["height"] - 18) / 2
        targets = [dict(x=area["x"]+6, y=area["y"]+6, width=width, height=area["height"]-12),
                   dict(x=area["x"]+12+width, y=area["y"]+6, width=width, height=height),
                   dict(x=area["x"]+12+width, y=area["y"]+12+height, width=width, height=height)]
        actions = [{"kind": "move", "window": w, "target": t, "target_space": screen["gather_space"]} for w, t in zip(originals, targets)]
        # Same rectangle with changed membership/fullscreen must be rejected.
        for field, value in (("space_ids", [0]), ("fullscreen", not originals[0]["fullscreen"])):
            stale = runtime.native_window_batch([{**actions[0], "window": {**originals[0], field: value}}])
            assert stale.results[originals[0]["id"]].get("skipped"), stale.results
        started = time.monotonic()
        gathered = runtime.native_window_batch(actions)
        elapsed = round((time.monotonic()-started)*1000)
        afters = [operations.observed_window(w, gathered.results[w["id"]]) for w in originals]
        assert all(operations.window_matches(a, live) for a, live in zip(actions, afters)), gathered.results
        assert all(not live["fullscreen"] and live["space_ids"] == [screen["gather_space"]] for live in afters)
        assert not any(frames_overlap(a["bounds"], b["bounds"]) for i, a in enumerate(afters) for b in afters[i+1:])
        journal = directory / "spaces-roundtrip.jsonl"
        entries = [{"event": "begin", "scope": "windows"}]
        for i, (a, after) in enumerate(zip(actions, afters)):
            entries.extend([{"event": "started", "index": i, "item": a},
                            {"event": "finished", "index": i, "result": {"ok": True, "after": after}}])
        journal.write_text("".join(json.dumps(e)+"\n" for e in entries))
        with patch("fenlet.operations.STATE", directory / "state"):
            undone = operations.undo(journal)
            assert undone["restored"] == 3 and not undone["skipped"], {"summary": undone, "observations": [json.loads(line) for line in journal.read_text().splitlines() if json.loads(line)["event"] == "undo_observed"]}
            assert operations.undo(journal)["restored"] == 0
        return {"all_spaces_close_verified": True, "three_spaces_gathered": True, "gather_ms": elapsed, "overlaps": 0,
                "stale_space_and_fullscreen_guard": True, "fullscreen_and_frame_undo": True}
    finally:
        if second.poll() is None:
            second.stdin.write("quit\n"); second.stdin.flush()
            try: second.wait(timeout=3)
            except subprocess.TimeoutExpired: second.terminate(); second.wait(timeout=2)
        second.stdin.close(); second.stdout.close()


def main():
    started = time.monotonic()
    report = {}
    with tempfile.TemporaryDirectory(prefix="fenlet-native-") as temporary:
        directory = Path(temporary)
        executable = directory / "FenletFixture"
        subprocess.run(["xcrun", "swiftc", "-O", "-import-objc-header", str(ROOT / "native/Bridge.h"),
                        str(ROOT / "native/Fixture.swift"), "-o", str(executable)], check=True)
        focus = runtime.native_json("focus")
        fixture = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            def references(command=None):
                if command:
                    fixture.stdin.write(command + "\n"); fixture.stdin.flush()
                if not select.select([fixture.stdout], [], [], 5)[0]:
                    raise TimeoutError("Fixture did not respond.")
                return json.loads(fixture.stdout.readline())

            windows = references()
            assert len(windows) == 3 and all(w["pid"] == fixture.pid for w in windows)
            assert runtime.native_json("focus") == focus, "Fixture changed active focus."
            displays = runtime.native_json("displays")
            screen = max(displays, key=lambda s: s["usable"]["width"] * s["usable"]["height"])
            u = screen["usable"]
            targets = [{"x": u["x"] + 6 + i * 706, "y": u["y"] + 6, "width": 700, "height": min(600, u["height"] - 12)} for i in range(2)]
            # A small display can verify the same moves sequentially without changing other apps.
            if targets[1]["x"] + 700 > u["x"] + u["width"]:
                targets[1]["x"] = targets[0]["x"]
            actions = [{"kind": "move", "window": w, "target": target} for w, target in zip(windows[:2], targets)]
            moved = runtime.native_window_batch(actions)
            assert all(same_bounds(moved.results[w["id"]]["bounds"], t, 2) for w, t in zip(windows, targets))
            assert moved.timings["app_index_loads"] == 1, moved.timings
            assert moved.focus_check["before"] == moved.focus_check["after"], moved.focus_check
            report["batch_move_and_focus"] = True
            report["focused_window_available"] = bool(focus["window_id"])

            current = [{**w, "bounds": moved.results[w["id"]]["bounds"]} for w in windows[:2]]
            noops = runtime.native_window_batch([{"kind": "move", "window": w, "target": w["bounds"]} for w in current])
            assert all(r.get("unchanged") for r in noops.results.values())
            assert noops.timings["app_index_loads"] == 0, noops.timings
            report["no_op_without_ax_enumeration"] = True

            stale = runtime.native_window_batch([{"kind": "move", "window": windows[0], "target": windows[0]["bounds"]}])
            assert stale.results[windows[0]["id"]].get("skipped")
            wrong = runtime.native_window_batch([{"kind": "close", "window": {**current[0], "process_instance": "wrong"}}])
            assert wrong.results[current[0]["id"]].get("skipped")
            report["stale_bounds_and_process_guards"] = True

            references("rename")
            changed = runtime.native_window_batch([{"kind": "close", "window": {**current[0], "title_source": "ax"}}])
            assert changed.results[current[0]["id"]].get("skipped")
            renamed = runtime.native_window_batch([{"kind": "move", "window": current[0], "target": {**targets[0], "y": targets[0]["y"] + 30}}])
            assert renamed.results[current[0]["id"]].get("delivered")
            report["title_changes_preserve_move_identity_and_guard_close"] = True

            edited = runtime.native_window_batch([{"kind": "close", "window": {**windows[2], "title_source": "ax"}}])
            assert edited.results[windows[2]["id"]].get("skipped"), edited.results
            report["unsaved_window_preserved"] = True

            before_min = current[1]
            minimized = runtime.native_window_batch([{"kind": "minimize", "window": before_min}])
            assert minimized.results[before_min["id"]].get("minimized"), minimized.results
            assert before_min["id"] not in {w["id"] for w in minimized.inventory["windows"]}, "Dock animation became a fixed layout obstacle."
            # Use the production journal reader and batched Undo, including a moved window.
            with patch("fenlet.operations.STATE", directory / "state"):
                journal = directory / "roundtrip.jsonl"
                entries = [{"event": "begin", "scope": "windows"}]
                for index, (original, result) in enumerate([(windows[0], renamed.results[current[0]["id"]]), (before_min, minimized.results[before_min["id"]])]):
                    entries.extend([
                        {"event": "started", "index": index, "item": {"kind": "move" if index == 0 else "minimize", "window": original}},
                        {"event": "finished", "index": index, "result": {"ok": True, "after": {**original, "bounds": result["bounds"], "minimized": result.get("minimized", False)}}}])
                journal.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
                restored = operations.undo(journal)
                assert restored["restored"] == 2 and not restored["skipped"], restored
                assert restored["focus_check"]["before"] == restored["focus_check"]["after"]
                assert operations.undo(journal)["restored"] == 0
            report["minimize_move_and_batched_undo"] = True

            closed = runtime.native_window_batch([{"kind": "close", "window": {**before_min, "title_source": "ax"}}])
            assert closed.results[before_min["id"]].get("closed"), closed.results
            report["normal_close_verified"] = True
            assert runtime.native_json("focus") == focus, "Verification changed active focus."
            if "--spaces" in sys.argv:
                report["spaces"] = verify_spaces(fixture, references, directory)
        finally:
            if fixture.poll() is None:
                fixture.stdin.write("quit\n"); fixture.stdin.flush()
                try:
                    fixture.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    fixture.terminate(); fixture.wait(timeout=2)
            fixture.stdin.close(); fixture.stdout.close()
    report["elapsed_ms_including_fixture_compile"] = round((time.monotonic() - started) * 1000)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
