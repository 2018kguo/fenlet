import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from desk_tidy.core import fingerprint
from desk_tidy.operations import (apply, apply_window_batch, read_plan,
                                   screenshot_ready, undo)
from desk_tidy.runtime import run_json, WindowBatch
from tests.test_core import window, inventory


def batch(results):
    return WindowBatch(results, {"windows": [], "coverage": {"complete": True, "errors": []}},
                       {"before": {"pid": 1, "window_id": "w-1"}, "after": {"pid": 1, "window_id": "w-1"}, "unchanged": True}, {})


class SafetyTest(unittest.TestCase):
    def test_failed_close_becomes_fixed_obstacle_without_repeating_close(self):
        from desk_tidy.core import build_actions, frames_overlap
        work, browser, clutter = window(focused=True, x=-2500), window("w-2", "Safari", x=-2500), window("w-3", "Finder", x=-2500)
        inv = inventory([work, browser, clutter]); inv["displays"] = inv["displays"][:1]
        clutter["bounds"] = {"x": -2560, "y": -500, "width": 800, "height": 600}
        p = {"inventory": inv, "actions": build_actions(inv, [{"id": w["id"], "role": "close" if w is clutter else "display_external"} for w in inv["windows"]])}
        calls = []
        def native(actions, **kwargs):
            calls.append(actions)
            raw = {a["window"]["id"]: {"bounds": a.get("target", a["window"]["bounds"]), "minimized": a["kind"] == "minimize"} for a in actions}
            observed = [clutter] + [{**a["window"], **raw[a["window"]["id"]]} for a in actions if a["kind"] != "close"]
            return WindowBatch(raw, {**inv, "windows": observed, "coverage": {"complete": True}}, {}, {})
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.operations.STATE", Path(directory)), patch("desk_tidy.operations.native_window_batch", side_effect=native):
            with open(Path(directory) / "journal", "w+") as f:
                outcome = apply_window_batch(p, f)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(a["kind"] == "move" for a in calls[1]))
        self.assertTrue(all(not frames_overlap(a["target"], clutter["bounds"]) for a in calls[1]))
        self.assertEqual(sum(r["ok"] for r in outcome.results), 2)

    def test_native_stale_guard_is_preserved_even_if_user_moved_to_the_target(self):
        w = window()
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.operations.STATE", Path(directory)):
            action = {"kind": "move", "window": w, "display": "external", "target": w["bounds"]}
            p = {"inventory": {"displays": []}, "actions": [action]}
            native = batch({w["id"]: {"skipped": True, "bounds": w["bounds"], "error": "Window changed since preview."}})
            with open(Path(directory) / "journal", "w") as f, patch("desk_tidy.operations.native_window_batch", return_value=native):
                r = apply_window_batch(p, f).results[0]
            self.assertFalse(r["ok"])
            self.assertTrue(r["skipped"])

    def test_confirmed_minimum_size_clamp_reflows_the_whole_display(self):
        from desk_tidy.core import build_actions, frames_overlap
        ws = [window(), window("w-2")]
        inv = inventory(ws)
        inv["displays"] = inv["displays"][1:]
        p = {"inventory": inv, "actions": build_actions(inv, [{"id": w["id"], "role": "display_laptop"} for w in ws])}
        calls = []
        def native(actions, **kwargs):
            calls.append(actions)
            result = {a["window"]["id"]: {"bounds": dict(a["target"]), "minimized": False} for a in actions}
            if len(calls) == 1:
                result["w-2"]["bounds"]["width"] = 770
            return batch(result)
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.operations.STATE", Path(directory)), patch("desk_tidy.operations.native_window_batch", side_effect=native):
            with open(Path(directory) / "journal", "w+") as f:
                results = apply_window_batch(p, f).results
                f.seek(0); events = [json.loads(line)["event"] for line in f]
            self.assertEqual(len(calls), 2)
            self.assertIn("repair_started", events)
            self.assertTrue(all(r["ok"] for r in results))
            self.assertFalse(frames_overlap(*(r["after"]["bounds"] for r in results)))
            self.assertGreaterEqual(calls[-1][1]["target"]["width"], 770)

    def test_closed_window_does_not_break_layout_undo(self):
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.operations.STATE", Path(directory) / "state"):
            journal = Path(directory) / "journal.jsonl"
            journal.write_text("\n".join(json.dumps(e) for e in [
                {"event": "begin", "scope": "windows"},
                {"event": "started", "index": 0, "item": {"kind": "close", "window": window()}},
                {"event": "finished", "index": 0, "result": {"ok": True, "after": None}}]) + "\n")
            with patch("desk_tidy.operations.native_window_batch") as inspect:
                self.assertEqual(undo(journal)["restored"], 0)
                inspect.assert_not_called()

    def test_cleanup_rejects_symlinks_fresh_files_modified_files_and_other_paths(self):
        with tempfile.TemporaryDirectory() as directory, patch("pathlib.Path.home", return_value=Path(directory)):
            root = Path(directory) / "Desktop"
            root.mkdir()
            old = root / "Screenshot 2020-01-01 at 1.00.00 PM.png"
            old.write_bytes(b"fake image")
            # Birth time also needs to be old; inject only time for this boundary test.
            future = time.time() + 86400 * 100
            item = {"path": str(old), "fingerprint": fingerprint(old.stat())}
            with patch("desk_tidy.operations.time.time", return_value=future):
                screenshot_ready(item, 30)
                old.write_bytes(b"changed")
                with self.assertRaises(ValueError): screenshot_ready(item, 30)
                link = root / "Screenshot 2020-01-01 at 2.00.00 PM.png"
                link.symlink_to(old)
                with self.assertRaises(ValueError): screenshot_ready({"path": str(link), "fingerprint": fingerprint(link.lstat())}, 30)
                with self.assertRaises(ValueError): screenshot_ready({"path": str(root.parent / old.name), "fingerprint": item["fingerprint"]}, 30)
            with self.assertRaises(ValueError): screenshot_ready({"path": str(old), "fingerprint": fingerprint(old.stat())}, 30)

    def test_undo_never_overwrites_new_screenshot(self):
        with tempfile.TemporaryDirectory() as directory, patch("pathlib.Path.home", return_value=Path(directory)), patch("desk_tidy.operations.STATE", Path(directory) / "state"):
            root = Path(directory) / "Desktop"; root.mkdir()
            trash = Path(directory) / ".Trash"; trash.mkdir()
            src = trash / "old.png"; src.write_bytes(b"old screenshot")
            dst = root / "Screenshot 2020-01-01 at 1.00.00 PM.png"; dst.write_bytes(b"new screenshot")
            journal = Path(directory) / "journal.jsonl"
            entries = [{"event": "begin", "scope": "screenshots"},
                       {"event": "started", "index": 0, "item": {"path": str(dst)}},
                       {"event": "finished", "index": 0, "result": {"ok": True, "trashed_path": str(src), "fingerprint": fingerprint(src.stat())}}]
            journal.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
            r = undo(journal)
            self.assertEqual(r["restored"], 0)
            self.assertEqual(dst.read_bytes(), b"new screenshot")
            self.assertEqual(src.read_bytes(), b"old screenshot")
            dst.unlink()
            self.assertEqual(undo(journal)["restored"], 1)
            self.assertEqual(dst.read_bytes(), b"old screenshot")
            self.assertEqual(undo(journal)["restored"], 0)

    def test_undo_does_not_overwrite_user_layout(self):
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.operations.STATE", Path(directory) / "state"):
            w = window()
            after = {**w, "bounds": {**w["bounds"], "x": 200}}
            journal = Path(directory) / "journal.jsonl"
            entries = [{"event": "begin", "scope": "windows"},
                       {"event": "started", "index": 0, "item": {"kind": "move", "window": w}},
                       {"event": "finished", "index": 0, "result": {"ok": True, "after": after}}]
            journal.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
            with patch("desk_tidy.operations.native_window_batch", return_value=batch({w["id"]: {"bounds": w["bounds"], "minimized": False}})) as native:
                self.assertEqual(undo(journal)["restored"], 0)
                self.assertEqual(native.call_count, 1)
                self.assertTrue(all(a["kind"] == "inspect" for a in native.call_args.args[0]))

    def test_native_list_output_and_error_envelopes(self):
        self.assertEqual(run_json(["python3", "-c", "print('[1,2]')"]), [1, 2])
        with self.assertRaises(RuntimeError):
            run_json(["python3", "-c", "print('{\"ok\":false,\"error\":{\"code\":\"TIMEOUT\"}}')"])

    def test_actual_effect_is_verified_even_when_native_api_reports_an_error(self):
        w = window()
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.operations.STATE", Path(directory)):
            p = {"version": 1, "id": "a" * 32, "inventory": {"created_at": time.time(), "displays": []},
                 "actions": [{"kind": "minimize", "window": w}]}
            before = {"w-1": {"ok": True, "bounds": w["bounds"], "minimized": False}}
            after = {"w-1": {"ok": False, "error": "AX verification timed out", "bounds": w["bounds"], "minimized": True}}
            with patch("desk_tidy.operations.read_plan", return_value=p), patch("desk_tidy.operations.run_json", return_value=[]), patch("desk_tidy.operations.audit_layout", return_value={"overlap_count": 0}), patch("desk_tidy.operations.native", return_value="helper"), patch("desk_tidy.operations.native_window_batch", return_value=batch(after)) as native:
                r = apply("preview.json", "windows")
                self.assertEqual(r["succeeded"], 1)
                self.assertEqual(r["failed"], 0)
                self.assertEqual(native.call_count, 1)
                entries = [json.loads(l) for l in Path(r["journal_path"]).read_text().splitlines()]
                self.assertTrue(entries[-1]["result"]["after"]["minimized"])

    def test_undo_recovers_the_observed_effect_of_an_interrupted_minimize(self):
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.operations.STATE", Path(directory) / "state"):
            w = window(); after = {**w, "minimized": True}
            journal = Path(directory) / "journal.jsonl"
            entries = [{"event": "begin", "scope": "windows"},
                       {"event": "started", "index": 0, "item": {"kind": "minimize", "window": w}},
                       {"event": "failed", "index": 0, "error": "AX timeout"}]
            journal.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
            observed = batch({w["id"]: {"bounds": after["bounds"], "minimized": True}})
            restored = batch({w["id"]: {"bounds": w["bounds"], "minimized": False}})
            with patch("desk_tidy.operations.native_window_batch", side_effect=[observed, restored]) as native:
                self.assertEqual(undo(journal)["restored"], 1)
                self.assertEqual(native.call_count, 2)
                self.assertEqual(native.call_args_list[1].args[0][0]["kind"], "restore")


if __name__ == "__main__":
    unittest.main()
