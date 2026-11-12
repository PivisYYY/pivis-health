import SwiftUI

/// 对话里的表情包：24 个 Q 版线条表情（∞ 小人），分作息、夸夸、陪伴、提醒四组。
/// 卡片写法 `{"type":"sticker","name":"抱抱"}`，放在一条回复的最后，不带边框。
/// 图形和关键帧都在 Stickers.json 里（scripts/stickers/compile.py 从设计稿生成，别手改）：
/// 路径只有 M / L / C / Z，变换是 2x3 矩阵，动画写成「哪一种 + 绕哪个点 + 延迟」，这里用 Canvas 现算。
/// 出现时动 8 秒、点一下再动；系统开了「减弱动态效果」就一直静止。
struct StickerView: View {
    let name: String
    var size: CGFloat = 112
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var playing = false
    @State private var startedAt = Date()
    @State private var replay = 0

    var body: some View {
        if let sticker = StickerLib.shared.sticker(named: name) {
            VStack(spacing: 2) {
                TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduceMotion || !playing)) { tl in
                    let t: Double? = (reduceMotion || !playing) ? nil : tl.date.timeIntervalSince(startedAt)
                    Canvas { ctx, sz in
                        StickerLib.shared.draw(sticker, in: ctx, size: sz, time: t)
                    }
                }
                .frame(width: size, height: size)
                Text(sticker.name)
                    .font(E.light(13))
                    .tracking(3)
                    .foregroundStyle(E.text)
            }
            .contentShape(Rectangle())
            .onTapGesture { replay += 1 }
            .task(id: replay) {
                startedAt = Date()
                playing = true
                try? await Task.sleep(nanoseconds: 8_000_000_000)
                playing = false
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("表情：\(sticker.name)")
            .accessibilityIdentifier("gen-sticker")
        }
    }
}

final class StickerLib {
    static let shared = StickerLib()

    struct Sticker {
        let name: String
        let root: Node
    }

    struct Anim {
        let kind: String
        let origin: CGPoint
        let delay: Double
    }

    struct Node {
        var transform: CGAffineTransform = .identity
        var anim: Anim?
        var children: [Node] = []
        var path: Path?
        var fill: Color?
        var stroke: Color?
        var width: CGFloat = 1.4
        var dash: [CGFloat] = []
    }

    /// 一种动画的关键帧：每个属性一串 [进度, 值]（tx ty sx sy r op do = 平移、缩放、旋转角度、透明度、虚线偏移）
    struct Keys: Decodable {
        let d: Double
        let e: String
        let dir: String?
        let p: [String: [[Double]]]
    }

    private(set) var stickers: [String: Sticker] = [:]
    private(set) var order: [String] = []
    private var anims: [String: Keys] = [:]
    private var viewBox: CGFloat = 120

    private init() {
        guard let url = Bundle.main.url(forResource: "Stickers", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let raw = try? JSONDecoder().decode(RawFile.self, from: data) else { return }
        viewBox = CGFloat(raw.size)
        anims = raw.anims
        for s in raw.stickers {
            stickers[s.name] = Sticker(name: s.name, root: Self.build(s.root))
            order.append(s.name)
        }
    }

    func sticker(named name: String) -> Sticker? {
        stickers[name.trimmingCharacters(in: .whitespacesAndNewlines)]
    }

    // MARK: 画

    func draw(_ s: Sticker, in ctx: GraphicsContext, size: CGSize, time: Double?) {
        let k = min(size.width, size.height) / viewBox
        let base = CGAffineTransform(scaleX: k, y: k)
        draw(s.root, ctx, ctm: base, time: time, lineScale: max(1, k))
    }

    private func draw(_ n: Node, _ ctx: GraphicsContext, ctm: CGAffineTransform, time: Double?, lineScale: CGFloat) {
        var c = ctx
        var local = CGAffineTransform.identity
        var dashPhase: CGFloat = 0
        if let a = n.anim, let time, let keys = anims[a.kind] {
            let t = time - a.delay
            let tx = value("tx", keys, t) ?? 0, ty = value("ty", keys, t) ?? 0
            let sx = value("sx", keys, t) ?? 1, sy = value("sy", keys, t) ?? 1
            let r = value("r", keys, t) ?? 0
            if let op = value("op", keys, t) { c.opacity *= op }
            if let off = value("do", keys, t) { dashPhase = CGFloat(off) }
            // 和 CSS 一样：绕 transform-origin 先缩放、再旋转、再平移
            local = CGAffineTransform(translationX: -a.origin.x, y: -a.origin.y)
                .concatenating(CGAffineTransform(scaleX: sx, y: sy))
                .concatenating(CGAffineTransform(rotationAngle: r * .pi / 180))
                .concatenating(CGAffineTransform(translationX: tx + a.origin.x, y: ty + a.origin.y))
        }
        let full = local.concatenating(n.transform).concatenating(ctm)
        if let p = n.path {
            let sp = p.applying(full)
            if let f = n.fill { c.fill(sp, with: .color(f)) }
            if let s = n.stroke {
                let scale = sqrt(abs(full.a * full.d - full.b * full.c))
                c.stroke(sp, with: .color(s), style: StrokeStyle(
                    lineWidth: n.width * lineScale * 0.94, lineCap: .round, lineJoin: .round,
                    dash: n.dash.map { $0 * scale }, dashPhase: dashPhase * scale))
            }
        }
        for child in n.children {
            draw(child, c, ctm: full, time: time, lineScale: lineScale)
        }
    }

    /// 某个属性在 t 秒时的值（没有这个属性就 nil）
    private func value(_ prop: String, _ keys: Keys, _ t: Double) -> Double? {
        guard let ks = keys.p[prop], let last = ks.last, keys.d > 0 else { return nil }
        var x = t / keys.d
        let cycle = floor(x)
        x -= cycle
        if keys.dir == "alt", Int(cycle) % 2 != 0 { x = 1 - x }
        if keys.dir == "rev" { x = 1 - x }
        for i in 0..<(ks.count - 1) where x >= ks[i][0] && x <= ks[i + 1][0] {
            let span = ks[i + 1][0] - ks[i][0]
            let u = span > 0 ? (x - ks[i][0]) / span : 1
            return ks[i][1] + (ks[i + 1][1] - ks[i][1]) * Self.ease(keys.e, u)
        }
        return last[1]
    }

    private static func ease(_ name: String, _ x: Double) -> Double {
        switch name {
        case "linear": return x
        case "in": return bezier(0.42, 0, 1, 1, x)
        case "out": return bezier(0, 0, 0.58, 1, x)
        case "ease": return bezier(0.25, 0.1, 0.25, 1, x)
        default: return bezier(0.42, 0, 0.58, 1, x)
        }
    }

    private static func bezier(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, _ x: Double) -> Double {
        func s(_ t: Double, _ a: Double, _ b: Double) -> Double { 3 * a * (1 - t) * (1 - t) * t + 3 * b * (1 - t) * t * t + t * t * t }
        func ds(_ t: Double, _ a: Double, _ b: Double) -> Double { 3 * a * (1 - t) * (1 - t) + 6 * (b - a) * (1 - t) * t + 3 * (1 - b) * t * t }
        var t = x
        for _ in 0..<8 {
            let err = s(t, x1, x2) - x
            let d = ds(t, x1, x2)
            if abs(err) < 1e-5 || abs(d) < 1e-6 { break }
            t -= err / d
        }
        return s(min(max(t, 0), 1), y1, y2)
    }

    // MARK: 读 Stickers.json

    private struct RawFile: Decodable {
        let size: Double
        let stickers: [RawSticker]
        let anims: [String: Keys]
    }

    private struct RawSticker: Decodable {
        let name: String
        let root: RawNode
    }

    private struct RawAnim: Decodable {
        let k: String
        let o: [Double]
        let dl: Double?
    }

    private struct RawNode: Decodable {
        let t: [Double]?
        let an: RawAnim?
        let c: [RawNode]?
        let p: String?
        let f: String?
        let s: String?
        let w: Double?
        let da: [Double]?
    }

    private static func build(_ r: RawNode) -> Node {
        var n = Node()
        if let t = r.t, t.count == 6 {
            n.transform = CGAffineTransform(a: t[0], b: t[1], c: t[2], d: t[3], tx: t[4], ty: t[5])
        }
        if let a = r.an, a.o.count == 2 {
            n.anim = Anim(kind: a.k, origin: CGPoint(x: a.o[0], y: a.o[1]), delay: a.dl ?? 0)
        }
        n.children = (r.c ?? []).map(build)
        if let p = r.p { n.path = parsePath(p) }
        n.fill = r.f.flatMap(color)
        n.stroke = r.s.flatMap(color)
        if let w = r.w { n.width = CGFloat(w) }
        n.dash = (r.da ?? []).map { CGFloat($0) }
        return n
    }

    /// "M x y L x y C x1 y1 x2 y2 x y Z"（生成器只写这四种、全是绝对坐标）
    private static func parsePath(_ d: String) -> Path {
        var path = Path()
        let tok = d.split(separator: " ")
        var i = 0
        func num() -> CGFloat {
            defer { i += 1 }
            return i < tok.count ? CGFloat(Double(tok[i]) ?? 0) : 0
        }
        while i < tok.count {
            let cmd = tok[i]
            i += 1
            switch cmd {
            case "M": path.move(to: CGPoint(x: num(), y: num()))
            case "L": path.addLine(to: CGPoint(x: num(), y: num()))
            case "C":
                let c1 = CGPoint(x: num(), y: num()), c2 = CGPoint(x: num(), y: num()), p = CGPoint(x: num(), y: num())
                path.addCurve(to: p, control1: c1, control2: c2)
            case "Z": path.closeSubpath()
            default: break
            }
        }
        return path
    }

    private static func color(_ hex: String) -> Color? {
        var h = hex.trimmingCharacters(in: .whitespaces)
        guard h.hasPrefix("#") else { return nil }
        h.removeFirst()
        if h.count == 3 { h = h.map { "\($0)\($0)" }.joined() }
        guard h.count == 6, let v = UInt32(h, radix: 16) else { return nil }
        return Color(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255, blue: Double(v & 0xff) / 255)
    }
}
