#!/usr/bin/env python3
"""Measure read-only fresh CLI versus the persistent engine; never emit titles."""
import argparse
import json
import os
from pathlib import Path
import select
import statistics
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cli", type=Path)
    parser.add_argument("--samples", type=int, default=7)
    args = parser.parse_args()
    if not 3 <= args.samples <= 30: parser.error("Use 3–30 samples.")
    cli = str(args.cli.resolve())
    with tempfile.TemporaryDirectory(prefix="fenlet-session-") as temporary:
        env = {**os.environ, "FENLET_STATE": temporary}
        command = ["scan", "--all-spaces"]
        fresh, warm = [], []
        for _ in range(args.samples):
            started = time.perf_counter()
            response = json.loads(subprocess.check_output([cli] + command, env=env, timeout=30))
            assert response["ok"]
            fresh.append((time.perf_counter() - started) * 1000)
        worker = subprocess.Popen([cli, "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
        try:
            for request in range(args.samples + 1):
                started = time.perf_counter()
                worker.stdin.write(json.dumps({"id": request + 1, "args": command}) + "\n"); worker.stdin.flush()
                assert select.select([worker.stdout], [], [], 30)[0], "Engine timed out."
                response = json.loads(worker.stdout.readline())
                assert response["ok"] and response["id"] == request + 1
                elapsed = (time.perf_counter() - started) * 1000
                if request: warm.append(elapsed)
                else: cold = elapsed
            assert worker.poll() is None
        finally:
            worker.stdin.close()
            worker.wait(timeout=5); worker.stdout.close()
        result = dict(samples=args.samples, measurement="read-only inventory wall milliseconds", warmup_ms=round(cold, 1),
            fresh_median_ms=round(statistics.median(fresh), 1), warm_median_ms=round(statistics.median(warm), 1),
            warm_speedup=round(statistics.median(fresh) / statistics.median(warm), 2),
            window_count=len(response["data"]["windows"]), display_count=len(response["data"]["displays"]),
            inventory_complete=response["data"]["coverage"]["complete"])
        print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
