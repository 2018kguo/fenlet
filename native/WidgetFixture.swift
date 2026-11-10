// Synthetic rendering harness. Never included in the installed application.
import AppKit
import SwiftUI

@main struct WidgetFixture {
    @MainActor static func main() throws {
        let input = URL(fileURLWithPath: CommandLine.arguments[1])
        let preview = try JSONDecoder().decode(PreviewInfo.self, from: Data(contentsOf: input))
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let store = Store()
        store.journal = nil
        store.liveInventory = preview.plan.inventory
        store.preview = preview; store.hasLayout = true; store.liveReadOK = true
        if CommandLine.arguments.contains("--verify-state") {
            precondition(store.settings.model == "beam", "Existing configuration failed to load.")
            let arguments = store.layoutArguments("plan")
            precondition(store.scanArguments == ["scan", "--all-spaces"] && arguments.contains("--all-spaces"))
            precondition(!arguments.contains(where: { ["--display", "--work-display", "--chat-display", "--reference-display"].contains($0) }), "An old display choice overrode the connected setup.")
            store.windowPreviews.loadDemo(preview.plan.inventory.windows)
            store.error = "An old display error"
            store.observeInventory(InventoryInfo(displays: [], windows: preview.plan.inventory.windows))
            precondition(store.hasLayout && store.preview?.plan_path == preview.plan_path && store.availableDisplays.isEmpty && store.error == nil, "A live observation discarded reviewed draft edits.")
            store.liveInventory = preview.plan.inventory; store.preview = preview; store.hasLayout = true
            let failure = ApplyInfo(journal_path: "synthetic", succeeded: 0, failed: 1, planned: 1, apply_ms: 12,
                closed: 0, arranged: 0, minimized: 0, undoable: false,
                layout_check: .init(overlap_count: 0, windows: preview.plan.inventory.windows, displays: preview.plan.inventory.displays),
                results: [.init(ok: false, error: "Window changed since preview.")])
            store.complete(failure, from: preview, elapsed: 12)
            precondition(!store.hasLayout && !store.hasDraft, "An applied plan stayed confirmable.")
            precondition(store.error?.contains(preview.plan.actions[0].window.app_name) == true, "Failure did not identify its app.")
            store.onboarding = true; store.keyConfigured = false
            store.windowPreviews.loadPermissionFixture(allowed: false)
            store.updatePermissions(.init(accessibility: true, screen_recording: false))
            precondition(store.onboarding && store.accessibility, "Setup skipped window previews.")
            store.updatePermissions(.init(accessibility: true, screen_recording: true))
            precondition(store.previewRestartNeeded && store.onboarding, "A restart requirement was hidden.")
            store.windowPreviews.loadPermissionFixture(allowed: true)
            precondition(store.updatePermissions(.init(accessibility: true, screen_recording: true)), "New grants did not finish setup.")
            precondition(!store.onboarding)
            store.error = nil; store.preview = preview; store.hasLayout = true
            store.status = "Nothing moves or closes until you confirm."
        }
        if CommandLine.arguments.contains("--onboarding") {
            store.onboarding = true; store.accessibility = false; store.keyConfigured = true
            store.windowPreviews.loadPermissionFixture(allowed: false)
            if let index = CommandLine.arguments.firstIndex(of: "--permission-file"), index + 1 < CommandLine.arguments.count {
                let permissionFile = URL(fileURLWithPath: CommandLine.arguments[index + 1])
                var previous: Data?
                Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in
                    MainActor.assumeIsolated {
                        guard let data = try? Data(contentsOf: permissionFile), data != previous,
                              let info = try? JSONDecoder().decode(PermissionInfo.self, from: data) else { return }
                        previous = data
                        store.windowPreviews.loadPermissionFixture(allowed: info.screen_recording)
                        store.updatePermissions(info)
                    }
                }
            }
        }
        let demo = CommandLine.arguments.contains("--demo") || CommandLine.arguments.contains("--demo-live")
        if demo {
            store.windowPreviews.loadDemo(preview.plan.inventory.windows)
            store.status = "Nothing moves or closes until you confirm."
            store.settings.customInstructions = "Keep my browser beside my terminal. Chat and references on my laptop."
        }
        if let index = CommandLine.arguments.firstIndex(of: "--export-icons"), index + 1 < CommandLine.arguments.count {
            let directory = URL(fileURLWithPath: CommandLine.arguments[index + 1])
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            for name in Set(preview.plan.inventory.windows.map(\.app_name)).sorted() {
                guard let icon = DemoWindows.appIcon(name), let tiff = icon.tiffRepresentation,
                      let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) else { continue }
                try png.write(to: directory.appendingPathComponent("icon-\(name.lowercased()).png"))
            }
        }
        if CommandLine.arguments.contains("--demo-live") {
            store.preview = nil; store.hasLayout = false
            store.status = "Ready when you are."
        }
        if !demo { store.settings.customInstructions = "Keep my browser beside my terminal. Put chat on another display when there is room." }
        let window = NSWindow(contentRect: NSRect(x: 100, y: 180, width: 420, height: store.panelHeight), styleMask: demo ? [.borderless] : [.titled, .closable], backing: .buffered, defer: false)
        window.title = demo ? "Fenlet" : "Fenlet layout verification"
        window.contentView = NSHostingView(rootView: Panel(store: store))
        if demo {
            window.isOpaque = false; window.backgroundColor = .clear
            window.contentView?.wantsLayer = true
            window.contentView?.layer?.cornerRadius = 18
            window.contentView?.layer?.masksToBounds = true
            if let screen = NSScreen.screens.max(by: { $0.backingScaleFactor < $1.backingScaleFactor }) {
                window.setFrameOrigin(NSPoint(x: screen.visibleFrame.minX + 40, y: screen.visibleFrame.maxY - store.panelHeight - 40))
            }
        }
        window.isReleasedWhenClosed = false; window.orderFrontRegardless()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            window.displayIfNeeded(); print("\(window.windowNumber)"); fflush(stdout)
        }
        Timer.scheduledTimer(withTimeInterval: 60, repeats: false) { _ in app.terminate(nil) }
        withExtendedLifetime((store, window)) { app.run() }
    }
}
