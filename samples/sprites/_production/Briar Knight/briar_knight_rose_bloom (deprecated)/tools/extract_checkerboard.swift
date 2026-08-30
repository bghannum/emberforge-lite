import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 3 else {
    fputs("usage: extract_checkerboard.swift input.png output.png\n", stderr)
    exit(2)
}

let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL, nil)!
let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
let width = image.width, height = image.height, rowBytes = width * 4
var pixels = [UInt8](repeating: 0, count: height * rowBytes)
let context = CGContext(data: &pixels, width: width, height: height, bitsPerComponent: 8,
                        bytesPerRow: rowBytes, space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))

func isLightNeutral(_ index: Int) -> Bool {
    let offset = index * 4
    let r = Int(pixels[offset]), g = Int(pixels[offset + 1]), b = Int(pixels[offset + 2])
    return min(r, g, b) >= 225 && max(r, g, b) - min(r, g, b) <= 18
}

let pixelCount = width * height
var barrier = [Bool](repeating: false, count: pixelCount)
for index in 0..<pixelCount { barrier[index] = !isLightNeutral(index) }

// Close one-pixel outline gaps so bright armor and sword interiors cannot leak into the exterior mask.
var closedBarrier = barrier
for y in 0..<height {
    for x in 0..<width where barrier[y * width + x] {
        for dy in -1...1 {
            for dx in -1...1 {
                let nx = x + dx, ny = y + dy
                if nx >= 0 && nx < width && ny >= 0 && ny < height {
                    closedBarrier[ny * width + nx] = true
                }
            }
        }
    }
}

var background = [Bool](repeating: false, count: pixelCount)
var queue: [Int] = []
func enqueue(_ index: Int) {
    if !background[index] && !closedBarrier[index] {
        background[index] = true
        queue.append(index)
    }
}
for x in 0..<width { enqueue(x); enqueue((height - 1) * width + x) }
for y in 0..<height { enqueue(y * width); enqueue(y * width + width - 1) }
var cursor = 0
while cursor < queue.count {
    let index = queue[cursor]; cursor += 1
    let x = index % width, y = index / width
    if x > 0 { enqueue(index - 1) }
    if x + 1 < width { enqueue(index + 1) }
    if y > 0 { enqueue(index - width) }
    if y + 1 < height { enqueue(index + width) }
}

// Remove the temporary one-pixel safety ring where it still matches the checkerboard.
let exterior = background
for y in 0..<height {
    for x in 0..<width {
        let index = y * width + x
        if background[index] || !isLightNeutral(index) { continue }
        var touchesExterior = false
        for dy in -1...1 {
            for dx in -1...1 {
                let nx = x + dx, ny = y + dy
                if nx >= 0 && nx < width && ny >= 0 && ny < height && exterior[ny * width + nx] {
                    touchesExterior = true
                }
            }
        }
        if touchesExterior { background[index] = true }
    }
}

let outputSize = max(width, height) + ((4 - max(width, height) % 4) % 4)
let xInset = (outputSize - width) / 2, yInset = (outputSize - height) / 2
var output = [UInt8](repeating: 0, count: outputSize * outputSize * 4)
for y in 0..<height {
    for x in 0..<width {
        let sourceIndex = y * width + x
        if background[sourceIndex] { continue }
        let sourceOffset = sourceIndex * 4
        let outputOffset = ((y + yInset) * outputSize + x + xInset) * 4
        output[outputOffset] = pixels[sourceOffset]
        output[outputOffset + 1] = pixels[sourceOffset + 1]
        output[outputOffset + 2] = pixels[sourceOffset + 2]
        output[outputOffset + 3] = 255
    }
}

let outputContext = CGContext(data: &output, width: outputSize, height: outputSize, bitsPerComponent: 8,
                              bytesPerRow: outputSize * 4, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: CommandLine.arguments[2]) as CFURL,
                                                   UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(destination, outputContext.makeImage()!, nil)
guard CGImageDestinationFinalize(destination) else { exit(1) }
