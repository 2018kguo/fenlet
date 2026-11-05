"""Desktop decisions. No GUI, network, or filesystem effects in this module."""
import math
import re
from .overlap import analyze_overlaps

WINDOW_EFFECTS = ("close", "minimize", "unchanged")
PANE_GAP = 6
VIDEO_APPS = {"TV", "QuickTime Player", "VLC", "IINA", "mpv"}
BROWSER_APPS = {"Safari", "Google Chrome", "Firefox", "Arc", "Brave Browser", "Microsoft Edge", "Zen", "Orion"}
TERMINAL_APPS = {"Terminal", "Ghostty", "Rex", "Rex Beta", "iTerm2", "Alacritty", "WezTerm", "Warp", "Rio"}


def preferred_aspect(window):
    # Bounded metadata hint, not a claim that a particular video is playing.
    title = window.get("title", "").lower()
    return 16 / 9 if window["app_name"] in VIDEO_APPS or title.endswith((" - youtube", " - vimeo")) else 0.65
DEFAULT_INTENT = (
    "Tile my current work with no overlapping windows across the available displays. "
    "Use the display preferences for work, chat and references. "
    "When coding, put the relevant work browser beside the active terminal. Keep chat separate. "
    "Minimize useful background documents and tools. Actually close useless "
    "idle launchers, extra folder windows, old sign-in windows and unwanted media."
)
# Leaf recognizer for macOS's default screenshot names; never read image contents.
SCREENSHOT = re.compile(r"(?:Screenshot|Screen Shot) \d{4}-\d{2}-\d{2} at .+\.png", re.I)


def eligible_windows(inventory):
    # Test browsers can belong to another automation run. Leave them alone.
    return [w for w in inventory["windows"] if not w.get("minimized") and not w.get("hidden") and not w.get("protected") and w.get("accessible", True)
            and w["app_name"] not in ("Desk Tidy", "Google Chrome for Testing")]


def fingerprint(stat):
    return {"device": stat.st_dev, "inode": stat.st_ino,
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def same_bounds(a, b, tolerance=3):
    return all(abs(a[k] - b[k]) <= tolerance for k in ("x", "y", "width", "height"))


def valid_bounds(b):
    return (isinstance(b, dict) and set(b) == {"x", "y", "width", "height"}
            and all(type(v) in (int, float) and math.isfinite(v) for v in b.values())
            and b["width"] > 0 and b["height"] > 0)


def screen_key(screen):
    return "display_" + screen["id"]


def display_assignments(inventory):
    screens = sorted(inventory["displays"], key=lambda s: s["usable"]["width"] * s["usable"]["height"], reverse=True)
    if not screens:
        raise ValueError("No usable display is connected. Connect or wake a display, then scan again.")
    preferences = inventory.get("display_preferences", {})
    known = {s["id"]: s for s in screens}
    work = known.get(preferences.get("work"), screens[0])
    others = [s for s in screens if s["id"] != work["id"]]
    chat_default = next((s for s in others if s["built_in"]), (others or [work])[-1])
    chat = known.get(preferences.get("chat"), chat_default)
    reference_default = next((s for s in others if s["id"] != chat["id"]), chat)
    return {"work": work, "chat": chat, "references": known.get(preferences.get("references"), reference_default)}


def available_roles(inventory):
    return (*WINDOW_EFFECTS, *(screen_key(s) for s in inventory["displays"]))


def screen_for_window(window, screens):
    b = window["bounds"]
    return max(screens, key=lambda s: max(0, min(b["x"] + b["width"], s["usable"]["x"] + s["usable"]["width"]) - max(b["x"], s["usable"]["x"])) * max(0, min(b["y"] + b["height"], s["usable"]["y"] + s["usable"]["height"]) - max(b["y"], s["usable"]["y"])))


def validate_decisions(windows, decisions, roles):
    if not isinstance(decisions, list) or len(decisions) != len(windows):
        raise ValueError("The model must return one assignment per window. Preview again.")
    ids = {w["id"] for w in windows}
    allowed = set(roles)
    seen = set()
    for d in decisions:
        if (not isinstance(d, dict) or set(d) != {"id", "role"}
                or d["id"] not in ids or d["id"] in seen or d["role"] not in allowed):
            raise ValueError("Invalid or duplicate model assignment. No changes were made.")
        seen.add(d["id"])
    return decisions


def model_state(inventory, intent):
    return {"intent": intent,
            "displays": [{k: s[k] for k in ("id", "name", "built_in", "usable")}
                         for s in inventory["displays"]],
            "windows": [{**{k: w.get(k) for k in ("id", "app_name", "title", "is_focused")},
                         "application_kind": "terminal" if w["app_name"] in TERMINAL_APPS else "browser" if w["app_name"] in BROWSER_APPS else "other"}
                        for w in eligible_windows(inventory)]}


def tile_frames(count, usable):
    if not count:
        return []
    gap = PANE_GAP
    if count == 2:
        if usable["width"] >= usable["height"]:
            width = (usable["width"] - 3 * gap) / 2
            return [{"x": round(usable["x"] + gap + i * (width + gap)), "y": round(usable["y"] + gap), "width": round(width), "height": round(usable["height"] - 2 * gap)} for i in range(2)]
        height = (usable["height"] - 3 * gap) / 2
        return [{"x": round(usable["x"] + gap), "y": round(usable["y"] + gap + i * (height + gap)), "width": round(usable["width"] - 2 * gap), "height": round(height)} for i in range(2)]
    columns = min(range(1, count + 1), key=lambda c:
        abs(math.log((usable["width"] / c) / (usable["height"] / math.ceil(count / c)) / 0.65))
        + (c * math.ceil(count / c) - count) * .1)
    rows = math.ceil(count / columns)
    height = (usable["height"] - gap * (rows + 1)) / rows
    frames, remaining = [], count
    for row in range(rows):
        in_row = math.ceil(remaining / (rows - row))
        width = (usable["width"] - gap * (in_row + 1)) / in_row
        for col in range(in_row):
            frames.append({"x": round(usable["x"] + gap + col * (width + gap)),
                           "y": round(usable["y"] + gap + row * (height + gap)),
                           "width": round(width), "height": round(height)})
        remaining -= in_row
    return frames


def frames_overlap(a, b):
    return (min(a["x"] + a["width"], b["x"] + b["width"]) > max(a["x"], b["x"]) + 1
            and min(a["y"] + a["height"], b["y"] + b["height"]) > max(a["y"], b["y"]) + 1)


def fits_tile(actual, target, tolerance=12):
    return (abs(actual["x"] - target["x"]) <= tolerance
            and abs(actual["y"] - target["y"]) <= tolerance
            and abs(actual["width"] - target["width"]) <= tolerance
            and abs(actual["height"] - target["height"]) <= tolerance)


def window_minimum(window):
    limits = {k: window["bounds"][k] for k in ("width", "height")} if window.get("resizable") is False else window.get("min_size", {"width": 500, "height": 320})
    if any(type(limits.get(k)) not in (int, float) or not math.isfinite(limits[k]) or limits[k] <= 0 for k in ("width", "height")):
        raise ValueError("Window minimum sizes must be finite and positive.")
    return limits


def constrained_tiles(windows, usable):
    """Try only row counts that can physically fit readable panes.

    Width prefix sums reject impossible rows before allocating frames. Search
    depends on screen capacity, rather than the total number of open windows.
    """
    if not windows:
        return []
    gap, choices = PANE_GAP, []
    minimums = [window_minimum(w) for w in windows]
    max_rows = max(0, min(len(windows), math.floor((usable["height"] - gap) / (min(m["height"] for m in minimums) + gap))))
    max_columns = max(0, math.floor((usable["width"] - gap) / (min(m["width"] for m in minimums) + gap)))
    if not max_columns or len(windows) > max_rows * max_columns:
        return None
    prefix_widths = [0]
    for m in minimums:
        prefix_widths.append(prefix_widths[-1] + m["width"])
    tall = all(preferred_aspect(w) < 1 for w in windows)
    for rows in range(math.ceil(len(windows) / max_columns), max_rows + 1):
        groups, remaining, offset = [], len(windows), 0
        for row in range(rows):
            size = math.ceil(remaining / (rows - row))
            groups.append((offset, offset + size))
            offset += size
            remaining -= size
        if any(prefix_widths[b] - prefix_widths[a] + gap * (b - a + 1) > usable["width"] for a, b in groups):
            continue
        heights = [max(minimums[i]["height"] for i in range(a, b)) for a, b in groups]
        slack_y = usable["height"] - gap * (rows + 1) - sum(heights)
        if slack_y < 0:
            continue
        frames, y = [], usable["y"] + gap
        for (a, b), minimum_height in zip(groups, heights):
            slack_x = usable["width"] - gap * (b - a + 1) - (prefix_widths[b] - prefix_widths[a])
            height, x = minimum_height + slack_y / rows, usable["x"] + gap
            for i in range(a, b):
                width = minimums[i]["width"] + slack_x / (b - a)
                frame = {"x": round(x), "y": round(y), "width": math.floor(width), "height": math.floor(height)}
                if windows[i].get("resizable") is False:
                    frame.update(width=windows[i]["bounds"]["width"], height=windows[i]["bounds"]["height"])
                frames.append(frame)
                x += width + gap
            y += height + gap
        if tall:
            return frames
        score = sum(abs(math.log(f["width"] / f["height"] / preferred_aspect(w))) for w, f in zip(windows, frames))
        choices.append((score, frames))
    return min(choices, key=lambda item: item[0])[1] if choices else None


def snap_frame(zone, usable):
    frame = tile_frames(1, usable)[0]
    if zone in ("left", "right"):
        frame["width"] = math.floor((usable["width"] - 3 * PANE_GAP) / 2)
        if zone == "right":
            frame["x"] = usable["x"] + usable["width"] - PANE_GAP - frame["width"]
    elif zone in ("top", "bottom"):
        frame["height"] = math.floor((usable["height"] - 3 * PANE_GAP) / 2)
        if zone == "bottom":
            frame["y"] = usable["y"] + usable["height"] - PANE_GAP - frame["height"]
    return frame


def free_regions(usable, fixed, minimum=None):
    minimum = minimum or {"width": 0, "height": 0}
    regions = [usable]
    for obstacle in fixed:
        remaining = []
        for r in regions:
            left, right = max(r["x"], obstacle["x"]), min(r["x"] + r["width"], obstacle["x"] + obstacle["width"])
            top, bottom = max(r["y"], obstacle["y"]), min(r["y"] + r["height"], obstacle["y"] + obstacle["height"])
            if right <= left or bottom <= top:
                remaining.append(r)
                continue
            candidates = [(r["x"], r["y"], left - r["x"], r["height"]),
                          (right, r["y"], r["x"] + r["width"] - right, r["height"]),
                          (left, r["y"], right - left, top - r["y"]),
                          (left, bottom, right - left, r["y"] + r["height"] - bottom)]
            remaining.extend(dict(zip(("x", "y", "width", "height"), values)) for values in candidates if values[2] > 0 and values[3] > 0)
        regions = [r for r in remaining if r["width"] >= minimum["width"] + 2 * PANE_GAP and r["height"] >= minimum["height"] + 2 * PANE_GAP]
        if not regions:
            break
    return sorted(regions, key=lambda r: (r["height"], r["width"] * r["height"]), reverse=True)


def pack_regions(windows, regions):
    pending, packed = list(windows), []
    limits = {w["id"]: window_minimum(w) for w in windows}
    for region in regions:
        compatible = [w for w in pending if all(limits[w["id"]][axis] + 2 * PANE_GAP <= region[axis] for axis in ("width", "height"))]
        if not compatible:
            continue
        minimum_width = min(limits[w["id"]]["width"] for w in compatible)
        minimum_height = min(limits[w["id"]]["height"] for w in compatible)
        capacity = math.floor((region["width"] - PANE_GAP) / (minimum_width + PANE_GAP)) * math.floor((region["height"] - PANE_GAP) / (minimum_height + PANE_GAP))
        for count in range(min(len(compatible), capacity), 0, -1):
            ordered = companion_order(compatible[:count])
            frames = constrained_tiles(ordered, region)
            if frames is not None:
                packed.extend(zip(ordered, frames))
                assigned = {w["id"] for w in ordered}
                pending = [w for w in pending if w["id"] not in assigned]
                break
    return packed, pending


def build_actions(inventory, decisions):
    windows = eligible_windows(inventory)
    validate_decisions(windows, decisions, available_roles(inventory))
    roles = {d["id"]: d["role"] for d in decisions}
    screens = inventory["displays"]
    preferred = display_assignments(inventory)
    actions = []
    groups = {screen_key(s): [] for s in screens}
    screens_by_role = {screen_key(s): s for s in screens}
    fixed = [w["bounds"] for w in windows if roles[w["id"]] == "unchanged"]
    for w in windows:
        role = roles[w["id"]]
        if w["is_focused"] and role in ("close", "minimize"):
            role = screen_key(preferred["work"])
        if role in groups:
            groups[role].append(w)
        elif role != "unchanged":
            actions.append({"kind": role, "window": w})
    for role, group in groups.items():
        if not group:
            continue
        group = [w for w in group if w["is_focused"]] + [w for w in group if not w["is_focused"]]
        screen = screens_by_role[role]
        minimum = {axis: min(window_minimum(w)[axis] for w in group) for axis in ("width", "height")}
        packed, overflow_windows = pack_regions(group, free_regions(screen["usable"], fixed, minimum))
        for overflow in overflow_windows:
            if overflow["is_focused"]:
                raise ValueError("The focused window cannot fit this display. Choose a larger display.")
            actions.append({"kind": "minimize", "window": overflow, "reason": "No remaining pane fits this window's minimum size."})
        for w, target in packed:
            actions.append({"kind": "move", "window": w, "target": target,
                            "display": screen["id"], "display_name": screen["name"]})
    # Remove reviewed clutter before laying out the active windows.
    return sorted(actions, key=lambda a: a["kind"] == "move")


def companion_order(windows):
    """Keep a work browser and terminal adjacent without changing destinations."""
    browsers = [w for w in windows if w["app_name"] in BROWSER_APPS]
    terminals = [w for w in windows if w["app_name"] in TERMINAL_APPS]
    if not browsers or not terminals:
        return windows
    pair_ids = {w["id"] for w in browsers + terminals}
    terminal_ids = {w["id"] for w in terminals}
    first = next((w for w in windows if w.get("is_focused") and w["id"] in pair_ids), terminals[0])
    partner = browsers[0] if first["id"] in terminal_ids else terminals[0]
    chosen = {first["id"], partner["id"]}
    return [first, partner, *(w for w in windows if w["id"] not in chosen)]


def layout_report(observed):
    windows = eligible_windows(observed)
    analysis = analyze_overlaps([w["bounds"] for w in windows])
    overlaps = [{"a": windows[i]["id"], "b": windows[j]["id"], "apps": [windows[i]["app_name"], windows[j]["app_name"]]} for i, j in analysis.examples]
    return {"visible_windows": len(windows), "windows": windows, "displays": observed.get("displays", []), "overlap_count": analysis.count, "overlaps": overlaps,
            "overlaps_truncated": analysis.count > len(overlaps),
            "coverage": observed["coverage"], "excluded_apps": ["Desk Tidy", "Google Chrome for Testing"]}
