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
        if preview.plan.inventory.all_spaces == true {
            store.settings.allSpaces = true
            store.settings.gatherScreen = preview.plan.inventory.displays.first?.id
        }
        store.preview = preview; store.hasLayout = true; store.liveReadOK = true
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
