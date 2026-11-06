import copy
import unittest

from fenlet.core import constrained_tiles, frames_overlap, physical_size, display_assignments
from tests.test_core import window


def display(width=2560, height=1440, inches=(23.7, 13.33)):
    return {"id": "screen", "name": "Screen", "built_in": False,
            "bounds": {"x": 0, "y": 0, "width": width, "height": height},
            "usable": {"x": 0, "y": 0, "width": width, "height": height},
            "physical_size_mm": {"width": inches[0] * 25.4, "height": inches[1] * 25.4},
            "physical_size_source": "system_reported"}


class PhysicalLayoutTest(unittest.TestCase):
    def test_four_windows_use_three_readable_columns_instead_of_four_narrow_ones(self):
        s = display()
        frames = constrained_tiles([window(f"w-{i}") for i in range(4)], s["usable"], s)
        self.assertEqual(len({f["x"] for f in frames}), 3)
        self.assertTrue(all(6 <= f["width"] / s["bounds"]["width"] * 23.7 <= 8 for f in frames))
        self.assertFalse(any(frames_overlap(a, b) for i, a in enumerate(frames) for b in frames[i+1:]))

    def test_portrait_uses_height_when_two_columns_would_be_too_narrow(self):
        s = display(1080, 1920, (10, 17.78))
        frames = constrained_tiles([window(), window("w-2")], s["usable"], s)
        self.assertEqual(frames[0]["x"], frames[1]["x"])
        self.assertNotEqual(frames[0]["y"], frames[1]["y"])
        self.assertGreaterEqual(frames[0]["width"] / 1080 * 10, 6)

    def test_same_physical_monitor_uses_same_partition_at_different_retina_scaling(self):
        shapes = []
        for scale in (1, 1.25, 2):
            s = display(2560 * scale, 1440 * scale)
            frames = constrained_tiles([window(f"w-{i}") for i in range(4)], s["usable"], s)
            shapes.append((len({f["x"] for f in frames}), len({f["y"] for f in frames})))
        self.assertEqual(shapes, [(3, 2)] * 3)

    def test_estimated_dimensions_fall_back_without_inventing_inches(self):
        s = display(); s["physical_size_source"] = "estimated"
        ws = [window(f"w-{i}") for i in range(4)]
        self.assertIsNone(physical_size(s))
        self.assertEqual(constrained_tiles(ws, s["usable"], s), constrained_tiles(ws, s["usable"]))

    def test_rotation_aligns_millimeters_and_auto_work_uses_physical_area(self):
        portrait = display(1080, 1920, (17.78, 10))
        self.assertEqual(physical_size(portrait)["width"], 254)
        small = display(3840, 2160, (12, 6.75)); small["id"] = "small"
        big = display(1920, 1080, (24, 13.5)); big["id"] = "big"
        self.assertEqual(display_assignments({"displays": [small, big]})["work"]["id"], "big")
