import Foundation
import Darwin
import AppKit

@MainActor enum SingleInstance {
    private static var descriptor: Int32 = -1
    static func acquire() -> Bool {
        let directory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Fenlet")
        do { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]) }
        catch { return false }
        descriptor = open(directory.appendingPathComponent("instance.lock").path, O_CREAT | O_RDWR | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { return false }
        let acquired = flock(descriptor, LOCK_EX | LOCK_NB) == 0
        let existing = NSRunningApplication.runningApplications(withBundleIdentifier: "org.2018kguo.desk-tidy").first(where: { $0.processIdentifier != getpid() && $0.isFinishedLaunching })
        if acquired && existing == nil { return true }
        close(descriptor); descriptor = -1
        if let url = existing?.bundleURL {
            NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
        }
        return false
    }
}

/// A serial connection to the shared CLI. A failed request is never resent.
final class Engine: @unchecked Sendable {
    private let queue = DispatchQueue(label: "org.2018kguo.fenlet.engine")
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var sequence = 0
    private func stop() {
        try? input?.close()
        if let process, process.isRunning { process.terminate() }
        try? output?.close()
        process = nil; input = nil; output = nil
    }
    func stopWhenIdle() { queue.async { self.stop() } }
    func request(_ args: [String], settings: Settings, input text: String? = nil, workFocus: WorkFocus? = nil) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    if self.process?.isRunning != true {
                        self.stop()
                        let process = Process(), input = Pipe(), output = Pipe()
                        let root = Bundle.main.resourceURL!
                        process.executableURL = root.appendingPathComponent("bin/fenlet")
                        process.arguments = ["--json", "serve"]
                        process.currentDirectoryURL = root
                        process.standardInput = input; process.standardOutput = output; process.standardError = FileHandle.nullDevice
                        try process.run()
                        self.process = process; self.input = input.fileHandleForWriting; self.output = output.fileHandleForReading
                    }
                    self.sequence += 1
                    var arguments = args
                    if let file = settings.envFile, !file.isEmpty { arguments = ["--env-file", file] + arguments }
                    var request: [String: Any] = ["id": self.sequence, "args": arguments]
                    if let text { request["input"] = text }
                    if let focus = workFocus { request["focus"] = ["pid": focus.pid, "window_id": focus.windowID] }
                    var data = try JSONSerialization.data(withJSONObject: request); data.append(10)
                    try self.input!.write(contentsOf: data)
                    var response = Data()
                    let deadline = Date().addingTimeInterval(60)
                    while response.last != 10 {
                        var descriptor = pollfd(fd: self.output!.fileDescriptor, events: Int16(POLLIN), revents: 0)
                        guard Date() < deadline, poll(&descriptor, 1, 500) >= 0 else { throw TidyError.message("Engine response timed out. Inspect the desktop before trying again.") }
                        if descriptor.revents == 0 { continue }
                        // FileHandle can wait to fill the requested size on a pipe.
                        // One POSIX read returns the bytes currently available.
                        var chunk = [UInt8](repeating: 0, count: 65536)
                        let count = Darwin.read(self.output!.fileDescriptor, &chunk, chunk.count)
                        guard count > 0, response.count + count <= 32 * 1024 * 1024 else { throw TidyError.message("The engine disconnected. Inspect the desktop before trying again.") }
                        response.append(contentsOf: chunk.prefix(count))
                    }
                    guard let object = try JSONSerialization.jsonObject(with: response) as? [String: Any], object["id"] as? Int == self.sequence else {
                        throw TidyError.message("The engine returned an unmatched response. Inspect before trying again.")
                    }
                    continuation.resume(returning: response)
                } catch {
                    self.stop()
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
