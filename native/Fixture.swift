// Disposable windows for real AX verification. Never activates or raises an app.
import AppKit
import Darwin

let app = NSApplication.shared
app.setActivationPolicy(.regular)
var windows: [NSWindow] = []
let top = NSScreen.screens.first!.frame.maxY
for index in 0..<3 {
    let window = NSWindow(contentRect: NSRect(x: 100 + index * 70, y: 150 + index * 40, width: 640, height: 480),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
    window.title = "Fenlet verification \(index)"
    window.isReleasedWhenClosed = false
    window.minSize = NSSize(width: index == 2 ? 700 : 300, height: 240)
    window.isDocumentEdited = index == 2
    window.orderBack(nil)
    windows.append(window)
}
func reply() {
    var info = proc_bsdinfo()
    let pid = getpid()
    _ = proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, Int32(MemoryLayout<proc_bsdinfo>.size))
    let references = windows.filter { $0.isVisible || $0.isMiniaturized }.map { w -> [String: Any] in
        let frame = w.frame
        return ["id": "w-\(w.windowNumber)", "pid": pid,
                "process_instance": "macos-proc-v1:\(info.pbi_start_tvsec):\(info.pbi_start_tvusec)",
                "app_name": "FenletFixture", "title": w.title, "title_source": "cg",
                "bounds": ["x": frame.minX, "y": top - frame.maxY, "width": frame.width, "height": frame.height],
                "minimized": w.isMiniaturized, "hidden": false, "is_focused": false]
    }
    let data = try! JSONSerialization.data(withJSONObject: references)
    print(String(data: data, encoding: .utf8)!)
    fflush(stdout)
}
DispatchQueue.global().async {
    while let line = readLine() {
        DispatchQueue.main.async {
            if line == "quit" { app.terminate(nil) }
            if line == "rename" { windows[0].title = "Fenlet verification renamed" }
            reply()
        }
    }
    DispatchQueue.main.async { app.terminate(nil) }
}
Timer.scheduledTimer(withTimeInterval: 45, repeats: false) { _ in app.terminate(nil) }
DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { reply() }
app.run()
