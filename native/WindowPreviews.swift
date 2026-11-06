import AppKit
import ScreenCaptureKit
import SwiftUI

/// A nonactivating image tooltip; inspecting a pane never replaces the controls.
@MainActor final class WindowPeek {
    private var panel: NSPanel?
    private var host: NSHostingView<PeekCard>?
    private var shownID: String?
    private var hoverTask: Task<Void, Never>?
    func schedule(_ window: WindowInfo, captures: WindowPreviews, in windows: [WindowInfo]) {
        hoverTask?.cancel()
        hoverTask = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 250_000_000) } catch { return }
            guard !Task.isCancelled else { return }
            captures.prioritize([window], in: windows)
            self?.show(window, captures: captures)
        }
    }
    func show(_ window: WindowInfo, captures: WindowPreviews) {
        if panel == nil {
            let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 336, height: 242), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            p.level = .popUpMenu; p.hasShadow = true; p.isOpaque = false; p.backgroundColor = .clear
            p.ignoresMouseEvents = true; p.hidesOnDeactivate = false; p.isReleasedWhenClosed = false
            panel = p
        }
        shownID = window.id
        let card = PeekCard(window: window, captures: captures)
        if let host { host.rootView = card }
        else { let view = NSHostingView(rootView: card); host = view; panel?.contentView = view }
        guard let panel else { return }
        let anchor = NSApp.windows.first { $0 !== panel && $0.isVisible && $0.frame.width > 200 }?.frame ?? CGRect(origin: NSEvent.mouseLocation, size: .zero)
        let screen = NSScreen.screens.first { $0.frame.intersects(anchor) } ?? NSScreen.main
        let available = screen?.visibleFrame ?? anchor.insetBy(dx: -600, dy: -400)
        var x = anchor.maxX + 12
        if x + 336 > available.maxX { x = anchor.minX - 348 }
        x = max(available.minX, min(x, available.maxX - 336))
        let y = max(available.minY, min(anchor.maxY - 290, available.maxY - 242))
        panel.setFrameOrigin(CGPoint(x: x, y: y)); panel.orderFrontRegardless()
    }
    func update(_ windows: [WindowInfo], captures: WindowPreviews) {
        guard let id = shownID else { return }
        guard let window = windows.first(where: { $0.id == id }) else { hide(); return }
        host?.rootView = PeekCard(window: window, captures: captures)
    }
    func hide() { hoverTask?.cancel(); hoverTask = nil; shownID = nil; panel?.orderOut(nil) }
    private struct PeekCard: View {
        let window: WindowInfo
        @ObservedObject var captures: WindowPreviews
        var body: some View {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 7) {
                    AppGlyph(name: window.app_name)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(window.app_name).font(.system(size: 11, weight: .semibold))
                        Text(window.title).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                WindowThumbnail(window: window, captures: captures).frame(height: 184).clipShape(RoundedRectangle(cornerRadius: 7))
            }.padding(10).frame(width: 336, height: 242)
                .background(Color(nsColor: .windowBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                .overlay { RoundedRectangle(cornerRadius: 12).strokeBorder(.primary.opacity(0.12), lineWidth: 0.5) }
        }
    }
}

/// Small, one-shot window captures. Pixels never leave this process or touch disk.
@MainActor final class WindowPreviews: ObservableObject {
    struct Thumbnail {
        let identity: String
        let image: NSImage
    }
    @Published private var thumbnails: [String: Thumbnail] = [:]
    @Published private(set) var allowed = CGPreflightScreenCaptureAccess()
    @Published private(set) var loading = false
    private var refreshTask: Task<Void, Never>?
    private var generation = 0
    private var refreshedAt = Date.distantPast
    private var requestedIdentities: [String] = []
    private var priorityIDs: [String] = []

    #if FENLET_UI_TEST
    private var fixtureMode = false
    func loadDemo(_ windows: [WindowInfo]) {
        fixtureMode = true; allowed = true
        thumbnails = Dictionary(uniqueKeysWithValues: windows.map { window in
            (window.id, Thumbnail(identity: Self.identity(window), image: DemoWindows.image(for: window)))
        })
    }
    func loadPermissionFixture(allowed: Bool) { fixtureMode = true; self.allowed = allowed }
    #endif

    nonisolated static func identity(_ window: WindowInfo) -> String {
        "\(window.pid)/\(window.process_instance)/\(window.id)"
    }
    func image(for window: WindowInfo) -> NSImage? {
        guard let thumbnail = thumbnails[window.id], thumbnail.identity == Self.identity(window) else { return nil }
        return thumbnail.image
    }
    var supported: Bool { if #available(macOS 14.0, *) { return true }; return false }
    func refreshAuthorization() {
        #if FENLET_UI_TEST
        if fixtureMode { return }
        #endif
        allowed = CGPreflightScreenCaptureAccess()
    }
    func enable() {
        if CGRequestScreenCaptureAccess() { allowed = true }
        else { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!) }
    }
    func pause() {
        generation += 1; refreshTask?.cancel(); refreshTask = nil; loading = false
    }
    func prioritize(_ preferred: [WindowInfo], in windows: [WindowInfo]) {
        priorityIDs = Array(preferred.prefix(24).map(\.id))
        refresh(windows, maxAge: 0)
    }
    func refresh(_ windows: [WindowInfo], maxAge: TimeInterval = 5) {
        #if FENLET_UI_TEST
        if fixtureMode { return }
        #endif
        allowed = CGPreflightScreenCaptureAccess()
        guard allowed, supported else {
            generation += 1; refreshTask?.cancel(); loading = false; thumbnails = [:]; return
        }
        // At most 24 x 512 x 320 x 4 bytes (~15 MB), with three captures in flight.
        // This budget affects thumbnails only, never window arrangement.
        guard !loading else { return }
        let known = Dictionary(uniqueKeysWithValues: windows.map { ($0.id, $0) })
        let ordered = priorityIDs.compactMap { known[$0] } + windows
        var seen = Set<String>(), requested: [WindowInfo] = []
        for window in ordered where !window.minimized {
            if seen.insert(window.id).inserted { requested.append(window) }
            if requested.count == 24 { break }
        }
        let identities = requested.map { Self.identity($0) + "/" + $0.title + "/\($0.bounds.width)x\($0.bounds.height)" }
        if identities == requestedIdentities && Date().timeIntervalSince(refreshedAt) < maxAge { return }
        requestedIdentities = identities
        generation += 1
        let revision = generation
        refreshTask?.cancel()
        let current = Set(requested.map(Self.identity))
        thumbnails = thumbnails.filter { current.contains($0.value.identity) }
        refreshTask = Task {
            loading = true
            defer { if revision == generation { loading = false } }
            let started = Date()
            guard #available(macOS 14.0, *), !requested.isEmpty else { return }
            do {
                let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: !requested.contains { $0.space_ids != nil })
                guard !Task.isCancelled, revision == generation else { return }
                let available = Dictionary(uniqueKeysWithValues: content.windows.map { ($0.windowID, $0) })
                for offset in stride(from: 0, to: requested.count, by: 3) {
                    if Task.isCancelled { return }
                    let batch = requested[offset..<min(offset + 3, requested.count)]
                    await withTaskGroup(of: (String, String, CGImage)?.self) { group in
                        for window in batch {
                            guard let number = UInt32(window.id.dropFirst(2)), let capture = available[number],
                                  capture.owningApplication?.processID == window.pid else { continue }
                            group.addTask {
                                guard !Task.isCancelled, let image = try? await Self.capture(capture) else { return nil }
                                return (window.id, Self.identity(window), image)
                            }
                        }
                        for await result in group {
                            guard !Task.isCancelled, revision == generation, let (id, identity, image) = result else { continue }
                            thumbnails[id] = Thumbnail(identity: identity, image: NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height)))
                        }
                    }
                }
                guard !Task.isCancelled, revision == generation else { return }
                refreshedAt = Date()
                if CommandLine.arguments.contains("--diagnose") {
                    fputs("window previews: \(thumbnails.count)/\(requested.count), \(Int(Date().timeIntervalSince(started) * 1000))ms, memory only\n", stderr)
                }
            } catch {
                // Capture is optional. Layout and window controls remain available.
                if revision == generation { thumbnails = [:]; allowed = CGPreflightScreenCaptureAccess() }
                if CommandLine.arguments.contains("--diagnose") {
                    let failure = error as NSError
                    fputs("window preview error: \(failure.domain) \(failure.code)\n", stderr)
                }
            }
        }
    }
    @available(macOS 14.0, *)
    private static func capture(_ window: SCWindow) async throws -> CGImage {
        let configuration = SCStreamConfiguration()
        let scale = min(1, 512 / max(1, window.frame.width), 320 / max(1, window.frame.height))
        configuration.width = max(1, Int(window.frame.width * scale))
        configuration.height = max(1, Int(window.frame.height * scale))
        configuration.showsCursor = false
        configuration.ignoreShadowsSingleWindow = true
        configuration.scalesToFit = true
        return try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: window), configuration: configuration)
    }
}
