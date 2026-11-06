import AppKit
import Foundation
import Darwin
import Security

// Keep the installed OS/Keychain identity stable across the Fenlet rename.

// Cocoa must enter multithreaded mode before AX work runs on dispatch workers.
// A dispatch queue alone does not establish this AppKit runtime condition.
if !Thread.isMultiThreaded() {
    let bootstrap = Thread {}
    bootstrap.start()
    while !bootstrap.isFinished { Thread.sleep(forTimeInterval: 0.001) }
}

struct WindowRef: Decodable {
    let id: String
    let pid: Int32
    let process_instance: String
    let title: String?
    let title_source: String?
    let bounds: WindowFrame?
    let minimized: Bool?
}
struct WindowFrame: Codable, Equatable, Sendable {
    let x, y, width, height: Double
}
struct WindowAction: Decodable {
    let kind: String
    let window: WindowRef
    let target: WindowFrame?
}

func axValue(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
    var value: CFTypeRef?
    for timeout: Float in [0.25, 0.7, 1.0] {
        AXUIElementSetMessagingTimeout(element, timeout)
        let status = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        if status == .success { return value }
        if status != .cannotComplete { return nil }
    }
    return nil
}

enum WindowLookup { case found(AXUIElement), absent, unavailable(String) }

func focusedApplication() -> (AXUIElement, Int32)? {
    guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
    return (AXUIElementCreateApplication(app.processIdentifier), app.processIdentifier)
}
func currentFocus() -> [String: Any] {
    guard let (element, pid) = focusedApplication() else { return ["pid": Int32(0), "window_id": ""] }
    var number: CGWindowID = 0
    var raw: CFTypeRef?
    // Focus observation cannot hold up the layout while a foreground app is busy.
    AXUIElementSetMessagingTimeout(element, 0.08)
    let status = AXUIElementCopyAttributeValue(element, kAXFocusedWindowAttribute as CFString, &raw)
    if status == .success, let raw = raw, CFGetTypeID(raw) == AXUIElementGetTypeID() {
        _ = _AXUIElementGetWindow((raw as! AXUIElement), &number)
    }
    return ["pid": pid, "window_id": number == 0 ? "" : "w-\(number)"]
}

enum WindowIndex {
    case complete([CGWindowID: AXUIElement]), partial([CGWindowID: AXUIElement]), unavailable(String), gone
}
func readWindowIndex(_ w: WindowRef) -> WindowIndex {
    guard processMatches(w) else { return .gone }
    let app = AXUIElementCreateApplication(w.pid)
    var rawWindows: CFArray?
    var status: AXError = .cannotComplete
    for timeout: Float in [0.25, 0.7, 1.0] {
        AXUIElementSetMessagingTimeout(app, timeout)
        var count: CFIndex = 0
        status = AXUIElementGetAttributeValueCount(app, kAXWindowsAttribute as CFString, &count)
        if status == .success, count == 0 { return .complete([:]) }
        if status == .success { status = AXUIElementCopyAttributeValues(app, kAXWindowsAttribute as CFString, 0, count, &rawWindows) }
        if status != .cannotComplete { break }
    }
    guard status == .success, let windows = rawWindows as? [AXUIElement] else { return .unavailable("AXWindows read failed: \(status.rawValue)") }
    var index: [CGWindowID: AXUIElement] = [:], complete = true
    for element in windows {
        var number: CGWindowID = 0
        if _AXUIElementGetWindow(element, &number) == .success {
            if index[number] == nil { index[number] = element }
        } else { complete = false }
    }
    return complete ? .complete(index) : .partial(index)
}
func indexedWindow(_ w: WindowRef, in collection: WindowIndex) -> WindowLookup {
    guard let number = UInt32(w.id.dropFirst(2)) else { return .unavailable("Invalid window ID.") }
    switch collection {
    case .complete(let index): return index[number].map { .found($0) } ?? .absent
    case .partial(let index): return index[number].map { .found($0) } ?? .unavailable("Accessibility window identity coverage was incomplete.")
    case .unavailable(let error): return .unavailable(error)
    case .gone: return .absent
    }
}

func windowFrame(_ element: AXUIElement) -> [String: Double]? {
    guard let p = axValue(element, kAXPositionAttribute), let s = axValue(element, kAXSizeAttribute),
          CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero, size = CGSize.zero
    guard AXValueGetValue(p as! AXValue, .cgPoint, &point), AXValueGetValue(s as! AXValue, .cgSize, &size) else { return nil }
    return ["x": point.x, "y": point.y, "width": size.width, "height": size.height]
}

func placeWindow(_ element: AXUIElement, _ frame: WindowFrame) {
    var point = CGPoint(x: frame.x, y: frame.y), size = CGSize(width: frame.width, height: frame.height)
    let position = AXValueCreate(.cgPoint, &point)!, dimensions = AXValueCreate(.cgSize, &size)!
    // Size, position, size handles screen clamping without waiting on exact
    // pixel sizes that terminals legitimately round to their character grid.
    AXUIElementSetAttributeValue(element, kAXSizeAttribute as CFString, dimensions)
    AXUIElementSetAttributeValue(element, kAXPositionAttribute as CFString, position)
    AXUIElementSetAttributeValue(element, kAXSizeAttribute as CFString, dimensions)
}

final class BatchResults: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [Int: [String: Any]] = [:]
    private var indexLoads = 0
    func noteIndexLoad() { lock.lock(); indexLoads += 1; lock.unlock() }
    func indexLoadCount() -> Int { lock.lock(); defer { lock.unlock() }; return indexLoads }
    func set(_ index: Int, _ value: [String: Any]) { lock.lock(); values[index] = value; lock.unlock() }
    func ordered(_ count: Int) -> [[String: Any]] { (0..<count).map { values[$0]! } }
}

struct DisplayCheck: Decodable, Equatable {
    let id: String
    let bounds, usable: WindowFrame
}
struct BatchRequest: Decodable {
    let actions: [WindowAction]
    let expected_displays: [DisplayCheck]?
}
struct CGRecord: Sendable {
    let pid: Int32
    let title: String?
    let frame: WindowFrame
    let onscreen: Bool
}
func cgRecord(_ entry: [String: Any]) -> CGRecord? {
    guard let pid = (entry[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value,
          let bounds = entry[kCGWindowBounds as String] as? NSDictionary,
          let b = CGRect(dictionaryRepresentation: bounds) else { return nil }
    return CGRecord(pid: pid, title: entry[kCGWindowName as String] as? String,
        frame: WindowFrame(x: b.minX, y: b.minY, width: b.width, height: b.height),
        onscreen: (entry[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue ?? false)
}
func cgRecords(_ entries: [[String: Any]]) -> [String: CGRecord] {
    var records: [String: CGRecord] = [:]
    for entry in entries {
        if let id = (entry[kCGWindowNumber as String] as? NSNumber)?.uint32Value, let record = cgRecord(entry) { records["w-\(id)"] = record }
    }
    return records
}
func frameDictionary(_ b: WindowFrame) -> [String: Double] {
    ["x": b.x, "y": b.y, "width": b.width, "height": b.height]
}
func processMatches(_ w: WindowRef) -> Bool {
    var info = proc_bsdinfo()
    return proc_pidinfo(w.pid, PROC_PIDTBSDINFO, 0, &info, Int32(MemoryLayout<proc_bsdinfo>.size)) == MemoryLayout<proc_bsdinfo>.size
        && w.process_instance == "macos-proc-v1:\(info.pbi_start_tvsec):\(info.pbi_start_tvusec)"
}
func sameFrame(_ a: WindowFrame, _ b: WindowFrame) -> Bool {
    abs(a.x - b.x) <= 2 && abs(a.y - b.y) <= 2 && abs(a.width - b.width) <= 2 && abs(a.height - b.height) <= 2
}
func occupiesPane(_ a: WindowFrame, _ b: WindowFrame) -> Bool {
    abs(a.x - b.x) <= 1 && abs(a.y - b.y) <= 1
        && a.width <= b.width + 1 && a.height <= b.height + 1
        && a.width >= b.width - 12 && a.height >= b.height - 12
}
func batchWindows(_ request: BatchRequest) {
    let started = Date(), actions = request.actions
    guard actions.count <= 512, Set(actions.map { $0.window.id }).count == actions.count, AXIsProcessTrusted() else {
        output(["ok": false, "error": "Accessibility access is required; batches require unique IDs and support up to 512 windows."]); return
    }
    if let expected = request.expected_displays {
        let actual = try! JSONDecoder().decode([DisplayCheck].self, from: JSONSerialization.data(withJSONObject: displays()))
        if Dictionary(uniqueKeysWithValues: actual.map { ($0.id, $0) }) != Dictionary(uniqueKeysWithValues: expected.map { ($0.id, $0) }) {
            output(["ok": false, "error": "Display arrangement changed. Make a fresh preview."]); return
        }
    }
    let focusBefore = currentFocus()
    let beforeEntries = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]] ?? []
    let before = cgRecords(beforeEntries)
    let results = BatchResults()
    let groups = Array(Dictionary(grouping: Array(actions.enumerated()), by: { $0.element.window.pid }).values)
    let voiceOver = NSWorkspace.shared.isVoiceOverEnabled
    let prepared = Date()
    DispatchQueue.concurrentPerform(iterations: groups.count) { groupIndex in
        let group = groups[groupIndex]
        let app = AXUIElementCreateApplication(group[0].element.window.pid)
        let adjusts = group.contains { item in
            let a = item.element
            return a.kind == "restore" || (a.kind == "move" && (before[a.window.id].map { b in a.target.map { !occupiesPane(b.frame, $0) } ?? true } ?? true))
        }
        let enhanced = adjusts && (axValue(app, "AXEnhancedUserInterface") as? NSNumber)?.boolValue == true
        if enhanced && !voiceOver { AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanFalse) }
        defer { if enhanced && !voiceOver { AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue) } }
        var windowIndex: WindowIndex?
        for (index, action) in group {
            let w = action.window
            guard processMatches(w) else {
                if ["inspect", "metadata"].contains(action.kind) { results.set(index, ["id": w.id, "ok": true, "closed": true]); continue }
                results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Owning process identity changed."]); continue
            }
            let initial = before[w.id]
            // Already-correct windows need neither an AX lookup nor a resize.
            if action.kind == "move", let target = action.target, let current = initial,
               current.pid == w.pid, current.onscreen, occupiesPane(current.frame, target) {
                results.set(index, ["id": w.id, "ok": true, "unchanged": true, "bounds": frameDictionary(current.frame), "minimized": false]); continue
            }
            if action.kind == "inspect", let current = initial, current.pid == w.pid, current.onscreen {
                results.set(index, ["id": w.id, "ok": true, "bounds": frameDictionary(current.frame), "minimized": false]); continue
            }
            if windowIndex == nil { results.noteIndexLoad(); windowIndex = readWindowIndex(w) }
            let lookup = indexedWindow(w, in: windowIndex!)
            guard case let .found(element) = lookup else {
                if case .absent = lookup, ["inspect", "metadata"].contains(action.kind) {
                    results.set(index, ["id": w.id, "ok": true, "closed": true]); continue
                }
                let message: String
                switch lookup { case .unavailable(let detail): message = detail; default: message = "Window is no longer open." }
                results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": message]); continue
            }
            if ["inspect", "metadata"].contains(action.kind) {
                var result: [String: Any] = ["id": w.id, "ok": true]
                result["bounds"] = initial.map { frameDictionary($0.frame) } ?? windowFrame(element)
                result["minimized"] = (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue ?? false
                if action.kind == "metadata" { result["title"] = axValue(element, kAXTitleAttribute) as? String }
                results.set(index, result); continue
            }
            // Re-read WindowServer immediately before acting, after any slow AX
            // lookup. This preserves moves, minimizes and Space changes by the user.
            let number = UInt32(w.id.dropFirst(2)) ?? 0
            let freshEntries = CGWindowListCopyWindowInfo(.optionIncludingWindow, number) as? [[String: Any]] ?? []
            let current = freshEntries.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == number }).flatMap(cgRecord)
            var unchanged = false
            if let expected = w.bounds {
                if action.kind == "restore", w.minimized == true {
                    // Minimized windows may disappear from WindowServer's list.
                    // The exact AX identity, minimized state and frame remain available.
                    if (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue == true,
                       let b = windowFrame(element) {
                        unchanged = sameFrame(WindowFrame(x: b["x"]!, y: b["y"]!, width: b["width"]!, height: b["height"]!), expected)
                    }
                } else if let current = current {
                    unchanged = current.pid == w.pid && current.onscreen && sameFrame(current.frame, expected)
                }
            }
            guard unchanged else {
                results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Window changed since preview."]); continue
            }
            if ["minimize", "close"].contains(action.kind) {
                let app = focusedApplication()
                let focused = app?.1 == w.pid ? currentFocus()["window_id"] as? String ?? "" : nil
                if app == nil || focused == "" || focused == w.id {
                    results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Kept the current app's focused window."]); continue
                }
            }
            if (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue == true || (axValue(element, kAXModalAttribute) as? NSNumber)?.boolValue == true {
                results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Kept a fullscreen window or dialog."]); continue
            }
            var result: [String: Any] = ["id": w.id, "ok": true, "delivered": true]
            if ["move", "restore"].contains(action.kind), let target = action.target,
               [target.x, target.y, target.width, target.height].allSatisfy({ $0.isFinite }), target.width > 0, target.height > 0 {
                if action.kind == "restore" { AXUIElementSetAttributeValue(element, kAXMinimizedAttribute as CFString, kCFBooleanFalse) }
                var resizable: DarwinBoolean = true
                if AXUIElementIsAttributeSettable(element, kAXSizeAttribute as CFString, &resizable) == .success { result["resizable"] = resizable.boolValue }
                if resizable.boolValue { placeWindow(element, target) }
                else {
                    var p = CGPoint(x: target.x, y: target.y)
                    AXUIElementSetAttributeValue(element, kAXPositionAttribute as CFString, AXValueCreate(.cgPoint, &p)!)
                }
            } else if action.kind == "minimize" {
                AXUIElementSetAttributeValue(element, kAXMinimizedAttribute as CFString, kCFBooleanTrue)
            } else if action.kind == "close" {
                guard let close = axValue(element, kAXCloseButtonAttribute), CFGetTypeID(close) == AXUIElementGetTypeID() else {
                    results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "This window has no standard Close button."]); continue
                }
                // AppKit exposes the dirty indicator on the Close button; many
                // document windows do not implement AXEdited on the window.
                let edited = (axValue(element, kAXEditedAttribute) as? NSNumber)?.boolValue == true
                    || (axValue(close as! AXUIElement, kAXEditedAttribute) as? NSNumber)?.boolValue == true
                let sheets = axValue(element, "AXSheets") as? [AXUIElement] ?? []
                if edited || !sheets.isEmpty {
                    results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Kept unsaved work or a dialog."]); continue
                }
                let title = w.title_source == "ax" ? axValue(element, kAXTitleAttribute) as? String : current?.title
                if let expected = w.title, let actual = title, expected != actual {
                    results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Window contents changed since preview."]); continue
                }
                AXUIElementPerformAction(close as! AXUIElement, kAXPressAction as CFString)
            } else {
                results.set(index, ["id": w.id, "ok": false, "error": "Unsupported window action."]); continue
            }
            results.set(index, result)
        }
    }
    let effectsFinished = Date()
    var ordered = results.ordered(actions.count)
    // One shared compositor settle replaces a sleep after every window.
    if ordered.contains(where: { $0["delivered"] as? Bool == true }) { Thread.sleep(forTimeInterval: 0.04) }
    let settled = Date()
    var afterEntries = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]] ?? []
    var after = cgRecords(afterEntries)
    let restoring = actions.enumerated().filter {
        $0.element.kind == "restore" && $0.element.window.minimized == true && ordered[$0.offset]["delivered"] as? Bool == true
    }.map { $0.element }
    let animationDeadline = Date().addingTimeInterval(0.9)
    // WindowServer reports the animated Dock thumbnail as the window frame.
    // Observe restoration until its real rectangle returns; never resend the write.
    while !restoring.isEmpty && Date() < animationDeadline && restoring.contains(where: { action in
        guard let current = after[action.window.id], let target = action.target else { return true }
        return !current.onscreen || !occupiesPane(current.frame, target)
    }) {
        Thread.sleep(forTimeInterval: 0.02)
        afterEntries = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]] ?? []
        after = cgRecords(afterEntries)
    }
    var verificationIndices: [Int32: WindowIndex] = [:]
    for (index, action) in actions.enumerated() {
        if ordered[index]["skipped"] as? Bool == true || ["inspect", "metadata"].contains(action.kind) { continue }
        if let current = after[action.window.id], current.pid == action.window.pid {
            if ordered[index]["unchanged"] as? Bool == true, let previous = before[action.window.id], !sameFrame(current.frame, previous.frame) {
                ordered[index]["ok"] = false; ordered[index]["skipped"] = true
                ordered[index]["error"] = "Window changed while arranging; preserved the new placement."
            }
            ordered[index]["bounds"] = frameDictionary(current.frame)
            ordered[index]["minimized"] = !current.onscreen
        }
        if action.kind == "minimize" || action.kind == "close" {
            if verificationIndices[action.window.pid] == nil {
                results.noteIndexLoad(); verificationIndices[action.window.pid] = readWindowIndex(action.window)
            }
            let lookup = indexedWindow(action.window, in: verificationIndices[action.window.pid]!)
            if case let .found(element) = lookup {
                ordered[index]["minimized"] = (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue ?? false
                if action.kind == "close" { ordered[index]["ok"] = false; ordered[index]["error"] = "Window stayed open; its contents were preserved." }
                if ordered[index]["bounds"] == nil { ordered[index]["bounds"] = before[action.window.id].map { frameDictionary($0.frame) } }
            } else if case .absent = lookup {
                ordered[index]["closed"] = true
                ordered[index]["ok"] = action.kind == "close"
            } else {
                ordered[index]["ok"] = false; ordered[index]["error"] = "Window could not be verified."
            }
        }
    }
    let focusAfter = currentFocus()
    let focusAvailable = (focusBefore["window_id"] as? String ?? "") != "" && (focusAfter["window_id"] as? String ?? "") != ""
    let focus: [String: Any] = ["before": focusBefore, "after": focusAfter, "unchanged": focusAvailable ? NSDictionary(dictionary: focusBefore).isEqual(to: focusAfter) as Any : NSNull()]
    // During a Dock animation CG still calls the thumbnail an onscreen window.
    // Confirmed AX minimizations must not become obstacles in the next partition.
    let removedIDs = Set(ordered.filter { $0["minimized"] as? Bool == true || $0["closed"] as? Bool == true }.compactMap { $0["id"] as? String })
    let observed = inventoryData(entries: afterEntries.filter {
        let id = ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value ?? 0
        return ($0[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue == true && !removedIDs.contains("w-\(id)")
    }, focus: focusAfter)
    output(["ok": true, "data": ["results": ordered, "focus_check": focus, "inventory": observed,
        "timings": ["prepare_ms": prepared.timeIntervalSince(started) * 1000,
                    "effects_ms": effectsFinished.timeIntervalSince(prepared) * 1000,
                    "settle_ms": settled.timeIntervalSince(effectsFinished) * 1000,
                    "verify_ms": Date().timeIntervalSince(settled) * 1000,
                    "app_index_loads": Double(results.indexLoadCount()),
                    "native_ms": Date().timeIntervalSince(started) * 1000]]])
}

func output(_ value: Any) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
    fflush(stdout)
}

func rect(_ r: NSRect, _ top: CGFloat) -> [String: Double] {
    ["x": r.minX, "y": top - r.maxY, "width": r.width, "height": r.height]
}

func displays() -> [[String: Any]] {
    let top = NSScreen.screens.first?.frame.maxY ?? 0
    return NSScreen.screens.map { s -> [String: Any] in
        let id = (s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as! NSNumber).uint32Value
        let uuid = CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue()
        let stableID = uuid.map { CFUUIDCreateString(nil, $0) as String } ?? "cg-\(id)"
        var mm = CGDisplayScreenSize(id)
        if mm.width > 0, mm.height > 0 {
            let aspect = s.frame.width / s.frame.height
            if abs(log(mm.height / mm.width / aspect)) < abs(log(mm.width / mm.height / aspect)) {
                mm = CGSize(width: mm.height, height: mm.width)
            }
        }
        // Quartz can synthesize 72-DPI dimensions when EDID is absent.
        let estimated = abs(mm.width - s.frame.width * 25.4 / 72) < 1 && abs(mm.height - s.frame.height * 25.4 / 72) < 1
        let known = !estimated && mm.width.isFinite && mm.height.isFinite && mm.width > 0 && mm.height > 0
        return ["id": stableID, "name": s.localizedName, "built_in": CGDisplayIsBuiltin(id) != 0,
                "physical_size_mm": known ? ["width": mm.width, "height": mm.height] as Any : NSNull(),
                "physical_size_source": known ? "system_reported" : "estimated",
                "bounds": rect(s.frame, top), "usable": rect(s.visibleFrame, top)]
    }
}

func inventoryData(entries: [[String: Any]], focus: [String: Any]) -> [String: Any] {
    let apps = Dictionary(uniqueKeysWithValues: NSWorkspace.shared.runningApplications.map { ($0.processIdentifier, $0) })
    let frontmost = focus["pid"] as? Int32
    let focusedID = focus["window_id"] as? String ?? ""
    var windows: [[String: Any]] = [], errors: [[String: String]] = [], checked = Set<String>(), focusedFound = false
    for entry in entries {
        guard (entry[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
              let pid = (entry[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value,
              let app = apps[pid] ?? NSRunningApplication(processIdentifier: pid), app.activationPolicy == .regular,
              app.bundleIdentifier != "org.2018kguo.desk-tidy",
              let id = (entry[kCGWindowNumber as String] as? NSNumber)?.uint32Value,
              let bounds = entry[kCGWindowBounds as String] as? NSDictionary,
              let frame = CGRect(dictionaryRepresentation: bounds), frame.width >= 220, frame.height >= 180 else { continue }
        let name = app.localizedName ?? "App"
        var process = proc_bsdinfo()
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &process, Int32(MemoryLayout<proc_bsdinfo>.size)) == MemoryLayout<proc_bsdinfo>.size else { errors.append(["app": name, "error": "Process identity unavailable."]); continue }
        let focused = focusedID.isEmpty ? frontmost == pid && !focusedFound : focusedID == "w-\(id)"
        if focused { focusedFound = true }
        let title = entry[kCGWindowName as String] as? String ?? name
        windows.append(["id": "w-\(id)", "app_name": name, "title": title, "pid": pid,
            "title_source": entry[kCGWindowName as String] is String ? "cg" : "app",
            "process_instance": "macos-proc-v1:\(process.pbi_start_tvsec):\(process.pbi_start_tvusec)",
            "bounds": ["x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height],
            "minimized": false, "hidden": false, "visible": true, "is_focused": focused])
        checked.insert(name)
    }
    return ["displays": displays(), "windows": windows,
        "coverage": ["scope": "onscreen regular app windows at least 220 by 180 points", "checked_apps": checked.sorted(), "errors": errors, "complete": errors.isEmpty]]
}

func inventory() {
    guard AXIsProcessTrusted() else { output(["ok": false, "error": "Allow Fenlet in System Settings → Privacy & Security → Accessibility."]); return }
    guard let entries = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        output(["ok": false, "error": "The current screen inventory is unavailable."]); return
    }
    output(["ok": true, "data": inventoryData(entries: entries, focus: currentFocus())])
}

func nativeCommand(_ command: String, payload: Data? = nil) -> Bool {
    switch command {
    case "displays": output(displays())
    case "inventory": inventory()
    case "permissions": output(["ok": true, "data": ["accessibility": AXIsProcessTrusted()]])
    case "focus": output(["ok": true, "data": currentFocus()])
    case "windows":
        do { batchWindows(try JSONDecoder().decode(BatchRequest.self, from: payload ?? FileHandle.standardInput.readDataToEndOfFile())) }
        catch { output(["ok": false, "error": error.localizedDescription]) }
    default: return false
    }
    return true
}

if CommandLine.arguments.dropFirst().first == "session" {
    // One short-lived connection per CLI invocation; no background daemon.
    while let line = readLine() {
        CFRunLoopRunInMode(.defaultMode, 0.002, false)
        do {
            guard let request = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
                  let operation = request["operation"] as? String else {
                output(["ok": false, "error": "Invalid native request."]); continue
            }
            let data = try JSONSerialization.data(withJSONObject: request["payload"] ?? [:], options: [.fragmentsAllowed])
            if !nativeCommand(operation, payload: data) { output(["ok": false, "error": "Unsupported native operation."]) }
        } catch { output(["ok": false, "error": error.localizedDescription]) }
    }
} else if nativeCommand(CommandLine.arguments.dropFirst().first ?? "") {
} else if CommandLine.arguments.dropFirst().first == "watch-focus" {
    let duration = min(15, max(0.1, Double(CommandLine.arguments.last ?? "3") ?? 3))
    let end = Date().addingTimeInterval(duration)
    var samples: [[String: Any]] = []
    while Date() < end {
        samples.append(currentFocus())
        Thread.sleep(forTimeInterval: 0.02)
    }
    output(["ok": true, "data": ["samples": samples]])
} else if CommandLine.arguments.dropFirst().first == "credential" {
    let provider = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "gateway"
    let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "org.2018kguo.desk-tidy", kSecAttrAccount as String: provider,
        kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
    var item: CFTypeRef?
    if SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data {
        output(["ok": true, "data": ["key": String(data: data, encoding: .utf8) ?? ""]])
    } else { output(["ok": true, "data": ["key": ""]]) }
} else if CommandLine.arguments.dropFirst().first == "save-credential" {
    struct Credential: Decodable { let provider, key: String }
    do {
        let request = try JSONDecoder().decode(Credential.self, from: FileHandle.standardInput.readDataToEndOfFile())
        guard ["gateway", "openrouter"].contains(request.provider), !request.key.isEmpty, request.key.count < 4096 else {
            output(["ok": false, "error": "Enter a valid provider API key."]); exit(1)
        }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "org.2018kguo.desk-tidy", kSecAttrAccount as String: request.provider]
        let data = Data(request.key.utf8)
        var status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var add = query; add[kSecValueData as String] = data
            status = SecItemAdd(add as CFDictionary, nil)
        }
        output(["ok": status == errSecSuccess, "data": ["saved": status == errSecSuccess]])
    } catch { output(["ok": false, "error": "Could not read the API key."]) }
 } else {
    fputs("Usage: desktop-helper session | inventory | windows | focus | permissions\n", stderr)
    exit(2)
}
