import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fenlet.runtime import decide, WindowBatch
from fenlet.operations import save_plan, apply, revise_plan
from fenlet.core import build_actions
from tests.test_core import inventory, window


class InventoryContextTest(unittest.TestCase):
    def test_work_focus_uses_exact_window_and_disproved_constraints_are_discarded(self):
        from fenlet.runtime import inventory as scan
        work = {**window("work", "Google Chrome"), "min_size": dict(width=500, height=320)}
        chat = window("chat", "Google Chrome")
        widget = {**window("widget", "Fenlet", focused=True), "pid": 999}
        observed = {**inventory([chat, work, widget]), "coverage": {"complete": True, "errors": []}}
        with tempfile.TemporaryDirectory() as d, patch("fenlet.runtime.STATE", Path(d)), patch("fenlet.runtime.native_json", return_value=observed), patch.dict("os.environ", {"FENLET_FRONTMOST_PID": "100", "FENLET_FRONTMOST_WINDOW_ID": "work"}):
            (Path(d)/"window-constraints.json").write_text(json.dumps({"version": 2, "windows": {"proc-100/work": dict(width=900, height=893)}}))
            result = scan()
        self.assertTrue(next(w for w in result["windows"] if w["id"] == "work")["is_focused"])
        self.assertFalse(next(w for w in result["windows"] if w["id"] == "chat")["is_focused"])
        self.assertEqual(work["min_size"], dict(width=800, height=600))

    def test_legacy_unverified_size_limits_do_not_displace_a_work_terminal(self):
        from fenlet.runtime import inventory as scan
        work = window("work", "Rex Beta", focused=True)
        observed = {**inventory([work]), "coverage": {"complete": True, "errors": []}}
        with tempfile.TemporaryDirectory() as d, patch("fenlet.runtime.STATE", Path(d)), patch("fenlet.runtime.native_json", return_value=observed):
            (Path(d)/"window-constraints.json").write_text(json.dumps({"proc-100/work": dict(width=500, height=893)}))
            inv = scan()
        self.assertNotIn("min_size", work)
        self.assertEqual(build_actions(inv, [{"id": "work", "role": "display_laptop"}])[0]["kind"], "move")

    def test_browser_automation_permission_prompt_is_not_work_or_clutter(self):
        from fenlet.runtime import inventory as scan
        from fenlet.core import eligible_windows
        dialog = {**window("prompt", "Google Chrome"), "title": "Allow remote debugging?"}
        work = window("work", "Google Chrome")
        observed = {**inventory([dialog, work]), "coverage": {"complete": True, "errors": []}}
        with tempfile.TemporaryDirectory() as d, patch("fenlet.runtime.STATE", Path(d)), patch("fenlet.runtime.native_json", return_value=observed), patch.dict("os.environ", {"FENLET_FRONTMOST_PID": "100", "FENLET_FRONTMOST_WINDOW_ID": "prompt"}):
            inv = scan()
        self.assertEqual([w["id"] for w in eligible_windows(inv)], ["work"])
        self.assertFalse(dialog["is_focused"])


class DecisionCacheTest(unittest.TestCase):
    def test_confirmed_layout_overrides_cached_classification_until_the_window_changes(self):
        inv = {**inventory([window(focused=True), window("w-2", "Safari"), window("w-3", "Notes")]),
               "created_at": time.time(), "scan_ms": 0, "coverage": {"complete": True, "errors": []}}
        reviewed = [{"id": w["id"], "role": "display_external"} for w in inv["windows"]]
        classifier = [{"id": w["id"], "role": "minimize" if w["id"] == "w-3" else "display_external"} for w in inv["windows"]]
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.runtime.STATE", Path(directory)), patch("fenlet.operations.STATE", Path(directory)):
            # Populate the real decision cache with the classification the user corrected.
            with patch("fenlet.runtime.request_decisions", return_value=(classifier, {"latency_ms": 10})):
                decide(inv, "Arrange", use_cache=True)
            path, plan = save_plan(inv, reviewed, "Arrange", None)
            observed = {**inv, "windows": [{**a["window"], "bounds": a["target"]} for a in plan["actions"]]}
            def native(actions, **kwargs):
                return WindowBatch({w["id"]: {"bounds": w["bounds"], "minimized": False} for w in observed["windows"]}, observed, {}, {})
            with patch("fenlet.operations.native_window_batch", side_effect=native):
                outcome = apply(path)
            history_path = Path(directory) / "widget-history.json"
            self.assertEqual(json.loads(history_path.read_bytes())["journal"], outcome["journal_path"])
            # Confirming an already tiled layout still records the user's choices,
            # without replacing the previous action available to Undo.
            noop_path, _ = save_plan(observed, reviewed, "Arrange", None)
            def native_noop(actions, **kwargs):
                batch = native(actions, **kwargs)
                return WindowBatch({id: {**value, "unchanged": True} for id, value in batch.results.items()}, observed, {}, {})
            with patch("fenlet.operations.native_window_batch", side_effect=native_noop):
                confirmation = apply(noop_path)
            self.assertFalse(confirmation["undoable"])
            history = history_path.read_bytes()
            self.assertEqual(json.loads(history)["confirmed_journal"], confirmation["journal_path"])
            self.assertEqual(json.loads(history)["journal"], outcome["journal_path"])
            with patch("fenlet.runtime.request_decisions", side_effect=AssertionError("Repeated a reviewed layout through the model")):
                decisions, meta = decide(observed, "Arrange", use_cache=True)
            self.assertEqual(decisions, reviewed)
            self.assertTrue(meta["kept_reviewed_layout"])
            self.assertEqual({a["window"]["id"]: a["target"] for a in build_actions(observed, decisions)},
                             {a["window"]["id"]: a["target"] for a in plan["actions"]})
            # Editing/canceling a new draft does not replace the last confirmation.
            revise_plan(path, "minimize", "w-3")
            self.assertEqual(history_path.read_bytes(), history)
            for field, value in (("process_instance", "reused-process"), ("bounds", {**observed["windows"][2]["bounds"], "x": 200}), ("space_ids", [99]), ("fullscreen", True)):
                changed = copy.deepcopy(observed); changed["windows"][2][field] = value
                with patch("fenlet.runtime.request_decisions", return_value=(classifier, {"latency_ms": 10})):
                    result, _ = decide(changed, "Arrange", use_cache=True)
                self.assertEqual(next(d["role"] for d in result if d["id"] == "w-3"), "minimize")
            with patch("fenlet.runtime.request_decisions", return_value=(classifier, {"latency_ms": 10})) as request:
                changed_intent, _ = decide(observed, "Different instructions", use_cache=True)
            request.assert_called_once()
            self.assertEqual(changed_intent, classifier)

    def test_identical_state_reuses_classification_but_changed_context_does_not(self):
        inv = inventory([window()])
        response = ([{"id": "w-1", "role": "display_external"}], {"model": "test", "latency_ms": 250, "cost": .001})
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.runtime.STATE", Path(directory)), patch("fenlet.runtime.request_decisions", return_value=response) as request:
            decide(inv, "Arrange", use_cache=True)
            _, meta = decide(inv, "Arrange", use_cache=True)
            self.assertEqual(request.call_count, 1)
            self.assertTrue(meta["cache_hit"])
            self.assertEqual(meta["cost"], 0)
            moved = copy.deepcopy(inv)
            moved["windows"][0]["bounds"]["x"] += 200
            decide(moved, "Arrange", use_cache=True)
            self.assertEqual(request.call_count, 1)
            for field, value in [("title", "New project"), ("process_instance", "new-process"), ("is_focused", True)]:
                changed = copy.deepcopy(inv)
                changed["windows"][0][field] = value
                decide(changed, "Arrange", use_cache=True)
            self.assertEqual(request.call_count, 4)
            decide(inv, "Different request", use_cache=True)
            self.assertEqual(request.call_count, 5)
            inv["displays"] = inv["displays"][:1]
            decide(inv, "Arrange", use_cache=True)
            self.assertEqual(request.call_count, 6)

    def test_benchmarks_do_not_use_the_decision_cache(self):
        inv = inventory([window()])
        response = ([{"id": "w-1", "role": "display_external"}], {"cost": .001})
        with patch("fenlet.runtime.request_decisions", return_value=response) as request:
            decide(inv, "Arrange")
            decide(inv, "Arrange")
            self.assertEqual(request.call_count, 2)
