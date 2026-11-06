// Synthetic example content, compiled only into the documentation/test fixture.
import AppKit
import SwiftUI

enum DemoWindows {
    @MainActor static func appIcon(_ name: String) -> NSImage? {
        let bundles = ["Terminal": "com.apple.Terminal", "Safari": "com.apple.Safari", "Messages": "com.apple.MobileSMS",
                       "TextEdit": "com.apple.TextEdit", "Notes": "com.apple.Notes", "Music": "com.apple.Music", "Calendar": "com.apple.iCal"]
        guard let bundle = bundles[name], let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundle) else { return nil }
        return NSWorkspace.shared.icon(forFile: url.path)
    }
    @MainActor static func image(for window: WindowInfo) -> NSImage {
        let renderer = ImageRenderer(content: ExampleWindow(app: window.app_name, kind: window.id).frame(width: 800, height: 1050))
        renderer.scale = 0.8
        return renderer.nsImage ?? NSImage(size: NSSize(width: 640, height: 840))
    }
}

private struct ExampleWindow: View {
    let app: String
    let kind: String
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                ForEach([Color.red, .yellow, .green], id: \.self) { color in Circle().fill(color.opacity(0.8)).frame(width: 10, height: 10) }
                Spacer()
                Text(app).font(.system(size: 15, weight: .medium)).foregroundStyle(.gray)
                Spacer()
            }.padding(15).background(Color(white: 0.13))
            if app == "Terminal" { terminal }
            else if app == "Messages" { chat }
            else if app == "Music" { music }
            else if app == "TextEdit" { editor }
            else if kind == "reference" { reference }
            else if kind == "scratch" { scratch }
            else if kind == "newtab" { startPage }
            else if app == "Calendar" { calendar }
            else { notebook }
        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
    private var terminal: some View {
        VStack(alignment: .leading, spacing: 24) {
            Text("mila  ~/projects/garden  main").foregroundStyle(.mint)
            Text("$ npm run dev\n\n> garden@1.4.0 dev\n> vite\n\n  VITE ready\n\n  Local: localhost:5173").foregroundStyle(Color(white: 0.83))
            Text("✓ Navigation\n✓ Keyboard shortcuts\n✓ Window layout\n\nAll checks passed.").foregroundStyle(Color(white: 0.58))
            Text("$ ▍").foregroundStyle(.mint)
            Spacer()
        }.font(.system(size: 21, design: .monospaced)).padding(30).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Color(red: 0.04, green: 0.07, blue: 0.11))
    }
    private var notebook: some View {
        VStack(alignment: .leading, spacing: 30) {
            Text("Garden / Project notes").font(.system(size: 16)).foregroundStyle(.secondary)
            Text("A little more\nbreathing room.").font(.system(size: 38, weight: .semibold))
            Text("Make the useful things easy to find.").font(.system(size: 23)).foregroundStyle(.secondary)
            Divider()
            Text("Today’s focus").font(.system(size: 25, weight: .semibold))
            ForEach(["Finish the new navigation", "Review keyboard shortcuts", "Ship the first preview"], id: \.self) { text in
                HStack(spacing: 16) { Image(systemName: "checkmark.circle.fill").foregroundStyle(.green); Text(text) }.font(.system(size: 21))
            }
            Divider()
            Text("Notes").font(.system(size: 25, weight: .semibold))
            Text("Browser beside the terminal.\nChat on the other display.\nKeep the rest close by.").font(.system(size: 23)).lineSpacing(14).foregroundStyle(.secondary)
            Spacer()
        }.padding(36).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(white: 0.97)).foregroundStyle(.black)
    }
    private var chat: some View {
        VStack(alignment: .leading, spacing: 30) {
            Text("Team chat").font(.system(size: 30, weight: .semibold))
            Text("Today, 10:42 AM").font(.system(size: 16)).foregroundStyle(.secondary).frame(maxWidth: .infinity)
            Text("Mila\nThe notes are ready for a look.").font(.system(size: 23)).padding(22).background(Color(white: 0.91), in: RoundedRectangle(cornerRadius: 22))
            Text("Perfect. I’ve got them right here.").font(.system(size: 23)).foregroundStyle(.white).padding(22).background(.blue, in: RoundedRectangle(cornerRadius: 22)).frame(maxWidth: .infinity, alignment: .trailing)
            Text("Sam\nI’ll review the build after lunch.").font(.system(size: 23)).padding(22).background(Color(white: 0.91), in: RoundedRectangle(cornerRadius: 22))
            Spacer()
            Text("Message").font(.system(size: 21)).foregroundStyle(.secondary).padding(18).frame(maxWidth: .infinity, alignment: .leading).background(Color(white: 0.94), in: RoundedRectangle(cornerRadius: 20))
        }.padding(30).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(white: 0.98)).foregroundStyle(.black)
    }
    private var editor: some View {
        VStack(alignment: .leading, spacing: 28) {
            Text("layout.py").foregroundStyle(.gray)
            Text("# Give every window a place.\n\ndef arrange_workspace(\n    windows, displays\n):\n    groups = group_by_display(\n        windows, displays\n    )\n\n    for screen, panes in groups:\n        layout = pack_columns(\n            screen, panes\n        )\n        yield from layout").foregroundStyle(Color(red: 0.78, green: 0.73, blue: 0.9))
            Spacer()
        }.font(.system(size: 23, design: .monospaced)).padding(30).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(red: 0.125, green: 0.137, blue: 0.192))
    }
    private var reference: some View {
        VStack(alignment: .leading, spacing: 28) {
            Text("Reference").font(.system(size: 18)).foregroundStyle(.gray)
            Text("Keyboard shortcuts").font(.system(size: 34, weight: .semibold))
            ForEach(["Switch apps                 ⌘ Tab", "Quick search              ⌘ Space", "New tab                       ⌘ T", "Find                             ⌘ F"], id: \.self) { line in Text(line).font(.system(size: 23)); Divider() }
            Spacer()
        }.padding(30).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(white: 0.98)).foregroundStyle(.black)
    }
    private var scratch: some View {
        VStack(alignment: .leading, spacing: 25) { Text("Untitled").font(.system(size: 34, weight: .semibold)); Text("Maybe later…\n\nold ideas\none more tab\nwhere did that window go?").font(.system(size: 24)); Spacer() }
            .padding(35).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(red: 1, green: 0.98, blue: 0.91)).foregroundStyle(.black)
    }
    private var startPage: some View {
        VStack(spacing: 30) { Text("Start Page").font(.system(size: 40, weight: .medium)); Text("Search or enter a website").padding(25).background(Color.gray.opacity(0.12), in: RoundedRectangle(cornerRadius: 15)); Spacer() }
            .padding(.top, 170).frame(maxWidth: .infinity, maxHeight: .infinity).background(Color(white: 0.97)).foregroundStyle(.gray)
    }
    private var calendar: some View {
        VStack(alignment: .leading, spacing: 35) { Text("November").font(.system(size: 24)); Text("05").font(.system(size: 80, weight: .light)); Text("10:00  Design review\n\n12:30  Lunch\n\n15:00  A quiet hour").font(.system(size: 27)); Spacer() }
            .padding(40).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(white: 0.98)).foregroundStyle(.black)
    }
    private var music: some View {
        VStack(spacing: 30) {
            Spacer()
            Image(systemName: "music.note").font(.system(size: 130)).frame(width: 300, height: 300)
                .background(LinearGradient(colors: [.indigo, .purple], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: 30))
            Text("Focus mix").font(.system(size: 35, weight: .semibold))
            Text("An example background window").font(.system(size: 20)).foregroundStyle(.secondary)
            Image(systemName: "pause.fill").font(.system(size: 30))
            Spacer()
        }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Color(white: 0.1)).foregroundStyle(.white)
    }
}
