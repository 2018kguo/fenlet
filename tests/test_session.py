import copy
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fenlet.core import build_actions, local_decisions, reconcile_actions
from fenlet.operations import reconcile_plan, save_plan, revise_plan
from fenlet.runtime import automatic_decisions
from fenlet.worker import serve
from tests.test_core import inventory, window


class DraftSessionTest(unittest.TestCase):
    def setUp(self):
        self.inv = inventory([window(focused=True, x=-2500), window("w-2", "Safari", x=-2500), window("w-3", "Messages")])
        self.inv.update(created_at=time.time(), scan_ms=0, coverage={"complete": True, "errors": []})

    def plan(self):
        return {"inventory": self.inv, "actions": build_actions(self.inv, local_decisions(self.inv))}

    def test_local_layout_prioritizes_work_and_never_closes(self):
        self.inv["windows"].append(window("settings", "System Settings"))
        roles = {d["id"]: d["role"] for d in local_decisions(self.inv)}
        self.assertEqual(roles, {"w-1": "display_external", "w-2": "display_external", "w-3": "display_laptop", "settings": "minimize"})

    def test_local_does_not_read_credentials_and_provider_failure_falls_back(self):
        with patch("fenlet.runtime.provider_key") as key, patch("fenlet.runtime.verified_layout_roles", return_value={}):
            decisions, meta = automatic_decisions(self.inv, "custom instructions", local_only=True)
            key.assert_not_called()
            self.assertEqual(meta["model"], "Local")
            self.assertIn("instructions", meta["notice"])
        with patch("fenlet.runtime.provider_key", return_value="test"), patch("fenlet.runtime.decide", side_effect=TimeoutError) as model, patch("fenlet.runtime.verified_layout_roles", return_value={}):
            fallback, meta = automatic_decisions(self.inv, "custom instructions")
            self.assertEqual(fallback, decisions)
            self.assertEqual(model.call_args.kwargs["request_timeout"], 4)
            self.assertIn("unavailable", meta["notice"])

    def test_poll_keeps_swapped_targets_without_writing_new_plans(self):
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.operations.STATE", Path(directory)):
            path, _ = save_plan(self.inv, local_decisions(self.inv), "intent", {})
            edited = revise_plan(path, "swap", "w-1", "w-2")
            result = reconcile_plan(edited["plan_path"], copy.deepcopy(self.inv))
            self.assertFalse(result["changed"])
            self.assertEqual(result["preview"]["plan_path"], edited["plan_path"])
            self.assertEqual(len(list(Path(directory).glob("plans/*.json"))), 2)

    def test_manual_takeover_and_reused_ids_lose_their_old_actions(self):
        before = self.plan()
        current = copy.deepcopy(self.inv)
        current["windows"][0]["bounds"]["x"] += 100
        current["windows"][1]["process_instance"] = "replacement"
        actions = reconcile_actions(before, current)
        self.assertEqual([a["window"]["id"] for a in actions], ["w-3"])

    def test_long_open_draft_is_renewed_without_discarding_placements(self):
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.operations.STATE", Path(directory)):
            old = {**self.inv, "created_at": time.time() - 901}
            path, before = save_plan(old, local_decisions(old), "intent", {})
            result = reconcile_plan(path, self.inv)
            self.assertTrue(result["changed"])
            self.assertEqual(result["preview"]["plan"]["actions"], before["actions"])
            self.assertNotEqual(result["preview"]["plan_path"], str(path))

    def test_new_window_stays_visible_and_cannot_be_covered_by_a_target(self):
        before = self.plan()
        new = window("new", "Notes")
        new["bounds"] = dict(before["actions"][-1]["target"])
        current = {**self.inv, "windows": self.inv["windows"] + [new]}
        actions = reconcile_actions(before, current)
        self.assertNotIn("new", [a["window"]["id"] for a in actions])
        from fenlet.core import frames_overlap
        self.assertFalse(any(a["kind"] == "move" and frames_overlap(a["target"], new["bounds"]) for a in actions))

    def test_unplugged_display_reflows_retaining_background_choices(self):
        before = self.plan()
        before["actions"][-1] = {"kind": "minimize", "window": self.inv["windows"][-1]}
        current = {**self.inv, "displays": self.inv["displays"][1:]}
        actions = reconcile_actions(before, current)
        self.assertTrue(all(a["display"] == "laptop" for a in actions if a["kind"] == "move"))
        self.assertEqual(next(a["kind"] for a in actions if a["window"]["id"] == "w-3"), "minimize")

    def test_resolution_change_reflows_to_fill_the_new_display(self):
        before = self.plan()
        current = copy.deepcopy(self.inv)
        current["displays"][0]["usable"]["height"] += 400
        actions = reconcile_actions(before, current)
        moves = [a for a in actions if a["kind"] == "move" and a["display"] == "external"]
        self.assertTrue(all(a["target"]["height"] == 1788 for a in moves))

    def test_changed_close_title_or_new_focus_prevents_closing(self):
        before = self.plan()
        before["actions"][-1] = {"kind": "close", "window": self.inv["windows"][-1]}
        for change in ({"title": "Unsaved work"}, {"is_focused": True}):
            current = copy.deepcopy(self.inv); current["windows"][-1].update(change)
            self.assertFalse(any(a["kind"] == "close" for a in reconcile_actions(before, current)))

    def test_incomplete_scan_does_not_claim_unseen_window_was_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.operations.STATE", Path(directory)):
            path, _ = save_plan(self.inv, local_decisions(self.inv), "intent", {})
            partial = {**self.inv, "windows": self.inv["windows"][:-1], "coverage": {"complete": False, "errors": ["unavailable"]}}
            from fenlet.runtime import WindowBatch
            with patch("fenlet.operations.native_window_batch", return_value=WindowBatch({"w-3": {"closed": False}}, {}, {}, {})):
                result = reconcile_plan(path, partial)
            self.assertEqual(len(result["inventory"]["windows"]), 3)


class WorkerTest(unittest.TestCase):
    def run_requests(self, requests):
        output = io.StringIO()
        serve(io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n"), output)
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_duplicate_mutation_id_is_not_executed_twice(self):
        request = {"id": 1, "args": ["apply", "plan", "--yes"]}
        with patch("fenlet.worker.execute", return_value={}) as execute:
            responses = self.run_requests([request, request, {"id": 2, "args": ["scan"]}])
        self.assertEqual([r["ok"] for r in responses], [True, False, True])
        self.assertEqual(execute.call_count, 2)

    def test_bad_input_or_unconfirmed_write_does_not_poison_next_request(self):
        with patch("fenlet.worker.execute", return_value={}) as execute:
            responses = self.run_requests([{"id": 1, "args": ["apply", "plan"]}, {"id": 2, "args": ["scan"]}])
        self.assertEqual([r["ok"] for r in responses], [False, True])
        execute.assert_called_once()

    def test_request_environment_and_focus_cannot_leak_to_next_request(self):
        seen = []
        def execute(args, **kwargs):
            seen.append((os.environ.get("FENLET_FRONTMOST_PID"), os.environ.get("FENLET_TEST_KEY")))
            os.environ["FENLET_TEST_KEY"] = "private"
            return {}
        with patch.dict(os.environ, {}, clear=True), patch("fenlet.worker.execute", side_effect=execute):
            self.run_requests([{"id": 1, "args": ["scan"], "focus": {"pid": 42, "window_id": "w-1"}}, {"id": 2, "args": ["scan"]}])
            self.assertNotIn("FENLET_TEST_KEY", os.environ)
        self.assertEqual(seen, [("42", None), (None, None)])

    def test_observation_never_loads_env_or_looks_up_provider(self):
        with patch("fenlet.runtime.provider_key") as credential, patch("fenlet.__main__.load_env") as env, patch("fenlet.__main__.inventory", return_value={}):
            responses = self.run_requests([{"id": 1, "args": ["--env-file", "/missing", "scan"]}, {"id": 2, "args": ["scan"]}])
        self.assertTrue(all(r["ok"] for r in responses))
        credential.assert_not_called(); env.assert_not_called()

    def test_help_or_missing_key_input_cannot_corrupt_or_block_the_pipe(self):
        with patch("fenlet.worker.execute", return_value={}) as execute:
            responses = self.run_requests([{"id": 1, "args": ["--help"]}, {"id": 2, "args": ["setup", "--key-stdin"]}, {"id": 3, "args": ["scan"]}])
        self.assertEqual([r["ok"] for r in responses], [False, False, True])
        execute.assert_called_once()
