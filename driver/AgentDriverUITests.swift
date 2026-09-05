//
//  AgentDriverUITests.swift
//  ios-agent-use — https://github.com/NoelSason/ios-agent-use
//
//  Drop this one file into any XCUITest target. It stays inert during a normal
//  `xcodebuild test` run (it skips when its environment variable is absent), and
//  wakes up only when the `iosagent` CLI drives it.
//
//  The CLI passes a base64 JSON action script in TEST_RUNNER_IOSAGENT_SCRIPT_B64;
//  xcodebuild strips the TEST_RUNNER_ prefix before handing it to the runner.
//  Results come back as XCTAttachments, which the CLI extracts from the
//  .xcresult with `xcresulttool export attachments`.
//
//  Public API only. Nothing here is added to the app under test.
//

import XCTest
#if canImport(UIKit)
import UIKit
#endif

final class AgentDriverUITests: XCTestCase {

    // MARK: - Script model

    private struct Script: Decodable {
        var launch: Launch?
        var capture: Capture?
        var steps: [Step]
    }

    private struct Launch: Decodable {
        /// "activate" keeps app state across batches; "launch" starts clean.
        var mode: String?
        var args: [String]?
        var env: [String: String]?
    }

    private struct Capture: Decodable {
        var afterEveryStep: Bool?
        var screenshot: Bool?
        var tree: Bool?
        var treeDepth: Int?
    }

    private struct Selector: Decodable {
        var id: String?
        var label: String?
        var type: String?
        var index: Int?
        var point: [Double]?
        var norm: [Double]?
    }

    private struct Step: Decodable {
        var action: String
        // selector shorthands, so the common case stays a one-liner
        var id: String?
        var label: String?
        var type: String?
        var index: Int?
        var point: [Double]?
        var norm: [Double]?
        // explicit selectors
        var target: Selector?
        var from: Selector?
        var to: Selector?
        // parameters
        var text: String?
        var name: String?
        var value: String?
        var direction: String?
        var seconds: Double?
        var timeout: Double?
        var duration: Double?
        var scale: Double?
        var velocity: Double?
        var count: Int?

        var selector: Selector {
            target ?? Selector(id: id, label: label, type: type,
                               index: index, point: point, norm: norm)
        }
    }

    private struct StepResult: Encodable {
        var index: Int
        var action: String
        var ok: Bool
        var ms: Int
        var error: String?
        var screenshot: String?
        var tree: String?
        var note: String?
    }

    private struct RunResult: Encodable {
        var ok: Bool
        var steps: [StepResult]
        var screenSize: [Double]
        var imageSize: [Double]
        var orientation: Int
        var driverVersion: String
    }

    private enum DriverError: Error, CustomStringConvertible {
        case noMatch(String)
        case unknownAction(String)
        case badArguments(String)
        case assertionFailed(String)

        var description: String {
            switch self {
            case .noMatch(let s):        return "no element matched \(s)"
            case .unknownAction(let a):  return "unknown action '\(a)'"
            case .badArguments(let m):   return "bad arguments: \(m)"
            case .assertionFailed(let m):return "assertion failed: \(m)"
            }
        }
    }

    private static let version = "0.1.0"

    private var app: XCUIApplication!
    private var imageSize: [Double] = []
    private var capture = Capture(afterEveryStep: true, screenshot: true,
                                  tree: true, treeDepth: 60)

    // MARK: - Entry point

    func testAgentScript() throws {
        let environment = ProcessInfo.processInfo.environment
        guard let encoded = environment["IOSAGENT_SCRIPT_B64"],
              let data = Data(base64Encoded: encoded) else {
            throw XCTSkip("""
                Not driven by iosagent. This test is a driver for the ios-agent-use \
                CLI and is skipped during ordinary test runs.
                """)
        }

        continueAfterFailure = true

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let script = try decoder.decode(Script.self, from: data)
        if let requested = script.capture { capture = merge(capture, requested) }

        app = XCUIApplication()
        if let bundle = environment["IOSAGENT_BUNDLE_ID"], !bundle.isEmpty {
            app = XCUIApplication(bundleIdentifier: bundle)
        }
        startApp(script.launch)

        var results: [StepResult] = []
        var allOK = true

        // step 0 is the state the batch starts from, so a diff has a baseline
        results.append(observe(index: 0, action: "baseline", ok: true, ms: 0, error: nil))

        for (offset, step) in script.steps.enumerated() {
            let index = offset + 1
            let began = Date()
            var failure: String?
            var note: String?
            do {
                note = try perform(step)
            } catch {
                failure = String(describing: error)
                allOK = false
            }
            let ms = Int(Date().timeIntervalSince(began) * 1000)
            var result = observe(index: index, action: step.action,
                                 ok: failure == nil, ms: ms, error: failure)
            result.note = note
            results.append(result)
            if failure != nil { break }   // a broken step invalidates every later one
        }

        let size = app.frame.size
        let run = RunResult(ok: allOK, steps: results,
                            screenSize: [Double(size.width), Double(size.height)],
                            imageSize: imageSize,
                            orientation: XCUIDevice.shared.orientation.rawValue,
                            driverVersion: Self.version)
        attach(name: "iosagent-result.json",
               data: try JSONEncoder().encode(run), type: "public.json")

        XCTAssertTrue(allOK, "one or more agent steps failed; see iosagent-result.json")
    }

    // MARK: - Lifecycle

    private func startApp(_ launch: Launch?) {
        let mode = launch?.mode ?? "activate"
        if let args = launch?.args { app.launchArguments += args }
        if let env = launch?.env { env.forEach { app.launchEnvironment[$0] = $1 } }

        switch mode {
        case "activate":
            // Keeps whatever state the previous batch left behind. This is what
            // makes a sequence of batches feel like one session.
            app.activate()
        case "none":
            break
        default:
            app.launch()
        }
        _ = app.wait(for: .runningForeground, timeout: 30)
    }

    // MARK: - Actions

    private func perform(_ step: Step) throws -> String? {
        switch step.action {
        case "tap":
            try resolveInteractable(step.selector).tap()
        case "doubleTap":
            try resolveInteractable(step.selector).doubleTap()
        case "longPress":
            try resolveInteractable(step.selector).press(forDuration: step.duration ?? 1.0)
        case "type":
            let element = try resolveElement(step.selector)
            guard let text = step.text else { throw DriverError.badArguments("type needs `text`") }
            if !element.hasFocus { element.tap() }
            element.typeText(text)
        case "clear":
            let element = try resolveElement(step.selector)
            element.tap()
            let existing = (element.value as? String) ?? ""
            if !existing.isEmpty {
                element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue,
                                        count: existing.count))
            }
        case "drag":
            guard let from = step.from, let to = step.to else {
                throw DriverError.badArguments("drag needs `from` and `to`")
            }
            let start = try coordinate(from)
            let end = try coordinate(to)
            start.press(forDuration: step.duration ?? 0.1, thenDragTo: end)
        case "swipe":
            let element = try resolveElement(step.selector)
            let velocity = XCUIGestureVelocity(rawValue: CGFloat(step.velocity ?? 1000))
            switch (step.direction ?? "up").lowercased() {
            case "down":  element.swipeDown(velocity: velocity)
            case "left":  element.swipeLeft(velocity: velocity)
            case "right": element.swipeRight(velocity: velocity)
            default:      element.swipeUp(velocity: velocity)
            }
        case "pinch":
            try resolveElement(step.selector)
                .pinch(withScale: CGFloat(step.scale ?? 2.0),
                       velocity: CGFloat(step.velocity ?? 1.0))
        case "rotate":
            try resolveElement(step.selector)
                .rotate(CGFloat(step.value.flatMap(Double.init) ?? 1.0),
                        withVelocity: CGFloat(step.velocity ?? 1.0))
        case "scrollTo":
            return try scrollTo(step)
        case "wait":
            Thread.sleep(forTimeInterval: step.seconds ?? 1.0)
        case "waitFor":
            let element = try resolveElement(step.selector, mustExist: false)
            if !element.waitForExistence(timeout: step.timeout ?? 10) {
                throw DriverError.noMatch(describe(step.selector))
            }
        case "waitGone":
            let element = try resolveElement(step.selector, mustExist: false)
            let deadline = Date().addingTimeInterval(step.timeout ?? 10)
            while element.exists && Date() < deadline { Thread.sleep(forTimeInterval: 0.25) }
            if element.exists {
                throw DriverError.assertionFailed("\(describe(step.selector)) is still present")
            }
        case "assertExists":
            _ = try resolveElement(step.selector)
        case "assertLabel":
            let element = try resolveElement(step.selector)
            guard let expected = step.text ?? step.value else {
                throw DriverError.badArguments("assertLabel needs `text`")
            }
            guard element.label.contains(expected) else {
                throw DriverError.assertionFailed(
                    "label is '\(element.label)', expected it to contain '\(expected)'")
            }
        case "screenshot", "dumpTree":
            break   // observation happens after every step anyway
        case "activate":
            app.activate()
        case "terminate":
            app.terminate()
        case "relaunch":
            app.terminate()
            app.launch()
        case "rotateDevice":
            XCUIDevice.shared.orientation = orientation(step.value ?? step.direction ?? "portrait")
        case "pressHome":
            XCUIDevice.shared.press(.home)
        default:
            throw DriverError.unknownAction(step.action)
        }
        return nil
    }

    private func scrollTo(_ step: Step) throws -> String {
        let element = try resolveElement(step.selector, mustExist: false)
        var scroller: XCUIElement = app
        if let within = step.from, let found = try? resolveElement(within) {
            scroller = found
        }
        let limit = step.count ?? 10
        for attempt in 0..<limit {
            if element.exists && element.isHittable {
                return "found after \(attempt) swipe(s)"
            }
            switch (step.direction ?? "up").lowercased() {
            case "down":  scroller.swipeDown()
            case "left":  scroller.swipeLeft()
            case "right": scroller.swipeRight()
            default:      scroller.swipeUp()
            }
        }
        throw DriverError.noMatch("\(describe(step.selector)) after \(limit) swipes")
    }

    private func orientation(_ name: String) -> UIDeviceOrientation {
        switch name.lowercased() {
        case "landscape", "landscapeleft":  return .landscapeLeft
        case "landscaperight":              return .landscapeRight
        case "portraitupsidedown":          return .portraitUpsideDown
        default:                            return .portrait
        }
    }

    // MARK: - Element resolution

    private func query(for selector: Selector) -> XCUIElementQuery {
        // Naming a `type` narrows the traversal. On dense screens an untyped
        // query walks the whole tree and can take tens of seconds.
        var query = app.descendants(matching: elementType(selector.type))
        if let id = selector.id { query = query.matching(identifier: id) }
        if let label = selector.label {
            query = query.containing(NSPredicate(format: "label CONTAINS[c] %@", label))
        }
        return query
    }

    private func resolveElement(_ selector: Selector, mustExist: Bool = true) throws -> XCUIElement {
        if selector.point != nil || selector.norm != nil {
            throw DriverError.badArguments(
                "this action needs an element (`id`, `label` or `type`), not a coordinate")
        }
        if selector.id == nil && selector.label == nil && selector.type == nil {
            throw DriverError.badArguments("empty selector")
        }
        let matches = query(for: selector)
        let element = selector.index.map { matches.element(boundBy: $0) } ?? matches.firstMatch
        if mustExist && !element.waitForExistence(timeout: 5) {
            throw DriverError.noMatch(describe(selector))
        }
        return element
    }

    /// Same as `resolveElement`, but falls back to a coordinate tap so callers can
    /// address anything on screen, identifier or not.
    private func resolveInteractable(_ selector: Selector) throws -> Tappable {
        if selector.point != nil || selector.norm != nil {
            return .coordinate(try coordinate(selector))
        }
        return .element(try resolveElement(selector))
    }

    private func coordinate(_ selector: Selector) throws -> XCUICoordinate {
        let base: XCUIElement
        if selector.id != nil || selector.label != nil || selector.type != nil {
            base = try resolveElement(selector)
        } else {
            base = app
        }
        if let norm = selector.norm, norm.count == 2 {
            return base.coordinate(withNormalizedOffset:
                CGVector(dx: norm[0], dy: norm[1]))
        }
        if let point = selector.point, point.count == 2 {
            return base.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
                       .withOffset(CGVector(dx: point[0], dy: point[1]))
        }
        return base.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
    }

    private enum Tappable {
        case element(XCUIElement)
        case coordinate(XCUICoordinate)

        func tap() {
            switch self {
            case .element(let e):    e.tap()
            case .coordinate(let c): c.tap()
            }
        }
        func doubleTap() {
            switch self {
            case .element(let e):    e.doubleTap()
            case .coordinate(let c): c.doubleTap()
            }
        }
        func press(forDuration duration: TimeInterval) {
            switch self {
            case .element(let e):    e.press(forDuration: duration)
            case .coordinate(let c): c.press(forDuration: duration)
            }
        }
    }

    private func describe(_ selector: Selector) -> String {
        var parts: [String] = []
        if let id = selector.id { parts.append("id='\(id)'") }
        if let label = selector.label { parts.append("label~'\(label)'") }
        if let type = selector.type { parts.append("type=\(type)") }
        if let index = selector.index { parts.append("index=\(index)") }
        return parts.isEmpty ? "<empty selector>" : parts.joined(separator: " ")
    }

    // MARK: - Observation

    private func observe(index: Int, action: String, ok: Bool,
                         ms: Int, error: String?) -> StepResult {
        var result = StepResult(index: index, action: action, ok: ok, ms: ms, error: error)
        guard capture.afterEveryStep ?? true else { return result }

        if capture.screenshot ?? true {
            let name = String(format: "iosagent-%03d-screen.png", index)
            // XCUIScreen captures the whole display -- including popovers and
            // sheets, which live outside the application element and so are
            // missing from app.screenshot(). Its image is the device's native
            // framebuffer, which stays portrait however the interface is
            // rotated; `orientation` below tells the host how to turn it back.
            let shot = XCUIScreen.main.screenshot()
            let image = shot.image
            imageSize = [Double(image.size.width * image.scale),
                         Double(image.size.height * image.scale)]
            attach(name: name, data: shot.pngRepresentation, type: "public.png")
            result.screenshot = name
        }
        if capture.tree ?? true, let data = treeJSON() {
            let name = String(format: "iosagent-%03d-tree.json", index)
            attach(name: name, data: data, type: "public.json")
            result.tree = name
        }
        return result
    }


    private func treeJSON() -> Data? {
        guard let snapshot = try? app.snapshot() else { return nil }
        let root = node(from: snapshot, depth: 0, limit: capture.treeDepth ?? 60)
        return try? JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }

    private func node(from snapshot: XCUIElementSnapshot, depth: Int, limit: Int) -> [String: Any] {
        let frame = snapshot.frame
        var payload: [String: Any] = [
            "type": typeName(snapshot.elementType),
            "frame": [Int(frame.origin.x), Int(frame.origin.y),
                      Int(frame.size.width), Int(frame.size.height)],
        ]
        if !snapshot.identifier.isEmpty { payload["id"] = snapshot.identifier }
        if !snapshot.label.isEmpty { payload["label"] = snapshot.label }
        if let value = snapshot.value as? String, !value.isEmpty { payload["value"] = value }
        if !snapshot.isEnabled { payload["enabled"] = false }
        if snapshot.isSelected { payload["selected"] = true }
        if depth < limit, !snapshot.children.isEmpty {
            payload["children"] = snapshot.children.map {
                node(from: $0, depth: depth + 1, limit: limit)
            }
        }
        return payload
    }

    private func attach(name: String, data: Data, type: String) {
        let attachment = XCTAttachment(uniformTypeIdentifier: type, name: name,
                                       payload: data, userInfo: nil)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func merge(_ base: Capture, _ override: Capture) -> Capture {
        Capture(afterEveryStep: override.afterEveryStep ?? base.afterEveryStep,
                screenshot: override.screenshot ?? base.screenshot,
                tree: override.tree ?? base.tree,
                treeDepth: override.treeDepth ?? base.treeDepth)
    }

    private func elementType(_ name: String?) -> XCUIElement.ElementType {
        switch (name ?? "any").lowercased() {
        case "button":       return .button
        case "statictext", "text": return .staticText
        case "textfield":    return .textField
        case "securetextfield": return .secureTextField
        case "textview":     return .textView
        case "image":        return .image
        case "cell":         return .cell
        case "switch":       return .switch
        case "slider":       return .slider
        case "link":         return .link
        case "navigationbar":return .navigationBar
        case "tabbar":       return .tabBar
        case "toolbar":      return .toolbar
        case "menuitem":     return .menuItem
        case "collectionview": return .collectionView
        case "table":        return .table
        case "scrollview":   return .scrollView
        case "webview":      return .webView
        case "alert":        return .alert
        case "sheet":        return .sheet
        case "window":       return .window
        case "other":        return .other
        default:             return .any
        }
    }

    private func typeName(_ type: XCUIElement.ElementType) -> String {
        switch type {
        case .application: return "Application"
        case .window: return "Window"
        case .button: return "Button"
        case .staticText: return "StaticText"
        case .textField: return "TextField"
        case .secureTextField: return "SecureTextField"
        case .textView: return "TextView"
        case .image: return "Image"
        case .cell: return "Cell"
        case .switch: return "Switch"
        case .slider: return "Slider"
        case .link: return "Link"
        case .navigationBar: return "NavigationBar"
        case .tabBar: return "TabBar"
        case .toolbar: return "Toolbar"
        case .menuItem: return "MenuItem"
        case .collectionView: return "CollectionView"
        case .table: return "Table"
        case .scrollView: return "ScrollView"
        case .webView: return "WebView"
        case .alert: return "Alert"
        case .sheet: return "Sheet"
        case .other: return "Other"
        case .any: return "Any"
        default: return "Type\(type.rawValue)"
        }
    }
}
