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
    let controller = NSApplication.shared
    controller.setActivationPolicy(.accessory)
    controller.finishLaunching()
    try openBundle(["-n"] + arguments)
    try waitFor("Could not locate the installed app after launch") { instance() != nil }
    guard let app = instance() else { throw ProbeFailure("The installed app exited during launch") }
    defer {
        if !app.isTerminated {
            _ = app.terminate()
            do { try waitFor("App did not terminate") { app.isTerminated } }
            catch { _ = app.forceTerminate() }
        }
    }
    let pid = app.processIdentifier
    do {
        try waitFor("Installed workspace never appeared") {
            guard let contents = try? String(contentsOf: log, encoding: .utf8) else { return false }
            return contents.contains(" app start") && hasWorkspaceWindow(pid)
        }
        try openBundle(arguments)
        try waitFor("LaunchServices did not activate the installed workspace") { app.isActive }
        if !app.hide() {
            // Send the standard Hide shortcut only to the disposable app.
            guard CGPreflightPostEventAccess(),
                  let down = CGEvent(keyboardEventSource: nil, virtualKey: 4, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: 4, keyDown: false) else {
                throw ProbeFailure("macOS declined to hide the active app and input automation is unavailable")
            }
            down.flags = .maskCommand
            up.flags = .maskCommand
            down.postToPid(pid)
            up.postToPid(pid)
        }
        try waitFor("The installed workspace did not disappear") { app.isHidden && !hasWorkspaceWindow(pid) }
    } catch {
        let started = (try? String(contentsOf: log, encoding: .utf8).contains(" app start")) ?? false
        throw ProbeFailure("\(error.localizedDescription); profileStarted=\(started) active=\(app.isActive) hidden=\(app.isHidden) visible=\(hasWorkspaceWindow(pid)) policy=\(app.activationPolicy.rawValue)")
    }
    let offset = try Data(contentsOf: log).count
    try openBundle(arguments)
    do {
        try waitFor("Reopen did not restore the original workspace") {
            !app.isTerminated && app.isActive && !app.isHidden && hasWorkspaceWindow(pid)
        }
    } catch {
        throw ProbeFailure("\(error.localizedDescription); active=\(app.isActive) hidden=\(app.isHidden) visible=\(hasWorkspaceWindow(pid)) terminated=\(app.isTerminated)")
    }
    let tail = try Data(contentsOf: log).dropFirst(offset)
    let handledReopen = String(decoding: tail, as: UTF8.self).contains("macOS asked Yap to reopen the main window")
    print("LaunchServices reopened the hidden workspace in the original Yap process \(pid); Tauri reopen event observed: \(handledReopen).")
}

guard CommandLine.arguments.count == 3 else { throw ProbeFailure("Expected an app bundle and fresh profile directory") }
try verifyReopen(bundle: URL(fileURLWithPath: CommandLine.arguments[1]),
                 profile: URL(fileURLWithPath: CommandLine.arguments[2]))
