import copy
import unittest

from desk_tidy.core import build_actions, same_bounds, validate_decisions, eligible_windows, tile_frames, frames_overlap, constrained_tiles, snap_frame, display_assignments, screen_key


def window(id="w-1", app="Terminal", focused=False, x=10):
    return {"id": id, "app_name": app, "title": "Example", "pid": 100,
            "process_instance": "proc-100", "accessible": True, "minimized": False,
            "is_focused": focused, "bounds": {"x": x, "y": 20, "width": 800, "height": 600}}


def inventory(windows):
    return {"windows": windows, "displays": [
        {"id": "external", "name": "Display", "built_in": False,
         "usable": {"x": -2560, "y": -500, "width": 2560, "height": 1400}},
        {"id": "laptop", "name": "Laptop", "built_in": True,
         "usable": {"x": 0, "y": 25, "width": 1512, "height": 900}}]}


class LayoutTest(unittest.TestCase):
    def test_explicitly_fixed_window_is_an_obstacle_to_other_panes(self):
        ws = [window("fixed", "Safari"), window("terminal", "Ghostty", focused=True), window("editor", "Code")]
        ws[0]["bounds"] = {"x": -1400, "y": -450, "width": 1000, "height": 1000}
        inv = inventory(ws)
        actions = build_actions(inv, [{"id": w["id"], "role": "unchanged" if w["id"] == "fixed" else "display_external"} for w in ws])
        self.assertEqual(len(actions), 2)
        for a in actions:
            self.assertEqual(a["kind"], "move")
            self.assertFalse(frames_overlap(a["target"], ws[0]["bounds"]))
        self.assertFalse(frames_overlap(actions[0]["target"], actions[1]["target"]))
    def test_work_browser_and_terminal_are_neighbors_without_overriding_displays(self):
        ws = [window("editor", "Code", focused=True), window("browser", "Safari"), window("other", "Notes"), window("terminal", "Ghostty"), window("chat", "Messages")]
        inv = inventory(ws)
        actions = build_actions(inv, [{"id": w["id"], "role": "display_laptop" if w["id"] == "chat" else "display_external"} for w in ws])
        moved = {a["window"]["id"]: a for a in actions}
        browser, terminal = [moved[k]["target"] for k in ("browser", "terminal")]
        self.assertEqual(browser["y"], terminal["y"])
        self.assertEqual(terminal["x"] + terminal["width"] + 6, browser["x"])
        self.assertEqual(moved["chat"]["display"], "laptop")

    def test_measured_minimum_width_changes_partition_without_overlap(self):
        ws = [{**window(), "min_size": {"width": 500, "height": 320}},
              {**window("w-2"), "min_size": {"width": 770, "height": 445}}]
        b = {"x": 2560, "y": 765, "width": 1512, "height": 950}
        tiles = constrained_tiles(ws, b)
        self.assertGreaterEqual(tiles[1]["width"], 770)
        self.assertFalse(frames_overlap(*tiles))
        self.assertLessEqual(tiles[1]["x"] + tiles[1]["width"], 4072)

    def test_three_browser_work_windows_prefer_full_height_columns(self):
        ws = [window(f"w-{i}", app="Safari") for i in range(3)]
        b = {"x": 0, "y": 30, "width": 2560, "height": 1359}
        tiles = constrained_tiles(ws, b)
        self.assertEqual(len({t["y"] for t in tiles}), 1)
        self.assertTrue(all(t["height"] == 1347 for t in tiles))
        self.assertTrue(all(t["height"] > t["width"] for t in tiles))

    def test_portrait_display_prefers_readable_columns_over_short_rows(self):
        tiles = constrained_tiles([window(), window("w-2")], {"x": -1080, "y": 0, "width": 1080, "height": 1920})
        self.assertEqual(tiles[0]["y"], tiles[1]["y"])
        self.assertTrue(all(t["height"] == 1908 for t in tiles))

    def test_windows_that_cannot_fit_minimize_in_priority_order(self):
        ws = [{**window(f"w-{i}", focused=i == 2), "min_size": {"width": 1300, "height": 800}} for i in range(3)]
        actions = build_actions(inventory(ws), [{"id": w["id"], "role": "display_external"} for w in ws])
        self.assertEqual([a["window"]["id"] for a in actions if a["kind"] == "move"], ["w-2"])
        self.assertEqual(sum(a["kind"] == "minimize" for a in actions), 2)

    def test_snap_halves_respect_negative_display_coordinates(self):
        b = {"x": -2560, "y": -500, "width": 2560, "height": 1400}
        left, right = [snap_frame(z, b) for z in ("left", "right")]
        self.assertFalse(frames_overlap(left, right))
        self.assertEqual(right["x"] + right["width"], -6)
        self.assertFalse(frames_overlap(snap_frame("top", b), snap_frame("bottom", b)))

    def test_focused_window_is_preserved(self):
        inv = inventory([window(focused=True), window("w-2", "Browser")])
        actions = build_actions(inv, [{"id": "w-1", "role": "minimize"}, {"id": "w-2", "role": "minimize"}])
        self.assertFalse(any(a["window"]["id"] == "w-1" and a["kind"] in ("close", "minimize") for a in actions))

    def test_every_active_window_gets_a_non_overlapping_tile(self):
        inv = inventory([window(f"w-{i}", focused=i == 4) for i in range(5)])
        original = copy.deepcopy(inv)
        actions = build_actions(inv, [{"id": w["id"], "role": "display_external"} for w in inv["windows"]])
        moves = [a for a in actions if a["kind"] == "move"]
        self.assertEqual(len(moves), 5)
        self.assertEqual(moves[0]["window"]["id"], "w-4")
        for a in moves:
            b = a["target"]
            self.assertGreaterEqual(b["x"], -2560)
            self.assertGreaterEqual(b["y"], -500)
            self.assertLessEqual(b["x"] + b["width"], 0)
            self.assertLessEqual(b["y"] + b["height"], 900)
        self.assertFalse(any(frames_overlap(a["target"], b["target"]) for i, a in enumerate(moves) for b in moves[i + 1:]))
        self.assertEqual(inv, original)

    def test_single_display_tiles_all_active_windows(self):
        inv = inventory([window(), window("w-2")])
        inv["displays"] = inv["displays"][1:]
        actions = build_actions(inv, [{"id": "w-1", "role": "display_laptop"}, {"id": "w-2", "role": "display_laptop"}])
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(a["display"] == "laptop" for a in actions))
        self.assertLess(actions[0]["target"]["x"], actions[1]["target"]["x"])

    def test_layout_uses_one_to_six_displays_including_portrait_and_negative_origins(self):
        for count in range(1, 7):
            screens = [{"id": str(i), "name": f"Display {i}", "built_in": False,
                        "usable": {"x": -1440 if i == 1 else i * 1920, "y": -400 if i == 1 else 30,
                                   "width": 1440 if i == 1 else 1920, "height": 2560 if i == 1 else 1080}} for i in range(count)]
            ws = [window(f"w-{i}", focused=i == 0) for i in range(count * 3)]
            inv = {"windows": ws, "displays": screens}
            ds = [{"id": w["id"], "role": screen_key(screens[i % count])} for i, w in enumerate(ws)]
            actions = build_actions(inv, ds)
            self.assertEqual({a["display"] for a in actions}, {s["id"] for s in screens})
            self.assertEqual(len(actions), len(ws))
            self.assertFalse(any(frames_overlap(a["target"], b["target"]) for i, a in enumerate(actions) for b in actions[i + 1:] if a["display"] == b["display"]))

    def test_unplugged_display_preferences_fall_back_to_connected_displays(self):
        inv = inventory([])
        inv["display_preferences"] = {"work": "unplugged", "chat": "unplugged", "references": "unplugged"}
        self.assertEqual(display_assignments(inv)["work"]["id"], "external")
        inv["displays"] = inv["displays"][1:]
        self.assertEqual({s["id"] for s in display_assignments(inv).values()}, {"laptop"})
        inv["displays"] = []
        with self.assertRaisesRegex(ValueError, "No usable display"):
            display_assignments(inv)

    def test_third_monitor_gets_references_and_explicit_assignments_win(self):
        inv = inventory([])
        inv["displays"].append({"id": "portrait", "name": "Portrait", "built_in": False,
                                "usable": {"x": -3640, "y": -500, "width": 1080, "height": 1920}})
        self.assertEqual(display_assignments(inv)["references"]["id"], "portrait")
        inv["display_preferences"] = {"work": "portrait", "chat": "external", "references": "laptop"}
        self.assertEqual({k: s["id"] for k, s in display_assignments(inv).items()}, inv["display_preferences"])

    def test_repeating_a_layout_produces_the_same_geometry(self):
        inv = inventory([window()])
        ds = [{"id": "w-1", "role": "display_external"}]
        a = build_actions(inv, ds)[0]
        inv["windows"][0]["bounds"] = a["target"]
        self.assertEqual(build_actions(inv, ds)[0]["target"], a["target"])

    def test_unknown_duplicate_missing_and_injected_actions_refused(self):
        ws = [window(), window("w-2")]
        for ds in [[], [{"id": "w-1", "role": "display_external"}] * 2,
                   [{"id": "w-1", "role": "display_external"}, {"id": "evil", "role": "display_external"}],
                   [{"id": "w-1", "role": "display_external"}, {"id": "w-2", "role": "rm -rf"}]]:
            with self.assertRaises(ValueError):
                validate_decisions(ws, ds, ("display_external", "display_laptop", "close", "minimize", "unchanged"))

    def test_tile_geometry_for_one_to_32_windows_on_each_screen(self):
        for b in [{"x": -2560, "y": -500, "width": 2560, "height": 1440}, {"x": 0, "y": 30, "width": 1512, "height": 950}]:
            for n in range(1, 33):
                tiles = tile_frames(n, b)
                self.assertEqual(len(tiles), n)
                for t in tiles:
                    self.assertGreater(t["width"], 0)
                    self.assertGreater(t["height"], 0)
                    self.assertGreaterEqual(t["x"], b["x"])
                    self.assertGreaterEqual(t["y"], b["y"])
                    self.assertLessEqual(t["x"] + t["width"], b["x"] + b["width"])
                    self.assertLessEqual(t["y"] + t["height"], b["y"] + b["height"])
                self.assertFalse(any(frames_overlap(a, c) for i, a in enumerate(tiles) for c in tiles[i+1:]))

    def test_other_automation_is_excluded(self):
        inv = inventory([window(), window("w-2", "Google Chrome for Testing")])
        self.assertEqual([w["id"] for w in eligible_windows(inv)], ["w-1"])


if __name__ == "__main__":
    unittest.main()
