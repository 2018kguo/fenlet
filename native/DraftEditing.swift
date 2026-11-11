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

struct GrabDots: View {
    var body: some View {
        VStack(spacing: 2) {
            ForEach(0..<3) { _ in
                HStack(spacing: 2) { Circle().frame(width: 2, height: 2); Circle().frame(width: 2, height: 2) }
            }
        }.foregroundStyle(.secondary).frame(width: 8, height: 12).fixedSize().accessibilityHidden(true)
    }
}
/// Cursor rectangles keep hover local to the view without changing app focus.
struct CursorRegion: NSViewRepresentable {
    let cursor: NSCursor
    final class Region: NSView {
        var cursor: NSCursor = .arrow
        override func resetCursorRects() { addCursorRect(bounds, cursor: cursor) }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
    }
    func makeNSView(context: Context) -> Region { let view = Region(); view.cursor = cursor; return view }
    func updateNSView(_ view: Region, context: Context) {
        view.cursor = cursor; view.window?.invalidateCursorRects(for: view)
    }
}

struct DraftTileInteractions: ViewModifier {
    @ObservedObject var store: Store
    let window: WindowInfo
    @State private var angle = 0.0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func body(content: Content) -> some View {
        if store.hasLayout && window.protected_reason == nil {
            content.rotationEffect(.degrees(reduceMotion ? 0 : angle))
                .modifier(DraftTargetRegion(kind: .pane(window.id)))
                .opacity(store.draggedWindowID == window.id ? 0.4 : 1)
                .overlay { RoundedRectangle(cornerRadius: 7).strokeBorder(store.draftTarget == .pane(window.id) ? Color.accentColor : .clear, lineWidth: 2) }
                .highPriorityGesture(DragGesture(minimumDistance: 5, coordinateSpace: .named("fenletDraft"))
                    .onChanged { value in angle = 0; store.trackDraftDrag(window, at: value.location) }
                    .onEnded { value in store.finishDraftDrag(window.id, at: value.location) }, including: store.editingDraft ? .none : .all)
                .task {
                    guard store.claimDraftIntroduction(window.id), !reduceMotion else { return }
                    // A short edit-mode cue, once per window per draft. No idle loop.
                    for degrees in [-0.8, 0.8, -0.4, 0] {
                        guard !Task.isCancelled, store.draggedWindowID == nil else { angle = 0; return }
                        withAnimation(.easeInOut(duration: 0.1)) { angle = degrees }
                        do { try await Task.sleep(nanoseconds: 100_000_000) } catch { angle = 0; return }
                    }
                }
                .contextMenu {
                    Menu("Move to display") {
                        ForEach(store.availableDisplays) { display in
                            Button(display.name) { store.editDraft(["--move", window.id, display.id]) }
                        }
                    }
                    Button("Keep in background") { store.editDraft(["--minimize", window.id]) }.disabled(window.is_focused == true)
                    Button("Close window", role: .destructive) { store.editDraft(["--close", window.id]) }.disabled(window.is_focused == true)
                }.disabled(store.busy || store.editingDraft)
        } else { content }
    }
}

/// Every non-display action stays visible in the same drag coordinate space.
struct DraftTray: View {
    @ObservedObject var store: Store
    let kind: String
    var actions: [ActionInfo] { store.preview?.plan.actions.filter { $0.kind == kind } ?? [] }
    var title: String { kind == "close" ? "To close" : "To minimize" }
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Image(systemName: kind == "close" ? "xmark.rectangle" : "minus.rectangle")
                Text(title)
                Spacer(minLength: 0)
                Text("\(actions.count)").monospacedDigit().foregroundStyle(.secondary)
            }.font(.system(size: 11, weight: .medium))
            if actions.isEmpty {
                Text(kind == "close" ? "Drop to close" : "Drop to minimize")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView(.horizontal) {
                    LazyHStack(alignment: .top, spacing: 7) {
                        ForEach(actions) { action in
                            VStack(alignment: .leading, spacing: 3) {
                                WindowTile(window: action.window, compact: true, editable: true, captures: store.windowPreviews,
                                           inspect: { store.windowPeek.show(action.window, captures: store.windowPreviews) },
                                           hoverChange: { inside in
                                    if inside && store.draggedWindowID == nil {
                                        store.windowPeek.schedule(action.window, captures: store.windowPreviews, in: store.liveInventory?.windows ?? [])
                                    } else { store.windowPeek.hide() }
                                }).modifier(DraftTileInteractions(store: store, window: action.window))
                                    .frame(width: 78, height: 44)
                                    .accessibilityValue(kind == "close" ? "Will close only after confirmation. Drag to a display to keep visible." : "Will minimize only after confirmation. Drag to a display to keep visible.")
                                Text(action.window.title.isEmpty ? action.window.app_name : action.window.title)
                                    .font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1).frame(width: 78, alignment: .leading)
                            }
                        }
                    }.padding(.vertical, 1)
                }.scrollIndicators(.hidden)
            }
        }.padding(8).frame(maxWidth: .infinity).frame(height: 94)
            .background(.quaternary.opacity(0.18), in: RoundedRectangle(cornerRadius: 15))
            .overlay { RoundedRectangle(cornerRadius: 15).strokeBorder(store.draftTarget == .disposition(kind) ? Color.accentColor : .primary.opacity(0.05), lineWidth: 1) }
            .modifier(DraftTargetRegion(kind: .disposition(kind)))
            .accessibilityElement(children: .contain).accessibilityLabel(title + " after confirmation")
    }
}
