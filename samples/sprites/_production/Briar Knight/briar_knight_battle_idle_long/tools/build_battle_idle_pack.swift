import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let columns = 7
let rows = 4
let frameCount = columns * rows
let outputCell = 314

guard CommandLine.arguments.count == 8 else {
    fputs("usage: build_battle_idle_pack.swift source.png canonical_idle.png output_dir asset_stem animation_name res_directory delay1,...,delay28\n", stderr)
    exit(2)
}

let sourcePath = CommandLine.arguments[1]
let canonicalPath = CommandLine.arguments[2]
let outputDirectory = URL(fileURLWithPath: CommandLine.arguments[3], isDirectory: true)
let assetStem = CommandLine.arguments[4]
let animationName = CommandLine.arguments[5]
let resourceDirectory = CommandLine.arguments[6]
let delays = CommandLine.arguments[7].split(separator: ",").compactMap { Double($0) }
guard delays.count == frameCount else {
    fputs("exactly 28 comma-separated frame delays are required\n", stderr)
    exit(2)
}

struct Raster {
    var width: Int
    var height: Int
    var pixels: [UInt8]
}

func readRaster(_ path: String) -> Raster {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        fputs("unable to read \(path)\n", stderr); exit(1)
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
    guard CGImageDestinationFinalize(destination) else { throw NSError(domain: "BattleIdlePack", code: 1) }
}

func opaqueBounds(_ raster: Raster) -> (minX: Int, minY: Int, maxX: Int, maxY: Int)? {
    var minX = raster.width, minY = raster.height, maxX = -1, maxY = -1
    for y in 0..<raster.height { for x in 0..<raster.width {
        if raster.pixels[(y * raster.width + x) * 4 + 3] >= 8 {
            minX = min(minX, x); minY = min(minY, y); maxX = max(maxX, x); maxY = max(maxY, y)
        }
    }}
    return maxX >= minX ? (minX, minY, maxX, maxY) : nil
}

func rootX(_ raster: Raster, bounds: (minX: Int, minY: Int, maxX: Int, maxY: Int)) -> Int {
    let startY = max(bounds.minY, bounds.maxY - max(4, (bounds.maxY - bounds.minY + 1) / 10))
    var xs: [Int] = []
    for y in startY...bounds.maxY { for x in bounds.minX...bounds.maxX {
        if raster.pixels[(y * raster.width + x) * 4 + 3] >= 8 { xs.append(x) }
    }}
    xs.sort()
    return xs.isEmpty ? (bounds.minX + bounds.maxX) / 2 : xs[xs.count / 2]
}

let source = readRaster(sourcePath)
var canonical = readRaster(canonicalPath)
guard canonical.width == outputCell && canonical.height == outputCell,
      let canonicalBounds = opaqueBounds(canonical) else {
    fputs("canonical idle must be a non-empty 314x314 RGBA PNG\n", stderr); exit(1)
}
let targetRootX = rootX(canonical, bounds: canonicalBounds)
let targetBaseline = canonicalBounds.maxY
let targetHeight = canonicalBounds.maxY - canonicalBounds.minY + 1
let targetWidth = canonicalBounds.maxX - canonicalBounds.minX + 1

func isBackgroundNeutral(_ raster: Raster, _ x: Int, _ y: Int) -> Bool {
    let o = (y * raster.width + x) * 4
    let r = Int(raster.pixels[o]), g = Int(raster.pixels[o + 1]), b = Int(raster.pixels[o + 2])
    return min(r, g, b) >= 220 && max(r, g, b) - min(r, g, b) <= 24
}

func cleanedCell(column: Int, row: Int) -> Raster {
    let left = column * source.width / columns
    let right = (column + 1) * source.width / columns
    let top = row * source.height / rows
    let bottom = (row + 1) * source.height / rows
    let width = right - left, height = bottom - top
    var local = [UInt8](repeating: 0, count: width * height * 4)
    for y in 0..<height { for x in 0..<width {
        let src = ((top + y) * source.width + left + x) * 4
        let dst = (y * width + x) * 4
        local[dst] = source.pixels[src]; local[dst + 1] = source.pixels[src + 1]
        local[dst + 2] = source.pixels[src + 2]; local[dst + 3] = 255
    }}
    var raster = Raster(width: width, height: height, pixels: local)
    let count = width * height
    var barrier = [Bool](repeating: false, count: count)
    for y in 0..<height { for x in 0..<width { barrier[y * width + x] = !isBackgroundNeutral(raster, x, y) }}
    var closed = barrier
    for y in 0..<height { for x in 0..<width where barrier[y * width + x] {
        for dy in -1...1 { for dx in -1...1 {
            let nx = x + dx, ny = y + dy
            if nx >= 0 && nx < width && ny >= 0 && ny < height { closed[ny * width + nx] = true }
        }}
    }}
    var exterior = [Bool](repeating: false, count: count)
    var queue: [Int] = []
    func enqueue(_ index: Int) {
        if !exterior[index] && !closed[index] { exterior[index] = true; queue.append(index) }
    }
    for x in 0..<width { enqueue(x); enqueue((height - 1) * width + x) }
    for y in 0..<height { enqueue(y * width); enqueue(y * width + width - 1) }
    var cursor = 0
    while cursor < queue.count {
        let index = queue[cursor]; cursor += 1
        let x = index % width, y = index / width
        if x > 0 { enqueue(index - 1) }; if x + 1 < width { enqueue(index + 1) }
        if y > 0 { enqueue(index - width) }; if y + 1 < height { enqueue(index + width) }
    }
    for index in 0..<count where exterior[index] { raster.pixels[index * 4 + 3] = 0 }
    return raster
}

func cleanedAtlas(_ input: Raster) -> Raster {
    var raster = input
    let count = raster.width * raster.height
    var barrier = [Bool](repeating: false, count: count)
    for y in 0..<raster.height { for x in 0..<raster.width {
        barrier[y * raster.width + x] = !isBackgroundNeutral(raster, x, y)
    }}
    var closed = barrier
    for y in 0..<raster.height { for x in 0..<raster.width where barrier[y * raster.width + x] {
        for dy in -1...1 { for dx in -1...1 {
            let nx = x + dx, ny = y + dy
            if nx >= 0 && nx < raster.width && ny >= 0 && ny < raster.height {
                closed[ny * raster.width + nx] = true
            }
        }}
    }}
    var exterior = [Bool](repeating: false, count: count)
    var queue: [Int] = []
    func enqueue(_ index: Int) {
        if !exterior[index] && !closed[index] { exterior[index] = true; queue.append(index) }
    }
    for x in 0..<raster.width { enqueue(x); enqueue((raster.height - 1) * raster.width + x) }
    for y in 0..<raster.height { enqueue(y * raster.width); enqueue(y * raster.width + raster.width - 1) }
    var cursor = 0
    while cursor < queue.count {
        let index = queue[cursor]; cursor += 1
        let x = index % raster.width, y = index / raster.width
        if x > 0 { enqueue(index - 1) }; if x + 1 < raster.width { enqueue(index + 1) }
        if y > 0 { enqueue(index - raster.width) }; if y + 1 < raster.height { enqueue(index + raster.width) }
    }
    for index in 0..<count { raster.pixels[index * 4 + 3] = exterior[index] ? 0 : 255 }
    return raster
}

struct Component {
    var pixels: [Int]
    var minX: Int
    var minY: Int
    var maxX: Int
    var maxY: Int
}

let transparentSource = cleanedAtlas(source)
let pixelCount = transparentSource.width * transparentSource.height
var visited = [Bool](repeating: false, count: pixelCount)
var components: [Component] = []
let neighbors = [(-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)]
for start in 0..<pixelCount {
    if visited[start] || transparentSource.pixels[start * 4 + 3] < 8 { continue }
    visited[start] = true
    var queue = [start], cursor = 0
    var minX = start % transparentSource.width, maxX = minX
    var minY = start / transparentSource.width, maxY = minY
    while cursor < queue.count {
        let index = queue[cursor]; cursor += 1
        let x = index % transparentSource.width, y = index / transparentSource.width
        minX = min(minX, x); maxX = max(maxX, x); minY = min(minY, y); maxY = max(maxY, y)
        for (dx, dy) in neighbors {
            let nx = x + dx, ny = y + dy
            if nx < 0 || nx >= transparentSource.width || ny < 0 || ny >= transparentSource.height { continue }
            let next = ny * transparentSource.width + nx
            if !visited[next] && transparentSource.pixels[next * 4 + 3] >= 8 {
                visited[next] = true; queue.append(next)
            }
        }
    }
    components.append(Component(pixels: queue, minX: minX, minY: minY, maxX: maxX, maxY: maxY))
}

var pixelsByFrame = Array(repeating: [Int](), count: frameCount)
for component in components {
    let centerX = (component.minX + component.maxX) / 2
    let centerY = (component.minY + component.maxY) / 2
    var closest = 0, closestDistance = Int.max
    for frame in 0..<frameCount {
        let expectedX = ((frame % columns) * 2 + 1) * transparentSource.width / (columns * 2)
        let expectedY = ((frame / columns) * 2 + 1) * transparentSource.height / (rows * 2)
        let dx = centerX - expectedX, dy = centerY - expectedY
        let distance = dx * dx + dy * dy
        if distance < closestDistance { closestDistance = distance; closest = frame }
    }
    pixelsByFrame[closest].append(contentsOf: component.pixels)
}

var cleaned: [Raster] = []
var sourceHeights: [Int] = [], sourceWidths: [Int] = []
for index in 0..<frameCount {
    var frame = Raster(width: transparentSource.width, height: transparentSource.height,
                       pixels: [UInt8](repeating: 0, count: transparentSource.pixels.count))
    for pixel in pixelsByFrame[index] {
        let offset = pixel * 4
        frame.pixels[offset] = transparentSource.pixels[offset]
        frame.pixels[offset + 1] = transparentSource.pixels[offset + 1]
        frame.pixels[offset + 2] = transparentSource.pixels[offset + 2]
        frame.pixels[offset + 3] = transparentSource.pixels[offset + 3]
    }
    guard let bounds = opaqueBounds(frame) else { fputs("empty source frame \(index)\n", stderr); exit(1) }
    cleaned.append(frame)
    sourceHeights.append(bounds.maxY - bounds.minY + 1)
    sourceWidths.append(bounds.maxX - bounds.minX + 1)
}
let medianSourceHeight = sourceHeights.sorted()[frameCount / 2]
let medianSourceWidth = sourceWidths.sorted()[frameCount / 2]
let sharedScale = min(Double(targetHeight) / Double(medianSourceHeight),
                      Double(targetWidth) / Double(medianSourceWidth))

func aligned(_ raster: Raster, index: Int) -> Raster {
    let bounds = opaqueBounds(raster)!
    let width = bounds.maxX - bounds.minX + 1, height = bounds.maxY - bounds.minY + 1
    let scaledWidth = max(1, Int((Double(width) * sharedScale).rounded()))
    let scaledHeight = max(1, Int((Double(height) * sharedScale).rounded()))
    let sourceRoot = rootX(raster, bounds: bounds)
    let scaledRootOffset = Int((Double(sourceRoot - bounds.minX) * sharedScale).rounded())
    var targetLeft = targetRootX - scaledRootOffset
    var targetTop = targetBaseline - scaledHeight + 1
    targetLeft = max(2, min(targetLeft, outputCell - 2 - scaledWidth))
    targetTop = max(2, min(targetTop, outputCell - 2 - scaledHeight))
    var output = Raster(width: outputCell, height: outputCell,
                        pixels: [UInt8](repeating: 0, count: outputCell * outputCell * 4))
    for y in 0..<scaledHeight { for x in 0..<scaledWidth {
        let sx = bounds.minX + min(width - 1, Int(Double(x) / sharedScale))
        let sy = bounds.minY + min(height - 1, Int(Double(y) / sharedScale))
        let src = (sy * raster.width + sx) * 4
        if raster.pixels[src + 3] < 8 { continue }
        let dst = ((targetTop + y) * outputCell + targetLeft + x) * 4
        output.pixels[dst] = raster.pixels[src]; output.pixels[dst + 1] = raster.pixels[src + 1]
        output.pixels[dst + 2] = raster.pixels[src + 2]; output.pixels[dst + 3] = raster.pixels[src + 3]
    }}
    let frameLabel = String(format: "%02d", index)
    print("frame \(frameLabel): source \(width)x\(height), target \(scaledWidth)x\(scaledHeight), left \(targetLeft), baseline \(targetBaseline)")
    return output
}

try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
let framesDirectory = outputDirectory.appendingPathComponent("frames", isDirectory: true)
try FileManager.default.createDirectory(at: framesDirectory, withIntermediateDirectories: true)
try writePNG(transparentSource, outputDirectory.appendingPathComponent("\(assetStem)_source_clean.png"))
var frames = cleaned.enumerated().map { aligned($0.element, index: $0.offset) }
frames[0] = canonical
frames[frameCount - 1] = canonical

for index in 0..<frameCount {
    try writePNG(frames[index], framesDirectory.appendingPathComponent(String(format: "frame_%02d.png", index)))
}
try writePNG(canonical, outputDirectory.appendingPathComponent("canonical_idle_start.png"))
try writePNG(canonical, outputDirectory.appendingPathComponent("canonical_idle_end.png"))

var atlas = Raster(width: columns * outputCell, height: rows * outputCell,
                   pixels: [UInt8](repeating: 0, count: columns * outputCell * rows * outputCell * 4))
for index in 0..<frameCount {
    let ox = (index % columns) * outputCell, oy = (index / columns) * outputCell
    for y in 0..<outputCell { for x in 0..<outputCell {
        let src = (y * outputCell + x) * 4
        let dst = ((oy + y) * atlas.width + ox + x) * 4
        atlas.pixels[dst] = frames[index].pixels[src]; atlas.pixels[dst + 1] = frames[index].pixels[src + 1]
        atlas.pixels[dst + 2] = frames[index].pixels[src + 2]; atlas.pixels[dst + 3] = frames[index].pixels[src + 3]
    }}
}
try writePNG(atlas, outputDirectory.appendingPathComponent("\(assetStem)_28f_aligned.png"))

let gifURL = outputDirectory.appendingPathComponent("\(assetStem)_preview.gif")
let gif = CGImageDestinationCreateWithURL(gifURL as CFURL, UTType.gif.identifier as CFString, frameCount, nil)!
CGImageDestinationSetProperties(gif, [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary)
for index in 0..<frameCount {
    let props = [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFDelayTime: delays[index],
                                                  kCGImagePropertyGIFUnclampedDelayTime: delays[index]]] as CFDictionary
    CGImageDestinationAddImage(gif, makeImage(frames[index]), props)
}
guard CGImageDestinationFinalize(gif) else { exit(1) }

let delayJSON = delays.map { String(format: "%.3f", $0) }.joined(separator: ", ")
let profile = """
{
  "schema_version": 1,
  "animation": "\(animationName)",
  "frame_count": 28,
  "frame_order": "row_major",
  "atlas_grid": [7, 4],
  "cell_size_pixels": [314, 314],
  "root_anchor_pixels": [\(targetRootX), \(targetBaseline)],
  "loop": true,
  "resulting_visual_state": "canonical_idle",
  "frame_delays_seconds": [\(delayJSON)],
  "notes": ["Frames 0 and 27 are pixel-identical canonical idle frames.", "Visual idle only; no gameplay event hooks."]
}
"""
try profile.write(to: outputDirectory.appendingPathComponent("battle_idle_profile.json"), atomically: true, encoding: .utf8)

var tres = "[gd_resource type=\"SpriteFrames\" load_steps=29 format=3]\n\n"
for index in 0..<frameCount {
    let frameFilename = String(format: "frame_%02d.png", index)
    tres += "[ext_resource type=\"Texture2D\" path=\"\(resourceDirectory)/frames/\(frameFilename)\" id=\"\(index + 1)\"]\n"
}
let frameEntries = (0..<frameCount).map { index in
    let duration = delays[index] * 10.0
    let durationLabel = String(format: "%.2f", duration)
    return "{\"duration\":\(durationLabel),\"texture\":ExtResource(\"\(index + 1)\")}"
}.joined(separator: ",")
tres += "\n[resource]\nanimations = [{\"frames\":[\(frameEntries)],\"loop\":true,\"name\":&\"\(animationName)\",\"speed\":10.0}]\n"
try tres.write(to: outputDirectory.appendingPathComponent("\(assetStem)_frames.tres"), atomically: true, encoding: .utf8)
