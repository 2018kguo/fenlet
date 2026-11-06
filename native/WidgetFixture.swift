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
        store.liveInventory = preview.plan.inventory
        store.preview = preview; store.hasLayout = true; store.liveReadOK = true
        store.settings.customInstructions = "Keep my browser beside my terminal. Put chat on another display when there is room."
        let window = NSWindow(contentRect: NSRect(x: 100, y: 180, width: 420, height: 580), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Fenlet layout verification"
        window.contentView = NSHostingView(rootView: Panel(store: store))
        window.isReleasedWhenClosed = false; window.orderFrontRegardless()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            window.displayIfNeeded(); print("\(window.windowNumber)"); fflush(stdout)
        }
        Timer.scheduledTimer(withTimeInterval: 60, repeats: false) { _ in app.terminate(nil) }
        withExtendedLifetime((store, window)) { app.run() }
    }
}
