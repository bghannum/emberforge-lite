import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let cellSize = 314
let columnCount = 4
let rowCount = 4
let frameCount = columnCount * rowCount
let targetRootX = 157
let targetBaselineY = 300
let frameDelays = [0.083, 0.056, 0.056, 0.067, 0.056, 0.044, 0.044, 0.039,
                   0.036, 0.050, 0.044, 0.050, 0.056, 0.056, 0.061, 0.083]

guard CommandLine.arguments.count == 3 else {
    fputs("usage: build_pack.swift source-atlas.png output-directory\n", stderr)
    exit(2)
}

let inputPath = CommandLine.arguments[1]
let outputDirectory = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let framesDirectory = outputDirectory.appendingPathComponent("frames", isDirectory: true)
try FileManager.default.createDirectory(at: framesDirectory, withIntermediateDirectories: true)

guard
    let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: inputPath) as CFURL, nil),
    let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
    image.width == cellSize * columnCount,
    image.height == cellSize * rowCount
else {
    fputs("source atlas must be 1256x1256 RGBA\n", stderr)
    exit(1)
}

let atlasWidth = image.width
let atlasHeight = image.height
var atlasPixels = [UInt8](repeating: 0, count: atlasWidth * atlasHeight * 4)
guard let atlasContext = CGContext(
    data: &atlasPixels,
    width: atlasWidth,
    height: atlasHeight,
    bitsPerComponent: 8,
    bytesPerRow: atlasWidth * 4,
    space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
) else { exit(1) }
atlasContext.draw(image, in: CGRect(x: 0, y: 0, width: atlasWidth, height: atlasHeight))

func makeImage(pixels: [UInt8], width: Int, height: Int) -> CGImage {
    let provider = CGDataProvider(data: Data(pixels) as CFData)!
    return CGImage(
        width: width,
        height: height,
        bitsPerComponent: 8,
        bitsPerPixel: 32,
        bytesPerRow: width * 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
        provider: provider,
        decode: nil,
        shouldInterpolate: false,
        intent: .defaultIntent
    )!
}

func writePNG(_ pixels: [UInt8], width: Int, height: Int, to url: URL) throws {
    let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination, makeImage(pixels: pixels, width: width, height: height), nil)
    guard CGImageDestinationFinalize(destination) else {
        throw NSError(domain: "BriarKnightPack", code: 1, userInfo: [NSLocalizedDescriptionKey: "PNG write failed"])
    }
}

struct Component {
    var pixels: [Int]
    var minX: Int
    var minY: Int
    var maxX: Int
    var maxY: Int
}

var visited = [Bool](repeating: false, count: atlasWidth * atlasHeight)
var components: [Component] = []
let neighbors = [(-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)]
for start in 0..<(atlasWidth * atlasHeight) {
    if visited[start] || atlasPixels[start * 4 + 3] < 8 { continue }
    visited[start] = true
    var queue = [start]
    var cursor = 0
    var minX = start % atlasWidth, maxX = minX, minY = start / atlasWidth, maxY = minY
    while cursor < queue.count {
        let index = queue[cursor]; cursor += 1
        let x = index % atlasWidth, y = index / atlasWidth
        minX = min(minX, x); maxX = max(maxX, x); minY = min(minY, y); maxY = max(maxY, y)
        for (dx, dy) in neighbors {
            let nx = x + dx, ny = y + dy
            if nx < 0 || nx >= atlasWidth || ny < 0 || ny >= atlasHeight { continue }
            let next = ny * atlasWidth + nx
            if !visited[next] && atlasPixels[next * 4 + 3] >= 8 {
                visited[next] = true
                queue.append(next)
            }
        }
    }
    components.append(Component(pixels: queue, minX: minX, minY: minY, maxX: maxX, maxY: maxY))
}

var pixelsByFrame = Array(repeating: [Int](), count: frameCount)
for component in components {
    let centerX = (component.minX + component.maxX) / 2
    let centerY = (component.minY + component.maxY) / 2
    var closestFrame = 0
    var closestDistance = Int.max
    for frame in 0..<frameCount {
        let expectedX = targetRootX + (frame % columnCount) * cellSize
        let expectedY = targetRootX + (frame / columnCount) * cellSize
        let dx = centerX - expectedX, dy = centerY - expectedY
        let distance = dx * dx + dy * dy
        if distance < closestDistance { closestDistance = distance; closestFrame = frame }
    }
    pixelsByFrame[closestFrame].append(contentsOf: component.pixels)
}

func alignedFrame(sourceIndices: [Int], index: Int) -> [UInt8] {
    guard !sourceIndices.isEmpty else { return [UInt8](repeating: 0, count: cellSize * cellSize * 4) }
    let xs = sourceIndices.map { $0 % atlasWidth }
    let ys = sourceIndices.map { $0 / atlasWidth }
    let minX = xs.min()!, maxX = xs.max()!, minY = ys.min()!, maxY = ys.max()!
    var groundingXs = sourceIndices.filter { $0 / atlasWidth >= maxY - 24 }.map { $0 % atlasWidth }.sorted()
    if groundingXs.isEmpty { groundingXs = xs.sorted() }
    let rootX = groundingXs[groundingXs.count / 2]

    var shiftX = targetRootX - rootX
    var shiftY = targetBaselineY - maxY
    shiftX = max(2 - minX, min(shiftX, cellSize - 3 - maxX))
    shiftY = max(2 - minY, min(shiftY, cellSize - 3 - maxY))

    var result = [UInt8](repeating: 0, count: cellSize * cellSize * 4)
    for sourceIndex in sourceIndices {
        let sourceX = sourceIndex % atlasWidth, sourceY = sourceIndex / atlasWidth
        let targetX = sourceX + shiftX, targetY = sourceY + shiftY
        guard targetX >= 0, targetX < cellSize, targetY >= 0, targetY < cellSize else { continue }
        let sourceOffset = sourceIndex * 4
        let targetOffset = (targetY * cellSize + targetX) * 4
        result[targetOffset] = atlasPixels[sourceOffset]
        result[targetOffset + 1] = atlasPixels[sourceOffset + 1]
        result[targetOffset + 2] = atlasPixels[sourceOffset + 2]
        result[targetOffset + 3] = atlasPixels[sourceOffset + 3]
    }
    print("frame \(String(format: "%02d", index)): pixels \(sourceIndices.count), bbox \(minX),\(minY)-\(maxX),\(maxY), root \(rootX),\(maxY), shift \(shiftX),\(shiftY)")
    return result
}

var frames: [[UInt8]] = []
for index in 0..<frameCount { frames.append(alignedFrame(sourceIndices: pixelsByFrame[index], index: index)) }

// End on the exact same pixels as the opening idle so the recovery cannot pop.
frames[15] = frames[0]

for index in 0..<frameCount {
    let filename = String(format: "frame_%02d.png", index)
    try writePNG(frames[index], width: cellSize, height: cellSize, to: framesDirectory.appendingPathComponent(filename))
}
try writePNG(frames[0], width: cellSize, height: cellSize,
             to: outputDirectory.appendingPathComponent("briar_knight_idle_game.png"))

var alignedAtlas = [UInt8](repeating: 0, count: atlasWidth * atlasHeight * 4)
for index in 0..<frameCount {
    let column = index % columnCount
    let row = index / columnCount
    for y in 0..<cellSize {
        for x in 0..<cellSize {
            let sourceOffset = (y * cellSize + x) * 4
            let targetOffset = ((row * cellSize + y) * atlasWidth + column * cellSize + x) * 4
            alignedAtlas[targetOffset] = frames[index][sourceOffset]
            alignedAtlas[targetOffset + 1] = frames[index][sourceOffset + 1]
            alignedAtlas[targetOffset + 2] = frames[index][sourceOffset + 2]
            alignedAtlas[targetOffset + 3] = frames[index][sourceOffset + 3]
        }
    }
}
try writePNG(alignedAtlas, width: atlasWidth, height: atlasHeight,
             to: outputDirectory.appendingPathComponent("briar_knight_lunge_attack_16f_aligned.png"))

let gifURL = outputDirectory.appendingPathComponent("briar_knight_lunge_attack_preview.gif")
let gif = CGImageDestinationCreateWithURL(gifURL as CFURL, UTType.gif.identifier as CFString, frameCount, nil)!
CGImageDestinationSetProperties(gif, [
    kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]
] as CFDictionary)
for index in 0..<frameCount {
    let properties = [
        kCGImagePropertyGIFDictionary: [
            kCGImagePropertyGIFDelayTime: frameDelays[index],
            kCGImagePropertyGIFUnclampedDelayTime: frameDelays[index]
        ]
    ] as CFDictionary
    CGImageDestinationAddImage(gif, makeImage(pixels: frames[index], width: cellSize, height: cellSize), properties)
}
guard CGImageDestinationFinalize(gif) else { exit(1) }
