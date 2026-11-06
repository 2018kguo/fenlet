#!/usr/bin/env python3
"""Measure pure planning and exact overlap checks; no OS access or provider calls."""
import json
from pathlib import Path
import platform
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fenlet.core import build_actions
from fenlet.overlap import analyze_overlaps


def measure(function):
    samples = []
    for _ in range(5):
        started = time.process_time()
        result = function()
        samples.append((time.process_time() - started) * 1000)
    return result, round(statistics.median(samples), 3)


report = {"synthetic": True, "python": platform.python_version(), "architecture": platform.machine(),
          "measurement": "median process CPU milliseconds over five runs", "results": []}
for count in (16, 128, 1024, 8192):
    windows = [{"id": f"w-{i}", "app_name": "Safari" if i % 2 else "Terminal", "title": "Synthetic work",
                "is_focused": i == 0, "minimized": False, "accessible": True,
                "bounds": {"x": 0, "y": 0, "width": 800, "height": 600}} for i in range(count)]
    inv = {"windows": windows, "displays": [{"id": "screen", "name": "Synthetic display", "built_in": True,
            "bounds": {"x": 0, "y": 0, "width": 2560, "height": 1440},
            "physical_size_mm": {"width": 598, "height": 336}, "physical_size_source": "system_reported",
            "usable": {"x": 0, "y": 30, "width": 2560, "height": 1440}}]}
    decisions = [{"id": w["id"], "role": "display_screen"} for w in windows]
    actions, plan_ms = measure(lambda: build_actions(inv, decisions))
    dense, dense_ms = measure(lambda: analyze_overlaps([w["bounds"] for w in windows]))
    disjoint_frames = [{"x": i * 810, "y": 0, "width": 800, "height": 600} for i in range(count)]
    disjoint, disjoint_ms = measure(lambda: analyze_overlaps(disjoint_frames))
    assert dense.count == count * (count - 1) // 2 and disjoint.count == 0
    assert len(dense.examples) <= 32 and len(actions) == count
    report["results"].append({"windows": count, "plan_ms": plan_ms, "dense_overlap_ms": dense_ms,
        "disjoint_overlap_ms": disjoint_ms, "exact_dense_pairs": dense.count,
        "diagnostic_pairs": len(dense.examples), "visible_panes": sum(a["kind"] == "move" for a in actions)})
print(json.dumps(report, indent=2))
