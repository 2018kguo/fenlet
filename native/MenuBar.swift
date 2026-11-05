import AppKit
import SwiftUI
import ApplicationServices

struct Bounds: Decodable { let x, y, width, height: Double }
struct ScreenInfo: Decodable, Identifiable {
    let id, name: String
    let built_in: Bool
    let bounds, usable: Bounds
}
struct WindowInfo: Decodable, Identifiable {
    let id, app_name, title: String
    let bounds: Bounds
    let minimized: Bool
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
    let days: Int
}
struct PlanInfo: Decodable { let inventory: InventoryInfo; let actions: [ActionInfo] }
struct DoctorInfo: Decodable { let accessibility, key_configured, runtime_ready: Bool }
struct CoverageInfo: Decodable {
    struct ScanError: Decodable { let app: String }
    let errors: [ScanError]
}
struct ModelInfo: Decodable { let model: String; let latency_ms: Int }
struct PreviewInfo: Decodable {
    let plan_path: String
    let plan: PlanInfo
    let window_count, action_count: Int
    let screenshot_count, screenshot_bytes: Int?
    let model: ModelInfo?
    let coverage: CoverageInfo
    func showing(_ check: ApplyInfo.LayoutCheck) -> PreviewInfo {
        let inventory = InventoryInfo(displays: check.displays, windows: check.windows, days: plan.inventory.days)
        return PreviewInfo(plan_path: plan_path, plan: PlanInfo(inventory: inventory, actions: []), window_count: check.windows.count,
            action_count: 0, screenshot_count: screenshot_count, screenshot_bytes: screenshot_bytes, model: model, coverage: coverage)
    }
}
struct Envelope<T: Decodable>: Decodable { let ok: Bool; let data: T?; let error: String? }
struct ApplyInfo: Decodable {
    struct LayoutCheck: Decodable { let overlap_count: Int; let windows: [WindowInfo]; let displays: [ScreenInfo] }
    let journal_path: String
    let succeeded, failed, planned, apply_ms, closed, arranged, minimized: Int
    let undoable: Bool
    let layout_check: LayoutCheck?
}
struct TidyInfo: Decodable { let preview: PreviewInfo; let result: ApplyInfo; let elapsed_ms: Int }
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
}

enum TidyError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let s) = self { return s }; return nil }
}

@MainActor final class Store: ObservableObject {
    @Published var preview: PreviewInfo?
    @Published var filePreview: PreviewInfo?
    @Published var busy = false
    @Published var status = "Ready when you are."
    @Published var error: String?
    @Published var settings = Settings()
    @Published var hasLayout = false
    @Published var journal: String?
    @Published var journalScope = "windows"
    @Published var showingSettings = false
    @Published var screenshotDays = 30
    @Published var onboarding = false
    @Published var accessibility = false
    @Published var keyConfigured = false
    var frontmostPid = NSWorkspace.shared.frontmostApplication?.processIdentifier
    let config = ProcessInfo.processInfo.environment["DESK_TIDY_CONFIG"].map { URL(fileURLWithPath: $0) }
        ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".config/desk-tidy/config.json")
    let history = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/state/desk-tidy/widget-history.json")

    init() {
        if let d = try? Data(contentsOf: config), let s = try? JSONDecoder().decode(Settings.self, from: d) { settings = s }
        if let d = try? Data(contentsOf: history), let h = try? JSONDecoder().decode([String: String].self, from: d) { journal = h["journal"]; journalScope = h["scope"] ?? "windows" }
    }
    var layoutRequest: String {
        "Tile current work, chat and useful references using the supplied display preferences. "
        + "Minimize useful background windows. Close idle clutter. Keep the focused window open. "
        + "When coding, place the related work browser beside the active terminal; keep communication separate. "
        + "Additional user preferences take priority: \(settings.customInstructions ?? "")"
    }
    func destination(_ key: WritableKeyPath<Settings, String?>) -> Binding<String> {
        Binding(get: {
            guard let selected = self.settings[keyPath: key], self.preview?.plan.inventory.displays.contains(where: { $0.id == selected }) == true else { return "auto" }
            return selected
        }, set: {
            self.settings[keyPath: key] = $0; self.hasLayout = false
            do { try self.persist() } catch { self.error = error.localizedDescription }
        })
    }
    var customInstructions: Binding<String> {
        Binding(get: { self.settings.customInstructions ?? "" }, set: {
            self.settings.customInstructions = $0; self.hasLayout = false
            do { try self.persist() } catch { self.error = error.localizedDescription }
        })
    }
    func persist() throws {
        try FileManager.default.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try JSONEncoder().encode(settings).write(to: config, options: [.atomic])
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: config.path)
    }
    func remember(_ path: String, scope: String) {
        journal = path; journalScope = scope
        do {
            try FileManager.default.createDirectory(at: history.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try JSONEncoder().encode(["journal": path, "scope": scope]).write(to: history, options: [.atomic])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: history.path)
        } catch { self.error = error.localizedDescription }
    }
    static func command(_ args: [String], settings: Settings, input: String? = nil, frontmostPid: pid_t? = nil) async throws -> Data {
        let root = Bundle.main.resourceURL!
        return try await Task.detached {
            let p = Process()
            p.executableURL = root.appendingPathComponent("bin/desk-tidy")
            var prefix = ["--json"]
            if let file = settings.envFile, !file.isEmpty { prefix += ["--env-file", file] }
            p.arguments = prefix + args
            p.currentDirectoryURL = root
            var env = ProcessInfo.processInfo.environment
            env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:\(NSHomeDirectory())/.bun/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
            if let pid = frontmostPid { env["DESK_TIDY_FRONTMOST_PID"] = String(pid) }
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
                onboarding = !accessibility || !keyConfigured
                if !onboarding { scan(layout: false) }
            } catch { self.error = error.localizedDescription; onboarding = true }
        }
    }
    func saveKey(_ key: String) async throws {
        let d = try await Self.command(["setup", "--provider", settings.provider, "--key-stdin"], settings: settings, input: key)
        let e = try JSONDecoder().decode(Envelope<DoctorInfo>.self, from: d)
        guard e.ok else { throw TidyError.message(e.error ?? "Could not save the key.") }
        checkSetup()
    }
    func scan(layout: Bool, onReady: (() -> Void)? = nil) {
        guard !busy else { return }
        busy = true; error = nil; hasLayout = false
        status = layout ? "Finding a little more room…" : "Taking a look around…"
        let args = layout ? layoutArguments("plan") : ["cleanup", "--days", String(screenshotDays)]
        Task {
            defer { busy = false }
            do {
                let d = try await Self.command(args, settings: settings, frontmostPid: frontmostPid)
                let e = try JSONDecoder().decode(Envelope<PreviewInfo>.self, from: d)
                guard e.ok, let result = e.data else { throw TidyError.message(e.error ?? "Could not preview. Try again.") }
                if layout { preview = result }
                else { filePreview = result; if preview == nil { preview = result } }
                hasLayout = layout
                status = layout ? "\(result.action_count) window changes ready to review." : "\(result.window_count) windows across \(result.plan.inventory.displays.count) displays."
                onReady?()
            } catch { self.error = error.localizedDescription; status = "Nothing changed." }
        }
    }
    func layoutArguments(_ command: String) -> [String] {
        [command, layoutRequest, "--model", settings.model, "--provider", settings.provider, "--days", String(screenshotDays),
         "--work-display", settings.workScreen ?? "auto", "--chat-display", settings.chatScreen ?? "auto", "--reference-display", settings.referenceScreen ?? "auto"]
    }
    func complete(_ result: ApplyInfo, scope: String, from before: PreviewInfo, elapsed: Int) {
        if result.undoable { remember(result.journal_path, scope: scope) }
        if let check = result.layout_check { preview = before.showing(check) }
        if scope == "screenshots" { filePreview = nil }
        status = scope == "windows" ? "\(result.arranged) arranged · \(result.minimized) minimized · \(result.closed) closed · \(String(format: "%.1fs", Double(elapsed) / 1000))" : "\(result.succeeded) screenshots moved to Trash."
        if scope == "windows", result.arranged + result.minimized + result.closed == 0, result.failed == 0 { status = "Already tidy. · \(String(format: "%.1fs", Double(elapsed) / 1000))" }
        if result.failed > 0 { error = "\(result.failed) windows couldn’t be changed. Preview to review them." }
        if let check = result.layout_check, check.overlap_count > 0 { error = "\(check.overlap_count) overlapping window pairs remain. Preview to review." }
    }
    func tidy() {
        guard !busy else { return }
        busy = true; error = nil; hasLayout = false; status = "Arranging windows…"
        Task {
            defer { busy = false }
            do {
                let data = try await Self.command(layoutArguments("tidy") + ["--yes"], settings: settings, frontmostPid: frontmostPid)
                let response = try JSONDecoder().decode(Envelope<TidyInfo>.self, from: data)
                guard response.ok, let result = response.data else { throw TidyError.message(response.error ?? "Could not arrange windows.") }
                complete(result.result, scope: "windows", from: result.preview, elapsed: result.elapsed_ms)
            } catch { self.error = error.localizedDescription; status = "Preview to review your windows." }
        }
    }
    func apply(scope: String) {
        guard !busy, let preview = scope == "screenshots" ? filePreview : preview else { return }
        busy = true; error = nil
        status = scope == "windows" ? "Making room…" : "Moving old screenshots to Trash…"
        let path = preview.plan_path
        Task {
            defer { busy = false; hasLayout = false }
            do {
                let d = try await Self.command(["apply", path, "--scope", scope, "--yes"], settings: settings)
                let e = try JSONDecoder().decode(Envelope<ApplyInfo>.self, from: d)
                guard e.ok, let result = e.data else { throw TidyError.message(e.error ?? "Could not apply the preview.") }
                complete(result, scope: scope, from: preview, elapsed: result.apply_ms)
            } catch { self.error = error.localizedDescription; status = "Make a fresh preview to continue." }
        }
    }
    func undo() {
        guard !busy, let journal = journal else { return }
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
    var body: some View {
        Group {
            if let icon = NSWorkspace.shared.runningApplications.first(where: { $0.localizedName == name })?.icon {
                Image(nsImage: icon).resizable().aspectRatio(contentMode: .fit)
            } else { Image(systemName: "app.fill").resizable().aspectRatio(contentMode: .fit).foregroundStyle(.secondary) }
        }.frame(width: 16, height: 16)
    }
}

struct DisplayCard: View {
    let screen: ScreenInfo
    let windows: [WindowInfo]
    let actions: [ActionInfo]
    let proposed: Bool
    var arranged: [ActionInfo] { actions.filter { $0.kind == "move" && $0.display == screen.id } }
    var visibleHere: [WindowInfo] {
        windows.filter { w in
            let b = w.bounds, s = screen.bounds
            return !w.minimized && b.x + b.width / 2 >= s.x && b.x + b.width / 2 < s.x + s.width && b.y + b.height / 2 >= s.y && b.y + b.height / 2 < s.y + s.height
        }
    }
    var count: Int {
        visibleHere.count
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 6) {
                Image(systemName: screen.built_in ? "laptopcomputer" : "display").font(.system(size: 13))
                    .foregroundStyle(screen.built_in ? Color.teal : Color.accentColor)
                Text(screen.name).font(.system(size: 11, weight: .semibold)).lineLimit(1).help(screen.name)
                Spacer(minLength: 0)
            }
            if proposed {
                GeometryReader { geo in
                    let area = screen.usable
                    ZStack(alignment: .topLeading) {
                        RoundedRectangle(cornerRadius: 7).fill(.black.opacity(0.12))
                        ForEach(arranged) { action in
                            if let b = action.target {
                                RoundedRectangle(cornerRadius: 4).fill(Color.accentColor.opacity(0.2))
                                    .overlay { AppGlyph(name: action.window.app_name) }
                                    .frame(width: max(4, b.width / area.width * geo.size.width), height: max(4, b.height / area.height * geo.size.height))
                                    .offset(x: (b.x - area.x) / area.width * geo.size.width, y: (b.y - area.y) / area.height * geo.size.height)
                                    .help(action.window.app_name + " · " + action.window.title)
                            }
                        }
                    }
                }.frame(height: 66)
                Text("\(arranged.count) windows").font(.system(size: 10)).foregroundStyle(.secondary).monospacedDigit()
            } else {
                GeometryReader { geo in
                    let area = screen.usable
                    ZStack(alignment: .topLeading) {
                        RoundedRectangle(cornerRadius: 7).fill(.black.opacity(0.12))
                        ForEach(visibleHere) { w in
                            let b = w.bounds
                            RoundedRectangle(cornerRadius: 4).fill(Color.accentColor.opacity(0.2)).overlay { AppGlyph(name: w.app_name) }
                                .frame(width: max(4, b.width / area.width * geo.size.width), height: max(4, b.height / area.height * geo.size.height))
                                .offset(x: (b.x - area.x) / area.width * geo.size.width, y: (b.y - area.y) / area.height * geo.size.height)
                        }
                    }.clipped()
                }.frame(height: 66)
                Text("\(count) open").font(.system(size: 10)).foregroundStyle(.secondary).monospacedDigit()
            }
        }.frame(maxWidth: .infinity).frame(height: 108, alignment: .topLeading)
            .padding(11).background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 12))
    }
}

struct Panel: View {
    @ObservedObject var store: Store
    @State private var confirmCleanup = false
    @State private var showChanges = false
    @State private var showCustom = false
    var modelTitle: String { store.settings.model == "jev" ? "Jev 1.14" : store.settings.model == "hybrid" ? "Jev + Nemotron" : store.settings.model.capitalized }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 9) {
                Image(systemName: "rectangle.3.group.fill").font(.system(size: 19)).foregroundStyle(Color.accentColor)
                Text("Desk Tidy").font(.system(size: 16, weight: .semibold))
                Spacer()
                Button { store.showingSettings.toggle() } label: { Image(systemName: store.showingSettings ? "xmark" : "gearshape").frame(width: 30, height: 30) }
                    .buttonStyle(.plain).foregroundStyle(.secondary).help("Settings").accessibilityLabel("Settings")
            }
            if store.onboarding || store.showingSettings { SettingsPanel(store: store) }
            else {
                if let preview = store.preview {
                    let screens = preview.plan.inventory.displays
                    ScrollView(.horizontal, showsIndicators: screens.count > 2) {
                        HStack(alignment: .top, spacing: 10) {
                            ForEach(screens) { screen in
                                DisplayCard(screen: screen, windows: preview.plan.inventory.windows, actions: preview.plan.actions, proposed: store.hasLayout)
                                    .frame(width: screens.count == 1 ? 328 : 159)
                            }
                        }
                    }.frame(height: screens.count > 2 ? 142 : 130)
                } else {
                    HStack(spacing: 20) {
                        Image(systemName: "display").font(.system(size: 30, weight: .light))
                        Spacer()
                        Text(store.busy ? "Reading your displays…" : "Ready to arrange your windows").font(.system(size: 11)).foregroundStyle(.secondary)
                    }.foregroundStyle(.secondary).padding(12).frame(height: 82)
                        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 12))
                }
                VStack(spacing: 10) {
                    placement("Work", icon: "briefcase", selection: store.destination(\.workScreen))
                    placement("Chat", icon: "bubble.left.and.bubble.right", selection: store.destination(\.chatScreen))
                    placement("References", icon: "book", selection: store.destination(\.referenceScreen))
                }.padding(11).background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 10)).disabled(store.busy)
                DisclosureGroup("Custom instructions", isExpanded: $showCustom) {
                    TextField("e.g. Keep Safari beside my editor", text: store.customInstructions, axis: .vertical)
                        .lineLimit(2...4).textFieldStyle(.roundedBorder).padding(.top, 6)
                        .accessibilityLabel("Custom instructions")
                }.font(.system(size: 11)).foregroundStyle(.secondary).disabled(store.busy)
                if store.hasLayout, let preview = store.preview {
                    DisclosureGroup(isExpanded: $showChanges) {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 10) {
                                ForEach(preview.plan.actions) { a in
                                    HStack(spacing: 8) {
                                        Image(systemName: a.kind == "move" ? "arrow.up.right" : a.kind == "close" ? "xmark" : "minus").font(.system(size: 10)).frame(width: 12).foregroundStyle(.secondary)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(a.window.app_name).font(.system(size: 11, weight: .medium))
                                            Text(a.window.title).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                                        }
                                        Spacer()
                                        Text(a.kind == "move" ? "Arrange" : a.kind == "close" ? "Close" : "Minimize").font(.system(size: 10)).foregroundStyle(.secondary)
                                    }
                                }
                            }.padding(.top, 8).padding(.trailing, 4)
                        }.frame(height: min(140, CGFloat(preview.action_count) * 38))
                    } label: {
                        let moved = preview.plan.actions.filter { $0.kind == "move" }.count
                        Text("\(moved) to arrange · \(preview.plan.actions.filter { $0.kind == "close" }.count) to close").font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                }
                HStack(spacing: 8) {
                    if store.hasLayout {
                        Button { showChanges = false; store.scan(layout: true) } label: { Image(systemName: "arrow.clockwise").frame(width: 24, height: 28) }
                            .help("Refresh preview").accessibilityLabel("Refresh preview")
                    } else {
                        Button("Preview") { showChanges = false; store.scan(layout: true) }.controlSize(.large).accessibilityLabel("Preview layout")
                    }
                    Button { if store.hasLayout { store.apply(scope: "windows") } else { showChanges = false; store.tidy() } } label: {
                        Text(store.hasLayout ? "Apply layout" : "Tidy windows").frame(maxWidth: .infinity, minHeight: 28)
                    }.buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(store.hasLayout && store.preview?.action_count == 0)
                }.disabled(store.busy)
                Divider()
                HStack(spacing: 10) {
                    Image(systemName: "photo.on.rectangle").font(.system(size: 17)).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Desktop screenshots").font(.system(size: 12, weight: .medium))
                        if let file = store.filePreview, let count = file.screenshot_count, let bytes = file.screenshot_bytes {
                            Text("\(count.formatted()) older than \(file.plan.inventory.days) days · \(ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file))")
                                .font(.system(size: 10)).foregroundStyle(.secondary).monospacedDigit()
                        } else { Text("Move old captures to Trash.").font(.system(size: 10)).foregroundStyle(.secondary) }
                    }
                    Spacer()
                    Button(store.filePreview == nil ? "Scan" : "Review") {
                        store.scan(layout: false) { if (store.filePreview?.screenshot_count ?? 0) > 0 { confirmCleanup = true } else { store.status = "No old screenshots to clean." } }
                    }.controlSize(.small).disabled(store.busy)
                }
                if let preview = store.preview, !preview.coverage.errors.isEmpty {
                    Text("Some window details are unavailable: " + preview.coverage.errors.map(\.app).joined(separator: ", "))
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                if let error = store.error { Text(error).font(.system(size: 11)).foregroundStyle(.orange).textSelection(.enabled) }
                if store.busy {
                    HStack(spacing: 7) { ProgressView().controlSize(.small); Text(store.status).font(.system(size: 11)).foregroundStyle(.secondary) }
                } else if !store.hasLayout {
                    Text(store.status).font(.system(size: 11)).foregroundStyle(.secondary)
                }
                HStack(spacing: 6) {
                    Menu {
                        ForEach(store.settings.provider == "gateway" ? ["jev", "hybrid", "nemotron", "beam"] : ["nemotron", "beam"], id: \.self) { model in
                            Button(model == "jev" ? "Jev 1.14" : model == "hybrid" ? "Jev + Nemotron" : model.capitalized) {
                                store.settings.model = model; store.hasLayout = false
                                do { try store.persist() } catch { store.error = error.localizedDescription }
                            }
                        }
                    } label: { Label(modelTitle, systemImage: "bolt.fill") }.menuStyle(.borderlessButton).fixedSize().disabled(store.busy)
                    if let ms = store.preview?.model?.latency_ms { Text(String(format: "%.2fs", Double(ms) / 1000)).monospacedDigit().foregroundStyle(.tertiary) }
                    Spacer()
                    Button { store.undo() } label: { Label(store.journalScope == "screenshots" ? "Undo cleanup" : "Undo layout", systemImage: "arrow.uturn.backward") }
                        .buttonStyle(.plain).disabled(store.busy || store.journal == nil)
                    Menu { Button("Quit Desk Tidy") { NSApp.terminate(nil) } } label: { Image(systemName: "ellipsis").frame(width: 22, height: 20) }
                        .menuStyle(.borderlessButton).fixedSize().accessibilityLabel("More")
                }.font(.system(size: 10)).foregroundStyle(.secondary)
            }
        }.padding(16).frame(width: 360)
            .confirmationDialog("Move \((store.filePreview?.screenshot_count ?? 0).formatted()) old screenshots to Trash?", isPresented: $confirmCleanup, titleVisibility: .visible) {
                Button("Move to Trash", role: .destructive) { store.apply(scope: "screenshots") }
                Button("Cancel", role: .cancel) { }
            } message: { Text("Only default-named screenshots directly on Desktop older than \(store.filePreview?.plan.inventory.days ?? 30) days. Undo puts them back. Other files stay where they are.") }
    }
    private func placement(_ title: String, icon: String, selection: Binding<String>) -> some View {
        HStack {
            Label(title, systemImage: icon).font(.system(size: 12))
            Spacer()
            Picker(title, selection: selection) {
                Text("Automatic").tag("auto")
                ForEach(store.preview?.plan.inventory.displays ?? []) { Text($0.name).tag($0.id) }
            }.labelsHidden().frame(maxWidth: 160).controlSize(.small).accessibilityLabel("\(title) display")
        }
    }
}

struct SettingsPanel: View {
    @ObservedObject var store: Store
    @State private var apiKey = ""
    @State private var saving = false
    @State private var cliInstalled = false
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if store.onboarding {
                Text("A quick setup, then more room to work.").font(.system(size: 13)).foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 12) {
                Label("Everything included", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                Text("No Homebrew, Python, or browser tools to install.").font(.system(size: 11)).foregroundStyle(.secondary)
                HStack {
                    Label(store.accessibility ? "Window control allowed" : "Allow window control", systemImage: store.accessibility ? "checkmark.circle.fill" : "rectangle.on.rectangle")
                    Spacer()
                    if !store.accessibility {
                        Button("Allow…") {
                            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
                            _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
                            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                        }.controlSize(.small)
                    }
                }
                if !store.accessibility { Text("Enable Desk Tidy in Accessibility, then check again below.").font(.system(size: 11)).foregroundStyle(.secondary) }
            }.padding(12).background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 12))
            VStack(alignment: .leading, spacing: 10) {
                Picker("Provider", selection: $store.settings.provider) {
                    Text("Vercel AI Gateway").tag("gateway")
                    Text("OpenRouter").tag("openrouter")
                }
                if store.keyConfigured { Label("API key saved", systemImage: "checkmark.circle.fill").foregroundStyle(.green) }
                SecureField(store.keyConfigured ? "Replace API key (optional)" : "API key", text: $apiKey)
                    .textFieldStyle(.roundedBorder)
                Link("Get an API key ↗", destination: URL(string: store.settings.provider == "gateway" ? "https://vercel.com/ai-gateway" : "https://openrouter.ai/keys")!)
                    .font(.system(size: 11))
                Text("Keys stay in Keychain. Layout requests send app names and window titles; file contents stay on your Mac.")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }
            if !store.onboarding {
                Stepper("Screenshots older than \(store.screenshotDays) days", value: $store.screenshotDays, in: 1...365)
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
            if cliInstalled { Text("Run desk-tidy in a new Terminal.").font(.system(size: 10)).foregroundStyle(.secondary) }
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
            if let error = store.error { Text(error).font(.system(size: 11)).foregroundStyle(.orange) }
            if store.onboarding { Button("Quit Desk Tidy") { NSApp.terminate(nil) }.buttonStyle(.plain).font(.system(size: 10)).foregroundStyle(.secondary) }
        }.font(.system(size: 12))
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    let store = Store()
    var item: NSStatusItem!
    let popover = NSPopover()
    var previewWindow: NSWindow?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            let icon = NSImage(systemSymbolName: "rectangle.3.group", accessibilityDescription: "Desk Tidy")
            icon?.isTemplate = true; button.image = icon
            button.target = self; button.action = #selector(toggle)
            button.toolTip = "Desk Tidy"
        }
        popover.behavior = .transient
        let host = NSHostingController(rootView: Panel(store: store))
        host.sizingOptions = [.preferredContentSize]
        popover.contentViewController = host
        popover.contentSize = NSSize(width: 360, height: 500)
        if CommandLine.arguments.contains("--preview-window") {
            let window = NSWindow(contentRect: NSRect(x: 900, y: 300, width: 360, height: 540), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "Desk Tidy"
            window.contentView = NSHostingView(rootView: Panel(store: store))
            window.isReleasedWhenClosed = false; window.makeKeyAndOrderFront(nil)
            previewWindow = window; NSApp.activate(ignoringOtherApps: true)
        }
        // Launch reads local state; only Preview and Tidy request a model.
        store.checkSetup()
        if CommandLine.arguments.contains("--show") { DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.present() } }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        present()
        return true
    }
    func present() { if !popover.isShown, item != nil { toggle() } }
    @objc func toggle() {
        if popover.isShown { popover.performClose(nil) }
        else if let button = item.button {
            if let app = NSWorkspace.shared.frontmostApplication, app.processIdentifier != ProcessInfo.processInfo.processIdentifier { store.frontmostPid = app.processIdentifier }
            popover.contentViewController?.view.layoutSubtreeIfNeeded()
            if let size = popover.contentViewController?.view.fittingSize, size.height > 0 { popover.contentSize = size }
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            if CommandLine.arguments.contains("--diagnose") {
                fputs("popover shown=\(popover.isShown) size=\(popover.contentSize) anchor=\(String(describing: button.window?.frame))\n", stderr)
            }
        }
    }
}

@main struct DeskTidy {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
