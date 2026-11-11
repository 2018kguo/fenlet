"""Desktop decisions. No GUI, network, or filesystem effects in this module."""
import math
from collections import Counter, defaultdict
from .overlap import analyze_overlaps

WINDOW_EFFECTS = ("close", "minimize", "unchanged")
PANE_GAP = 6
VIDEO_APPS = {"TV", "QuickTime Player", "VLC", "IINA", "mpv"}
BROWSER_APPS = {"Safari", "Google Chrome", "Firefox", "Arc", "Brave Browser", "Microsoft Edge", "Zen", "Orion"}
TERMINAL_APPS = {"Terminal", "Ghostty", "Rex", "Rex Beta", "iTerm2", "Alacritty", "WezTerm", "Warp", "Rio"}
UTILITY_APPS = {"System Settings", "System Preferences", "Keychain Access", "Activity Monitor"}
COMMUNICATION_APPS = {"Slack", "Messages", "Mail", "Discord", "Microsoft Teams", "WhatsApp"}


def window_usage(window):
    app = window["app_name"]
    if app in UTILITY_APPS or window.get("bundle_id") in ("com.apple.systempreferences", "com.apple.keychainaccess", "com.apple.ActivityMonitor"):
        return "utility"
    title = window.get("title", "").casefold()
    if app in COMMUNICATION_APPS or app in BROWSER_APPS and (title.endswith((" - slack", " - discord")) or any(hint in title for hint in (" - slack - ", " | slack", "microsoft teams", " - discord"))):
        return "communication"
    if app == "Granola" or app in TERMINAL_APPS and title.split()[:1] == ["caffeinate"]:
        return "background"
    return "terminal" if app in TERMINAL_APPS else "browser" if app in BROWSER_APPS else "other"


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


def eligible_windows(inventory):
    # Test browsers and exact browser-automation prompts belong to an ongoing
    # automation run. They are excluded during planning and verification alike.
    return [w for w in inventory["windows"] if not w.get("minimized") and not w.get("hidden") and not w.get("protected") and w.get("accessible", True)
            and not (w["app_name"] == "Google Chrome" and w.get("title", "").casefold() == "allow remote debugging?")
            and w["app_name"] not in ("Fenlet", "Google Chrome for Testing")]




def same_bounds(a, b, tolerance=3):
    return all(abs(a[k] - b[k]) <= tolerance for k in ("x", "y", "width", "height"))


def same_space_state(a, b):
    return all(a.get(k) == b.get(k) for k in ("space_ids", "fullscreen") if k in a or k in b)


def valid_bounds(b):
    return (isinstance(b, dict) and set(b) == {"x", "y", "width", "height"}
            and all(type(v) in (int, float) and math.isfinite(v) for v in b.values())
            and b["width"] > 0 and b["height"] > 0)


def screen_key(screen):
    return "display_" + screen["id"]


def display_assignments(inventory):
    screens = inventory["displays"]
    physical = {s["id"]: physical_size(s) for s in screens}
    if screens and all(physical.values()):
        screens = sorted(screens, key=lambda s: physical[s["id"]]["width"] * physical[s["id"]]["height"], reverse=True)
    else:
        screens = sorted(screens, key=lambda s: s["usable"]["width"] * s["usable"]["height"], reverse=True)
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


def browser_window_context(windows, report, port):
    """Only homogeneous, count-matched bounds groups can prove empty windows.

    CDP and WindowServer use different IDs. Coincident windows cannot be paired
    individually. Useful tabs prevent Close; attached targets and count mismatches
    protect the group from all changes. Raw URLs and target IDs stay in the probe.
    """
    native_groups, browser_groups = defaultdict(list), defaultdict(list)
    def key(bounds):
        return tuple(round(bounds[k]) for k in ("x", "y", "width", "height"))
    for w in windows:
        native_groups[key(w["bounds"])].append(w)
    reports = report.get("windows", []) if isinstance(report, dict) and report.get("complete") is True else []
    if not isinstance(reports, list) or len(reports) > 512: reports = []
    for item in reports:
        if not isinstance(item, dict): browser_groups.clear(); break
        b = item.get("bounds", {})
        if not isinstance(b, dict): browser_groups.clear(); break
        rect = {k: b.get(v) for k, v in zip(("x", "y", "width", "height"), ("left", "top", "width", "height"))}
        if not valid_bounds(rect) or b.get("windowState") != "normal": continue
        browser_groups[key(rect)].append(item)
    contexts = {}
    for position, group in native_groups.items():
        reports = browser_groups[position]
        inactive = len(group) == len(reports) and all(type(r.get("empty")) is bool and r.get("attached") is False and type(r.get("tabs")) is int and r["tabs"] > 0 for r in reports)
        empty = inactive and all(r["empty"] for r in reports)
        for w in group:
            contexts[w["id"]] = {"kind": "empty_unattached" if empty else "background_unattached" if inactive else "protected", "port": port}
    return contexts


def clutter_hints(inventory):
    windows = eligible_windows(inventory)
    folders = Counter(w.get("title", "") for w in windows if w["app_name"] == "Finder")
    hints = {}
    for w in windows:
        if w.get("is_focused"): continue
        title, usage = w.get("title", ""), window_usage(w)
        if w.get("browser_context", {}).get("kind") == "empty_unattached":
            hints[w["id"]] = {"effect": "close", "reason": "Every tab is empty and no automation client is attached."}
        elif w.get("browser_context", {}).get("kind") == "background_unattached":
            hints[w["id"]] = {"effect": "minimize", "reason": "Preserve useful browser tabs while no automation client is attached."}
        elif w["app_name"] == "Finder" and title == "Desktop" and folders[title] > 1:
            hints[w["id"]] = {"effect": "close", "reason": "Duplicate Desktop folder window."}
        elif usage in ("background", "utility"):
            hints[w["id"]] = {"effect": "minimize", "reason": "Keep this background tool running."}
    return hints


def guard_cleanup_decisions(inventory, decisions):
    """A visible tab title cannot authorize closing every tab in its window."""
    known = {w["id"]: w for w in eligible_windows(inventory)}
    guarded = []
    for d in decisions:
        w = known.get(d["id"])
        if w and d["role"] == "close" and (w["app_name"] in TERMINAL_APPS or window_usage(w) == "background" or
            w["app_name"] in BROWSER_APPS and w.get("browser_context", {}).get("kind") != "empty_unattached"):
            guarded.append({**d, "role": "minimize"})
        else: guarded.append(d)
    return guarded


def local_decisions(inventory):
    """Offline roles with evidence-backed closes and useful background tools."""
    displays = display_assignments(inventory)
    hints = clutter_hints(inventory)
    result = []
    for w in eligible_windows(inventory):
        usage = window_usage(w)
        purpose = "chat" if usage == "communication" else "references" if w["app_name"] in {"Notes", "Preview", "Books", "Dictionary"} else "work"
        role = hints[w["id"]]["effect"] if w["id"] in hints else screen_key(displays["work" if w.get("is_focused") else purpose])
        result.append({"id": w["id"], "role": role})
    return result


def reconcile_actions(previous, current):
    """Keep reviewed choices while respecting windows moved outside the draft."""
    known = {w["id"]: w for w in eligible_windows(current)}
    screens = {s["id"]: s for s in current["displays"]}
    defaults = {d["id"]: d["role"] for d in local_decisions(current)}
    kept, roles, order = [], {id: "unchanged" for id in known}, []
    for action in previous["actions"]:
        old = action["window"]; live = known.get(old["id"])
        if not live or live["pid"] != old["pid"] or live.get("process_instance") != old.get("process_instance"):
            continue
        if not same_bounds(live["bounds"], old["bounds"], 2) or not same_space_state(live, old):
            continue  # Manual takeover: leave this window where it was moved.
        if action["kind"] in ("minimize", "close") and (live.get("is_focused") or action["kind"] == "close" and live.get("title") != old.get("title")):
            continue
        role = "display_" + action["display"] if action["kind"] == "move" and action["display"] in screens else defaults[live["id"]] if action["kind"] == "move" else action["kind"]
        roles[live["id"]] = role
        kept.append({**action, "window": live})
        if action["kind"] == "move": order.append(live["id"])
    fixed = [w for w in current["windows"] if w.get("protected") and not w.get("minimized") and not w.get("hidden")
             or w["id"] in known and roles[w["id"]] == "unchanged"]
    valid = screens == {s["id"]: s for s in previous["inventory"]["displays"]}
    targets = {}
    for a in kept:
        if a["kind"] != "move": continue
        screen = screens.get(a["display"]); b = a["target"]
        if screen is None:
            valid = False; continue
        u = screen["usable"]
        valid &= (u["x"] <= b["x"] and u["y"] <= b["y"] and b["x"]+b["width"] <= u["x"]+u["width"]+1
                  and b["y"]+b["height"] <= u["y"]+u["height"]+1
                  and a.get("target_space") == (screen.get("gather_space") if current.get("all_spaces") else None))
        targets.setdefault(a.get("target_space"), []).append(b)
    obstacles = {}
    for w in fixed:
        for space in (w.get("space_ids") or list(targets)) if current.get("all_spaces") else [None]:
            obstacles.setdefault(space, []).append(w["bounds"])
    # Compare exact counts rather than materializing target/obstacle pairs.
    for space, frames in targets.items():
        stationary = obstacles.get(space, [])
        valid &= analyze_overlaps(frames + stationary, 0).count == analyze_overlaps(stationary, 0).count
    return kept if valid else build_actions(current, [{"id": id, "role": role} for id, role in roles.items()], layout_order=order)


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
    hints = clutter_hints(inventory)
    return {"intent": intent, "all_spaces": inventory.get("all_spaces", False),
            "displays": [{k: s[k] for k in ("id", "name", "built_in", "usable")}
                         for s in inventory["displays"]],
            "windows": [{**{k: w.get(k) for k in ("id", "app_name", "title", "is_focused")},
                         "application_kind": window_usage(w), "cleanup_hint": hints.get(w["id"])}
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


def layout_minimum(window, usable):
    minimum = dict(window_minimum(window))
    if window.get("resizable") is not False and preferred_aspect(window) < 1:
        # A native minimum is not a readable text pane. Short displays keep
        # full-height work columns; portrait displays can still stack panes.
        minimum["height"] = max(minimum["height"], min(600, usable["height"] - 2 * PANE_GAP))
    return minimum


def physical_size(screen):
    """OS-reported, orientation-aligned millimeters; unknown is never inches."""
    if not screen or screen.get("physical_size_source") == "estimated":
        return None
    size, bounds = screen.get("physical_size_mm"), screen.get("bounds", screen.get("usable"))
    if not size or not bounds or any(type(size.get(k)) not in (int, float) or not math.isfinite(size[k]) or size[k] <= 0 for k in ("width", "height")):
        return None
    width, height = size["width"], size["height"]
    aspect = bounds["width"] / bounds["height"]
    if abs(math.log(height / width / aspect)) < abs(math.log(width / height / aspect)):
        width, height = height, width
    return {"width": width, "height": height}


def _spread(minimums, total):
    """Equal shares subject to lower bounds, in O(K log K)."""
    available = total - PANE_GAP * (len(minimums) + 1)
    if available < sum(minimums):
        return None
    result = [0] * len(minimums)
    ordered = sorted(enumerate(minimums), key=lambda pair: pair[1], reverse=True)
    for offset, (index, limit) in enumerate(ordered):
        share = available / (len(minimums) - offset)
        if limit <= share:
            for i, _ in ordered[offset:]:
                result[i] = share
            break
        result[index] = limit
        available -= limit
    return result


def _strip_tiles(windows, usable, strips, vertical):
    """Partition rows or columns; no empty grid cells or overlapping frames."""
    base, extra = divmod(len(windows), strips)
    counts = [base + (i >= strips - extra if vertical else i < extra) for i in range(strips)]
    groups, offset = [], 0
    for count in counts:
        groups.append(list(range(offset, offset + count))); offset += count
    outer, inner = ("width", "height") if vertical else ("height", "width")
    mins = [layout_minimum(w, usable) for w in windows]
    outer_sizes = _spread([max(mins[i][outer] for i in g) for g in groups], usable[outer])
    if outer_sizes is None:
        return None
    frames = [None] * len(windows)
    position = usable["x" if vertical else "y"] + PANE_GAP
    for group, outer_size in zip(groups, outer_sizes):
        sizes = _spread([mins[i][inner] for i in group], usable[inner])
        if sizes is None:
            return None
        cursor = usable["y" if vertical else "x"] + PANE_GAP
        for index, size in zip(group, sizes):
            x, y, width, height = (position, cursor, outer_size, size) if vertical else (cursor, position, size, outer_size)
            frame = {"x": round(x), "y": round(y), "width": round(x + width) - round(x), "height": round(y + height) - round(y)}
            if windows[index].get("resizable") is False:
                frame.update(width=windows[index]["bounds"]["width"], height=windows[index]["bounds"]["height"])
            frames[index] = frame
            cursor += size + PANE_GAP
        position += outer_size + PANE_GAP
    return frames


def _physical_layout_score(windows, frames, screen, size):
    bounds = screen.get("bounds", screen["usable"])
    inches_per_point = {k: size[k] / 25.4 / bounds[k] for k in ("width", "height")}
    score = 0
    for window, frame in zip(windows, frames):
        width, height = (frame[k] * inches_per_point[k] for k in ("width", "height"))
        if preferred_aspect(window) > 1:
            score += abs(math.log(width / height / preferred_aspect(window)))
        else:
            narrow = max(0, (6 - width) / 6)
            score += 9 * narrow + 30 * narrow * narrow
            score += .3 * max(0, (width - 8) / 8) + .2 * abs(math.log(width / 7))
            score += .5 * max(0, width / height - .85) + .05 * max(0, height / width - 3)
    return score / len(windows)


def constrained_tiles(windows, usable, screen=None):
    """Search strip counts bounded by screen capacity, not subsets of N windows.

    Known physical sizes prefer 6–8 inch reading widths (7 ideal). Portrait
    screens may stack panes; native minimums and finite screen area still win.
    Unknown size keeps the point-based tall-column preference.
    """
    if not windows:
        return []
    minimums = [layout_minimum(w, usable) for w in windows]
    max_rows = max(0, min(len(windows), math.floor((usable["height"] - PANE_GAP) / (min(m["height"] for m in minimums) + PANE_GAP))))
    max_columns = max(0, min(len(windows), math.floor((usable["width"] - PANE_GAP) / (min(m["width"] for m in minimums) + PANE_GAP))))
    if not max_columns or not max_rows or len(windows) > max_rows * max_columns:
        return None
    size, choices = physical_size(screen), []
    axes = [(True, math.ceil(len(windows) / max_rows), max_columns)] if size else []
    axes.append((False, math.ceil(len(windows) / max_columns), max_rows))
    tall = all(preferred_aspect(w) < 1 for w in windows)
    for vertical, first, last in axes:
        for strips in range(first, last + 1):
            frames = _strip_tiles(windows, usable, strips, vertical)
            if frames is None:
                continue
            if size:
                score = _physical_layout_score(windows, frames, screen, size)
            elif tall:
                return frames
            else:
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


def pack_regions(windows, regions, screen=None, order=None):
    pending, packed = list(windows), []
    for region in regions:
        limits = {w["id"]: layout_minimum(w, screen["usable"] if screen else region) for w in pending}
        compatible = [w for w in pending if all(limits[w["id"]][axis] + 2 * PANE_GAP <= region[axis] for axis in ("width", "height"))]
        if not compatible:
            continue
        compatible = sorted(compatible, key=lambda w: order.get(w["id"], len(order))) if order is not None else companion_order(compatible)
        minimum_width = min(limits[w["id"]]["width"] for w in compatible)
        minimum_height = min(limits[w["id"]]["height"] for w in compatible)
        capacity = math.floor((region["width"] - PANE_GAP) / (minimum_width + PANE_GAP)) * math.floor((region["height"] - PANE_GAP) / (minimum_height + PANE_GAP))
        for count in range(min(len(compatible), capacity), 0, -1):
            ordered = compatible[:count]
            frames = constrained_tiles(ordered, region, screen)
            if frames is not None:
                packed.extend(zip(ordered, frames))
                assigned = {w["id"] for w in ordered}
                pending = [w for w in pending if w["id"] not in assigned]
                break
    return packed, pending


def preserve_fitting_placements(packed):
    """Keep occupants in existing valid slots when opening a new draft.

    Slot origins use a 32-point spatial index. The planner's non-overlapping
    tiles and 6-point gaps bound bucket occupancy; there is no N-by-N scan.
    A changed screen, overlap, or minimum size falls back to the new partition.
    """
    buckets = {}
    for index, (_, target) in enumerate(packed):
        key = (math.floor(target["x"] / 32), math.floor(target["y"] / 32))
        buckets.setdefault(key, []).append(index)
    assigned, result = set(), []
    for window, _ in packed:
        bounds, minimum = window["bounds"], window_minimum(window)
        bx, by = math.floor(bounds["x"] / 32), math.floor(bounds["y"] / 32)
        matches = [index for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   for index in buckets.get((bx + dx, by + dy), [])
                   if fits_tile(bounds, packed[index][1])
                   and all(minimum[k] <= packed[index][1][k] for k in ("width", "height"))]
        if len(matches) != 1 or matches[0] in assigned:
            return packed
        index = matches[0]
        assigned.add(index); result.append((window, packed[index][1]))
    return result


def build_actions(inventory, decisions, layout_order=None):
    windows = eligible_windows(inventory)
    order = {id: i for i, id in enumerate(layout_order)} if layout_order is not None else None
    validate_decisions(windows, decisions, available_roles(inventory))
    roles = {d["id"]: d["role"] for d in decisions}
    screens = inventory["displays"]
    preferred = display_assignments(inventory)
    actions = []
    groups = {screen_key(s): [] for s in screens}
    screens_by_role = {screen_key(s): s for s in screens}
    fixed_windows = [w for w in inventory["windows"] if (w.get("protected") and not w.get("minimized") and not w.get("hidden"))
                     or w["id"] in roles and roles[w["id"]] == "unchanged"]
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
        fixed = [w["bounds"] for w in fixed_windows if not inventory.get("all_spaces")
                 or not w.get("space_ids") or screen.get("gather_space") in w["space_ids"]]
        packed, overflow_windows = pack_regions(group, free_regions(screen["usable"], fixed, minimum), screen, order)
        if order is None:
            packed = preserve_fitting_placements(packed)
        for overflow in overflow_windows:
            if overflow["is_focused"]:
                raise ValueError("The focused window cannot fit this display. Choose a larger display.")
            actions.append({"kind": "minimize", "window": overflow, "reason": "Kept in the background so visible panes remain readable."})
        for w, target in packed:
            gathering = inventory.get("all_spaces", False)
            if gathering and not screen.get("gather_space"):
                raise ValueError("This display has no regular destination Space. Choose another display.")
            actions.append({"kind": "move", "window": w, "target": target,
                            "display": screen["id"], "display_name": screen["name"],
                            **({"target_space": screen["gather_space"]} if gathering else {})})
    # Remove reviewed clutter before laying out the active windows.
    hints = clutter_hints(inventory)
    for action in actions:
        hint = hints.get(action["window"]["id"])
        if hint and action["kind"] == hint["effect"]: action.setdefault("reason", hint["reason"])
    return sorted(actions, key=lambda a: a["kind"] == "move")


def companion_order(windows):
    """Keep a work browser and terminal adjacent without changing destinations."""
    focused = [w for w in windows if w.get("is_focused")]
    windows = focused + sorted([w for w in windows if not w.get("is_focused")], key=lambda w: window_usage(w) in ("utility", "communication"))
    browsers = [w for w in windows if window_usage(w) == "browser"]
    terminals = [w for w in windows if window_usage(w) == "terminal"]
    if not browsers or not terminals:
        return windows
    pair_ids = {w["id"] for w in browsers + terminals}
    terminal_ids = {w["id"] for w in terminals}
    first = next((w for w in windows if w.get("is_focused") and w["id"] in pair_ids), terminals[0])
    partner = browsers[0] if first["id"] in terminal_ids else terminals[0]
    chosen = {w["id"] for w in focused} | {first["id"], partner["id"]}
    return focused + [w for w in (first, partner) if w["id"] not in {f["id"] for f in focused}] + [w for w in windows if w["id"] not in chosen]


def revise_actions(inventory, actions, operation, window_id, target=None):
    """Edit a draft only. Swaps retain slots; display moves reuse the planner."""
    known = {w["id"]: w for w in eligible_windows(inventory)}
    if window_id not in known:
        raise ValueError("This window is no longer in the draft. Refresh the preview.")
    if operation == "swap":
        indices = {a["window"]["id"]: i for i, a in enumerate(actions)}
        if window_id == target:
            return list(actions)
        if window_id not in indices or target not in indices:
            raise ValueError("Drop onto a window pane or a display.")
        left, right = actions[indices[window_id]], actions[indices[target]]
        if left["kind"] != "move" or right["kind"] != "move":
            raise ValueError("Drop background windows onto a display to restore them.")
        for slot, occupant in ((left, right["window"]), (right, left["window"])):
            minimum = window_minimum(occupant)
            if any(slot["target"][axis] < minimum[axis] for axis in ("width", "height")):
                raise ValueError(f"{occupant['app_name']} needs a larger pane. Drop it onto the display to reflow.")
        result = [dict(a) for a in actions]
        result[indices[window_id]]["window"] = right["window"]
        result[indices[target]]["window"] = left["window"]
        return result
    if operation not in ("move", "minimize", "close"):
        raise ValueError("Unknown layout edit.")
    if operation in ("minimize", "close") and known[window_id].get("is_focused"):
        raise ValueError("Keep the current work window visible.")
    roles = {id: "unchanged" for id in known}
    for action in actions:
        roles[action["window"]["id"]] = "display_" + action["display"] if action["kind"] == "move" else action["kind"]
    if operation == "move":
        if target not in {s["id"] for s in inventory["displays"]}:
            raise ValueError("That display is no longer connected. Refresh the preview.")
        roles[window_id] = "display_" + target
    else:
        roles[window_id] = operation
    order = [a["window"]["id"] for a in actions if a["kind"] == "move"]
    ordered_ids = set(order)
    order.extend(id for id in known if id not in ordered_ids)
    result = build_actions(inventory, [{"id": id, "role": role} for id, role in roles.items()], layout_order=order)
    if operation == "move" and not any(a["window"]["id"] == window_id and a["kind"] == "move" for a in result):
        raise ValueError("This window's minimum size will not fit there. Make room or choose another display.")
    return result


def layout_report(observed):
    windows = eligible_windows(observed)
    analysis = analyze_overlaps([w["bounds"] for w in windows])
    overlaps = [{"a": windows[i]["id"], "b": windows[j]["id"], "apps": [windows[i]["app_name"], windows[j]["app_name"]]} for i, j in analysis.examples]
    return {"visible_windows": len(windows), "windows": windows, "displays": observed.get("displays", []), "overlap_count": analysis.count, "overlaps": overlaps,
            "overlaps_truncated": analysis.count > len(overlaps),
            "coverage": observed["coverage"], "excluded_apps": ["Fenlet", "Google Chrome for Testing"]}
