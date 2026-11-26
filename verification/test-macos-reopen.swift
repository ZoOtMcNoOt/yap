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

func openBundle(_ arguments: [String]) throws {
    let launcher = Process()
    launcher.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    launcher.arguments = arguments
    try launcher.run()
    try waitFor("LaunchServices did not finish opening the bundle") { !launcher.isRunning }
    guard launcher.terminationStatus == 0 else { throw ProbeFailure("LaunchServices refused to open Yap") }
}

func verifyReopen(bundle: URL, profile: URL) throws {
    let log = profile.appendingPathComponent("logs/yap.log")
    let arguments = ["--env", "YAP_APP_DATA_DIR=\(profile.path)", "-a", bundle.path]
    guard let identity = Bundle(url: bundle)?.bundleIdentifier else {
        throw ProbeFailure("Missing bundle identifier")
    }
    func instance() -> NSRunningApplication? {
        NSRunningApplication.runningApplications(withBundleIdentifier: identity).first {
            $0.bundleURL?.resolvingSymlinksInPath().path == bundle.resolvingSymlinksInPath().path
        }
    }
    guard instance() == nil else { throw ProbeFailure("The first installed smoke process is still running") }
    try openBundle(["-n", "-g", "-j"] + arguments)
    try waitFor("Could not locate the installed app after hidden launch") { instance() != nil }
    guard let app = instance() else { throw ProbeFailure("The installed app exited during launch") }
    defer {
        if !app.isTerminated {
            _ = app.terminate()
            do { try waitFor("App did not terminate") { app.isTerminated } }
            catch { _ = app.forceTerminate() }
        }
    }
    let pid = app.processIdentifier
    try waitFor("Hidden launch did not establish a running hidden workspace") {
        guard let contents = try? String(contentsOf: log, encoding: .utf8) else { return false }
        return contents.contains(" app start") && app.isHidden && !hasWorkspaceWindow(pid)
    }
    let offset = try Data(contentsOf: log).count
    try openBundle(arguments)
    try waitFor("Reopen did not activate the original process and show its workspace") {
        let tail = try Data(contentsOf: log).dropFirst(offset)
        return !app.isTerminated && app.isActive && hasWorkspaceWindow(pid)
            && String(decoding: tail, as: UTF8.self).contains("macOS asked Yap to reopen the main window")
    }
    print("LaunchServices reopened the hidden workspace in the original Yap process \(pid).")
}

guard CommandLine.arguments.count == 3 else { throw ProbeFailure("Expected an app bundle and fresh profile directory") }
try verifyReopen(bundle: URL(fileURLWithPath: CommandLine.arguments[1]),
                 profile: URL(fileURLWithPath: CommandLine.arguments[2]))
