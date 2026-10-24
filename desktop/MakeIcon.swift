import AppKit
import Foundation

let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                      bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                      isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
        let factor = CGFloat(pixels) / 1024
        NSAffineTransform().apply { $0.scale(by: factor); $0.concat() }
        NSColor(calibratedRed: 0.07, green: 0.09, blue: 0.10, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 22, y: 22, width: 980, height: 980), xRadius: 190, yRadius: 190).fill()
        let yellow = NSColor(calibratedRed: 0.86, green: 0.81, blue: 0.40, alpha: 1)
        let attributes: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 450, weight: .black), .foregroundColor: yellow, .kern: -35]
        let text = NSString(string: "BD"); let bounds = text.size(withAttributes: attributes)
        text.draw(at: NSPoint(x: (1024-bounds.width)/2-8, y: 285), withAttributes: attributes)
        NSColor(calibratedRed: 0.47, green: 0.80, blue: 0.82, alpha: 1).setFill()
        let line = NSBezierPath(); line.move(to: NSPoint(x: 200, y: 225)); line.line(to: NSPoint(x: 825, y: 225))
        line.line(to: NSPoint(x: 790, y: 204)); line.line(to: NSPoint(x: 200, y: 204)); line.close(); line.fill()
        NSGraphicsContext.restoreGraphicsState()
        let name = "icon_\(size)x\(size)\(scale == 2 ? "@2x" : "").png"
        try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent(name))
    }
}

extension NSAffineTransform {
    func apply(_ block: (NSAffineTransform) -> Void) { block(self) }
}
