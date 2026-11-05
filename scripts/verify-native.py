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
from desk_tidy import runtime, operations
from desk_tidy.core import same_bounds


def main():
    started = time.monotonic()
    report = {}
    with tempfile.TemporaryDirectory(prefix="desk-tidy-native-") as temporary:
        directory = Path(temporary)
        executable = directory / "DeskTidyFixture"
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
            with patch("desk_tidy.operations.STATE", directory / "state"):
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
