import AppKit
import SwiftUI

struct DraftTarget: Equatable {
    enum Kind: Equatable { case pane(String), display(String), disposition(String) }
    let kind: Kind
    let frame: CGRect
}
struct DraftTargets: PreferenceKey {
    static var defaultValue: [DraftTarget] = []
    static func reduce(value: inout [DraftTarget], nextValue: () -> [DraftTarget]) { value += nextValue() }
}
struct DraftTargetRegion: ViewModifier {
    let kind: DraftTarget.Kind
    func body(content: Content) -> some View {
        content.background {
            GeometryReader { geometry in
                Color.clear.preference(key: DraftTargets.self, value: [DraftTarget(kind: kind, frame: geometry.frame(in: .named("fenletDraft")))])
            }
        }
    }
}
@MainActor final class DraftCursor: ObservableObject {
    struct Position { let window: WindowInfo; let point: CGPoint }
    @Published var position: Position?
}
struct DraftGhost: View {
    @ObservedObject var cursor: DraftCursor
    @ObservedObject var captures: WindowPreviews
    var body: some View {
        if let position = cursor.position {
            WindowThumbnail(window: position.window, captures: captures)
                .frame(width: 92, height: 64).clipShape(RoundedRectangle(cornerRadius: 7))
                .overlay { RoundedRectangle(cornerRadius: 7).strokeBorder(Color.accentColor, lineWidth: 2) }
                .shadow(color: .black.opacity(0.25), radius: 8, y: 3)
                .offset(x: position.point.x - 46, y: position.point.y - 32)
        }
    }
}
struct DraftTileInteractions: ViewModifier {
    @ObservedObject var store: Store
    let window: WindowInfo
    var draggable = true
    func body(content: Content) -> some View {
        if store.hasLayout && !store.editingDraft {
            content.modifier(DraftTargetRegion(kind: .pane(window.id)))
                .opacity(store.draggedWindowID == window.id ? 0.45 : 1)
                .overlay { RoundedRectangle(cornerRadius: 6).strokeBorder(store.draftTarget == .pane(window.id) ? Color.accentColor : .clear, lineWidth: 2) }
                .highPriorityGesture(DragGesture(minimumDistance: 5, coordinateSpace: .named("fenletDraft"))
                    .onChanged { value in store.trackDraftDrag(window, at: value.location) }
                    .onEnded { value in store.finishDraftDrag(window.id, at: value.location) }, including: draggable ? .all : .none)
                .contextMenu {
                    Menu("Move to display") {
                        ForEach(store.availableDisplays) { display in
                            Button(display.name) { store.editDraft(["--move", window.id, display.id]) }
                        }
                    }
                    Button("Keep in background") { store.editDraft(["--minimize", window.id]) }.disabled(window.is_focused == true)
                    Button("Close window", role: .destructive) { store.editDraft(["--close", window.id]) }.disabled(window.is_focused == true)
                }
        } else { content }
    }
}

struct DraftTray: View {
    @ObservedObject var store: Store
    let kind: String
    @State private var expanded = false
    var actions: [ActionInfo] { store.preview?.plan.actions.filter { $0.kind == kind } ?? [] }
    var body: some View {
        Button { expanded.toggle() } label: {
            HStack(spacing: 7) {
                Image(systemName: kind == "close" ? "xmark.rectangle" : "minus.rectangle")
                Text(kind == "close" ? "Close" : "Background")
                Spacer(minLength: 0)
                Text("\(actions.count)").monospacedDigit().foregroundStyle(.secondary)
            }.font(.system(size: 11, weight: .medium)).padding(11)
                .frame(maxWidth: .infinity).background(.quaternary.opacity(0.2), in: RoundedRectangle(cornerRadius: 9))
                .contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityLabel("\(kind == "close" ? "Close" : "Background"): \(actions.count) windows. Review or drop a window here.")
            .modifier(DraftTargetRegion(kind: .disposition(kind)))
            .popover(isPresented: $expanded, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(kind == "close" ? "Windows to close" : "Keep in the background").font(.system(size: 12, weight: .semibold))
                    Text("Right-click a window to move it to a display.")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                    if actions.isEmpty { Text("No windows here.").font(.system(size: 11)).foregroundStyle(.secondary) }
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(actions) { action in
                                HStack(spacing: 8) {
                                    AppGlyph(name: action.window.app_name)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(action.window.app_name).font(.system(size: 11, weight: .medium))
                                        Text(action.window.title).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                                    }
                                    Spacer()
                                }.padding(6).contentShape(Rectangle())
                                    .modifier(DraftTileInteractions(store: store, window: action.window, draggable: false))
                            }
                        }
                    }.frame(height: min(200, CGFloat(actions.count * 44)))
                }.padding(14).frame(width: 290)
            }
    }
}
