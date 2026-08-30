import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 5 else {
    fputs("usage: anchor_idle.swift input.png output.png left top\n", stderr)
    exit(2)
}

let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
let left = Int(CommandLine.arguments[3])!
let top = Int(CommandLine.arguments[4])!
let cell = 314
let source = CGImageSourceCreateWithURL(input as CFURL, nil)!
let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
guard left >= 0, top >= 0, left + image.width <= cell, top + image.height <= cell else { exit(1) }

var sourcePixels = [UInt8](repeating: 0, count: image.width * image.height * 4)
let sourceContext = CGContext(data: &sourcePixels, width: image.width, height: image.height,
                              bitsPerComponent: 8, bytesPerRow: image.width * 4,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
sourceContext.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))

var outputPixels = [UInt8](repeating: 0, count: cell * cell * 4)
for y in 0..<image.height {
    for x in 0..<image.width {
        let sourceOffset = (y * image.width + x) * 4
        let targetOffset = ((top + y) * cell + left + x) * 4
        outputPixels[targetOffset] = sourcePixels[sourceOffset]
        outputPixels[targetOffset + 1] = sourcePixels[sourceOffset + 1]
        outputPixels[targetOffset + 2] = sourcePixels[sourceOffset + 2]
        outputPixels[targetOffset + 3] = sourcePixels[sourceOffset + 3]
    }
}

let provider = CGDataProvider(data: Data(outputPixels) as CFData)!
let result = CGImage(width: cell, height: cell, bitsPerComponent: 8, bitsPerPixel: 32,
                     bytesPerRow: cell * 4, space: CGColorSpaceCreateDeviceRGB(),
                     bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                     provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
let destination = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(destination, result, nil)
guard CGImageDestinationFinalize(destination) else { exit(1) }
