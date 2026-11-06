import AppKit
import SwiftUI
import ApplicationServices
import Combine

struct Bounds: Decodable, Equatable { let x, y, width, height: Double }
struct PhysicalSize: Decodable, Equatable { let width, height: Double }
struct ScreenInfo: Decodable, Identifiable, Equatable {
    let id, name: String
    let built_in: Bool
    let bounds, usable: Bounds
    let physical_size_mm: PhysicalSize?
    var gather_space: UInt64? = nil
    var diagonal: String? {
        guard let mm = physical_size_mm else { return nil }
        return String(format: "%.0f″", hypot(mm.width, mm.height) / 25.4)
    }
}
struct WindowInfo: Decodable, Identifiable {
    let id, app_name, title: String
    let pid: Int32
    let process_instance: String
    let bounds: Bounds
    let minimized: Bool
    let is_focused: Bool?
    var space_ids: [UInt64]? = nil
    var fullscreen: Bool? = nil
}
struct ActionInfo: Decodable, Identifiable {
    let kind: String
    let window: WindowInfo
    let target: Bounds?
    let display: String?
    var id: String { window.id }
    var label: String {
        switch kind {
        case "move": return "Move & arrange"
        case "close": return "Close"
        default: return "Minimize"
        }
    }
}
struct InventoryInfo: Decodable {
    let displays: [ScreenInfo]
    let windows: [WindowInfo]
    var all_spaces: Bool? = nil
}
struct PlanInfo: Decodable { let inventory: InventoryInfo; let actions: [ActionInfo] }
struct DoctorInfo: Decodable { let accessibility, key_configured, runtime_ready: Bool }
struct PermissionInfo: Decodable { let accessibility, screen_recording: Bool }
struct CoverageInfo: Decodable {
    struct ScanError: Decodable { let app: String }
    let errors: [ScanError]
}
struct ModelInfo: Decodable { let model: String; let latency_ms: Int }
struct PreviewInfo: Decodable {
    let plan_path: String
    let plan: PlanInfo
    let window_count, action_count: Int
    let model: ModelInfo?
    let coverage: CoverageInfo
    func showing(_ check: ApplyInfo.LayoutCheck) -> PreviewInfo {
        let inventory = InventoryInfo(displays: check.displays, windows: check.windows)
        return PreviewInfo(plan_path: plan_path, plan: PlanInfo(inventory: inventory, actions: []), window_count: check.windows.count,
            action_count: 0, model: model, coverage: coverage)
    }
}
struct Envelope<T: Decodable>: Decodable { let ok: Bool; let data: T?; let error: String? }
struct ApplyInfo: Decodable {
    struct Change: Decodable { let ok: Bool; let error: String? }
    struct LayoutCheck: Decodable { let overlap_count: Int; let windows: [WindowInfo]; let displays: [ScreenInfo] }
    let journal_path: String
    let succeeded, failed, planned, apply_ms, closed, arranged, minimized: Int
    let undoable: Bool
    let layout_check: LayoutCheck?
    var results: [Change]? = nil
}
struct UndoInfo: Decodable {
    struct Skip: Decodable { let reason: String }
    let restored: Int
    let skipped: [Skip]
    let unresolved: Int
}
struct Settings: Codable {
    var model = "jev"
    var provider = "gateway"
    var envFile: String? = nil
    var workScreen: String?
    var chatScreen: String?
    var referenceScreen: String?
    var customInstructions: String?
    var allSpaces: Bool?
    var gatherScreen: String?
    var skipWindowPreviews: Bool?
}

enum LayoutPresentation {
    case live(PreviewInfo?), draft(PreviewInfo), stale(PreviewInfo)
    var preview: PreviewInfo? {
        switch self { case .live(let p): return p; case .draft(let p), .stale(let p): return p }
    }
    var isDraft: Bool { if case .draft = self { return true }; return false }
}

struct WorkFocus {
    let pid: pid_t
    let windowID: String
    static func capture(_ app: NSRunningApplication?) -> WorkFocus? {
        guard let app, app.processIdentifier != ProcessInfo.processInfo.processIdentifier,
              !["com.apple.systempreferences", "com.apple.keychainaccess", "com.apple.ActivityMonitor"].contains(app.bundleIdentifier ?? ""),
              let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]],
              let row = rows.first(where: { ($0[kCGWindowOwnerPID as String] as? Int32) == app.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0 }),
              let number = row[kCGWindowNumber as String] as? UInt32 else { return nil }
        return WorkFocus(pid: app.processIdentifier, windowID: "w-\(number)")
    }
}

enum TidyError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let s) = self { return s }; return nil }
}

@MainActor final class Store: ObservableObject {
    let windowPreviews = WindowPreviews()
    let windowPeek = WindowPeek()
    let draftCursor = DraftCursor()
    var draftTargets: [DraftTarget] = []
    @Published var draftTarget: DraftTarget.Kind?
    @Published var liveInventory: InventoryInfo?
    @Published var liveReadOK = false
    private var liveTask: Task<Void, Never>?
    private var desktopRevision = 0
    @Published var presentation = LayoutPresentation.live(nil)
    var preview: PreviewInfo? {
        get { presentation.preview }
        set {
            if let newValue, presentation.isDraft { presentation = .draft(newValue) }
            else { presentation = .live(newValue) }
        }
    }
    @Published var busy = false
    @Published var status = "Ready when you are."
    @Published var error: String?
    @Published var settings = Settings()
    var hasLayout: Bool {
        get { presentation.isDraft }
        set {
            guard let p = preview else { return }
            presentation = newValue ? .draft(p) : p.plan.actions.isEmpty ? .live(p) : .stale(p)
        }
    }
    @Published var editingDraft = false
    @Published var draggedWindowID: String?
    private var instructionSaveTask: Task<Void, Never>?
    private var introducedWindows = Set<String>()
    @Published var journal: String?
    @Published var showingSettings = false
    @Published var onboarding = false
    @Published var permissions = PermissionInfo(accessibility: false, screen_recording: false)
    var accessibility: Bool {
        get { permissions.accessibility }
        set { permissions = PermissionInfo(accessibility: newValue, screen_recording: permissions.screen_recording) }
    }
    @Published var keyConfigured = false
    var workFocus = WorkFocus.capture(NSWorkspace.shared.frontmostApplication)
    let config = ProcessInfo.processInfo.environment["FENLET_CONFIG"].map { URL(fileURLWithPath: $0) }
        ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".config/fenlet/config.json")
    let history = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/state/fenlet/widget-history.json")

    init() {
        if let d = try? Data(contentsOf: config), let s = try? JSONDecoder().decode(Settings.self, from: d) { settings = s }
        if let d = try? Data(contentsOf: history), let h = try? JSONDecoder().decode([String: String].self, from: d) { journal = h["journal"] }
    }
    func startPreviewUpdates() {
        guard liveTask == nil else { return }
        if CommandLine.arguments.contains("--diagnose") { fputs("live preview: started\n", stderr) }
        liveTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if !self.busy && !self.editingDraft && self.draggedWindowID == nil && !self.onboarding && !self.showingSettings {
                    let revision = self.desktopRevision
                    do {
                        let data = try await Self.command(self.scanArguments, settings: self.settings, workFocus: self.workFocus)
                        let response = try JSONDecoder().decode(Envelope<InventoryInfo>.self, from: data)
                        if !Task.isCancelled, !self.busy, !self.editingDraft, revision == self.desktopRevision, response.ok, let inventory = response.data {
                            self.liveReadOK = true
                            if self.hasLayout, let planned = self.preview?.plan.inventory, !Self.sameLayout(planned, inventory) {
                                self.hasLayout = false
                                self.status = "Windows changed. Refresh your layout to continue."
                            }
                            self.liveInventory = inventory
                            self.windowPeek.update(inventory.windows, captures: self.windowPreviews)
                            self.windowPreviews.refresh(inventory.windows, maxAge: 0.9)
                        } else if !Task.isCancelled { self.liveReadOK = false }
                    } catch { if !Task.isCancelled { self.liveReadOK = false } }
                } else if self.onboarding || self.showingSettings {
                    await self.refreshPermission()
                }
                do { try await Task.sleep(nanoseconds: 1_000_000_000) } catch { return }
            }
        }
    }
    func stopPreviewUpdates() {
        liveTask?.cancel(); liveTask = nil; windowPreviews.pause(); windowPeek.hide()
        liveReadOK = false
        if CommandLine.arguments.contains("--diagnose") { fputs("live preview: stopped\n", stderr) }
    }
    static func sameLayout(_ planned: InventoryInfo, _ live: InventoryInfo) -> Bool {
        guard planned.displays == live.displays, planned.windows.count == live.windows.count else { return false }
        let actual = Dictionary(uniqueKeysWithValues: live.windows.map { ($0.id, $0) })
        return planned.windows.allSatisfy { w in
            guard let current = actual[w.id] else { return false }
            return w.pid == current.pid && w.process_instance == current.process_instance && w.bounds == current.bounds && w.minimized == current.minimized && w.space_ids == current.space_ids && w.fullscreen == current.fullscreen
        }
    }
    var layoutRequest: String {
        "Tile current work, chat and useful references using the supplied display preferences. "
        + "Minimize useful background windows. Close idle clutter. Keep the focused window open. "
        + "When coding, place the related work browser beside the active terminal; keep communication separate. "
        + "Additional user preferences take priority: \(settings.customInstructions ?? "")"
    }
    var availableDisplays: [ScreenInfo] { liveInventory?.displays ?? preview?.plan.inventory.displays ?? [] }
    static func panelHeight(for inventory: InventoryInfo?, draft: Bool) -> CGFloat {
        guard let screens = inventory?.displays, !screens.isEmpty else { return 550 }
        let gallery: CGFloat = screens.count == 1 || screens.count > 2 ? 255
            : screens.contains(where: { $0.bounds.height > $0.bounds.width }) ? 231 : 193
        return 330 + gallery + (draft ? 104 : 0)
    }
    var panelHeight: CGFloat { onboarding || showingSettings ? 650 : Self.panelHeight(for: liveInventory, draft: hasLayout) }
    func claimDraftIntroduction(_ id: String) -> Bool { introducedWindows.insert(id).inserted }
    var hasStalePreview: Bool { !hasLayout && preview?.plan.actions.isEmpty == false }
    var hasDraft: Bool { preview?.plan.actions.isEmpty == false }
    func cancelPreview() { desktopRevision += 1; hasLayout = false; preview = nil; draggedWindowID = nil; draftCursor.position = nil; draftTarget = nil; editingDraft = false; status = "Ready to arrange." }
    func target(at point: CGPoint) -> DraftTarget.Kind? {
        let hit = draftTargets.filter { $0.frame.contains(point) }
        return hit.first { if case .pane = $0.kind { return true }; return false }?.kind
            ?? hit.first { if case .disposition = $0.kind { return true }; return false }?.kind
            ?? hit.first?.kind
    }
    func trackDraftDrag(_ window: WindowInfo, at point: CGPoint) {
        guard hasLayout, !busy, !editingDraft else { return }
        if draggedWindowID == nil { windowPeek.hide(); desktopRevision += 1; draggedWindowID = window.id }
        draftCursor.position = DraftCursor.Position(window: window, point: point)
        let next = target(at: point)
        if draftTarget != next { draftTarget = next }
    }
    func finishDraftDrag(_ id: String, at point: CGPoint) {
        let destination = target(at: point)
        draggedWindowID = nil; draftCursor.position = nil; draftTarget = nil
        guard hasLayout, let destination, let actions = preview?.plan.actions else { return }
        switch destination {
        case .pane(let other):
            guard id != other else { return }
            let source = actions.first(where: { $0.id == id }), target = actions.first(where: { $0.id == other })
            if target?.kind == "move", let display = target?.display {
                if source?.kind == "move" { editDraft(["--swap", id, other]) }
                else { editDraft(["--move", id, display]) }
            } else if let kind = target?.kind, kind == "minimize" || kind == "close" {
                editDraft(["--" + kind, id])
            }
        case .display(let display):
            if actions.first(where: { $0.id == id })?.display != display { editDraft(["--move", id, display]) }
        case .disposition(let kind): editDraft(["--" + kind, id])
        }
    }
    var scopeArguments: [String] { settings.allSpaces == true ? ["--all-spaces"] : [] }
    var scanArguments: [String] { ["scan"] + scopeArguments }
    var allSpaces: Binding<Bool> {
        Binding(get: { self.settings.allSpaces == true }, set: { value in
            guard self.settings.allSpaces != value else { return }
            self.settings.allSpaces = value
            self.cancelPreview()
            do { try self.persist() } catch { self.error = error.localizedDescription }
            self.scan(layout: false)
        })
    }
    func destination(_ key: WritableKeyPath<Settings, String?>) -> Binding<String> {
        Binding(get: {
            guard let selected = self.settings[keyPath: key], self.availableDisplays.contains(where: { $0.id == selected }) else { return "auto" }
            return selected
        }, set: {
            guard self.settings[keyPath: key] != $0 else { return }
            self.settings[keyPath: key] = $0; self.desktopRevision += 1; self.hasLayout = false
            do { try self.persist() } catch { self.error = error.localizedDescription }
        })
    }
    var customInstructions: Binding<String> {
        Binding(get: { self.settings.customInstructions ?? "" }, set: {
            guard (self.settings.customInstructions ?? "") != $0 else { return }
            self.settings.customInstructions = $0; self.desktopRevision += 1; self.hasLayout = false
            self.instructionSaveTask?.cancel()
            self.instructionSaveTask = Task {
                do { try await Task.sleep(nanoseconds: 250_000_000); try self.persist() }
                catch is CancellationError { }
                catch { self.error = error.localizedDescription }
            }
        })
    }
    func persist() throws {
        try FileManager.default.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try JSONEncoder().encode(settings).write(to: config, options: [.atomic])
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: config.path)
    }
    func remember(_ path: String) {
        journal = path
    }
    static func command(_ args: [String], settings: Settings, input: String? = nil, workFocus: WorkFocus? = nil) async throws -> Data {
        let root = Bundle.main.resourceURL!
        return try await Task.detached {
            let p = Process()
            p.executableURL = root.appendingPathComponent("bin/fenlet")
            var prefix = ["--json"]
            if let file = settings.envFile, !file.isEmpty { prefix += ["--env-file", file] }
            p.arguments = prefix + args
            p.currentDirectoryURL = root
            var env = ProcessInfo.processInfo.environment
            env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:\(NSHomeDirectory())/.bun/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
            if let focus = workFocus {
                env["FENLET_FRONTMOST_PID"] = String(focus.pid)
                env["FENLET_FRONTMOST_WINDOW_ID"] = focus.windowID
            }
            p.environment = env
            let pipe = Pipe()
            p.standardOutput = pipe
            // CLI reports domain errors as JSON; avoid an unread stderr pipe filling.
            p.standardError = FileHandle.nullDevice
            let stdinPipe = Pipe()
            if input != nil { p.standardInput = stdinPipe }
            try p.run()
            if let input = input { stdinPipe.fileHandleForWriting.write(Data(input.utf8)); try? stdinPipe.fileHandleForWriting.close() }
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit()
            return data
        }.value
    }
    func checkSetup() {
        Task {
            do {
                let d = try await Self.command(["doctor", "--provider", settings.provider], settings: settings)
                let e = try JSONDecoder().decode(Envelope<DoctorInfo>.self, from: d)
                guard e.ok, let result = e.data else { throw TidyError.message(e.error ?? "Could not check setup.") }
                accessibility = result.accessibility; keyConfigured = result.key_configured
                windowPreviews.refreshAuthorization()
                onboarding = !accessibility || !previewsReady || !keyConfigured
                if !onboarding { scan(layout: false) }
            } catch { self.error = error.localizedDescription; onboarding = true }
        }
    }
    func refreshPermission() async {
        do {
            let data = try await Self.command(["doctor", "--permissions-only"], settings: settings)
            let response = try JSONDecoder().decode(Envelope<PermissionInfo>.self, from: data)
            guard !Task.isCancelled else { return }
            guard response.ok, let result = response.data else { throw TidyError.message(response.error ?? "Could not check window control.") }
            if updatePermissions(result) {
                error = nil; scan(layout: false)
            }
        } catch { if !Task.isCancelled { self.error = error.localizedDescription } }
    }
    @discardableResult func updatePermissions(_ result: PermissionInfo) -> Bool {
        permissions = result
        windowPreviews.refreshAuthorization()
        let wasOnboarding = onboarding
        onboarding = !accessibility || !previewsReady || !keyConfigured
        return wasOnboarding && !onboarding
    }
    var previewRestartNeeded: Bool { permissions.screen_recording && !windowPreviews.allowed }
    var previewsReady: Bool { !windowPreviews.supported || windowPreviews.allowed || settings.skipWindowPreviews == true }
    func skipPreviews() {
        settings.skipWindowPreviews = true
        do { try persist(); checkSetup() } catch { self.error = error.localizedDescription }
    }
    func allowWindowControl() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
    }
    func restart() {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/sh")
        task.arguments = ["-c", "sleep 1; /usr/bin/open -n \"$1\" --args --show", "fenlet-restart", Bundle.main.bundlePath]
        do { try task.run(); NSApp.terminate(nil) } catch { self.error = error.localizedDescription }
    }
    func saveKey(_ key: String) async throws {
        let d = try await Self.command(["setup", "--provider", settings.provider, "--key-stdin"], settings: settings, input: key)
        let e = try JSONDecoder().decode(Envelope<DoctorInfo>.self, from: d)
        guard e.ok else { throw TidyError.message(e.error ?? "Could not save the key.") }
        checkSetup()
    }
    func scan(layout: Bool) {
        guard !busy else { return }
        desktopRevision += 1
        let revision = desktopRevision
        busy = true; error = nil; hasLayout = false
        status = layout ? "Preparing your layout…" : "Reading windows…"
        Task {
            defer { busy = false }
            do {
                let data = try await Self.command(layout ? layoutArguments("plan") : scanArguments, settings: settings, workFocus: workFocus)
                guard revision == desktopRevision else { status = "Ready to arrange."; return }
                let inventory: InventoryInfo
                if layout {
                    let response = try JSONDecoder().decode(Envelope<PreviewInfo>.self, from: data)
                    guard response.ok, let result = response.data else { throw TidyError.message(response.error ?? "Could not preview.") }
                    introducedWindows.removeAll()
                    preview = result; inventory = result.plan.inventory; hasLayout = true
                } else {
                    let response = try JSONDecoder().decode(Envelope<InventoryInfo>.self, from: data)
                    guard response.ok, let result = response.data else { throw TidyError.message(response.error ?? "Could not read windows.") }
                    inventory = result
                }
                liveInventory = inventory; liveReadOK = true
                if liveTask != nil { windowPreviews.refresh(inventory.windows) }
                status = layout ? (settings.allSpaces == true && inventory.windows.contains { $0.fullscreen == true }
                    ? "Fullscreen windows will leave fullscreen when you confirm." : "Nothing moves or closes until you confirm.") : "Ready to arrange."
                if layout, preview?.coverage.errors.isEmpty == false { status += " Some windows couldn't be inspected." }
            } catch { self.error = error.localizedDescription; status = "Try refreshing your preview." }
        }
    }
    func layoutArguments(_ command: String) -> [String] {
        let gather = settings.allSpaces == true ? availableDisplays.first { $0.id == settings.gatherScreen } : nil
        return [command, layoutRequest, "--model", settings.model, "--provider", settings.provider,
         "--work-display", settings.workScreen ?? "auto", "--chat-display", settings.chatScreen ?? "auto", "--reference-display", settings.referenceScreen ?? "auto"] + scopeArguments
            + (gather.map { ["--display", $0.id] } ?? [])
    }
    func complete(_ result: ApplyInfo, from before: PreviewInfo, elapsed: Int) {
        presentation = .live(nil)
        if result.undoable { remember(result.journal_path) }
        if let check = result.layout_check {
            preview = before.showing(check)
            liveInventory = InventoryInfo(displays: check.displays, windows: check.windows)
            if liveTask != nil { windowPreviews.refresh(check.windows) }
        }
        status = "\(result.arranged) arranged · \(result.minimized) minimized · \(result.closed) closed · \(String(format: "%.1fs", Double(elapsed) / 1000))"
        if result.arranged + result.minimized + result.closed == 0, result.failed == 0 { status = "Already arranged. · \(String(format: "%.1fs", Double(elapsed) / 1000))" }
        if !before.coverage.errors.isEmpty { status += " Some windows couldn't be inspected." }
        if result.failed > 0 {
            let failures = zip(before.plan.actions, result.results ?? []).filter { !$0.1.ok }
            if let first = failures.first {
                error = "\(first.0.window.app_name): \(first.1.error ?? "Couldn’t apply this change.") Refresh to review."
            } else { error = result.failed == 1 ? "One window couldn’t be changed. Refresh to review." : "\(result.failed) windows couldn’t be changed. Refresh to review." }
        }
        if let check = result.layout_check, check.overlap_count > 0 { error = "\(check.overlap_count) overlapping pairs remain. Refresh to review." }
    }
    func editDraft(_ arguments: [String]) {
        guard !busy, !editingDraft, hasLayout, let before = preview else { return }
        desktopRevision += 1
        let revision = desktopRevision
        editingDraft = true; error = nil; windowPeek.hide()
        // Swap occupants immediately; the shared engine validates and saves the draft.
        if arguments.count == 3, arguments[0] == "--swap",
           let a = before.plan.actions.firstIndex(where: { $0.id == arguments[1] }),
           let b = before.plan.actions.firstIndex(where: { $0.id == arguments[2] }) {
            var actions = before.plan.actions
            let left = actions[a], right = actions[b]
            actions[a] = ActionInfo(kind: left.kind, window: right.window, target: left.target, display: left.display)
            actions[b] = ActionInfo(kind: right.kind, window: left.window, target: right.target, display: right.display)
            preview = PreviewInfo(plan_path: before.plan_path, plan: PlanInfo(inventory: before.plan.inventory, actions: actions),
                                  window_count: before.window_count, action_count: before.action_count, model: before.model, coverage: before.coverage)
        }
        Task {
            defer { editingDraft = false }
            do {
                let data = try await Self.command(["edit", before.plan_path] + arguments, settings: settings)
                guard revision == desktopRevision else { return }
                let response = try JSONDecoder().decode(Envelope<PreviewInfo>.self, from: data)
                guard response.ok, let result = response.data else { throw TidyError.message(response.error ?? "Could not adjust this draft.") }
                preview = result; status = "Draft updated. Your windows haven’t moved yet."
            } catch {
                if revision == desktopRevision { preview = before; self.error = error.localizedDescription }
            }
        }
    }
    func apply() {
        guard !busy, !editingDraft, hasLayout, let preview else { return }
        desktopRevision += 1
        busy = true; error = nil; status = "Arranging windows…"
        Task {
            defer { busy = false; hasLayout = false }
            do {
                let data = try await Self.command(["apply", preview.plan_path, "--yes"], settings: settings)
                let response = try JSONDecoder().decode(Envelope<ApplyInfo>.self, from: data)
                guard response.ok, let result = response.data else { throw TidyError.message(response.error ?? "Could not apply this layout.") }
                complete(result, from: preview, elapsed: result.apply_ms)
            } catch { self.error = error.localizedDescription; status = "Refresh your preview to continue."; hasLayout = false }
        }
    }
    func undo() {
        guard !busy, let journal = journal else { return }
        desktopRevision += 1
        busy = true; error = nil; status = "Putting things back…"
        Task {
            defer { busy = false; hasLayout = false; preview = nil }
            do {
                let d = try await Self.command(["undo", journal], settings: settings)
                let e = try JSONDecoder().decode(Envelope<UndoInfo>.self, from: d)
                guard e.ok, let result = e.data else { throw TidyError.message(e.error ?? "Could not undo.") }
                status = "\(result.restored) changes undone."
                if let skip = result.skipped.first { error = skip.reason }
                if result.unresolved > 0 { error = "An interrupted change needs manual inspection." }
            } catch { self.error = error.localizedDescription }
        }
    }
}

struct AppGlyph: View {
    let name: String
    private var icon: NSImage? {
        if let running = NSWorkspace.shared.runningApplications.first(where: { $0.localizedName == name })?.icon { return running }
        #if FENLET_UI_TEST
        return DemoWindows.appIcon(name)
        #else
        return nil
        #endif
    }
    var body: some View {
        Group {
            if let icon {
                Image(nsImage: icon).resizable().aspectRatio(contentMode: .fit)
            } else { Image(systemName: "app.fill").resizable().aspectRatio(contentMode: .fit).foregroundStyle(.secondary) }
        }.frame(width: 16, height: 16)
    }
}

struct PreviewPane: Identifiable {
    let window: WindowInfo
    let frame: Bounds
    var id: String { window.id }
}

struct WindowThumbnail: View {
    let window: WindowInfo
    @ObservedObject var captures: WindowPreviews
    var body: some View {
        ZStack {
            Color(nsColor: .controlBackgroundColor)
            if let image = captures.image(for: window) {
                Image(nsImage: image).resizable().aspectRatio(contentMode: .fit)
            } else {
                GeometryReader { geometry in
                    VStack(spacing: 5) {
                        AppGlyph(name: window.app_name).scaleEffect(min(1, max(0.1, (geometry.size.height - 8) / 16)))
                        if geometry.size.height >= 42 {
                            Text(window.app_name).font(.system(size: 10, weight: .medium)).lineLimit(1)
                        }
                    }.foregroundStyle(.secondary).frame(width: geometry.size.width, height: geometry.size.height).clipped()
                }
            }
        }.clipped()
    }
}

struct WindowTile: View {
    let window: WindowInfo
    var compact = false
    var editable = false
    @ObservedObject var captures: WindowPreviews
    let inspect: () -> Void
    let hoverChange: (Bool) -> Void
    @State private var hovered = false
    @Environment(\.colorScheme) private var colorScheme
    var outline: Color {
        if hovered { return .accentColor }
        return colorScheme == .dark ? Color.white.opacity(0.14) : Color.black.opacity(0.12)
    }
    var body: some View {
        Button(action: inspect) {
            VStack(spacing: 0) {
                HStack(spacing: 4) {
                    AppGlyph(name: window.app_name).frame(width: 12, height: 12)
                    if !compact {
                        ViewThatFits(in: .horizontal) {
                            Text(window.app_name).font(.system(size: 10, weight: .medium)).fixedSize()
                            Color.clear.frame(width: 0, height: 0)
                        }
                    }
                    Spacer(minLength: 0)
                    if editable { GrabDots() }
                    else if window.fullscreen == true {
                        Image(systemName: "arrow.up.left.and.arrow.down.right").font(.system(size: 8)).foregroundStyle(.secondary).accessibilityLabel("Fullscreen window")
                    } else { Color.clear.frame(width: 8, height: 12).accessibilityHidden(true) }
                }.padding(.horizontal, 5).frame(height: 20)
                    .background(.primary.opacity(colorScheme == .dark ? 0.04 : 0.03))
                WindowThumbnail(window: window, captures: captures)
            }
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay { RoundedRectangle(cornerRadius: 7).strokeBorder(outline, lineWidth: hovered ? 1.5 : 0.5) }
            .shadow(color: .black.opacity(hovered ? 0.18 : 0.08), radius: hovered ? 4 : 2, y: 1)
            .overlay { CursorRegion(cursor: editable ? .openHand : .pointingHand).allowsHitTesting(false) }
        }.buttonStyle(.plain).onHover { hovered = $0; hoverChange($0) }
            .accessibilityLabel("Preview " + window.app_name + ": " + window.title)
            .accessibilityHint(editable ? "Drag to swap panes, move to another display, or change its disposition. Right-click for placement choices." : "Inspect this window")
    }
}

struct DisplayCard: View {
    @ObservedObject var store: Store
    let screen: ScreenInfo
    let inventory: InventoryInfo
    let actions: [ActionInfo]
    let proposed: Bool
    @ObservedObject var captures: WindowPreviews
    let peek: WindowPeek
    let single: Bool
    var panes: [PreviewPane] {
        let changed = proposed ? Set(actions.map(\.id)) : []
        let actual = Dictionary(uniqueKeysWithValues: inventory.windows.map { ($0.id, $0) })
        let current = inventory.windows.filter { w in
            let b = w.bounds, s = screen.bounds
            return !w.minimized && !changed.contains(w.id) && b.x + b.width / 2 >= s.x && b.x + b.width / 2 < s.x + s.width && b.y + b.height / 2 >= s.y && b.y + b.height / 2 < s.y + s.height
        }.map { PreviewPane(window: $0, frame: $0.bounds) }
        let arranged = proposed ? actions.filter { $0.kind == "move" && $0.display == screen.id }.compactMap { a in
            a.target.map { PreviewPane(window: actual[a.id] ?? a.window, frame: $0) }
        } : []
        if !proposed && sourceSpaceCount > 1 {
            // Distinct Spaces have independent coordinates. Show an overview,
            // rather than stacking several fullscreen previews on one rectangle.
            let ordered = current.sorted { $0.id < $1.id }
            let columns = min(3, Int(ceil(sqrt(Double(ordered.count)))))
            let rows = (ordered.count + columns - 1) / columns
            let area = screen.usable, gap = 12.0
            let width = (area.width - gap * Double(columns + 1)) / Double(columns)
            let height = (area.height - gap * Double(rows + 1)) / Double(rows)
            return ordered.enumerated().map { index, pane in
                PreviewPane(window: pane.window, frame: Bounds(x: area.x + gap + Double(index % columns) * (width + gap),
                    y: area.y + gap + Double(index / columns) * (height + gap), width: width, height: height))
            }
        }
        // CG lists frontmost first; draw it last to preserve actual stacking.
        return Array(current.reversed()) + arranged
    }
    var sourceSpaceCount: Int {
        let windows = inventory.windows.filter { w in
            let b = w.bounds, s = screen.bounds
            return !w.minimized && b.x + b.width / 2 >= s.x && b.x + b.width / 2 < s.x + s.width
                && b.y + b.height / 2 >= s.y && b.y + b.height / 2 < s.y + s.height
        }
        return Set(windows.flatMap { $0.space_ids ?? [] }).count
    }
    func show(_ window: WindowInfo) {
        captures.prioritize([window], in: inventory.windows)
        peek.show(window, captures: captures)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 5) {
                Image(systemName: screen.built_in ? "laptopcomputer" : "display").foregroundStyle(.secondary)
                Text(!proposed && sourceSpaceCount > 1 ? "\(screen.name) · \(sourceSpaceCount) Spaces" : screen.name).lineLimit(1).help(screen.name)
                Spacer(minLength: 2)
                Text("\(panes.count)").foregroundStyle(.secondary).monospacedDigit()
            }.font(.system(size: 10, weight: .medium))
            GeometryReader { geo in
                let area = screen.usable
                let scale = min(geo.size.width / area.width, geo.size.height / area.height)
                ZStack(alignment: .topLeading) {
                    Color(nsColor: .underPageBackgroundColor).opacity(0.6)
                    ForEach(panes) { pane in
                        WindowTile(window: pane.window, compact: pane.frame.width * scale < 90, editable: proposed, captures: captures, inspect: { show(pane.window) }, hoverChange: { inside in
                            if inside && store.draggedWindowID == nil { peek.schedule(pane.window, captures: captures, in: inventory.windows) } else { peek.hide() }
                        })
                            .modifier(DraftTileInteractions(store: store, window: pane.window))
                            .frame(width: max(2, pane.frame.width * scale), height: max(2, pane.frame.height * scale))
                            .offset(x: (pane.frame.x - area.x) * scale, y: (pane.frame.y - area.y) * scale)
                    }
                    if panes.isEmpty {
                        Text(proposed ? "Drop a window here" : "No windows").font(.system(size: 10)).foregroundStyle(.tertiary)
                            .frame(width: area.width * scale, height: area.height * scale)
                    }
                }.frame(width: area.width * scale, height: area.height * scale)
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .contentShape(Rectangle())
                    .modifier(DraftTargetRegion(kind: .display(screen.id)))
            }.frame(height: single ? 182 : screen.bounds.height > screen.bounds.width ? 148 : 110)
        }.padding(10).background(.quaternary.opacity(0.2), in: RoundedRectangle(cornerRadius: 17))
            .overlay { RoundedRectangle(cornerRadius: 17).strokeBorder(store.draftTarget == .display(screen.id) ? Color.accentColor : .primary.opacity(0.06), lineWidth: 1) }
    }
}

struct DisplayGallery: View {
    @ObservedObject var store: Store
    @ObservedObject var captures: WindowPreviews
    var body: some View {
        if let inventory = store.liveInventory {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(store.hasLayout ? "Drag to edit your layout" : "Your windows").font(.system(size: 11, weight: .medium))
                    Spacer()
                    if !store.hasLayout { Text(store.liveReadOK ? "Live" : "Updating…").font(.system(size: 10)).foregroundStyle(.secondary) }
                }
                ScrollView {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8, alignment: .top), count: inventory.displays.count == 1 ? 1 : 2), spacing: 8) {
                        ForEach(inventory.displays) { screen in
                            DisplayCard(store: store, screen: screen, inventory: inventory, actions: store.preview?.plan.actions ?? [], proposed: store.hasLayout,
                                        captures: captures, peek: store.windowPeek, single: inventory.displays.count == 1)
                        }
                    }
                    .padding(.trailing, inventory.displays.count > 2 ? 8 : 0)
                }.scrollIndicators(inventory.displays.count > 2 ? .visible : .hidden)
                Text(store.hasLayout ? "Drag a window to swap, move, or keep it visible" : "Hover a window for a closer look")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }.frame(maxHeight: .infinity, alignment: .top)
        } else {
            HStack(spacing: 10) { ProgressView().controlSize(.small); Text("Reading your windows…").font(.system(size: 12)).foregroundStyle(.secondary) }
                .frame(maxWidth: .infinity, minHeight: 130)
        }
    }
}

struct TidyButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 13, weight: .semibold))
            .foregroundStyle(.white.opacity(enabled ? 1 : 0.5))
            .frame(maxWidth: .infinity).frame(height: 40)
            .background(Color.accentColor.opacity(enabled ? 1 : 0.35), in: RoundedRectangle(cornerRadius: 11))
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.96 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

struct Panel: View {
    @ObservedObject var store: Store
    var modelTitle: String { store.settings.model == "jev" ? "Jev 1.14" : store.settings.model == "hybrid" ? "Jev + Nemotron" : store.settings.model.capitalized }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(nsImage: FenletBrand.widgetMark).renderingMode(.template).resizable().frame(width: 22, height: 22).foregroundStyle(Color.accentColor).accessibilityHidden(true)
                Text("Fenlet").font(.system(size: 16, weight: .semibold))
                Spacer()
                if store.hasDraft && !store.showingSettings {
                    Button { store.windowPeek.hide(); store.cancelPreview() } label: { Text("Cancel").frame(minWidth: 52, minHeight: 40).contentShape(Rectangle()) }
                        .buttonStyle(.plain).font(.system(size: 12)).foregroundStyle(.secondary).disabled(store.busy || store.editingDraft)
                        .accessibilityLabel("Cancel preview")
                }
                Button { store.windowPeek.hide(); store.showingSettings.toggle() } label: {
                    Image(systemName: store.showingSettings ? "xmark" : "gearshape").frame(width: 40, height: 40).contentShape(Rectangle())
                }.buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel(store.showingSettings ? "Back to windows" : "Settings")
                    .disabled(store.busy || store.editingDraft)
            }
            if store.onboarding || store.showingSettings {
                ScrollView { SettingsPanel(store: store).padding(.vertical, 4) }
            } else {
                HStack(spacing: 10) {
                    Picker("Window scope", selection: store.allSpaces) {
                        Text("Current Space").tag(false)
                        Text("All Spaces").tag(true)
                    }.pickerStyle(.segmented).labelsHidden().controlSize(.small).frame(width: 214).accessibilityLabel("Window scope")
                    if store.settings.allSpaces == true {
                        Picker("Gather destination", selection: store.destination(\.gatherScreen)) {
                            Text("Use display roles").tag("auto")
                            ForEach(store.availableDisplays) { screen in
                                Text(screen.built_in ? "Laptop" : screen.name).tag(screen.id)
                            }
                        }.labelsHidden().controlSize(.small)
                    } else { Spacer(minLength: 0) }
                }.disabled(store.busy || store.editingDraft)
                DisplayGallery(store: store, captures: store.windowPreviews)
                    .frame(maxHeight: .infinity)
                if store.hasLayout {
                    HStack(spacing: 8) {
                        DraftTray(store: store, kind: "minimize")
                        DraftTray(store: store, kind: "close")
                    }
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("How do you want to work?").font(.system(size: 11, weight: .medium))
                    TextField("Keep my browser beside my terminal…", text: store.customInstructions, axis: .vertical)
                        .lineLimit(2...2).textFieldStyle(.plain).font(.system(size: 12))
                        .padding(10).background(.quaternary.opacity(0.2), in: RoundedRectangle(cornerRadius: 10))
                        .accessibilityLabel("Layout instructions")
                }.disabled(store.busy || store.editingDraft)
                Button {
                    store.windowPeek.hide()
                    if store.hasLayout { store.apply() } else { store.scan(layout: true) }
                } label: {
                    HStack(spacing: 8) {
                        if store.busy || store.editingDraft { ProgressView().controlSize(.small).tint(.white) }
                        Text(store.busy ? "Preparing…" : store.editingDraft ? "Updating draft…" : store.hasLayout ? "Confirm arrangement" : store.hasStalePreview ? "Refresh arrangement" : "Arrange windows")
                    }
                }.buttonStyle(TidyButtonStyle()).disabled(store.busy || store.editingDraft)
                Text(store.error ?? store.status).font(.system(size: 10))
                    .foregroundStyle(store.error == nil ? Color.secondary : .orange).lineLimit(2)
                    .frame(maxWidth: .infinity, minHeight: 24, maxHeight: 24, alignment: .topLeading)
                HStack(spacing: 6) {
                    Menu {
                        ForEach(store.settings.provider == "gateway" ? ["jev", "hybrid", "nemotron", "beam"] : ["nemotron", "beam"], id: \.self) { model in
                            Button(model == "jev" ? "Jev 1.14" : model == "hybrid" ? "Jev + Nemotron" : model.capitalized) {
                                store.settings.model = model; store.hasLayout = false
                                do { try store.persist() } catch { store.error = error.localizedDescription }
                            }
                        }
                    } label: { Label(modelTitle, systemImage: "bolt.fill").frame(minHeight: 40).contentShape(Rectangle()) }.menuStyle(.borderlessButton).fixedSize().disabled(store.busy || store.editingDraft)
                    if let ms = store.preview?.model?.latency_ms { Text(ms == 0 ? "Cached" : String(format: "%.2fs", Double(ms) / 1000)).foregroundStyle(.tertiary).monospacedDigit() }
                    Spacer()
                    Button { store.windowPeek.hide(); store.undo() } label: { Label("Undo", systemImage: "arrow.uturn.backward").frame(minWidth: 60, minHeight: 40).contentShape(Rectangle()) }
                        .buttonStyle(.plain).disabled(store.busy || store.editingDraft || store.journal == nil)
                    Menu { Button("Quit Fenlet") { NSApp.terminate(nil) } } label: { Image(systemName: "ellipsis").frame(width: 40, height: 40).contentShape(Rectangle()) }
                        .menuStyle(.borderlessButton).fixedSize().accessibilityLabel("More")
                }.font(.system(size: 11)).foregroundStyle(.secondary).frame(height: 40)
            }
        }.padding(16).frame(width: 420, height: store.panelHeight).background(Color(nsColor: .windowBackgroundColor))
            .coordinateSpace(name: "fenletDraft")
            .onPreferenceChange(DraftTargets.self) { store.draftTargets = $0 }
            .overlay(alignment: .topLeading) { DraftGhost(cursor: store.draftCursor, captures: store.windowPreviews).allowsHitTesting(false) }
    }
}

struct DisplayPreferences: View {
    @ObservedObject var store: Store
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Display preferences").font(.system(size: 12, weight: .semibold))
            placement("Work", icon: "briefcase", selection: store.destination(\.workScreen))
            placement("Chat", icon: "bubble.left.and.bubble.right", selection: store.destination(\.chatScreen))
            placement("References", icon: "book", selection: store.destination(\.referenceScreen))
            Text("Automatic adapts to every connected display, including a single screen.").font(.system(size: 10)).foregroundStyle(.secondary)
        }.padding(12).background(.quaternary.opacity(0.2), in: RoundedRectangle(cornerRadius: 12))
    }
    private func placement(_ title: String, icon: String, selection: Binding<String>) -> some View {
        HStack {
            Label(title, systemImage: icon).font(.system(size: 11))
            Spacer()
            Picker(title, selection: selection) {
                Text("Automatic").tag("auto")
                ForEach(store.availableDisplays) { screen in Text(screen.name).tag(screen.id) }
            }.labelsHidden().frame(maxWidth: 190).accessibilityLabel(title + " display")
        }
    }
}

struct PermissionSetup: View {
    @ObservedObject var store: Store
    @ObservedObject var captures: WindowPreviews
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if store.onboarding {
                Text("A little setup. A lot more room.").font(.system(size: 20, weight: .semibold))
                Text("Allow these two things once. Fenlet will notice when you’re ready.")
                    .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            permissionCard(title: "Control your windows", icon: "rectangle.on.rectangle", allowed: store.accessibility,
                detail: "Move, resize, and minimize windows. Nothing changes until you confirm.",
                button: "Allow window control", action: store.allowWindowControl)
            if captures.supported {
                permissionCard(title: "See your window previews", icon: "macwindow", allowed: captures.allowed,
                    detail: "Screen Recording lets you see real windows as you arrange them. Previews stay on your Mac.",
                    button: store.previewRestartNeeded ? "Restart Fenlet for previews" : "Allow window previews", action: {
                        if store.previewRestartNeeded { store.restart(); return }
                        store.settings.skipWindowPreviews = false
                        try? store.persist()
                        captures.enable()
                    })
                if !captures.allowed {
                    Text(store.previewRestartNeeded ? "Permission is on. Restart Fenlet to finish setting up previews." : "Turn on Fenlet in Screen & System Audio Recording. Choose Quit & Reopen if macOS asks.")
                        .font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Already enabled? Restart Fenlet", action: store.restart)
                        Spacer()
                        Button("Skip previews", action: store.skipPreviews)
                    }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary).frame(minHeight: 40)
                }
            }
            if store.onboarding {
                Label("Everything is included. No other tools to install.", systemImage: "checkmark.circle")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }
    private func permissionCard(title: String, icon: String, allowed: Bool, detail: String, button: String, action: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: allowed ? "checkmark.circle.fill" : icon)
                    .font(.system(size: 20)).foregroundStyle(allowed ? Color.green : .accentColor).frame(width: 26)
                Text(title).font(.system(size: 13, weight: .semibold))
                Spacer()
                if allowed { Text("Allowed").font(.system(size: 11, weight: .medium)).foregroundStyle(.green) }
            }
            if !allowed {
                Text(detail).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Button(action: action) { Text(button).frame(maxWidth: .infinity, minHeight: 40) }
                    .buttonStyle(.borderedProminent).controlSize(.large)
            }
        }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 16))
    }
}

struct SettingsPanel: View {
    @ObservedObject var store: Store
    @State private var apiKey = ""
    @State private var saving = false
    @State private var cliInstalled = false
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if store.onboarding && (!store.accessibility || !store.previewsReady) {
                PermissionSetup(store: store, captures: store.windowPreviews)
            } else {
            if store.onboarding {
                Text("Connect your planner").font(.system(size: 20, weight: .semibold))
                Text("Your Mac is ready. Add a key to plan your first layout.").font(.system(size: 12)).foregroundStyle(.secondary)
            } else {
                PermissionSetup(store: store, captures: store.windowPreviews)
            }
            if !store.onboarding { DisplayPreferences(store: store) }
            VStack(alignment: .leading, spacing: 10) {
                Picker("Provider", selection: $store.settings.provider) {
                    Text("Vercel AI Gateway").tag("gateway")
                    Text("OpenRouter").tag("openrouter")
                }
                if store.keyConfigured { Label("Provider connected", systemImage: "checkmark.circle.fill").foregroundStyle(.green) }
                SecureField(store.keyConfigured ? "Replace API key (optional)" : "API key", text: $apiKey)
                    .textFieldStyle(.roundedBorder)
                Link("Get an API key ↗", destination: URL(string: store.settings.provider == "gateway" ? "https://vercel.com/ai-gateway" : "https://openrouter.ai/keys")!)
                    .font(.system(size: 11))
                Text("Keys stay in Keychain. Layout requests send app names and window titles; file contents stay on your Mac.")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }
            HStack {
                Label(cliInstalled ? "CLI & skill installed" : "Terminal & agents", systemImage: "terminal")
                Spacer()
                if !cliInstalled {
                    Button("Install CLI & skill") {
                        Task {
                            do {
                                let data = try await Store.command(["setup", "--provider", store.settings.provider, "--install-cli", "--install-skill"], settings: store.settings)
                                let response = try JSONDecoder().decode(Envelope<DoctorInfo>.self, from: data)
                                guard response.ok else { throw TidyError.message(response.error ?? "Could not install CLI.") }
                                cliInstalled = true
                            } catch { store.error = error.localizedDescription }
                        }
                    }.controlSize(.small)
                }
            }
            if cliInstalled { Text("Run fenlet in a new Terminal.").font(.system(size: 10)).foregroundStyle(.secondary) }
            Button {
                saving = true
                Task {
                    defer { saving = false }
                    do {
                        if !apiKey.isEmpty { try await store.saveKey(apiKey); apiKey = "" }
                        if store.settings.provider == "openrouter" && ["jev", "hybrid"].contains(store.settings.model) { store.settings.model = "nemotron" }
                        try store.persist(); store.preview = nil; store.hasLayout = false
                        store.showingSettings = false; store.checkSetup()
                    } catch { store.error = error.localizedDescription }
                }
            } label: {
                Text(saving ? "Connecting…" : store.onboarding ? "Save & check setup" : "Done").frame(maxWidth: .infinity, minHeight: 26)
            }.buttonStyle(.borderedProminent).controlSize(.large).disabled(saving)
            }
            if let error = store.error { Text(error).font(.system(size: 11)).foregroundStyle(.orange) }
            if store.onboarding { Button("Quit Fenlet") { NSApp.terminate(nil) }.buttonStyle(.plain).font(.system(size: 10)).foregroundStyle(.secondary) }
        }.font(.system(size: 12))
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate, NSWindowDelegate {
    let store = Store()
    var item: NSStatusItem!
    let popover = NSPopover()
    var previewWindow: NSWindow?
    private var sizeWatcher: AnyCancellable?
    private var focusObserver: NSObjectProtocol?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        focusObserver = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] event in
            MainActor.assumeIsolated {
                if let focus = WorkFocus.capture(event.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication) { self?.store.workFocus = focus }
            }
        }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            let icon = FenletBrand.mark(size: 20, template: true)
            button.image = icon
            button.target = self; button.action = #selector(toggle)
            button.toolTip = "Fenlet"
        }
        popover.behavior = .transient
        popover.delegate = self
        let host = NSHostingController(rootView: Panel(store: store))
        host.sizingOptions = [.preferredContentSize]
        popover.contentViewController = host
        popover.contentSize = NSSize(width: 420, height: store.panelHeight)
        if CommandLine.arguments.contains("--preview-window") {
            let window = NSWindow(contentRect: NSRect(x: 900, y: 180, width: 420, height: store.panelHeight), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "Fenlet"
            window.contentView = NSHostingView(rootView: Panel(store: store))
            window.isReleasedWhenClosed = false; window.makeKeyAndOrderFront(nil)
            window.delegate = self
            previewWindow = window; NSApp.activate(ignoringOtherApps: true)
            store.startPreviewUpdates()
        }
        sizeWatcher = store.objectWillChange.debounce(for: .milliseconds(10), scheduler: RunLoop.main).sink { [weak self] _ in
            guard let self else { return }
            let height = self.store.panelHeight
            guard abs(self.popover.contentSize.height - height) > 0.5 || self.previewWindow.map({ abs($0.contentLayoutRect.height - height) > 0.5 }) == true else { return }
            self.popover.contentSize = NSSize(width: 420, height: height)
            if let window = self.previewWindow {
                let top = window.frame.maxY
                window.setContentSize(NSSize(width: 420, height: height))
                window.setFrameOrigin(NSPoint(x: window.frame.minX, y: top - window.frame.height))
            }
        }
        // Launch and live updates only read. Arrange prepares a draft; Confirm applies it.
        store.checkSetup()
        if CommandLine.arguments.contains("--show") { DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.present() } }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        present()
        return true
    }
    func popoverDidShow(_ notification: Notification) { store.startPreviewUpdates() }
    func popoverDidClose(_ notification: Notification) { store.stopPreviewUpdates() }
    func windowWillClose(_ notification: Notification) {
        if notification.object as? NSWindow === previewWindow { store.stopPreviewUpdates() }
    }
    func windowDidMiniaturize(_ notification: Notification) { store.stopPreviewUpdates() }
    func windowDidDeminiaturize(_ notification: Notification) { store.startPreviewUpdates() }
    func present() { if !popover.isShown, item != nil { toggle() } }
    @objc func toggle() {
        if popover.isShown { popover.performClose(nil) }
        else if let button = item.button {
            if let focus = WorkFocus.capture(NSWorkspace.shared.frontmostApplication) { store.workFocus = focus }
            NSApp.activate(ignoringOtherApps: true)
            popover.contentViewController?.view.layoutSubtreeIfNeeded()
            if let size = popover.contentViewController?.view.fittingSize, size.height > 0 { popover.contentSize = size }
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            if CommandLine.arguments.contains("--diagnose") {
                fputs("popover shown=\(popover.isShown) size=\(popover.contentSize) anchor=\(String(describing: button.window?.frame))\n", stderr)
            }
        }
    }
}

#if !FENLET_UI_TEST
@main struct Fenlet {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
#endif
