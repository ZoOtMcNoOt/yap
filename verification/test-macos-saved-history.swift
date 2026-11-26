// Operate the installed Yap workspace through macOS Accessibility.
import ApplicationServices
import Foundation

struct HistoryFailure: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
        return nil
    }
    return value
}

func find(_ root: AXUIElement, role: String, label: String) -> AXUIElement? {
    var pending = [root]
    while let element = pending.popLast() {
        if attribute(element, kAXRoleAttribute) as? String == role {
            for name in [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute] {
                if let text = attribute(element, name) as? String,
                   text.trimmingCharacters(in: .whitespacesAndNewlines) == label {
                    return element
                }
            }
        }
        if let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] {
            pending.append(contentsOf: children.reversed())
        }
    }
    return nil
}

func waitFor(_ detail: String, _ ready: () throws -> Bool) throws {
    let limit = ProcessInfo.processInfo.systemUptime + 20
    repeat {
        if try ready() { return }
        Thread.sleep(forTimeInterval: 0.2)
    } while ProcessInfo.processInfo.systemUptime < limit
    throw HistoryFailure("Did not find \(detail) in the installed Yap workspace")
}

func press(_ button: AXUIElement, _ label: String) throws {
    let result = AXUIElementPerformAction(button, kAXPressAction as CFString)
    guard result == .success else {
        throw HistoryFailure("Could not activate \(label) (AX error \(result.rawValue))")
    }
}

guard CommandLine.arguments.count >= 3, let pid = Int32(CommandLine.arguments[1]) else {
    throw HistoryFailure("Expected the installed Yap process ID and workspace action")
}
guard AXIsProcessTrusted() else {
    throw HistoryFailure("The runner has not granted Accessibility access to the installed Yap workspace")
}
let app = AXUIElementCreateApplication(pid)

func clickButton(_ label: String) throws {
    var dismissed = false
    try waitFor(label) {
        if !dismissed, let skip = find(app, role: kAXButtonRole, label: "Skip for now") {
            try press(skip, "Skip for now")
            dismissed = true
            return false
        }
        guard let button = find(app, role: kAXButtonRole, label: label),
              attribute(button, kAXEnabledAttribute) as? Bool == true else { return false }
        try press(button, label)
        return true
    }
}

switch Array(CommandLine.arguments.dropFirst(2)) {
case ["settings"]:
    try clickButton("Settings")
    try clickButton("General")
case ["start"]:
    try clickButton("Start")
case ["stop"]:
    try clickButton("Stop")
default:
    guard CommandLine.arguments.count == 5, CommandLine.arguments[2] == "review" else {
        throw HistoryFailure("Expected settings, start, stop, or review with a recording name and transcript path")
    }
    let recording = CommandLine.arguments[3]
    let reference = try String(contentsOfFile: CommandLine.arguments[4], encoding: .utf8)
        .trimmingCharacters(in: .whitespacesAndNewlines)
    try clickButton("Review recording \(recording)")
    try waitFor("saved transcript and its open action") {
        find(app, role: kAXButtonRole, label: "Open transcript for \(recording)") != nil &&
            find(app, role: kAXStaticTextRole, label: reference) != nil
    }
    print("The installed Mac client reopened \(recording) from History and displayed the complete transcript.")
}
