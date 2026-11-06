import AppKit

/// An F made from three panes. This path drives the widget, menu bar and app icon.
enum FenletBrand {
    static func symbol() -> CGPath {
        let path = CGMutablePath()
        path.addRoundedRect(in: CGRect(x: 18, y: 12, width: 16, height: 76), cornerWidth: 3, cornerHeight: 3)
        path.addRoundedRect(in: CGRect(x: 40, y: 12, width: 44, height: 20), cornerWidth: 3, cornerHeight: 3)
        path.addRoundedRect(in: CGRect(x: 40, y: 38, width: 30, height: 20), cornerWidth: 3, cornerHeight: 3)
        return path
    }
    static func mark(size: CGFloat, template: Bool = false) -> NSImage {
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { rect in
            guard let c = NSGraphicsContext.current?.cgContext else { return false }
            c.translateBy(x: 0, y: rect.height)
            c.scaleBy(x: rect.width / 100, y: -rect.height / 100)
            c.setFillColor((template ? NSColor.black : NSColor.controlAccentColor).cgColor)
            c.addPath(symbol()); c.fillPath(); return true
        }
        image.isTemplate = template
        return image
    }
    static let widgetMark = mark(size: 24, template: true)
    static func appIcon(pixels: Int) -> CGImage {
        let space = CGColorSpace(name: CGColorSpace.sRGB)!
        let c = CGContext(data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: 0,
                          space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        c.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
        let square = CGPath(roundedRect: CGRect(x: 64, y: 64, width: 896, height: 896), cornerWidth: 206, cornerHeight: 206, transform: nil)
        c.saveGState(); c.addPath(square); c.clip()
        let colors = [CGColor(red: 0.16, green: 0.31, blue: 0.83, alpha: 1), CGColor(red: 0.29, green: 0.49, blue: 0.98, alpha: 1)]
        let gradient = CGGradient(colorsSpace: space, colors: colors as CFArray, locations: [0, 1])!
        c.drawLinearGradient(gradient, start: CGPoint(x: 450, y: 64), end: CGPoint(x: 570, y: 960), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        c.restoreGState()
        c.setStrokeColor(CGColor(gray: 1, alpha: 0.18)); c.setLineWidth(2); c.addPath(square); c.strokePath()
        c.translateBy(x: 145, y: 879); c.scaleBy(x: 7.34, y: -7.34)
        c.setFillColor(CGColor(gray: 1, alpha: 1)); c.addPath(symbol()); c.fillPath()
        return c.makeImage()!
    }
}
