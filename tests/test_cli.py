import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from fenlet.__main__ import main
from fenlet.runtime import WindowBatch
from fenlet.operations import save_plan, read_plan
from tests.test_core import inventory, window


class CLITest(unittest.TestCase):
    def test_permission_refresh_works_without_provider_credentials(self):
        observed = []
        with patch("fenlet.__main__.doctor", side_effect=AssertionError("Credential check during permission refresh")), \
             patch("fenlet.__main__.load_env", side_effect=AssertionError("Credential file read during permission refresh")), \
             patch("fenlet.__main__.native_json", side_effect=[{"accessibility": False}, {"accessibility": True}]) as native:
            for _ in range(2):
                output = io.StringIO()
                with patch("sys.argv", ["fenlet", "--env-file", "unused", "doctor", "--permissions-only"]), redirect_stdout(output):
                    main()
                response = json.loads(output.getvalue())
                self.assertTrue(response["ok"])
                observed.append(response["data"]["accessibility"])
            self.assertEqual(observed, [False, True])
            self.assertEqual(native.call_count, 2)

    def test_edit_dispatches_the_local_plan_revision_without_reading_the_desktop(self):
        inv = {**inventory([window(focused=True), window("w-2", "Safari")]),
               "created_at": time.time(), "scan_ms": 0, "coverage": {"complete": True, "errors": []}}
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.operations.STATE", Path(directory)):
            path, original = save_plan(inv, [{"id": w["id"], "role": "display_external"} for w in inv["windows"]], "Test", None)
            output = io.StringIO()
            with patch("sys.argv", ["fenlet", "edit", str(path), "--swap", "w-1", "w-2"]), \
                 patch("fenlet.__main__.inventory", side_effect=AssertionError("Desktop read during local edit")), \
                 patch("fenlet.__main__.decide", side_effect=AssertionError("Model call during local edit")), redirect_stdout(output):
                main()
            result = json.loads(output.getvalue())
            self.assertTrue(result["ok"])
            edited = read_plan(result["data"]["plan_path"])
            self.assertEqual(edited["actions"][0]["target"], original["actions"][0]["target"])
            self.assertEqual(edited["actions"][0]["window"]["id"], "w-2")
            self.assertEqual(read_plan(path), original)

    def test_arrange_runs_real_planning_and_journaling_through_the_cli(self):
        inv = {**inventory([window(focused=True), window("w-2", "Safari")]),
               "created_at": time.time(), "scan_ms": 0, "coverage": {"complete": True, "errors": []}}
        decisions = [{"id": w["id"], "role": "display_external"} for w in inv["windows"]]
        def effect(actions, **kwargs):
            observed = [{**a["window"], "bounds": a["target"], "minimized": False} for a in actions]
            return WindowBatch({w["id"]: {"bounds": w["bounds"], "minimized": False} for w in observed},
                               {**inv, "windows": observed}, {}, {})
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch("fenlet.operations.STATE", Path(directory)), \
             patch("sys.argv", ["fenlet", "arrange", "--yes"]), \
             patch("fenlet.__main__.inventory", return_value=inv), \
             patch("fenlet.__main__.decide", return_value=(decisions, {"model": "fixture", "latency_ms": 0})), \
             patch("fenlet.operations.native_window_batch", side_effect=effect) as native, redirect_stdout(output):
            main()
            response = json.loads(output.getvalue())
            self.assertTrue(response["ok"])
            result = response["data"]["result"]
            self.assertEqual((result["arranged"], result["failed"], result["layout_check"]["overlap_count"]), (2, 0, 0))
            native.assert_called_once()
            journal = [json.loads(line) for line in Path(result["journal_path"]).read_text().splitlines()]
            self.assertEqual([e["event"] for e in journal].count("finished"), 2)
            self.assertEqual(journal[0]["scope"], "windows")
