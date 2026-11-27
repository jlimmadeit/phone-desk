import AppKit
import ScreenCaptureKit
import CoreGraphics

func fail(_ text: String) -> Never {
    FileHandle.standardError.write(Data((text + "\n").utf8))
    exit(1)
}

@main struct Mirror {
    @MainActor static func main() async {
        _ = NSApplication.shared
        let args = Array(CommandLine.arguments.dropFirst())
        let appID = "com.apple.ScreenContinuity"
        if args == ["list"] && NSRunningApplication.runningApplications(withBundleIdentifier: appID).isEmpty {
            print("[]")
            return
        }
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
            let windows = content.windows.filter {
                $0.owningApplication?.bundleIdentifier == appID && $0.windowLayer == 0 &&
                $0.frame.width >= 180 && $0.frame.height >= 180
            }
            if args == ["list"] {
                let rows = windows.map { ["id": String($0.windowID), "name": $0.title ?? "iPhone Mirroring"] }
                FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: rows))
                return
            }
            guard args.count >= 2, let window = windows.first(where: { String($0.windowID) == args[1] }),
                  let pid = window.owningApplication?.processID else { fail("Open the selected iPhone Mirroring window.") }
            if args[0] == "stream" {
                let filter = SCContentFilter(desktopIndependentWindow: window)
                let config = SCStreamConfiguration()
                config.width = Int(window.frame.width)
                config.height = Int(window.frame.height)
                config.showsCursor = false
                config.ignoreShadowsSingleWindow = true
                while true {
                    let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
                    guard let data = NSBitmapImageRep(cgImage: image).representation(using: .jpeg, properties: [.compressionFactor: 0.78]) else { fail("Frame unavailable.") }
                    var size = UInt32(data.count).bigEndian
                    FileHandle.standardOutput.write(Data(bytes: &size, count: 4))
                    FileHandle.standardOutput.write(data)
                    try await Task.sleep(nanoseconds: 160_000_000)
                }
            }
            let tap = args[0] == "tap"
            guard (tap && args.count == 5) || (args[0] == "drag" && args.count == 7),
                  let duration = Double(args.last!), (0.05...2).contains(duration),
                  AXIsProcessTrusted(), let app = NSRunningApplication(processIdentifier: pid)
            else { fail("Allow Accessibility for Phone Desk to click the mirroring window.") }
            let coords = args.dropFirst(2).dropLast().compactMap { Double($0) }
            guard coords.count == (tap ? 2 : 4), coords.allSatisfy({ (0...1).contains($0) }) else { fail("Invalid click position.") }
            app.activate(options: [])
            try await Task.sleep(nanoseconds: 180_000_000)
            guard app.isActive else { fail("Bring iPhone Mirroring to the foreground.") }
            func point(_ i: Int) -> CGPoint {
                CGPoint(x: window.frame.minX + coords[i] * (window.frame.width-1),
                        y: window.frame.minY + coords[i+1] * (window.frame.height-1))
            }
            func mouse(_ type: CGEventType, _ pos: CGPoint) {
                guard let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: pos, mouseButton: .left)
                else { fail("Could not create pointer event.") }
                event.postToPid(pid)
            }
            let start = point(0)
            mouse(.leftMouseDown, start)
            var end = start
            if !tap {
                let dest = point(2)
                for step in 1...12 {
                    try await Task.sleep(nanoseconds: UInt64(duration * 1e9 / 12))
                    end = CGPoint(x: start.x + (dest.x-start.x)*Double(step)/12, y: start.y + (dest.y-start.y)*Double(step)/12)
                    mouse(.leftMouseDragged, end)
                }
            }
            mouse(.leftMouseUp, end)
        } catch { fail(error.localizedDescription) }
    }
}
