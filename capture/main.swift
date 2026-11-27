import Foundation
import AVFoundation
import CoreMediaIO
import CoreImage
import ImageIO
import UniformTypeIdentifiers

// Publish the listing result from the actual server launch context for local diagnostics.
func reportDiscovery(_ message: String) {
    guard CommandLine.arguments.dropFirst() == ["list"] else { return }
    let file = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
        .appendingPathComponent("capture-status.txt")
    try? message.write(to: file, atomically: true, encoding: .utf8)
}
func fail(_ message: String) -> Never {
    reportDiscovery(message)
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}
let args = CommandLine.arguments
func pump(_ seconds: Double) {
    RunLoop.current.run(until: Date().addingTimeInterval(seconds))
}
if args.dropFirst() == ["permission"] {
    print(AVCaptureDevice.authorizationStatus(for: .video).rawValue)
    exit(0)
}
if AVCaptureDevice.authorizationStatus(for: .video) == .notDetermined {
    AVCaptureDevice.requestAccess(for: .video) { _ in }
    let deadline = Date().addingTimeInterval(5)
    while AVCaptureDevice.authorizationStatus(for: .video) == .notDetermined && Date() < deadline { pump(0.1) }
}
guard AVCaptureDevice.authorizationStatus(for: .video) == .authorized else {
    fail("Camera access is required by the process running Phone Desk. Allow the macOS Camera prompt or enable the launching app in Privacy & Security → Camera.")
}
var address = CMIOObjectPropertyAddress(
    mSelector: CMIOObjectPropertySelector(kCMIOHardwarePropertyAllowScreenCaptureDevices),
    mScope: CMIOObjectPropertyScope(kCMIOObjectPropertyScopeGlobal),
    mElement: CMIOObjectPropertyElement(kCMIOObjectPropertyElementMain))
var enabled: UInt32 = 1
let system = CMIOObjectID(kCMIOObjectSystemObject)
guard CMIOObjectSetPropertyData(system, &address, 0, nil, 4, &enabled) == noErr else {
    fail("Could not enable wired screen capture.")
}
address.mSelector = CMIOObjectPropertySelector(kCMIOHardwarePropertyDevices)
let listener: CMIOObjectPropertyListenerBlock = { _, _ in }
_ = CMIOObjectAddPropertyListenerBlock(system, &address, DispatchQueue.main, listener)
var size: UInt32 = 0
if CMIOObjectGetPropertyDataSize(system, &address, 0, nil, &size) == noErr, size > 0 {
    var ids = [CMIOObjectID](repeating: 0, count: Int(size)/4)
    _ = ids.withUnsafeMutableBytes { CMIOObjectGetPropertyData(system, &address, 0, nil, size, &size, $0.baseAddress!) }
}
let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.external], mediaType: .muxed, position: .unspecified)
// Bind a verified USB phone to its opaque AVFoundation UUID across reconnects.
let bindingsFile = URL(fileURLWithPath: args[0]).deletingLastPathComponent()
    .appendingPathComponent("capture-bindings.json")
var bindings: [String: String] = [:]
if FileManager.default.fileExists(atPath: bindingsFile.path) {
    bindings = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: bindingsFile))
}
if let setting = ProcessInfo.processInfo.environment["PHONE_CAPTURE_MAP"],
   let overrides = try? JSONDecoder().decode([String: String].self, from: Data(setting.utf8)) {
    for key in overrides.keys { bindings.removeValue(forKey: key) }
}
guard Set(bindings.values).count == bindings.count else { fail("Duplicate wired screen binding.") }
let aliases = Dictionary(uniqueKeysWithValues: bindings.map { ($0.value, $0.key) })
let target = args.count == 3 ? (bindings[args[2]] ?? args[2]) : nil
let until = Date().addingTimeInterval(5)
while !discovery.devices.contains(where: { target == nil || $0.uniqueID == target }) && Date() < until { pump(0.1) }
if args.count == 2 && args[1] == "list" {
    let items = discovery.devices.map { ["id": $0.uniqueID, "name": $0.localizedName] }
    reportDiscovery(String(decoding: try JSONSerialization.data(withJSONObject: items), as: UTF8.self))
    let listed = discovery.devices.map { ["id": aliases[$0.uniqueID] ?? $0.uniqueID, "name": $0.localizedName] }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: listed))
    exit(0)
}
guard args.count == 3, args[1] == "stream", let device = discovery.devices.first(where: { $0.uniqueID == target }) else {
    fail("Select a connected screen by its capture ID.")
}
final class Frames: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let context = CIContext()
    var last = 0.0
    var reported = false
    func captureOutput(_ output: AVCaptureOutput, didOutput sample: CMSampleBuffer, from connection: AVCaptureConnection) {
        let now = ProcessInfo.processInfo.systemUptime
        guard now-last >= 0.1, let pixel = CMSampleBufferGetImageBuffer(sample) else { return }
        last = now
        let input = CIImage(cvPixelBuffer: pixel)
        let factor = min(1, 960/max(input.extent.width,input.extent.height))
        let image = input.transformed(by: CGAffineTransform(scaleX: factor, y: factor))
        guard let data = context.jpegRepresentation(of: image, colorSpace: CGColorSpaceCreateDeviceRGB(), options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.73]) else { return }
        var length = UInt32(data.count).bigEndian
        FileHandle.standardOutput.write(Data(bytes: &length, count: 4))
        FileHandle.standardOutput.write(data)
        if !reported {
            reported = true
            let status = bindingsFile.deletingLastPathComponent().appendingPathComponent("capture-first-frame.txt")
            try? "Delivered JPEG: \(data.count) bytes at \(Date())".write(to: status, atomically: true, encoding: .utf8)
        }
    }
}
let session = AVCaptureSession()
let input = try AVCaptureDeviceInput(device: device)
let output = AVCaptureVideoDataOutput()
let frames = Frames()
guard session.canAddInput(input) else { fail("Cannot add screen input.") }
session.addInput(input)
guard session.canAddOutput(output) else { fail("Cannot add video output.") }
session.addOutput(output)
output.alwaysDiscardsLateVideoFrames = true
output.setSampleBufferDelegate(frames, queue: DispatchQueue(label: "phone.frames"))
session.startRunning()
RunLoop.current.run()
