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

// Optional WindowServer bridge. Unsupported systems retain current-Space mode.
// Space membership is verified after a write; API delivery is never treated as proof.
final class SpaceBridge: @unchecked Sendable {
    static let shared = SpaceBridge()
    private let lock = NSLock()
    let transitionLock = NSLock()
    private let connection: Int32
    private let copyDisplays: (@convention(c) (Int32) -> Unmanaged<CFArray>?)?
    private let copySpaces: (@convention(c) (Int32, Int32, CFArray) -> Unmanaged<CFArray>?)?
    private let setCompat: (@convention(c) (Int32, UInt64, Int32) -> Int32)?
    private let setWorkspace: (@convention(c) (Int32, UnsafePointer<UInt32>, Int32, Int32) -> Int32)?
    private let moveManaged: (@convention(c) (Int32, CFArray, UInt64) -> Void)?
    init() {
        #if FENLET_NO_SPACE_BRIDGE
        let handle: UnsafeMutableRawPointer? = nil
        #else
        let handle = dlopen("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight", RTLD_LAZY)
        #endif
        func symbol<T>(_ name: String, _ type: T.Type) -> T? {
            guard let handle, let address = name.withCString({ dlsym(handle, $0) }) else { return nil }
            return unsafeBitCast(address, to: type)
        }
        connection = symbol("SLSMainConnectionID", (@convention(c) () -> Int32).self)?() ?? 0
        copyDisplays = symbol("SLSCopyManagedDisplaySpaces", (@convention(c) (Int32) -> Unmanaged<CFArray>?).self)
        copySpaces = symbol("SLSCopySpacesForWindows", (@convention(c) (Int32, Int32, CFArray) -> Unmanaged<CFArray>?).self)
        setCompat = symbol("SLSSpaceSetCompatID", (@convention(c) (Int32, UInt64, Int32) -> Int32).self)
        setWorkspace = symbol("SLSSetWindowListWorkspace", (@convention(c) (Int32, UnsafePointer<UInt32>, Int32, Int32) -> Int32).self)
        moveManaged = symbol("SLSMoveWindowsToManagedSpace", (@convention(c) (Int32, CFArray, UInt64) -> Void).self)
    }
    var available: Bool { connection != 0 && copyDisplays != nil && copySpaces != nil && ((setCompat != nil && setWorkspace != nil) || moveManaged != nil) }
    func displays() -> [[String: Any]] {
        guard available, let raw = copyDisplays?(connection)?.takeRetainedValue() else { return [] }
        return raw as? [[String: Any]] ?? []
    }
    func spaces(_ id: UInt32) -> [UInt64]? {
        guard available, let raw = copySpaces?(connection, 0x7, [NSNumber(value: id)] as CFArray)?.takeRetainedValue(),
              let numbers = raw as? [NSNumber] else { return nil }
        return numbers.map { $0.uint64Value }.sorted()
    }
    func types() -> [UInt64: Int] {
        var result: [UInt64: Int] = [:]
        for display in displays() {
            for space in display["Spaces"] as? [[String: Any]] ?? [] {
                if let id = space["ManagedSpaceID"] as? NSNumber, let type = space["type"] as? Int { result[id.uint64Value] = type }
            }
        }
        return result
    }
    func currentSpaces() -> Set<UInt64> {
        Set(displays().compactMap { (($0["Current Space"] as? [String: Any])?["ManagedSpaceID"] as? NSNumber)?.uint64Value })
    }
    func destinations() -> [String: UInt64] {
        var result: [String: UInt64] = [:]
        for display in displays() {
            guard let name = display["Display Identifier"] as? String else { continue }
            let spaces = display["Spaces"] as? [[String: Any]] ?? []
            let current = display["Current Space"] as? [String: Any]
            let target = current?["type"] as? Int == 0 ? current : spaces.first { $0["type"] as? Int == 0 }
            if let id = target?["ManagedSpaceID"] as? NSNumber { result[name.uppercased()] = id.uint64Value }
        }
        return result
    }
    func move(_ id: UInt32, to space: UInt64) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard types()[space] == 0 else { return false }
        if #available(macOS 14.5, *) {
            guard let setCompat, let setWorkspace else { return false }
            // WindowServer requires a temporary workspace ID on 14.5 and later.
            // Serialize this transaction, including clearing the ID on errors.
            let compat: Int32 = 0x79616265
            guard setCompat(connection, space, compat) == 0 else { return false }
            defer { _ = setCompat(connection, space, 0) }
            var number = id
            return setWorkspace(connection, &number, 1, compat) == 0
        }
        guard let moveManaged else { return false }
        moveManaged(connection, [NSNumber(value: id)] as CFArray, space)
        return true
    }
}

func leaveFullscreen(_ element: AXUIElement, number: UInt32, deadline: Date) -> Bool {
    SpaceBridge.shared.transitionLock.lock(); defer { SpaceBridge.shared.transitionLock.unlock() }
    guard Date() < deadline else { return false }
    AXUIElementSetAttributeValue(element, "AXFullScreen" as CFString, kCFBooleanFalse)
    let end = min(deadline, Date().addingTimeInterval(4))
    while Date() < end {
        let types = SpaceBridge.shared.types()
        if (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue == false,
           let spaces = SpaceBridge.shared.spaces(number), !spaces.isEmpty,
           spaces.allSatisfy({ types[$0] == 0 }) { return true }
        Thread.sleep(forTimeInterval: 0.03)
    }
    return false
}

struct WindowRef: Decodable {
    let id: String
    let pid: Int32
    let process_instance: String
    let title: String?
    let title_source: String?
    let bounds: WindowFrame?
    let minimized: Bool?
    let space_ids: [UInt64]?
    let fullscreen: Bool?
}
struct WindowFrame: Codable, Equatable, Sendable {
    let x, y, width, height: Double
}
struct WindowAction: Decodable {
    let kind: String
    let window: WindowRef
    let target: WindowFrame?
    let target_space: UInt64?
    let target_fullscreen: Bool?
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
func readWindowIndex(_ w: WindowRef, extraIDs: Set<CGWindowID> = []) -> WindowIndex {
    guard processMatches(w) else { return .gone }
    let app = AXUIElementCreateApplication(w.pid)
    var rawWindows: CFArray?
    var status: AXError = .cannotComplete
    for timeout: Float in [0.25, 0.7, 1.0] {
        AXUIElementSetMessagingTimeout(app, timeout)
        var count: CFIndex = 0
        status = AXUIElementGetAttributeValueCount(app, kAXWindowsAttribute as CFString, &count)
        if status == .success, count == 0 { rawWindows = [] as CFArray; break }
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
    if !extraIDs.isSubset(of: Set(index.keys)) {
        // Apps often expose their main/focused window across Spaces even when
        // AXWindows omits it. Resolve these public attributes before searching.
        for attribute in [kAXMainWindowAttribute, kAXFocusedWindowAttribute] {
            var raw: CFTypeRef?
            AXUIElementSetMessagingTimeout(app, 0.06)
            if AXUIElementCopyAttributeValue(app, attribute as CFString, &raw) == .success,
               let raw, CFGetTypeID(raw) == AXUIElementGetTypeID() {
                let element = raw as! AXUIElement
                var number: CGWindowID = 0
                if _AXUIElementGetWindow(element, &number) == .success, extraIDs.contains(number) { index[number] = element }
            }
        }
    }
    if !extraIDs.isSubset(of: Set(index.keys)) {
        // AXWindows omits other Spaces. Resolve a bounded set of Cocoa remote
        // element IDs, and accept only exact WindowServer IDs from this process.
        // Never claim a missing off-Space window is closed after a partial read.
        let handle = dlopen("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices", RTLD_LAZY)
        if let handle, let symbol = dlsym(handle, "_AXUIElementCreateWithRemoteToken") {
            let create = unsafeBitCast(symbol, to: (@convention(c) (CFData) -> Unmanaged<AXUIElement>?).self)
            var token = Data(count: 20), pid = w.pid, magic: UInt32 = 0x636f636f
            withUnsafeBytes(of: &pid) { token.replaceSubrange(0..<4, with: $0) }
            withUnsafeBytes(of: &magic) { token.replaceSubrange(8..<12, with: $0) }
            let deadline = Date().addingTimeInterval(0.18)
            var missing = extraIDs.subtracting(index.keys)
            for value in UInt64(0)..<1000 {
                if Date() >= deadline || missing.isEmpty { break }
                var value = value
                withUnsafeBytes(of: &value) { token.replaceSubrange(12..<20, with: $0) }
                guard let element = create(token as CFData)?.takeRetainedValue() else { continue }
                AXUIElementSetMessagingTimeout(element, 0.015)
                var role: CFTypeRef?
                guard AXUIElementCopyAttributeValue(element, kAXSubroleAttribute as CFString, &role) == .success,
                      let role = role as? String, [kAXStandardWindowSubrole, kAXDialogSubrole].contains(role) else { continue }
                var number: CGWindowID = 0
                if _AXUIElementGetWindow(element, &number) == .success, missing.contains(number) { index[number] = element; missing.remove(number) }
            }
            dlclose(handle)
        }
        complete = complete && extraIDs.isSubset(of: Set(index.keys))
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
    private var elements: [Int: AXUIElement] = [:]
    func retain(_ index: Int, _ element: AXUIElement) { lock.lock(); elements[index] = element; lock.unlock() }
    func element(_ index: Int) -> AXUIElement? { lock.lock(); defer { lock.unlock() }; return elements[index] }
    func noteIndexLoad() { lock.lock(); indexLoads += 1; lock.unlock() }
    func indexLoadCount() -> Int { lock.lock(); defer { lock.unlock() }; return indexLoads }
    func set(_ index: Int, _ value: [String: Any]) { lock.lock(); values[index] = value; lock.unlock() }
    func ordered(_ count: Int) -> [[String: Any]] { (0..<count).map { values[$0]! } }
}

struct DisplayCheck: Decodable, Equatable {
    let id: String
    let bounds, usable: WindowFrame
    let gather_space: UInt64?
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
        let destinations = SpaceBridge.shared.destinations()
        let tracked = expected.contains { $0.gather_space != nil }
        let screens = displays().map { screen -> [String: Any] in
            var screen = screen
            if tracked, let id = screen["id"] as? String { screen["gather_space"] = destinations[id.uppercased()] ?? destinations["MAIN"] }
            return screen
        }
        let actual = try! JSONDecoder().decode([DisplayCheck].self, from: JSONSerialization.data(withJSONObject: screens))
        if Dictionary(uniqueKeysWithValues: actual.map { ($0.id, $0) }) != Dictionary(uniqueKeysWithValues: expected.map { ($0.id, $0) }) {
            output(["ok": false, "error": "Your display setup changed. Arrange windows again."]); return
        }
    }
    let bridge = SpaceBridge.shared
    let transitionDeadline = Date().addingTimeInterval(12)
    // A destination must still be the reviewed regular Space, before any effects.
    let destinations = bridge.types()
    if actions.contains(where: { $0.target_space.map { destinations[$0] != 0 } ?? false }) {
        output(["ok": false, "error": "The destination Space changed. Make a fresh preview."]); return
    }
    let focusBefore = currentFocus()
    let beforeEntries = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]] ?? []
    let before = cgRecords(beforeEntries)
    let results = BatchResults()
    let trackedIDs = Dictionary(grouping: actions.filter { $0.window.space_ids != nil }, by: { $0.window.pid })
        .mapValues { Set($0.compactMap { UInt32($0.window.id.dropFirst(2)) }) }
    let groups = Array(Dictionary(grouping: Array(actions.enumerated()), by: { $0.element.window.pid }).values)
    let voiceOver = NSWorkspace.shared.isVoiceOverEnabled
    let prepared = Date()
    let performGroup: (Int) -> Void = { groupIndex in
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
               current.pid == w.pid, current.onscreen, occupiesPane(current.frame, target),
               w.fullscreen != true, action.target_fullscreen != true,
               w.space_ids.map({ bridge.spaces(UInt32(w.id.dropFirst(2)) ?? 0) == $0 }) ?? true,
               action.target_space.map({ bridge.spaces(UInt32(w.id.dropFirst(2)) ?? 0) == [$0] }) ?? true {
                results.set(index, ["id": w.id, "ok": true, "unchanged": true, "bounds": frameDictionary(current.frame), "minimized": false]); continue
            }
            if action.kind == "inspect", w.space_ids == nil, let current = initial, current.pid == w.pid, current.onscreen {
                results.set(index, ["id": w.id, "ok": true, "bounds": frameDictionary(current.frame), "minimized": false]); continue
            }
            if windowIndex == nil { results.noteIndexLoad(); windowIndex = readWindowIndex(w, extraIDs: trackedIDs[w.pid] ?? []) }
            let lookup = indexedWindow(w, in: windowIndex!)
            guard case let .found(element) = lookup else {
                if case .absent = lookup, ["inspect", "metadata"].contains(action.kind) {
                    results.set(index, ["id": w.id, "ok": true, "closed": true]); continue
                }
                let message: String
                switch lookup { case .unavailable(let detail): message = detail; default: message = "Window is no longer open." }
                results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": message]); continue
            }
            results.retain(index, element)
            if ["inspect", "metadata"].contains(action.kind) {
                var result: [String: Any] = ["id": w.id, "ok": true]
                result["bounds"] = initial.map { frameDictionary($0.frame) } ?? windowFrame(element)
                result["minimized"] = (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue ?? false
                if w.space_ids != nil {
                    result["space_ids"] = bridge.spaces(UInt32(w.id.dropFirst(2)) ?? 0)
                    result["fullscreen"] = (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue
                }
                if action.kind == "metadata" { result["title"] = axValue(element, kAXTitleAttribute) as? String }
                results.set(index, result); continue
            }
            // Re-read WindowServer immediately before acting, after any slow AX
            // lookup. This preserves moves, minimizes and Space changes by the user.
            let number = UInt32(w.id.dropFirst(2)) ?? 0
            let freshEntries = CGWindowListCopyWindowInfo(.optionIncludingWindow, number) as? [[String: Any]] ?? []
            let current = freshEntries.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == number }).flatMap(cgRecord)
            var unchanged = false
            var changed = "bounds"
            if let expected = w.bounds {
                if action.kind == "restore", w.minimized == true {
                    // Minimized windows may disappear from WindowServer's list.
                    // The exact AX identity, minimized state and frame remain available.
                    if (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue == true,
                       let b = windowFrame(element) {
                        unchanged = sameFrame(WindowFrame(x: b["x"]!, y: b["y"]!, width: b["width"]!, height: b["height"]!), expected)
                    }
                } else if let current = current {
                    if w.space_ids != nil && !current.onscreen, let frame = windowFrame(element) {
                        // CG's list can contain presentation coordinates while
                        // another Space slides. AX keeps the real window frame.
                        unchanged = current.pid == w.pid && sameFrame(WindowFrame(x: frame["x"]!, y: frame["y"]!, width: frame["width"]!, height: frame["height"]!), expected)
                    } else {
                        unchanged = current.pid == w.pid && current.onscreen && sameFrame(current.frame, expected)
                    }
                }
            }
            if let expectedSpaces = w.space_ids {
                if bridge.spaces(number) != expectedSpaces { unchanged = false; changed = "Space membership" }
                if (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue != (w.minimized ?? false) { unchanged = false; changed = "minimized state" }
                if (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue != (w.fullscreen ?? false) { unchanged = false; changed = "fullscreen state" }
            }
            guard unchanged else {
                results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Window \(changed) changed since preview.", "observed_bounds": current.map { frameDictionary($0.frame) } ?? [:]]); continue
            }
            if ["minimize", "close"].contains(action.kind) {
                let app = focusedApplication()
                let focused = app?.1 == w.pid ? currentFocus()["window_id"] as? String ?? "" : nil
                if app == nil || focused == "" || focused == w.id {
                    results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Kept the current app's focused window."]); continue
                }
            }
            let fullscreen = (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue == true
            if (axValue(element, kAXModalAttribute) as? NSNumber)?.boolValue == true || (fullscreen && w.space_ids == nil) {
                results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Kept this fullscreen window or dialog."]); continue
            }
            var result: [String: Any] = ["id": w.id, "ok": true, "delivered": true]
            if ["move", "restore"].contains(action.kind), let target = action.target,
               [target.x, target.y, target.width, target.height].allSatisfy({ $0.isFinite }), target.width > 0, target.height > 0 {
                if Date() >= transitionDeadline {
                    results.set(index, ["id": w.id, "ok": false, "skipped": true, "error": "Space transition budget reached. Make a fresh preview."]); continue
                }
                if action.kind == "restore" { AXUIElementSetAttributeValue(element, kAXMinimizedAttribute as CFString, kCFBooleanFalse) }
                if fullscreen && !leaveFullscreen(element, number: number, deadline: transitionDeadline) {
                    result["ok"] = false; result["error"] = "Fullscreen exit could not be verified; inspect before retrying."
                    results.set(index, result); continue
                }
                var resizable: DarwinBoolean = true
                if AXUIElementIsAttributeSettable(element, kAXSizeAttribute as CFString, &resizable) == .success { result["resizable"] = resizable.boolValue }
                if resizable.boolValue { placeWindow(element, target) }
                else {
                    var p = CGPoint(x: target.x, y: target.y)
                    AXUIElementSetAttributeValue(element, kAXPositionAttribute as CFString, AXValueCreate(.cgPoint, &p)!)
                }
                // Moving the frame across displays can change its Desktop. Do
                // that first; a later AX write can undo a WindowServer transfer.
                if let space = action.target_space, bridge.spaces(number) != [space] {
                    _ = bridge.move(number, to: space)
                    let deadline = min(transitionDeadline, Date().addingTimeInterval(1))
                    while bridge.spaces(number) != [space] && Date() < deadline { Thread.sleep(forTimeInterval: 0.02) }
                    guard bridge.spaces(number) == [space] else {
                        result["ok"] = false; result["error"] = "Couldn’t move this window to the target Desktop."
                        results.set(index, result); continue
                    }
                }
                if action.target_fullscreen == true {
                    bridge.transitionLock.lock(); defer { bridge.transitionLock.unlock() }
                    guard Date() < transitionDeadline else {
                        result["ok"] = false; result["error"] = "Fullscreen restore timed out; inspect before retrying."
                        results.set(index, result); continue
                    }
                    AXUIElementSetAttributeValue(element, "AXFullScreen" as CFString, kCFBooleanTrue)
                    let deadline = min(transitionDeadline, Date().addingTimeInterval(4))
                    while Date() < deadline {
                        if (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue == true,
                           bridge.spaces(number)?.contains(where: { bridge.types()[$0] == 4 }) == true,
                           let frame = windowFrame(element),
                           sameFrame(WindowFrame(x: frame["x"]!, y: frame["y"]!, width: frame["width"]!, height: frame["height"]!), target) { break }
                        Thread.sleep(forTimeInterval: 0.03)
                    }
                }
            } else if action.kind == "minimize" {
                if fullscreen && !leaveFullscreen(element, number: number, deadline: transitionDeadline) {
                    result["ok"] = false; result["error"] = "Fullscreen exit could not be verified; inspect before retrying."
                    results.set(index, result); continue
                }
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
    // Fullscreen transitions change the active Space for other apps. Interleaved
    // transfers can land on that transient Space instead of their destination.
    // Ordinary moves retain parallel per-app batches.
    if actions.contains(where: { $0.window.fullscreen == true || $0.target_fullscreen == true }) {
        for index in groups.indices { performGroup(index) }
    } else {
        DispatchQueue.concurrentPerform(iterations: groups.count, execute: performGroup)
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
    let closing = actions.enumerated().filter {
        $0.element.kind == "close" && ordered[$0.offset]["delivered"] as? Bool == true
    }.map { $0.element.window.id }
    let animationDeadline = Date().addingTimeInterval(0.9)
    // WindowServer reports the animated Dock thumbnail as the window frame.
    // Observe restoration and Close animations; never resend either write.
    while Date() < animationDeadline && (closing.contains(where: { id in
        guard let current = after[id] else { return false }
        return current.onscreen || (bridge.available && bridge.spaces(UInt32(id.dropFirst(2)) ?? 0) != [])
    }) || restoring.contains(where: { action in
        guard let current = after[action.window.id], let target = action.target else { return true }
        return !current.onscreen || !occupiesPane(current.frame, target)
    })) {
        Thread.sleep(forTimeInterval: 0.02)
        afterEntries = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]] ?? []
        after = cgRecords(afterEntries)
    }
    var verificationIndices: [Int32: WindowIndex] = [:]
    let spaceTypes = bridge.types(), activeSpaces = bridge.currentSpaces()
    let closedIDs = Set(actions.filter { $0.kind == "close" }.compactMap { UInt32($0.window.id.dropFirst(2)) })
    for (index, action) in actions.enumerated() {
        if ordered[index]["skipped"] as? Bool == true || ["inspect", "metadata"].contains(action.kind) { continue }
        let number = UInt32(action.window.id.dropFirst(2)) ?? 0
        let current = after[action.window.id]
        if let current, current.pid == action.window.pid {
            if ordered[index]["unchanged"] as? Bool == true, let previous = before[action.window.id], !sameFrame(current.frame, previous.frame) {
                ordered[index]["ok"] = false; ordered[index]["skipped"] = true
                ordered[index]["error"] = "Window changed while arranging; preserved the new placement."
            }
            ordered[index]["bounds"] = frameDictionary(current.frame)
            ordered[index]["minimized"] = !current.onscreen
        }
        if action.kind == "close" {
            if verificationIndices[action.window.pid] == nil {
                results.noteIndexLoad()
                // Closed NSWindows may retain their Space entries. Discover
                // other tracked windows, then use the scoped removal check
                // below with the complete AX roster to distinguish minimization.
                let liveIDs = (trackedIDs[action.window.pid] ?? []).subtracting(closedIDs).filter { bridge.spaces($0) != [] }
                verificationIndices[action.window.pid] = readWindowIndex(action.window, extraIDs: Set(liveIDs))
            }
            let lookup = indexedWindow(action.window, in: verificationIndices[action.window.pid]!)
            let membership = bridge.spaces(number)
            let sameDesktop = before[action.window.id]?.onscreen == true
                && action.window.space_ids.map { !activeSpaces.isDisjoint(with: $0) && membership == $0 } == true
            // A retained closed NSWindow may keep its CG ID and Space. A
            // complete current-Desktop AX roster still distinguishes Close
            // from minimization, hiding the app, or moving to another Space.
            let scopedRemoved = !processMatches(action.window) || ((membership == [] || sameDesktop) && current?.onscreen != true
                && NSRunningApplication(processIdentifier: action.window.pid)?.isHidden == false)
            if action.window.space_ids != nil { ordered[index]["space_ids"] = membership }
            if case .absent = lookup, action.window.space_ids == nil || scopedRemoved {
                ordered[index]["closed"] = true; ordered[index]["ok"] = true
            } else {
                ordered[index]["ok"] = false
                ordered[index]["error"] = "Close could not be verified; inspect before retrying."
            }
            continue
        }
        if action.window.space_ids != nil || action.target_space != nil || action.target_fullscreen != nil {
            let spaces = bridge.spaces(number)
            ordered[index]["space_ids"] = spaces
            if let current, current.onscreen, spaces?.allSatisfy({ spaceTypes[$0] == 0 }) == true, action.kind == "move" {
                ordered[index]["fullscreen"] = false; ordered[index]["minimized"] = false
            } else if let element = results.element(index) {
                ordered[index]["fullscreen"] = (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue
                ordered[index]["minimized"] = (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue
                ordered[index]["bounds"] = windowFrame(element) ?? ordered[index]["bounds"]
            } else {
                ordered[index]["minimized"] = nil
            }
            if let target = action.target_space, action.target_fullscreen != true, spaces != [target] {
                ordered[index]["ok"] = false; ordered[index]["error"] = "Couldn’t move this window to the target Desktop."
            }
        }
        if action.kind == "minimize", let element = results.element(index) {
            ordered[index]["minimized"] = (axValue(element, kAXMinimizedAttribute) as? NSNumber)?.boolValue
            if ordered[index]["bounds"] == nil { ordered[index]["bounds"] = before[action.window.id].map { frameDictionary($0.frame) } }
        }
    }
    let focusAfter = currentFocus()
    let focusAvailable = (focusBefore["window_id"] as? String ?? "") != "" && (focusAfter["window_id"] as? String ?? "") != ""
    let focus: [String: Any] = ["before": focusBefore, "after": focusAfter, "unchanged": focusAvailable ? NSDictionary(dictionary: focusBefore).isEqual(to: focusAfter) as Any : NSNull()]
    // During a Dock animation CG still calls the thumbnail an onscreen window.
    // Confirmed AX minimizations must not become obstacles in the next partition.
    let removedIDs = Set(ordered.filter { $0["minimized"] as? Bool == true || $0["closed"] as? Bool == true }.compactMap { $0["id"] as? String })
    let destinationSpaces = Set(actions.compactMap { $0.target_space })
    let gathering = !destinationSpaces.isEmpty
    let observed = inventoryData(entries: afterEntries.filter {
        let id = ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value ?? 0
        let included = gathering ? bridge.spaces(id).map { !destinationSpaces.isDisjoint(with: $0) } ?? false
            : ($0[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue == true
        return included && !removedIDs.contains("w-\(id)")
    }, focus: focusAfter, allSpaces: gathering)
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

func inventoryData(entries: [[String: Any]], focus: [String: Any], allSpaces: Bool = false) -> [String: Any] {
    let bridge = SpaceBridge.shared, types = allSpaces ? SpaceBridge.shared.types() : [:]
    var indices: [Int32: WindowIndex] = [:]
    var memberships: [UInt32: [UInt64]] = [:]
    if allSpaces {
        for entry in entries where (entry[kCGWindowLayer as String] as? NSNumber)?.intValue == 0 {
            if let id = (entry[kCGWindowNumber as String] as? NSNumber)?.uint32Value { memberships[id] = bridge.spaces(id) }
        }
    }
    let byOwner = allSpaces ? Dictionary(grouping: entries.filter {
        let id = ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value ?? 0
        return ($0[kCGWindowLayer as String] as? NSNumber)?.intValue == 0 && memberships[id]?.isEmpty == false
    }, by: { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value ?? 0 }) : [:]
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
        var row: [String: Any] = ["id": "w-\(id)", "app_name": name, "bundle_id": app.bundleIdentifier ?? "", "title": title, "pid": pid,
            "title_source": entry[kCGWindowName as String] is String ? "cg" : "app",
            "process_instance": "macos-proc-v1:\(process.pbi_start_tvsec):\(process.pbi_start_tvusec)",
            "bounds": ["x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height],
            "minimized": false, "hidden": false, "visible": true, "is_focused": focused]
        if allSpaces {
            guard let membership = memberships[id] else {
                errors.append(["app": name, "error": "Space membership unavailable."]); continue
            }
            if membership.isEmpty { continue }
            if membership.count > 1 {
                errors.append(["app": name, "error": "Kept a window pinned to multiple Spaces."]); continue
            }
            row["space_ids"] = membership
            row["fullscreen"] = membership.contains { types[$0] == 4 }
            row["onscreen"] = (entry[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue ?? false
            if app.isHidden { continue }
            if row["onscreen"] as? Bool != true {
                let reference = try! JSONDecoder().decode(WindowRef.self, from: JSONSerialization.data(withJSONObject: row))
                if indices[pid] == nil { indices[pid] = readWindowIndex(reference, extraIDs: Set((byOwner[pid] ?? []).compactMap { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value })) }
                guard case let .found(element) = indexedWindow(reference, in: indices[pid]!),
                      let minimized = axValue(element, kAXMinimizedAttribute) as? NSNumber else {
                    errors.append(["app": name, "error": "Off-Space window could not be inspected within the discovery budget."]); continue
                }
                if minimized.boolValue { continue }
                guard let actualFrame = windowFrame(element) else {
                    errors.append(["app": name, "error": "Off-Space window geometry unavailable."]); continue
                }
                row["bounds"] = actualFrame
                row["fullscreen"] = (axValue(element, "AXFullScreen") as? NSNumber)?.boolValue ?? row["fullscreen"]
            }
        }
        windows.append(row)
        checked.insert(name)
    }
    let destinations = allSpaces ? bridge.destinations() : [:]
    let screens = displays().map { screen -> [String: Any] in
        var value = screen
        if let id = screen["id"] as? String, let space = (destinations[id.uppercased()] ?? destinations["MAIN"]) { value["gather_space"] = space }
        return value
    }
    return ["displays": screens, "windows": windows, "all_spaces": allSpaces,
        "coverage": ["scope": allSpaces ? "regular app windows across all Spaces at least 220 by 180 points, excluding hidden and minimized windows" : "onscreen regular app windows at least 220 by 180 points", "checked_apps": checked.sorted(), "errors": errors, "complete": errors.isEmpty]]
}

func inventory(allSpaces: Bool = false) {
    guard AXIsProcessTrusted() else { output(["ok": false, "error": "Allow Fenlet in System Settings → Privacy & Security → Accessibility."]); return }
    let canGather = allSpaces && SpaceBridge.shared.available && !SpaceBridge.shared.destinations().isEmpty
    guard let entries = CGWindowListCopyWindowInfo(canGather ? [.optionAll, .excludeDesktopElements] : [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        output(["ok": false, "error": "The current screen inventory is unavailable."]); return
    }
    var data = inventoryData(entries: entries, focus: currentFocus(), allSpaces: canGather)
    if allSpaces && !canGather, var coverage = data["coverage"] as? [String: Any] {
        var errors = coverage["errors"] as? [[String: String]] ?? []
        errors.append(["app": "Fenlet", "error": "This macOS version only exposes visible windows. Windows on other Desktops are left alone."])
        coverage["errors"] = errors; coverage["complete"] = false; data["coverage"] = coverage
    }
    output(["ok": true, "data": data])
}

// Read only: never attach to a page, activate a browser, or create a target.
// Semaphore publication keeps the synchronous JSON pipe independent of AppKit.
final class BrowserProbeReply: @unchecked Sendable {
    let ready = DispatchSemaphore(value: 0)
    var value: [String: Any] = ["complete": false, "windows": []]
}

struct BrowserWindowSummary {
    let bounds: [String: Any]
    var tabs = 0
    var empty = true
    var attached = false
    var json: [String: Any] { ["bounds": bounds, "tabs": tabs, "empty": empty, "attached": attached] }
}

func browserContext(_ port: Int) {
    let reply = BrowserProbeReply()
    let task = Task {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 0.5
        configuration.timeoutIntervalForResource = 1
        configuration.httpShouldSetCookies = false
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel(); reply.ready.signal() }
        do {
            let (data, response) = try await session.data(from: URL(string: "http://127.0.0.1:\(port)/json/version")!)
            guard (response as? HTTPURLResponse)?.statusCode == 200, data.count < 1_048_576,
                  let version = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let address = version["webSocketDebuggerUrl"] as? String, let url = URL(string: address),
                  url.scheme == "ws", ["127.0.0.1", "localhost"].contains(url.host ?? ""),
                  url.port == port, url.path.hasPrefix("/devtools/browser/"), url.user == nil else { return }
            let socket = session.webSocketTask(with: url); socket.resume()
            defer { socket.cancel(with: .goingAway, reason: nil) }
            var sequence = 0
            func read(_ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
                sequence += 1
                let request = try JSONSerialization.data(withJSONObject: ["id": sequence, "method": method, "params": params])
                try await socket.send(.string(String(decoding: request, as: UTF8.self)))
                for _ in 0..<8 {
                    let message = try await socket.receive()
                    let bytes: Data
                    switch message {
                    case .data(let d): bytes = d
                    case .string(let s): bytes = Data(s.utf8)
                    @unknown default: throw CocoaError(.coderReadCorrupt)
                    }
                    guard bytes.count < 2_097_152, let object = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { throw CocoaError(.coderReadCorrupt) }
                    if object["id"] as? Int == sequence, let result = object["result"] as? [String: Any] { return result }
                }
                throw CocoaError(.coderReadCorrupt)
            }
            let result = try await read("Target.getTargets")
            guard let targets = result["targetInfos"] as? [[String: Any]], targets.count <= 512 else { return }
            var windows: [Int: BrowserWindowSummary] = [:]
            for target in targets where target["type"] as? String == "page" {
                guard let id = target["targetId"] as? String, let url = target["url"] as? String,
                      let attached = target["attached"] as? Bool else { return }
                let window = try await read("Browser.getWindowForTarget", ["targetId": id])
                guard let number = window["windowId"] as? Int, let bounds = window["bounds"] as? [String: Any] else { return }
                var group = windows[number] ?? BrowserWindowSummary(bounds: bounds)
                group.tabs += 1
                group.empty = group.empty && ["about:blank", "chrome://newtab/", "chrome://new-tab-page/"].contains(url)
                group.attached = group.attached || attached
                windows[number] = group
            }
            reply.value = ["complete": true, "windows": windows.values.map(\.json)]
        } catch {
            let error = error as NSError
            reply.value["error"] = "\(error.domain) \(error.code)"
        }
    }
    if reply.ready.wait(timeout: .now() + 1.5) == .success { output(["ok": true, "data": reply.value]) }
    else { task.cancel(); output(["ok": true, "data": ["complete": false, "windows": []]]) }
}

func nativeCommand(_ command: String, payload: Data? = nil) -> Bool {
    switch command {
    case "displays": output(displays())
    case "browser-context":
        if let payload, let value = try? JSONSerialization.jsonObject(with: payload) as? [String: Any],
           let port = value["port"] as? Int, (1...65535).contains(port) { browserContext(port) }
        else { output(["ok": false, "error": "Invalid local browser port."]) }
    case "inventory":
        let options = payload.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        inventory(allSpaces: options?["all_spaces"] as? Bool ?? false)
    case "permissions": output(["ok": true, "data": ["accessibility": AXIsProcessTrusted(), "screen_recording": CGPreflightScreenCaptureAccess()]])
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
