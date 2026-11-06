#!/usr/bin/env python3
"""Run the same public, synthetic cases through each candidate. No desktop actions."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fenlet.runtime import STATE, decide, load_env, write_json

parser = argparse.ArgumentParser()
parser.add_argument("--env-file")
parser.add_argument("--models", nargs="+", default=["jev", "nemotron", "hybrid"])
parser.add_argument("--repeats", type=int, default=1)
args = parser.parse_args()
if args.env_file:
    load_env(args.env_file)
cases = json.loads((Path(__file__).resolve().parents[1] / "tests/model_cases.json").read_text())
results = []
for case in cases:
    windows = [{"id": f"w-{i}", "app_name": w["app"], "title": w["title"], "accessible": True,
                "minimized": False, "is_focused": False} for i, w in enumerate(case["windows"])]
    inv = {"windows": windows, "displays": case.get("displays", [
        {"id": "main", "name": "Studio Display", "built_in": False, "usable": {"x": 0, "y": 0, "width": 2560, "height": 1440}},
        {"id": "laptop", "name": "MacBook", "built_in": True, "usable": {"x": 2560, "y": 0, "width": 1512, "height": 950}}])}
    expected = {f"w-{i}": w["role"] for i, w in enumerate(case["windows"])}
    for model in args.models:
        for repeat in range(args.repeats):
            try:
                ds, meta = decide(inv, case["intent"], model)
            except Exception as error:
                results.append({"case": case["name"], "split": case["split"], "model": model,
                                "correct": 0, "total": len(windows), "error": str(error), "meta": {}})
                print(json.dumps(results[-1]), flush=True)
                continue
            wrong = [{"window": windows[int(d["id"].split("-")[1])]["app_name"],
                      "expected": expected[d["id"]], "actual": d["role"]}
                     for d in ds if d["role"] != expected[d["id"]]]
            result = {"case": case["name"], "split": case["split"], "model": model,
                      "correct": len(ds) - len(wrong), "total": len(ds), "wrong": wrong, "meta": meta}
            results.append(result)
            print(json.dumps(result), flush=True)
report = {"synthetic_cases": True, "results": results, "summary": {}}
for model in args.models:
    selected = [r for r in results if r["model"] == model]
    report["summary"][model] = {"correct": sum(r["correct"] for r in selected),
        "total": sum(r["total"] for r in selected),
        "failed_requests": sum("error" in r for r in selected),
        "median_ms": statistics.median(r["meta"]["latency_ms"] for r in selected if "latency_ms" in r["meta"]),
        "reported_cost_usd": sum(float(r["meta"].get("cost") or 0) for r in selected),
        "cost_excludes_failed_requests": True}
path = STATE / "benchmarks" / f"synthetic-{int(time.time()*1000)}.json"
write_json(path, report)
print(json.dumps({"report": str(path), "summary": report["summary"]}))
