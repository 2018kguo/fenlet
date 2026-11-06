"""Cross-Space drafts and Undo must prove membership as well as geometry."""
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fenlet import operations, runtime
from fenlet.core import build_actions, revise_actions, frames_overlap
from fenlet.__main__ import resolve_display
from tests.test_core import window, inventory


def fixture():
    windows = [{**window(f"w-{i}", focused=i == 0), "space_ids": [10 + i], "fullscreen": i > 0} for i in range(3)]
    inv = {**inventory(windows), "all_spaces": True, "created_at": time.time(), "coverage": {"complete": True}, "scan_ms": 0}
    for screen, space in zip(inv["displays"], (10, 20)):
        screen["gather_space"] = space
    # This membership fixture has room for three readable work columns.
    inv["displays"][1]["usable"]["width"] = 1920
    return inv


def batch(raw):
    return runtime.WindowBatch(raw, {"windows": [], "displays": [], "coverage": {"complete": True}}, {}, {})


class SpaceTest(unittest.TestCase):
    def test_all_spaces_share_one_destination_and_drag_moves_update_it(self):
        inv = fixture()
        actions = build_actions(inv, [{"id": w["id"], "role": "display_laptop"} for w in inv["windows"]])
        self.assertEqual(len(actions), 3)
        self.assertTrue(all(a["target_space"] == 20 and a["display"] == "laptop" for a in actions))
        self.assertFalse(any(frames_overlap(a["target"], b["target"]) for i, a in enumerate(actions) for b in actions[i+1:]))
        revised = revise_actions(inv, actions, "move", "w-2", "external")
        self.assertEqual(next(a for a in revised if a["window"]["id"] == "w-2")["target_space"], 10)
        self.assertEqual(resolve_display(inv, "laptop")["id"], "laptop")

    def test_unchanged_window_on_another_space_does_not_block_destination(self):
        inv = fixture(); fixed, work = inv["windows"][:2]
        fixed["bounds"] = dict(inv["displays"][1]["usable"])
        actions = build_actions(inv, [{"id": w["id"], "role": "unchanged" if w is fixed else "display_laptop"} for w in inv["windows"]])
        self.assertTrue(all(a["kind"] == "move" for a in actions))

    def test_destination_without_a_regular_space_cannot_be_planned(self):
        inv = fixture(); del inv["displays"][1]["gather_space"]
        with self.assertRaisesRegex(ValueError, "regular destination"):
            build_actions(inv, [{"id": w["id"], "role": "display_laptop"} for w in inv["windows"]])

    def test_correct_rectangle_on_wrong_space_or_still_fullscreen_is_not_success(self):
        inv = fixture(); w = inv["windows"][1]
        action = {"kind": "move", "window": w, "target": w["bounds"], "target_space": 20}
        for state in ({"space_ids": [11], "fullscreen": False}, {"space_ids": [20], "fullscreen": True}, {}):
            self.assertFalse(operations.window_matches(action, {**w, **state}) if state else
                             operations.window_matches(action, window()))
        self.assertTrue(operations.window_matches(action, {**w, "space_ids": [20], "fullscreen": False}))

    def test_failed_transfer_is_journaled_and_never_geometrically_retried(self):
        inv = fixture(); w = inv["windows"][1]
        action = {"kind": "move", "window": w, "target": w["bounds"], "display": "laptop", "target_space": 20}
        raw = {w["id"]: {"ok": False, "bounds": w["bounds"], "space_ids": [10], "fullscreen": False, "minimized": False}}
        with patch("fenlet.operations.native_window_batch", return_value=batch(raw)) as native:
            log = io.StringIO()
            with patch("fenlet.operations.record_many", side_effect=lambda f, rows: [f.write(json.dumps(r)+'\n') for r in rows]):
                result = operations.apply_window_batch({"inventory": inv, "actions": [action]}, log)
            self.assertEqual(native.call_count, 1)
            self.assertFalse(result.results[0]["ok"])
            self.assertEqual(result.results[0]["after"]["space_ids"], [10])
            self.assertFalse(result.results[0].get("skipped"))

    def test_undo_preserves_later_space_changes_even_with_identical_bounds(self):
        self.undo_case(later_space=True)

    def test_undo_restores_original_regular_space(self):
        self.undo_case()

    def test_undo_restores_fullscreen_without_reusing_destroyed_space_id(self):
        self.undo_case(fullscreen=True)

    def undo_case(self, *, later_space=False, fullscreen=False):
        original = {**window(), "space_ids": [99], "fullscreen": fullscreen}
        after = {**original, "bounds": {**original["bounds"], "x": 40}, "space_ids": [20], "fullscreen": False}
        raw = {**after, "space_ids": [30] if later_space else [20]}
        restored = {**original, "space_ids": [101] if fullscreen else [99]}
        with tempfile.TemporaryDirectory() as d, patch("fenlet.operations.STATE", Path(d)/"state"):
            journal = Path(d)/"run.jsonl"
            journal.write_text('\n'.join(json.dumps(e) for e in [
                {"event": "begin", "scope": "windows"},
                {"event": "started", "index": 0, "item": {"kind": "move", "window": original, "target": after["bounds"], "target_space": 20}},
                {"event": "finished", "index": 0, "result": {"ok": True, "after": after}}])+'\n')
            with patch("fenlet.operations.native_window_batch", side_effect=[batch({original["id"]: raw}), batch({original["id"]: restored})]) as native:
                result = operations.undo(journal)
                self.assertEqual(result["restored"], 0 if later_space else 1)
                self.assertEqual(native.call_count, 1 if later_space else 2)
                if not later_space:
                    action = native.call_args.args[0][0]
                    self.assertEqual(action["target_fullscreen"], fullscreen)
                    self.assertEqual(action.get("target_space"), None if fullscreen else 99)

    def test_missing_observation_does_not_inherit_expected_membership(self):
        w = fixture()["windows"][0]
        live = operations.observed_window(w, {"bounds": w["bounds"]})
        self.assertNotIn("space_ids", live)
        self.assertIsNone(live["minimized"])
        self.assertFalse(operations.same_space_state(w, live))

    def test_native_projection_keeps_scope_guards_and_restore_targets(self):
        w = fixture()["windows"][0]
        action = {"kind": "restore", "window": w, "target": w["bounds"], "target_space": 20, "target_fullscreen": False}
        response = {"results": [{"id": w["id"]}], "inventory": {}, "focus_check": {}, "timings": {}}
        with patch("fenlet.runtime.native_json", return_value=response) as native:
            runtime.native_window_batch([action])
            sent = native.call_args.args[1]["actions"][0]
            self.assertEqual(sent["window"]["space_ids"], [10])
            self.assertEqual(sent["target_space"], 20)
            self.assertIs(sent["target_fullscreen"], False)
            self.assertNotIn("title", sent["window"])

    def test_saved_plan_rejects_an_unreviewed_destination_space(self):
        inv = fixture()
        actions = build_actions(inv, [{"id": w["id"], "role": "display_laptop"} for w in inv["windows"]])
        with tempfile.TemporaryDirectory() as d, patch("fenlet.operations.STATE", Path(d)):
            path, plan = operations.save_plan(inv, None, "Gather on laptop", None, actions=actions)
            operations.read_plan(path)
            forged = copy.deepcopy(plan); forged["actions"][0]["target_space"] = 99
            path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, "destination Space"):
                operations.read_plan(path)
