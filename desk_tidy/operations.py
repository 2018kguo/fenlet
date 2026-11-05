"""Apply reviewed plans once, verify effects, and record enough to undo them."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass

from .core import SCREENSHOT, build_actions, fingerprint, same_bounds, valid_bounds, fits_tile, frames_overlap, eligible_windows, constrained_tiles, layout_report
from .runtime import STATE, native, native_window_batch, private_dir, run_json, write_json, replace_private_json, native_json
from .overlap import analyze_overlaps


def save_plan(inv, decisions, intent, model, *, actions=None):
    plan = {"version": 1, "id": uuid.uuid4().hex, "inventory": inv, "intent": intent,
            "model": model, "actions": actions if actions is not None else build_actions(inv, decisions) if decisions is not None else []}
    path = STATE / "plans" / f"{plan['id']}.json"
    write_json(path, plan)
    return path, plan


def read_plan(path):
    p = json.loads(Path(path).read_text())
    if p.get("version") != 1 or not isinstance(p.get("id"), str) or len(p["id"]) != 32 or not all(c in "0123456789abcdef" for c in p["id"]):
        raise ValueError("Unrecognized plan. Generate a fresh preview.")
    if Path(p["inventory"]["desktop"]) != Path.home() / "Desktop":
        raise ValueError("Cleanup is restricted to your Desktop.")
    days = p["inventory"]["days"]
    if type(days) is not int or days < 1:
        raise ValueError("Screenshot age must be at least one day.")
    known = {w["id"]: w for w in p["inventory"]["windows"]}
    seen = set()
    for a in p["actions"]:
        w = a["window"]
        if a["kind"] not in ("move", "minimize", "close") or known.get(w["id"]) != w or w["id"] in seen:
            raise ValueError("Invalid or duplicate window action.")
        seen.add(w["id"])
        if w.get("accessible") is False or w.get("minimized") or not w.get("process_instance"):
            raise ValueError("Window has no stable, accessible identity.")
        if a["kind"] in ("close", "minimize") and w.get("is_focused"):
            raise ValueError("The focused window must be preserved.")
        if a["kind"] == "move":
            target = a["target"]
            s = next(s for s in p["inventory"]["displays"] if s["id"] == a["display"])["usable"]
            if not valid_bounds(target) or not (s["x"] <= target["x"] and s["y"] <= target["y"]
                and target["x"] + target["width"] <= s["x"] + s["width"] + 1
                and target["y"] + target["height"] <= s["y"] + s["height"] + 1):
                raise ValueError("Window target falls outside its display.")
    return p


@contextmanager
def operation_lock():
    private_dir(STATE)
    with open(STATE / "operation.lock", "a") as f:
        os.chmod(f.name, 0o600)
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another tidy operation is running. Wait for it to finish.")
        yield


def record(f, entry):
    record_many(f, [entry])


def record_many(f, entries):
    for entry in entries:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    f.flush()
    os.fsync(f.fileno())


def window_matches(action, live):
    if action["kind"] == "close":
        return live is None
    if action["kind"] == "move" and live and live.get("resizable") is False:
        b, t = live["bounds"], action["target"]
        return (not live.get("minimized") and abs(b["x"] - t["x"]) <= 2 and abs(b["y"] - t["y"]) <= 2
                and b["width"] <= t["width"] + 1 and b["height"] <= t["height"] + 1)
    return bool(live and (live.get("minimized") if action["kind"] == "minimize"
                          else not live.get("minimized") and fits_tile(live["bounds"], action["target"])))


def screenshot_ready(item, days):
    path = Path(item["path"])
    root = Path.home() / "Desktop"
    if path.parent != root or not SCREENSHOT.fullmatch(path.name):
        raise ValueError("Only default-named screenshots directly on Desktop can be cleaned.")
    # Reject an aliased Desktop and symlinks; never recurse into a folder.
    if root.is_symlink():
        raise ValueError("Desktop is a symlink. Cleanup needs a real Desktop folder.")
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or fingerprint(s) != item["fingerprint"]:
        raise ValueError("Screenshot changed since preview. Scan again.")
    if max(s.st_mtime, getattr(s, "st_birthtime", s.st_mtime)) >= time.time() - days * 86400:
        raise ValueError("Screenshot is newer than the cleanup cutoff.")


def summary(p, path):
    inv = p["inventory"]
    return {"plan_path": str(path), "plan": p, "window_count": len(inv["windows"]),
            "screenshot_count": len(inv["screenshots"]) if inv.get("screenshots_scanned", True) else None,
            "screenshot_bytes": sum(x["fingerprint"]["size"] for x in inv["screenshots"]) if inv.get("screenshots_scanned", True) else None,
            "action_count": len(p["actions"]), "model": p["model"], "scan_ms": inv["scan_ms"],
            "coverage": inv["coverage"]}


def audit_layout():
    observed = native_json("inventory")
    return layout_report(observed)


@dataclass(frozen=True)
class AppliedWindows:
    results: list
    inventory: dict
    focus_check: dict
    timings: dict


def apply_window_batch(p, f):
    actions = p["actions"]
    record_many(f, ({"event": "started", "index": i, "item": action} for i, action in enumerate(actions)))
    selected, results = list(enumerate(actions)), {}
    batch = native_window_batch(actions, expected_displays=p["inventory"]["displays"])
    raw, final_inventory, timings = batch.results, batch.inventory, dict(batch.timings)
    focus_before, focus_after = batch.focus_check.get("before"), batch.focus_check.get("after")
    for i, action in selected:
        w = action["window"]
        r = raw[w["id"]]
        if r.get("skipped"):
            results[i] = {"ok": False, "skipped": True, "error": r.get("error", "Window changed since preview.")}
            continue
        after = {**w, **{k: r[k] for k in ("resizable", "min_size") if k in r}, "bounds": r["bounds"], "minimized": r.get("minimized", False)} if r.get("bounds") else None
        verified = (r.get("closed") is True if action["kind"] == "close" else window_matches(action, after))
        results[i] = {"ok": verified, "after": after, "unchanged": bool(r.get("unchanged"))}
        if not verified:
            results[i]["error"] = r.get("error", "Window did not fit its assigned tile.")
    # Some apps don't expose AXMinSize. Learn a confirmed size clamp and make
    # one new partition from observed rectangles; never resend an uncertain move.
    for screen in p["inventory"]["displays"]:
        group = [(i, a) for i, a in selected if a["kind"] == "move" and a["display"] == screen["id"]]
        if not group or not all(results[i].get("after") for i, _ in group):
            continue
        clamped = any(results[i]["after"]["bounds"][k] > a["target"][k] + 1 for i, a in group for k in ("width", "height"))
        if not clamped:
            continue
        windows = []
        for i, a in group:
            w = results[i]["after"]
            minimum = dict(w.get("min_size", {"width": 500, "height": 320}))
            for key in ("width", "height"):
                if w["bounds"][key] > a["target"][key] + 1:
                    minimum[key] = w["bounds"][key]
            windows.append({**w, "min_size": minimum})
        targets = constrained_tiles(windows, screen["usable"])
        constraint_path = STATE / "window-constraints.json"
        learned = json.loads(constraint_path.read_text()) if constraint_path.exists() else {}
        for w in windows:
            learned[w["process_instance"] + "/" + w["id"]] = w["min_size"]
        replace_private_json(constraint_path, dict(list(learned.items())[-128:]))
        if targets is None:
            continue
        repairs = [{"kind": "move", "window": w, "target": t} for w, t in zip(windows, targets)]
        record(f, {"event": "repair_started", "indices": [i for i, _ in group], "items": repairs})
        repair_batch = native_window_batch(repairs, expected_displays=p["inventory"]["displays"])
        observed, final_inventory = repair_batch.results, repair_batch.inventory
        focus_after = repair_batch.focus_check.get("after")
        timings["reflow_ms"] = timings.get("reflow_ms", 0) + repair_batch.timings.get("native_process_ms", 0)
        for (i, _), repair in zip(group, repairs):
            r = observed[repair["window"]["id"]]
            after = {**repair["window"], "bounds": r["bounds"], "minimized": r.get("minimized", False)} if r.get("bounds") else None
            was_unchanged = results[i].get("unchanged", False)
            results[i] = {"ok": not r.get("skipped") and window_matches(repair, after), "after": after,
                          "reflowed": True, "skipped": bool(r.get("skipped")), "unchanged": was_unchanged and bool(r.get("unchanged"))}
            if not results[i]["ok"]:
                results[i]["error"] = r.get("error", "App would not fit its pane.")
        record(f, {"event": "repair_finished", "results": {str(i): results[i] for i, _ in group}})
    # Preserve fixed windows, failed closes, and windows opened during the run.
    # Only confirmed movable windows participate in this new geometric repair.
    if layout_report(final_inventory)["overlap_count"]:
        movable = {a["window"]["id"]: (i, a) for i, a in selected if a["kind"] == "move" and results[i].get("after") and not results[i].get("skipped")}
        actual_windows = [{**w, **{k: results[movable[w["id"]][0]]["after"][k] for k in ("min_size", "resizable")
                                 if k in results[movable[w["id"]][0]]["after"]}} if w["id"] in movable else w for w in final_inventory["windows"]]
        decisions = [{"id": w["id"], "role": "display_" + movable[w["id"]][1]["display"] if w["id"] in movable else "unchanged"} for w in eligible_windows({"windows": actual_windows})]
        try:
            repairs = build_actions({**final_inventory, "windows": actual_windows}, decisions)
        except ValueError as error:
            record(f, {"event": "repair_unavailable", "reason": str(error)})
            repairs = []
        if repairs:
            indices = [movable[a["window"]["id"]][0] for a in repairs]
            record(f, {"event": "repair_started", "indices": indices, "items": repairs})
            repaired = native_window_batch(repairs, expected_displays=p["inventory"]["displays"])
            final_inventory, focus_after = repaired.inventory, repaired.focus_check.get("after")
            timings["obstacle_reflow_ms"] = repaired.timings.get("native_process_ms", 0)
            for i, repair in zip(indices, repairs):
                raw_result = repaired.results[repair["window"]["id"]]
                after = {**repair["window"], "bounds": raw_result["bounds"], "minimized": raw_result.get("minimized", False)} if raw_result.get("bounds") else None
                was_unchanged = results[i].get("unchanged", False)
                results[i] = {"ok": not raw_result.get("skipped") and window_matches(repair, after), "after": after,
                              "applied_kind": repair["kind"], "skipped": bool(raw_result.get("skipped")),
                              "unchanged": was_unchanged and bool(raw_result.get("unchanged"))}
                if not results[i]["ok"]:
                    results[i]["error"] = raw_result.get("error", "Window did not fit around a fixed window.")
            record(f, {"event": "repair_finished", "results": {str(i): results[i] for i in indices}})
    moved = [(i, r["after"]["bounds"]) for i, r in results.items()
             if actions[i]["kind"] == "move" and r.get("after") and not r["after"].get("minimized") and not r.get("skipped")]
    for index in analyze_overlaps([b for _, b in moved], example_limit=0).affected:
        i = moved[index][0]
        results[i]["ok"] = False
        results[i]["error"] = "Window minimum size overlaps another tile."
    record_many(f, ({"event": "finished", "index": i, "result": results[i]} for i, _ in selected))
    known_focus = bool(focus_before and focus_before.get("window_id") and focus_after and focus_after.get("window_id"))
    return AppliedWindows([results[i] for i in sorted(results)], final_inventory,
        {"before": focus_before, "after": focus_after, "unchanged": focus_before == focus_after if known_focus else None}, timings)


def apply(path, scope):
    started_at = time.monotonic()
    with operation_lock():
        p = read_plan(path)
        if scope == "screenshots" and not p["inventory"].get("screenshots_scanned", True):
            raise ValueError("Run cleanup first. Window layouts do not scan Desktop files.")
        if not 0 <= time.time() - p["inventory"]["created_at"] <= 900:
            raise ValueError("Preview expired after 15 minutes. Make a fresh preview.")
        window_outcome = None
        log = private_dir(STATE / "runs") / f"{p['id']}-{scope}.jsonl"
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        results = []
        items = p["actions"] if scope == "windows" else p["inventory"]["screenshots"]
        with os.fdopen(fd, "w") as f:
            record(f, {"event": "begin", "at": time.time(), "plan_path": str(Path(path).resolve()), "scope": scope})
            if scope == "windows":
                window_outcome = apply_window_batch(p, f)
                results = window_outcome.results
            else:
                helper = subprocess.Popen([native(), "trash"], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, text=True, bufsize=1)
                try:
                    for index, item in enumerate(items):
                        record(f, {"event": "started", "index": index, "item": item})
                        try:
                            screenshot_ready(item, p["inventory"]["days"])
                            helper.stdin.write(json.dumps(item) + "\n")
                            helper.stdin.flush()
                            result = json.loads(helper.stdout.readline())
                            if not result.get("ok"):
                                raise ValueError(result.get("error", "Trash did not confirm completion."))
                            if Path(item["path"]).exists():
                                raise ValueError("Original file still exists. Inspect Trash before continuing.")
                            result["fingerprint"] = fingerprint(Path(result["trashed_path"]).lstat())
                            record(f, {"event": "finished", "index": index, "result": result})
                            results.append(result)
                        except Exception as e:
                            record(f, {"event": "failed", "index": index, "error": str(e)})
                            results.append({"ok": False, "error": str(e)})
                            break
                finally:
                    helper.stdin.close()
                    helper.wait(timeout=10)
        checked = layout_report(window_outcome.inventory) if window_outcome else None
        return {"journal_path": str(log), "succeeded": sum(r["ok"] for r in results),
                "undoable": any((a["kind"] != "close" and not r.get("skipped") and not r.get("unchanged") and r.get("after"))
                                if scope == "windows" else r.get("ok") for a, r in zip(items, results)),
                "focus_check": window_outcome.focus_check if window_outcome else None,
                "timings": window_outcome.timings if window_outcome else {},
                "failed": sum(not r["ok"] for r in results), "planned": len(items), "results": results,
                "apply_ms": round((time.monotonic() - started_at) * 1000),
                "layout_check": checked,
                "closed": sum(r.get("applied_kind", a["kind"]) == "close" and r["ok"] and not r.get("unchanged") for a, r in zip(items, results)) if scope == "windows" else 0,
                "minimized": sum(r.get("applied_kind", a["kind"]) == "minimize" and r["ok"] and not r.get("unchanged") for a, r in zip(items, results)) if scope == "windows" else 0,
                "arranged": sum(r.get("applied_kind", a["kind"]) == "move" and r["ok"] and not r.get("unchanged") for a, r in zip(items, results)) if scope == "windows" else 0}


def undo(path):
    with operation_lock():
        entries = [json.loads(line) for line in Path(path).read_text().splitlines()]
        started = {e["index"]: e["item"] for e in entries if e["event"] == "started"}
        finished = {}
        expected = dict(started)
        for entry in entries:
            if entry["event"] == "repair_started":
                expected.update(zip(entry["indices"], entry["items"]))
            elif entry["event"] == "repair_finished":
                finished.update({int(i): result for i, result in entry["results"].items()})
            elif entry["event"] == "finished":
                finished[entry["index"]] = entry["result"]
        undone = {e["index"] for e in entries if e["event"] == "undone"}
        scope = entries[0]["scope"]
        restored, skipped = 0, []
        with open(path, "a") as f:
            if scope == "windows":
                undo_started = {e["index"] for e in entries if e["event"] == "undo_started"}
                return undo_window_batch(started, finished, expected, undone, undo_started, f)
            for index in sorted(finished, reverse=True):
                if index in undone:
                    continue
                item, result = started[index], finished[index]
                try:
                    src, dst = Path(result["trashed_path"]), Path(item["path"])
                    if dst.parent != Path.home() / "Desktop" or not SCREENSHOT.fullmatch(dst.name):
                        raise ValueError("Restore destination is not a Desktop screenshot.")
                    if src.is_symlink() or fingerprint(src.lstat()) != result["fingerprint"]:
                        raise ValueError("File in Trash changed; restore it manually.")
                    os.link(src, dst, follow_symlinks=False)  # exclusive: never overwrite a new file
                    src.unlink()
                    record(f, {"event": "undone", "index": index})
                    restored += 1
                except Exception as e:
                    skipped.append({"index": index, "reason": str(e)})
        unresolved = len(set(started) - set(finished))
        return {"restored": restored, "skipped": skipped, "unresolved": unresolved,
                "note": "Interrupted actions need manual inspection." if unresolved else ""}


def undo_window_batch(started, finished, expected, undone, undo_started, journal):
    candidates = [i for i in reversed(list(started)) if i not in undone and started[i]["kind"] != "close"
                  and not finished.get(i, {}).get("skipped") and not finished.get(i, {}).get("unchanged")]
    if not candidates:
        return {"restored": 0, "skipped": [], "unresolved": 0, "note": ""}
    observed = native_window_batch([{"kind": "inspect", "window": started[i]["window"]} for i in candidates])
    selected, skipped, restored = [], [], 0
    for i in candidates:
        original, raw = started[i]["window"], observed.results[started[i]["window"]["id"]]
        if raw.get("closed"):
            finished[i] = {"ok": False, "skipped": True, "error": "Original window is closed."}
            record(journal, {"event": "finished", "index": i, "result": finished[i]})
            skipped.append({"index": i, "reason": "Original window is closed."})
            continue
        live = {**original, "bounds": raw["bounds"], "minimized": raw.get("minimized", False)} if raw.get("bounds") else None
        if i in undo_started and live and not live["minimized"] and same_bounds(live["bounds"], original["bounds"], 2):
            record(journal, {"event": "undone", "index": i, "recovered": True})
            restored += 1
            continue
        if i not in finished or not finished[i].get("after"):
            if window_matches(expected[i], live) and live:
                finished[i] = {"ok": True, "after": live, "recovered": True}
                record(journal, {"event": "finished", "index": i, "result": finished[i]})
            else:
                skipped.append({"index": i, "reason": raw.get("error", "Interrupted change no longer matches its expected state.")})
                continue
        after = finished[i]["after"]
        if not live or live["minimized"] != after.get("minimized") or (not live["minimized"] and not same_bounds(live["bounds"], after["bounds"], 2)):
            skipped.append({"index": i, "reason": "Window changed after tidy; preserved the current layout."})
            continue
        if not live["minimized"] and same_bounds(live["bounds"], original["bounds"], 2):
            record(journal, {"event": "undone", "index": i})
            continue
        action = {"kind": "restore", "window": live, "target": original["bounds"]}
        selected.append((i, action))
    focus = observed.focus_check
    if selected:
        record_many(journal, ({"event": "undo_started", "index": i, "item": a} for i, a in selected))
        result = native_window_batch([a for _, a in selected])
        focus = result.focus_check
        for i, action in selected:
            raw = result.results[action["window"]["id"]]
            if not raw.get("skipped") and raw.get("bounds") and not raw.get("minimized") and fits_tile(raw["bounds"], action["target"]):
                record(journal, {"event": "undone", "index": i})
                restored += 1
            else:
                skipped.append({"index": i, "reason": raw.get("error", "Restore could not be verified.")})
    unresolved = len({i for i in candidates if i not in finished})
    return {"restored": restored, "skipped": skipped, "unresolved": unresolved, "focus_check": focus,
            "note": "Interrupted actions need inspection." if unresolved else ""}
