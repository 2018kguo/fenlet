import AppKit

@main struct RenderIcon {
    static func main() throws {
        let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for points in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let image = FenletBrand.appIcon(pixels: points * scale)
                let bitmap = NSBitmapImageRep(cgImage: image)
                let suffix = scale == 2 ? "@2x" : ""
                try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
            }
        }
        var commands: [String] = []
        func point(_ p: CGPoint) -> String { "\(p.x),\(p.y)" }
        FenletBrand.symbol().applyWithBlock { item in
            let e = item.pointee
            switch e.type {
            case .moveToPoint: commands.append("M" + point(e.points[0]))
            case .addLineToPoint: commands.append("L" + point(e.points[0]))
            case .addQuadCurveToPoint: commands.append("Q" + point(e.points[0]) + " " + point(e.points[1]))
            case .addCurveToPoint: commands.append("C" + point(e.points[0]) + " " + point(e.points[1]) + " " + point(e.points[2]))
            case .closeSubpath: commands.append("Z")
            @unknown default: fatalError("Unrecognized logo path element")
            }
        }
        let svg = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\"><path fill=\"#3b6ef6\" d=\"" + commands.joined(separator: " ") + "\"/></svg>\n"
        try svg.write(to: output.deletingLastPathComponent().appendingPathComponent("fenlet.svg"), atomically: true, encoding: .utf8)
    }
}
