// Exercise LaunchServices against the running smoke-test bundle without Accessibility input.
import AppKit
import CoreGraphics
import Foundation

struct ProbeFailure: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

func waitFor(_ message: String, _ ready: () throws -> Bool) throws {
    let deadline = ProcessInfo.processInfo.systemUptime + 10
    while try !ready() {
        guard ProcessInfo.processInfo.systemUptime < deadline else { throw ProbeFailure(message) }
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.05))
    }
}

func hasWorkspaceWindow(_ pid: pid_t) -> Bool {
    guard let windows = CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID)
            as? [[String: Any]] else { return false }
    // Window titles may be redacted without Screen Recording permission. The
    // workspace is at least 640 × 480 points, much larger than the live overlay.
    return windows.contains { window in
        guard window[kCGWindowOwnerPID as String] as? Int32 == pid,
              window[kCGWindowLayer as String] as? Int == 0,
              let bounds = window[kCGWindowBounds as String] as? [String: Double],
              let width = bounds["Width"], let height = bounds["Height"] else { return false }
        return width >= 640 && height >= 480
    }
}

guard CommandLine.arguments.count == 4, let pid = Int32(CommandLine.arguments[1]),
      let app = NSRunningApplication(processIdentifier: pid),
      app.bundleURL?.standardizedFileURL.path ==
        URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL.path else {
    throw ProbeFailure("Expected the smoke-test process to own the supplied app bundle")
}
let log = URL(fileURLWithPath: CommandLine.arguments[3])
try waitFor("No visible workspace before hiding the app") { hasWorkspaceWindow(pid) }
guard app.hide() else { throw ProbeFailure("macOS did not accept the request to hide Yap") }
try waitFor("The running workspace did not disappear") { app.isHidden && !hasWorkspaceWindow(pid) }
let offset = try Data(contentsOf: log).count

let launcher = Process()
launcher.executableURL = URL(fileURLWithPath: "/usr/bin/open")
// Keep a failed launch in the smoke profile even if LaunchServices starts a process.
let profile = log.deletingLastPathComponent().deletingLastPathComponent()
launcher.arguments = ["--env", "YAP_APP_DATA_DIR=\(profile.path)", "-a", CommandLine.arguments[2]]
try launcher.run()
try waitFor("LaunchServices did not finish opening the bundle") { !launcher.isRunning }
guard launcher.terminationStatus == 0 else { throw ProbeFailure("LaunchServices refused to open Yap") }
try waitFor("Reopen did not activate the original process and show its workspace") {
    let tail = try Data(contentsOf: log).dropFirst(offset)
    return !app.isTerminated && app.isActive && hasWorkspaceWindow(pid)
        && String(decoding: tail, as: UTF8.self).contains("macOS asked Yap to reopen the main window")
}
print("LaunchServices reopened the hidden workspace in the original Yap process \(pid).")
