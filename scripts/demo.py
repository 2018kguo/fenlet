#!/usr/bin/env python3
"""Render the real widget with synthetic content. No desktop scan or model calls."""
import argparse
import json
import os
from pathlib import Path
import runpy
import select
import shlex
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fenlet.core import build_actions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs")
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    harness = runpy.run_path(str(ROOT / "scripts/verify-widget.py"))
    with tempfile.TemporaryDirectory(prefix="fenlet-demo-") as temporary:
        directory = Path(temporary)
        executable = directory / "FenletDemo"
        harness["build_fixture"](executable)
        # The fixture may only edit its synthetic plan; every OS/model operation is denied.
        (directory / "bin").mkdir()
        cli = directory / "bin/fenlet"
        cli.write_text('#!/bin/sh\n[ "$1" != "--json" ] || shift\nif [ "$1" != "edit" ]; then printf \'%s\\n\' \'{"ok":false,"error":"This is a synthetic demo."}\'; exit 1; fi\nexec ' + shlex.quote(str(ROOT / "bin/fenlet")) + ' --json "$@"\n')
        cli.chmod(0o700)
        sample = harness["fixture"](2, False, "background")
        inv = sample["plan"]["inventory"]
        inv["displays"][0]["name"] = "Work display"
        laptop = inv["displays"][1]; laptop["name"] = "Laptop"; laptop["built_in"] = True
        laptop["bounds"].update(width=1512, height=982)
        laptop["usable"].update(width=1512, height=922)
        laptop["physical_size_mm"] = {"width": 301, "height": 196}
        for window, app, title in zip(inv["windows"], ["Terminal", "Safari", "Messages"], ["Fenlet · main", "Project notebook", "Team chat"]):
            window.update(app_name=app, title=title)
        music = {**inv["windows"][-1], "id": "music", "app_name": "Music", "title": "Focus mix", "is_focused": False}
        inv["windows"].append(music)
        decisions = [{"id": w["id"], "role": "minimize" if w["id"] == "music" else "display_screen-1" if w["app_name"] == "Messages" else "display_screen-0"} for w in inv["windows"]]
        plan = {"version": 1, "id": uuid.uuid4().hex, "intent": "Synthetic documentation demo", "model": None,
                "inventory": inv, "actions": build_actions(inv, decisions)}
        path = directory / "plan.json"; path.write_text(json.dumps(plan))
        preview = {"plan_path": str(path), "plan": plan, "window_count": 4, "action_count": 4, "model": None, "coverage": {"errors": []}}
        input_path = directory / "input.json"; input_path.write_text(json.dumps(preview))
        env = {**os.environ, "FENLET_STATE": str(directory / "state"), "FENLET_CONFIG": str(directory / "config.json")}
        process = subprocess.Popen([str(executable), str(input_path), "--demo"], stdout=subprocess.PIPE, text=True, env=env)
        try:
            if not select.select([process.stdout], [], [], 10)[0]: raise TimeoutError("Demo did not open")
            window = int(process.stdout.readline())
            frames = []
            def capture():
                destination = directory / f"frame-{len(frames):02d}.png"
                result = subprocess.run(["peekaboo", "see", "--window-id", str(window), "--no-elements", "--path", str(destination), "--json"], capture_output=True, text=True)
                assert json.loads(result.stdout).get("success"), result.stdout
                frames.append(destination); return destination
            # Let the one-shot edit cue settle, then capture stable documentation pixels.
            first = harness["snapshot"](window)
            capture()
            data = harness["snapshot"](window)
            source = next(e for e in data["ui_elements"] if e.get("label") == "Preview Music: Focus mix")
            target = next(e for e in data["ui_elements"] if e.get("label") == "Preview Messages: Team chat")
            moving = subprocess.Popen(["peekaboo", "drag", "--from", source["id"], "--to", target["id"], "--snapshot", data["snapshot_id"],
                                       "--duration", "900ms", "--steps", "48", "--json"], stdout=subprocess.PIPE, text=True)
            while moving.poll() is None: capture()
            receipt = json.loads(moving.stdout.read()); moving.stdout.close()
            assert receipt.get("success"), receipt.get("error")
            deadline = time.monotonic() + 4
            while True:
                data = harness["snapshot"](window)
                if any(e.get("label") == "Draft updated. Your windows haven’t moved yet." for e in data["ui_elements"]): break
                if time.monotonic() > deadline: raise AssertionError("Demo drag did not complete")
                time.sleep(.1)
            capture()
            (args.output / "preview.png").write_bytes(frames[0].read_bytes())
            sequence = directory / "frames.txt"
            lines = []
            for index, frame in enumerate(frames):
                lines += ["file " + shlex.quote(str(frame)), "duration " + ("1.8" if index in (0, len(frames)-1) else "0.16")]
            lines += ["file " + shlex.quote(str(frames[-1]))]
            sequence.write_text("\n".join(lines) + "\n")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(sequence),
                            "-filter_complex", "[0:v]split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=sierra2_4a", "-loop", "0", str(args.output / "demo.gif")], check=True)
            print(json.dumps({"synthetic": True, "frames": len(frames), "model_calls": 0, "desktop_window_operations": 0, "output": str(args.output)}))
        finally:
            if process.poll() is None: process.terminate()
            process.wait(timeout=3); process.stdout.close()


if __name__ == "__main__":
    main()
