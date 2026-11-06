import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fenlet.core import build_actions, revise_actions, frames_overlap
from fenlet.operations import save_plan, revise_plan, read_plan
from tests.test_core import inventory, window


class DraftEditTest(unittest.TestCase):
    def setUp(self):
        self.inv = {**inventory([window(focused=True), window("w-2", "Safari"), window("w-3", "Notes")]),
                    "created_at": time.time(), "scan_ms": 0, "coverage": {"complete": True, "errors": []}}
        self.actions = build_actions(self.inv, [{"id": w["id"], "role": "display_external"} for w in self.inv["windows"]])

    def test_swap_changes_occupants_and_preserves_the_nonoverlapping_slots(self):
        original = copy.deepcopy(self.actions)
        result = revise_actions(self.inv, self.actions, "swap", "w-1", "w-2")
        before = {a["window"]["id"]: a for a in original}
        after = {a["window"]["id"]: a for a in result}
        self.assertEqual(after["w-1"]["target"], before["w-2"]["target"])
        self.assertEqual(after["w-2"]["target"], before["w-1"]["target"])
        self.assertEqual(self.actions, original)

    def test_cross_display_move_reflows_and_background_can_return_to_a_display(self):
        minimized = revise_actions(self.inv, self.actions, "minimize", "w-2")
        moved = revise_actions(self.inv, minimized, "move", "w-2", "laptop")
        action = next(a for a in moved if a["window"]["id"] == "w-2")
        self.assertEqual(action["display"], "laptop")
        boxes = [a["target"] for a in moved if a["kind"] == "move"]
        self.assertFalse(any(frames_overlap(a,b) for i,a in enumerate(boxes) for b in boxes[i+1:]))

    def test_cannot_close_focused_work_or_swap_a_window_into_a_too_small_pane(self):
        with self.assertRaises(ValueError): revise_actions(self.inv, self.actions, "close", "w-1")
        self.actions[0]["window"]["min_size"] = {"width": 2000, "height": 500}
        with self.assertRaises(ValueError): revise_actions(self.inv, self.actions, "swap", "w-1", "w-2")

    def test_edit_creates_a_new_valid_plan_without_model_or_os_access(self):
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.operations.STATE", Path(directory)), \
             patch("fenlet.runtime.native_json", side_effect=AssertionError("OS access during draft edit")), \
             patch("fenlet.runtime.request_decisions", side_effect=AssertionError("Model call during draft edit")):
            path, original = save_plan(self.inv, None, "Test workspace", None, actions=self.actions)
            edited = revise_plan(path, "swap", "w-1", "w-2")
            self.assertNotEqual(str(path), edited["plan_path"])
            self.assertEqual(read_plan(path), original)
            self.assertEqual(len(read_plan(edited["plan_path"])["actions"]), 3)
