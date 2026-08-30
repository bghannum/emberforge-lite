import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let cellSize = 314
let columnCount = 4
let rowCount = 4
let frameCount = columnCount * rowCount
let targetRootX = 157
let targetBaselineY = 254
let targetSpriteHeight = 194
let targetSpriteMaxWidth = 280
guard CommandLine.arguments.count == 9 else {
    fputs("usage: build_pack.swift source-atlas.png output-directory asset-stem preserve|match-first start-idle-name end-idle-name canonical-idle.png delay1,...,delay16\n", stderr)
    exit(2)
}

let inputPath = CommandLine.arguments[1]
let outputDirectory = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let assetStem = CommandLine.arguments[3]
let preserveFinalFrame = CommandLine.arguments[4] == "preserve"
let startIdleName = CommandLine.arguments[5]
let endIdleName = CommandLine.arguments[6]
let canonicalIdlePath = CommandLine.arguments[7]
let frameDelays = CommandLine.arguments[8].split(separator: ",").compactMap { Double($0) }
guard frameDelays.count == frameCount else {
    fputs("exactly 16 comma-separated frame delays are required\n", stderr)
    exit(2)
}
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

func readExactFrame(path: String) -> [UInt8] {
    let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil)!
    let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
    guard image.width == cellSize && image.height == cellSize else {
        fputs("canonical idle must be 314x314\n", stderr)
        exit(1)
    }
    var result = [UInt8](repeating: 0, count: cellSize * cellSize * 4)
    let context = CGContext(data: &result, width: cellSize, height: cellSize, bitsPerComponent: 8,
                            bytesPerRow: cellSize * 4, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    context.draw(image, in: CGRect(x: 0, y: 0, width: cellSize, height: cellSize))
    return result
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

    let sourceWidth = maxX - minX + 1
    let sourceHeight = maxY - minY + 1
    let scale = min(1.0, min(Double(targetSpriteHeight) / Double(sourceHeight),
                             Double(targetSpriteMaxWidth) / Double(sourceWidth)))
    let scaledWidth = max(1, Int((Double(sourceWidth) * scale).rounded()))
    let scaledHeight = max(1, Int((Double(sourceHeight) * scale).rounded()))
    let scaledRootX = Int((Double(rootX - minX) * scale).rounded())
    var targetLeft = targetRootX - scaledRootX
    var targetTop = targetBaselineY - scaledHeight + 1
    targetLeft = max(2, min(targetLeft, cellSize - 2 - scaledWidth))
    targetTop = max(2, min(targetTop, cellSize - 2 - scaledHeight))

    let membership = Set(sourceIndices)
    var result = [UInt8](repeating: 0, count: cellSize * cellSize * 4)
    for targetYInSprite in 0..<scaledHeight {
        let sourceYInSprite = min(sourceHeight - 1, Int(Double(targetYInSprite) / scale))
        for targetXInSprite in 0..<scaledWidth {
            let sourceXInSprite = min(sourceWidth - 1, Int(Double(targetXInSprite) / scale))
            let sourceIndex = (minY + sourceYInSprite) * atlasWidth + minX + sourceXInSprite
            if !membership.contains(sourceIndex) { continue }
            let sourceOffset = sourceIndex * 4
            let targetOffset = ((targetTop + targetYInSprite) * cellSize + targetLeft + targetXInSprite) * 4
            result[targetOffset] = atlasPixels[sourceOffset]
            result[targetOffset + 1] = atlasPixels[sourceOffset + 1]
            result[targetOffset + 2] = atlasPixels[sourceOffset + 2]
            result[targetOffset + 3] = atlasPixels[sourceOffset + 3]
        }
    }
    print("frame \(String(format: "%02d", index)): pixels \(sourceIndices.count), bbox \(minX),\(minY)-\(maxX),\(maxY), scale \(String(format: "%.3f", scale)), target \(targetLeft),\(targetTop) \(scaledWidth)x\(scaledHeight)")
    return result
}

var frames: [[UInt8]] = []
for index in 0..<frameCount { frames.append(alignedFrame(sourceIndices: pixelsByFrame[index], index: index)) }

// Every animation begins on the shared canonical game idle for seamless transitions.
frames[0] = readExactFrame(path: canonicalIdlePath)

if !preserveFinalFrame {
    // Recovery animations end on the exact opening pixels so the return to idle cannot pop.
    frames[15] = frames[0]
}

for index in 0..<frameCount {
    let filename = String(format: "frame_%02d.png", index)
    try writePNG(frames[index], width: cellSize, height: cellSize, to: framesDirectory.appendingPathComponent(filename))
}
try writePNG(frames[0], width: cellSize, height: cellSize,
             to: outputDirectory.appendingPathComponent(startIdleName))
try writePNG(frames[15], width: cellSize, height: cellSize,
             to: outputDirectory.appendingPathComponent(endIdleName))

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
             to: outputDirectory.appendingPathComponent("\(assetStem)_16f_aligned.png"))

let gifURL = outputDirectory.appendingPathComponent("\(assetStem)_preview.gif")
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
