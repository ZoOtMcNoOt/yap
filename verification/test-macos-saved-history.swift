// Read a saved dictation through the installed application's accessibility tree.
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

guard CommandLine.arguments.count == 3, let pid = Int32(CommandLine.arguments[1]) else {
    throw HistoryFailure("Expected the installed Yap process ID and reference transcript path")
}
guard AXIsProcessTrusted() else {
    throw HistoryFailure("The runner has not granted Accessibility access to read the installed Yap workspace")
}

let app = AXUIElementCreateApplication(pid)
let recording = "live-s-package-dictation"
let reference = try String(contentsOfFile: CommandLine.arguments[2], encoding: .utf8)
    .trimmingCharacters(in: .whitespacesAndNewlines)
var dismissedOnboarding = false
try waitFor("Review recording \(recording)") {
    if !dismissedOnboarding, let skip = find(app, role: kAXButtonRole, label: "Skip for now") {
        try press(skip, "Skip for now")
        dismissedOnboarding = true
        return false
    }
    guard let review = find(app, role: kAXButtonRole, label: "Review recording \(recording)") else {
        return false
    }
    try press(review, "Review recording")
    return true
}
try waitFor("saved transcript and its open action") {
    find(app, role: kAXButtonRole, label: "Open transcript for \(recording)") != nil &&
        find(app, role: kAXStaticTextRole, label: reference) != nil
}
print("The installed Mac client reopened the saved dictation from History and displayed the complete reference transcript.")
