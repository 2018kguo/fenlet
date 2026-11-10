import Foundation
#if canImport(Sparkle) && !FENLET_UI_TEST
import Sparkle

@MainActor final class Updates: NSObject, SPUUpdaterDelegate {
    static let shared = Updates()
    private var controller: SPUStandardUpdaterController?
    private var isBusy: () -> Bool = { false }
    func start(isBusy: @escaping () -> Bool) {
        self.isBusy = isBusy
        controller = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: self, userDriverDelegate: nil)
        controller?.startUpdater()
    }
    func check() { controller?.checkForUpdates(nil) }
    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem, untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        guard isBusy() else { return false }
        Task {
            while isBusy() { try? await Task.sleep(nanoseconds: 250_000_000) }
            Store.engine.stopWhenIdle()
            installHandler()
        }
        return true
    }
}
#else
@MainActor final class Updates {
    static let shared = Updates()
    func start(isBusy: @escaping () -> Bool) { }
    func check() { }
}
#endif
