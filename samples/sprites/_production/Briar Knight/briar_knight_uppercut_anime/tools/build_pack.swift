import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let columns = 4
let rows = 3
let frameCount = columns * rows
let outputCell = 314
let targetRootX = 157
let targetBaselineY = 300
let sourceScale = 0.60
let delays = [0.10, 0.07, 0.07, 0.09, 0.055, 0.045, 0.040, 0.045, 0.070, 0.080, 0.090, 0.120]

guard CommandLine.arguments.count == 4 else {
    fputs("usage: build_pack.swift source.png canonical_idle.png output_dir\n", stderr)
    exit(2)
}

let sourceURL = URL(fileURLWithPath: CommandLine.arguments[1])
let canonicalURL = URL(fileURLWithPath: CommandLine.arguments[2])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[3], isDirectory: true)
let framesURL = outputURL.appendingPathComponent("frames", isDirectory: true)
try FileManager.default.createDirectory(at: framesURL, withIntermediateDirectories: true)

struct Raster {
    var width: Int
    var height: Int
    var pixels: [UInt8]
}

func readRaster(_ url: URL) -> Raster {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        fputs("unable to read \(url.path)\n", stderr); exit(1)
    }
    var pixels = [UInt8](repeating: 0, count: image.width * image.height * 4)
    let context = CGContext(data: &pixels, width: image.width, height: image.height,
                            bitsPerComponent: 8, bytesPerRow: image.width * 4,
                            space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
    return Raster(width: image.width, height: image.height, pixels: pixels)
}

func makeImage(_ raster: Raster) -> CGImage {
    let provider = CGDataProvider(data: Data(raster.pixels) as CFData)!
    return CGImage(width: raster.width, height: raster.height, bitsPerComponent: 8,
                   bitsPerPixel: 32, bytesPerRow: raster.width * 4,
                   space: CGColorSpaceCreateDeviceRGB(),
                   bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                   provider: provider, decode: nil, shouldInterpolate: false,
                   intent: .defaultIntent)!
}

func writePNG(_ raster: Raster, _ url: URL) throws {
    let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination, makeImage(raster), nil)
    guard CGImageDestinationFinalize(destination) else { throw NSError(domain: "UppercutAnimePack", code: 1) }
}

var source = readRaster(sourceURL)
let pixelCount = source.width * source.height

func isLightNeutral(_ pixel: Int) -> Bool {
    let offset = pixel * 4
    let r = Int(source.pixels[offset]), g = Int(source.pixels[offset + 1]), b = Int(source.pixels[offset + 2])
    return min(r, min(g, b)) >= 220 && max(r, max(g, b)) - min(r, min(g, b)) <= 18
}

// ImageGen occasionally renders its alpha preview into the pixels. Flood only the
// edge-connected light-neutral field so outlined white armor and blade interiors survive.
var barrier = [Bool](repeating: false, count: pixelCount)
for pixel in 0..<pixelCount { barrier[pixel] = !isLightNeutral(pixel) }
var closedBarrier = barrier
for y in 0..<source.height {
    for x in 0..<source.width where barrier[y * source.width + x] {
        for dy in -1...1 { for dx in -1...1 {
            let nx = x + dx, ny = y + dy
            if nx >= 0 && nx < source.width && ny >= 0 && ny < source.height {
                closedBarrier[ny * source.width + nx] = true
            }
        }}
    }
}

var background = [Bool](repeating: false, count: pixelCount)
var queue: [Int] = []
func enqueue(_ pixel: Int) {
    if !background[pixel] && !closedBarrier[pixel] {
        background[pixel] = true
        queue.append(pixel)
    }
}
for x in 0..<source.width { enqueue(x); enqueue((source.height - 1) * source.width + x) }
for y in 0..<source.height { enqueue(y * source.width); enqueue(y * source.width + source.width - 1) }
var cursor = 0
while cursor < queue.count {
    let pixel = queue[cursor]; cursor += 1
    let x = pixel % source.width, y = pixel / source.width
    if x > 0 { enqueue(pixel - 1) }
    if x + 1 < source.width { enqueue(pixel + 1) }
    if y > 0 { enqueue(pixel - source.width) }
    if y + 1 < source.height { enqueue(pixel + source.width) }
}

for pixel in 0..<pixelCount {
    if background[pixel] { source.pixels[pixel * 4 + 3] = 0 }
    else { source.pixels[pixel * 4 + 3] = 255 }
}
try writePNG(source, outputURL.appendingPathComponent("briar_knight_uppercut_anime_source_clean.png"))

let canonical = readRaster(canonicalURL)
guard canonical.width == outputCell && canonical.height == outputCell else {
    fputs("canonical idle must be 314x314\n", stderr); exit(1)
}

func generatedFrame(_ index: Int) -> Raster {
    let column = index % columns, row = index / columns
    let left = column * source.width / columns
    let right = (column + 1) * source.width / columns
    let top = row * source.height / rows
    let bottom = (row + 1) * source.height / rows
    let sourceCellWidth = right - left, sourceCellHeight = bottom - top
    let sourceCenterX = Double(sourceCellWidth) / 2.0
    let sourceBaselineY = Double(sourceCellHeight) * 0.94
    var output = Raster(width: outputCell, height: outputCell,
                        pixels: [UInt8](repeating: 0, count: outputCell * outputCell * 4))
    for y in 0..<outputCell { for x in 0..<outputCell {
        let localX = Int(((Double(x - targetRootX) / sourceScale) + sourceCenterX).rounded(.down))
        let localY = Int(((Double(y - targetBaselineY) / sourceScale) + sourceBaselineY).rounded(.down))
        guard localX >= 0 && localX < sourceCellWidth && localY >= 0 && localY < sourceCellHeight else { continue }
        let sourceOffset = ((top + localY) * source.width + left + localX) * 4
        guard source.pixels[sourceOffset + 3] >= 8 else { continue }
        let targetOffset = (y * outputCell + x) * 4
        output.pixels[targetOffset] = source.pixels[sourceOffset]
        output.pixels[targetOffset + 1] = source.pixels[sourceOffset + 1]
        output.pixels[targetOffset + 2] = source.pixels[sourceOffset + 2]
        output.pixels[targetOffset + 3] = 255
    }}
    // Discard tiny checkerboard remnants and neighboring-cell flecks on the
    // non-impact poses. Detached anime speed accents are retained at the apex.
    if index > 0 && index < 11 && index != 7 && index != 8 {
        var visited = [Bool](repeating: false, count: outputCell * outputCell)
        let neighbors = [(-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)]
        for start in 0..<(outputCell * outputCell) {
            if visited[start] || output.pixels[start * 4 + 3] < 8 { continue }
            visited[start] = true
            var component = [start]
            var componentCursor = 0
            while componentCursor < component.count {
                let pixel = component[componentCursor]; componentCursor += 1
                let x = pixel % outputCell, y = pixel / outputCell
                for (dx, dy) in neighbors {
                    let nx = x + dx, ny = y + dy
                    if nx < 0 || nx >= outputCell || ny < 0 || ny >= outputCell { continue }
                    let next = ny * outputCell + nx
                    if !visited[next] && output.pixels[next * 4 + 3] >= 8 {
                        visited[next] = true
                        component.append(next)
                    }
                }
            }
            if component.count < 100 {
                for pixel in component { output.pixels[pixel * 4 + 3] = 0 }
            }
        }
    }
    return output
}

var frames = (0..<frameCount).map(generatedFrame)
frames[0] = canonical
frames[11] = canonical

for index in 0..<frameCount {
    try writePNG(frames[index], framesURL.appendingPathComponent(String(format: "frame_%02d.png", index)))
}

var atlas = Raster(width: columns * outputCell, height: rows * outputCell,
                   pixels: [UInt8](repeating: 0, count: columns * outputCell * rows * outputCell * 4))
for index in 0..<frameCount {
    let offsetX = (index % columns) * outputCell
    let offsetY = (index / columns) * outputCell
    for y in 0..<outputCell { for x in 0..<outputCell {
        let sourceOffset = (y * outputCell + x) * 4
        let targetOffset = ((offsetY + y) * atlas.width + offsetX + x) * 4
        atlas.pixels[targetOffset..<(targetOffset + 4)] = frames[index].pixels[sourceOffset..<(sourceOffset + 4)]
    }}
}
try writePNG(atlas, outputURL.appendingPathComponent("briar_knight_uppercut_anime_12f_aligned.png"))

let gifURL = outputURL.appendingPathComponent("briar_knight_uppercut_anime_preview.gif")
let gif = CGImageDestinationCreateWithURL(gifURL as CFURL, UTType.gif.identifier as CFString, frameCount, nil)!
CGImageDestinationSetProperties(gif, [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary)
for index in 0..<frameCount {
    let properties = [kCGImagePropertyGIFDictionary: [
        kCGImagePropertyGIFDelayTime: delays[index],
        kCGImagePropertyGIFUnclampedDelayTime: delays[index]
    ]] as CFDictionary
    CGImageDestinationAddImage(gif, makeImage(frames[index]), properties)
}
guard CGImageDestinationFinalize(gif) else { exit(1) }

print("exported 12 frames, 1256x942 atlas, and timing GIF")
