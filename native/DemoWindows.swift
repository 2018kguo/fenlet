// Synthetic example content, compiled only into the documentation/test fixture.
import AppKit
import SwiftUI

enum DemoWindows {
    @MainActor static func image(for window: WindowInfo) -> NSImage {
        let renderer = ImageRenderer(content: ExampleWindow(app: window.app_name).frame(width: 800, height: 1050))
        renderer.scale = 0.8
        return renderer.nsImage ?? NSImage(size: NSSize(width: 640, height: 840))
    }
}

private struct ExampleWindow: View {
    let app: String
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
            else { notebook }
        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
    private var terminal: some View {
        VStack(alignment: .leading, spacing: 24) {
            Text("~/work/fenlet  main").foregroundStyle(.mint)
            Text("$ fenlet plan\n\nReading windows…\n\n  Work display\n  ├─ Terminal\n  └─ Project notebook\n\n  Laptop\n  └─ Team chat\n\nReady to review.").foregroundStyle(Color(white: 0.83))
            Text("$ python3 -m unittest\n\n............................................\n\n44 tests passed").foregroundStyle(Color(white: 0.58))
            Text("$ ▍").foregroundStyle(.mint)
            Spacer()
        }.font(.system(size: 21, design: .monospaced)).padding(30).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Color(red: 0.04, green: 0.07, blue: 0.11))
    }
    private var notebook: some View {
        VStack(alignment: .leading, spacing: 30) {
            Text("example.test / project").font(.system(size: 16)).foregroundStyle(.secondary)
            Text("Project notebook").font(.system(size: 38, weight: .semibold))
            Text("A little room to think.").font(.system(size: 23)).foregroundStyle(.secondary)
            Divider()
            Text("Next release").font(.system(size: 25, weight: .semibold))
            ForEach(["Keep the useful windows together", "Give each screen a purpose", "Review before making changes"], id: \.self) { text in
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
            Text("Ava\nThe notes are ready for a look.").font(.system(size: 23)).padding(22).background(Color(white: 0.22), in: RoundedRectangle(cornerRadius: 22))
            Text("Great — keeping them next to my terminal.").font(.system(size: 23)).padding(22).background(.blue, in: RoundedRectangle(cornerRadius: 22)).frame(maxWidth: .infinity, alignment: .trailing)
            Text("Lin\nI’ll check the new layout after lunch.").font(.system(size: 23)).padding(22).background(Color(white: 0.22), in: RoundedRectangle(cornerRadius: 22))
            Spacer()
            Text("Message").font(.system(size: 21)).foregroundStyle(.secondary).padding(18).frame(maxWidth: .infinity, alignment: .leading).background(Color(white: 0.2), in: RoundedRectangle(cornerRadius: 20))
        }.padding(30).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color(white: 0.12)).foregroundStyle(.white)
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
