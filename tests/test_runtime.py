import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desk_tidy.runtime import decide
from tests.test_core import inventory, window


class DecisionCacheTest(unittest.TestCase):
    def test_identical_state_reuses_classification_but_changed_context_does_not(self):
        inv = inventory([window()])
        response = ([{"id": "w-1", "role": "display_external"}], {"model": "test", "latency_ms": 250, "cost": .001})
        with tempfile.TemporaryDirectory() as directory, patch("desk_tidy.runtime.STATE", Path(directory)), patch("desk_tidy.runtime.request_decisions", return_value=response) as request:
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
        with patch("desk_tidy.runtime.request_decisions", return_value=response) as request:
            decide(inv, "Arrange")
            decide(inv, "Arrange")
            self.assertEqual(request.call_count, 2)
