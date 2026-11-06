"""Apply reviewed plans once, verify effects, and record enough to undo them."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
import uuid
from dataclasses import dataclass

from .core import build_actions, same_bounds, same_space_state, valid_bounds, fits_tile, frames_overlap, eligible_windows, constrained_tiles, layout_report, revise_actions
from .runtime import STATE, native_window_batch, private_dir, write_json, replace_private_json, native_json
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
            screen = next(s for s in p["inventory"]["displays"] if s["id"] == a["display"])
            if p["inventory"].get("all_spaces") and (not screen.get("gather_space") or a.get("target_space") != screen["gather_space"]):
                raise ValueError("The destination Space does not match this preview.")
            s = screen["usable"]
            if not valid_bounds(target) or not (s["x"] <= target["x"] and s["y"] <= target["y"]
                and target["x"] + target["width"] <= s["x"] + s["width"] + 1
                and target["y"] + target["height"] <= s["y"] + s["height"] + 1):
                raise ValueError("Window target falls outside its display.")
    return p


def revise_plan(path, operation, window_id, target=None):
    before = read_plan(path)
    if not 0 <= time.time() - before["inventory"]["created_at"] <= 900:
        raise ValueError("Preview expired. Arrange again to make a fresh preview.")
    actions = revise_actions(before["inventory"], before["actions"], operation, window_id, target)
    new_path, plan = save_plan(before["inventory"], None, before["intent"], before["model"], actions=actions)
    read_plan(new_path)
    return summary(plan, new_path)


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


def gathered(action, live):
    return ("target_space" not in action or bool(live and live.get("fullscreen") is False
            and live.get("space_ids") == [action["target_space"]]))


def observed_window(original, raw):
    return {**{k: v for k, v in original.items() if k not in ("space_ids", "fullscreen")}, **{k: raw[k] for k in ("bounds", "resizable", "min_size", "space_ids", "fullscreen") if k in raw},
            "minimized": raw.get("minimized", None if "space_ids" in original else False)} if raw.get("bounds") else None


def restored_window(original, live):
    if not live or live.get("minimized") is not False:
        return False
    if original.get("fullscreen"):
        # macOS creates a new fullscreen Space; its old numeric ID no longer exists.
        return bool(live.get("fullscreen") and same_bounds(live["bounds"], original["bounds"], 2))
    return same_space_state(original, live) and same_bounds(live["bounds"], original["bounds"], 2)


def window_matches(action, live):
    if not gathered(action, live) or live and not isinstance(live.get("minimized"), bool):
        return False
    if action["kind"] == "close":
        return live is None
    if action["kind"] == "move" and live and live.get("resizable") is False:
        b, t = live["bounds"], action["target"]
        return (not live.get("minimized") and abs(b["x"] - t["x"]) <= 2 and abs(b["y"] - t["y"]) <= 2
                and b["width"] <= t["width"] + 1 and b["height"] <= t["height"] + 1)
    return bool(live and (live.get("minimized") if action["kind"] == "minimize"
                          else not live.get("minimized") and fits_tile(live["bounds"], action["target"])))




def summary(p, path):
    inv = p["inventory"]
    return {"plan_path": str(path), "plan": p, "window_count": len(inv["windows"]),
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
        after = observed_window(w, r)
        verified = (r.get("closed") is True if action["kind"] == "close" else window_matches(action, after))
        results[i] = {"ok": verified, "after": after, "unchanged": bool(r.get("unchanged"))}
        if not verified:
            results[i]["error"] = r.get("error", "Window did not fit its assigned tile.")
    # Some apps don't expose AXMinSize. Learn a confirmed size clamp and make
    # one new partition from observed rectangles; never resend an uncertain move.
    for screen in p["inventory"]["displays"]:
        group = [(i, a) for i, a in selected if a["kind"] == "move" and a["display"] == screen["id"]]
        if not group or not all(results[i].get("after") and gathered(a, results[i]["after"]) for i, a in group):
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
        targets = constrained_tiles(windows, screen["usable"], screen)
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
            after = observed_window(repair["window"], r)
            was_unchanged = results[i].get("unchanged", False)
            results[i] = {"ok": not r.get("skipped") and window_matches(repair, after), "after": after,
                          "reflowed": True, "skipped": bool(r.get("skipped")), "unchanged": was_unchanged and bool(r.get("unchanged"))}
            if not results[i]["ok"]:
                results[i]["error"] = r.get("error", "App would not fit its pane.")
        record(f, {"event": "repair_finished", "results": {str(i): results[i] for i, _ in group}})
    # Preserve fixed windows, failed closes, and windows opened during the run.
    # Only confirmed movable windows participate in this new geometric repair.
    if layout_report(final_inventory)["overlap_count"]:
        movable = {a["window"]["id"]: (i, a) for i, a in selected if a["kind"] == "move" and results[i].get("after") and not results[i].get("skipped") and gathered(a, results[i]["after"])}
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
                after = observed_window(repair["window"], raw_result)
                was_unchanged = results[i].get("unchanged", False)
                results[i] = {"ok": not raw_result.get("skipped") and window_matches(repair, after), "after": after,
                              "applied_kind": repair["kind"], "skipped": bool(raw_result.get("skipped")),
                              "unchanged": was_unchanged and bool(raw_result.get("unchanged"))}
                if not results[i]["ok"]:
                    results[i]["error"] = raw_result.get("error", "Window did not fit around a fixed window.")
            record(f, {"event": "repair_finished", "results": {str(i): results[i] for i in indices}})
    moved = [(i, r["after"]["bounds"]) for i, r in results.items()
             if actions[i]["kind"] == "move" and r.get("after") and gathered(actions[i], r["after"]) and not r["after"].get("minimized") and not r.get("skipped")]
    for index in analyze_overlaps([b for _, b in moved], example_limit=0).affected:
        i = moved[index][0]
        results[i]["ok"] = False
        results[i]["error"] = "Window minimum size overlaps another tile."
    record_many(f, ({"event": "finished", "index": i, "result": results[i]} for i, _ in selected))
    known_focus = bool(focus_before and focus_before.get("window_id") and focus_after and focus_after.get("window_id"))
    return AppliedWindows([results[i] for i in sorted(results)], final_inventory,
        {"before": focus_before, "after": focus_after, "unchanged": focus_before == focus_after if known_focus else None}, timings)


def apply(path):
    started_at = time.monotonic()
    with operation_lock():
        p = read_plan(path)
        if not 0 <= time.time() - p["inventory"]["created_at"] <= 900:
            raise ValueError("Preview expired after 15 minutes. Make a fresh preview.")
        log = private_dir(STATE / "runs") / f"{p['id']}-windows.jsonl"
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        items = p["actions"]
        with os.fdopen(fd, "w") as f:
            record(f, {"event": "begin", "at": time.time(), "plan_path": str(Path(path).resolve()), "scope": "windows"})
            outcome = apply_window_batch(p, f)
        results = outcome.results
        result = {"journal_path": str(log), "succeeded": sum(r["ok"] for r in results),
                "undoable": any(a["kind"] != "close" and not r.get("skipped") and not r.get("unchanged") and r.get("after") for a, r in zip(items, results)),
                "focus_check": outcome.focus_check, "timings": outcome.timings,
                "failed": sum(not r["ok"] for r in results), "planned": len(items), "results": results,
                "apply_ms": round((time.monotonic() - started_at) * 1000),
                "layout_check": layout_report(outcome.inventory),
                "closed": sum(r.get("applied_kind", a["kind"]) == "close" and r["ok"] and not r.get("unchanged") for a, r in zip(items, results)),
                "minimized": sum(r.get("applied_kind", a["kind"]) == "minimize" and r["ok"] and not r.get("unchanged") for a, r in zip(items, results)),
                "arranged": sum(r.get("applied_kind", a["kind"]) == "move" and r["ok"] and not r.get("unchanged") for a, r in zip(items, results))}
        history_path = STATE / "widget-history.json"
        if result["undoable"] or (result["failed"] == 0 and items):
            history = json.loads(history_path.read_text()) if history_path.exists() else {}
            if result["undoable"]:
                history["journal"] = str(log)
            if result["failed"] == 0:
                history["confirmed_journal"] = str(log)
            replace_private_json(history_path, history)
        return result


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
        if entries[0]["scope"] != "windows":
            raise ValueError("Only window-layout journals are supported.")
        with open(path, "a") as f:
            undo_started = {e["index"] for e in entries if e["event"] == "undo_started"}
            return undo_window_batch(started, finished, expected, undone, undo_started, f)


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
        live = observed_window(original, raw)
        if live and not isinstance(live.get("minimized"), bool):
            skipped.append({"index": i, "reason": "Window state unavailable; inspect before retrying."})
            continue
        if i in undo_started and restored_window(original, live):
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
        if not live or not same_space_state(live, after) or live["minimized"] != after.get("minimized") or (not live["minimized"] and not same_bounds(live["bounds"], after["bounds"], 2)):
            skipped.append({"index": i, "reason": "Window changed after tidy; preserved the current layout."})
            continue
        if restored_window(original, live):
            record(journal, {"event": "undone", "index": i})
            continue
        action = {"kind": "restore", "window": live, "target": original["bounds"]}
        if "fullscreen" in original:
            action["target_fullscreen"] = original["fullscreen"]
        if original.get("space_ids") and not original.get("fullscreen"):
            if len(original["space_ids"]) != 1:
                skipped.append({"index": i, "reason": "Cannot restore a window pinned to multiple Spaces."})
                continue
            action["target_space"] = original["space_ids"][0]
        selected.append((i, action))
    focus = observed.focus_check
    if selected:
        record_many(journal, ({"event": "undo_started", "index": i, "item": a} for i, a in selected))
        result = native_window_batch([a for _, a in selected])
        focus = result.focus_check
        for i, action in selected:
            raw = result.results[action["window"]["id"]]
            record(journal, {"event": "undo_observed", "index": i, "result": raw})
            if not raw.get("skipped") and restored_window(started[i]["window"], observed_window(action["window"], raw)):
                record(journal, {"event": "undone", "index": i})
                restored += 1
            else:
                skipped.append({"index": i, "reason": raw.get("error", "Restore could not be verified.")})
    unresolved = len({i for i in candidates if i not in finished})
    return {"restored": restored, "skipped": skipped, "unresolved": unresolved, "focus_check": focus,
            "note": "Interrupted actions need inspection." if unresolved else ""}
