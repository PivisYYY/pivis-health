import SwiftUI

// MARK: - Pivis 莫比乌斯（方案 C · 收束线）
// 几根细线跟着带子扭半圈，在右端收成一个点。用在 P-Health 头像、底栏中间的按钮、开屏标记。
// active 时一个白点沿环走（P-Health 正在回复）；看不见、减少动态效果时不动。

struct MobiusMark: View {
    var lineWidth: CGFloat = 1
    var active = false
    /// 线的根数：大图 4 根；很小的时候（对话头像）用 2 根，免得糊成一团
    var strands: Int = 4
    var background: Color = .black
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Environment(\.motionPaused) private var paused

    var body: some View {
        let moving = active && !reduce && !paused
        TimelineView(.animation(minimumInterval: ambientFrame, paused: !moving)) { ctx in
            Canvas { g, size in
                MobiusGeometry.draw(in: &g, size: size, lineWidth: lineWidth, strands: strands,
                                    background: background,
                                    runner: moving ? (ctx.date.timeIntervalSinceReferenceDate / 2.8).truncatingRemainder(dividingBy: 1) : nil)
            }
        }
        .aspectRatio(2, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

enum MobiusGeometry {
    /// 坐标系：宽 100、高 50，原点在中心；伯努利双纽线 a = 42
    private static let a = 42.0
    private static let width = 3.6           // 带子半宽（再乘每根线的系数）
    private static let cross = 3 * Double.pi / 2   // 从上面压过去的那一段在这个参数附近

    private static func point(_ t: Double) -> CGPoint {
        let s = sin(t), c = cos(t), den = 1 + s * s
        return CGPoint(x: a * c / den, y: a * s * c / den)
    }

    private static func normal(_ t: Double) -> CGVector {
        let e = 1e-4
        let p0 = point(t - e), p1 = point(t + e)
        let dx = p1.x - p0.x, dy = p1.y - p0.y
        let l = max(hypot(dx, dy), 1e-9)
        return CGVector(dx: -dy / l, dy: dx / l)
    }

    /// 一根线：带宽矢量随参数转半圈（sin(t/2)），所以各根线在右端（t = 0）汇到一点
    private static func strand(_ k: Double, _ t0: Double, _ t1: Double, _ n: Int) -> [CGPoint] {
        (0...n).map { i in
            let t = t0 + (t1 - t0) * Double(i) / Double(n)
            let p = point(t), nv = normal(t), o = k * width * sin(t / 2)
            return CGPoint(x: p.x + nv.dx * o, y: p.y + nv.dy * o)
        }
    }

    private static func ks(_ n: Int) -> [Double] {
        n <= 2 ? [1.5, -1.5] : [1.5, 0.51, -0.51, -1.5]
    }

    private static func build(_ n: Int) -> (full: [[CGPoint]], over: [[CGPoint]]) {
        let k = ks(n)
        return (k.map { strand($0, 0, 2 * .pi, 120) }, k.map { strand($0, cross - 0.42, cross + 0.42, 16) })
    }
    private static let two = build(2)
    private static let four = build(4)
    private static func lines(_ n: Int) -> (full: [[CGPoint]], over: [[CGPoint]]) { n <= 2 ? two : four }

    /// 交叉处压在下面的那几根要断开：沿上面那段画一条底色的带子盖住
    private static func mask(extra: Double) -> [CGPoint] {
        var left: [CGPoint] = [], right: [CGPoint] = []
        for i in 0...10 {
            let t = cross - 0.42 + 0.84 * Double(i) / 10
            let p = point(t), nv = normal(t)
            let w = (2 * 1.5 * width * abs(sin(t / 2)) + 3.2 + extra) / 2
            left.append(CGPoint(x: p.x + nv.dx * w, y: p.y + nv.dy * w))
            right.append(CGPoint(x: p.x - nv.dx * w, y: p.y - nv.dy * w))
        }
        return left + right.reversed()
    }

    static func draw(in g: inout GraphicsContext, size: CGSize, lineWidth: CGFloat, strands: Int,
                     background: Color, runner: Double?) {
        let s = min(size.width / 100, size.height / 50)
        let cx = size.width / 2, cy = size.height / 2
        func map(_ p: CGPoint) -> CGPoint { CGPoint(x: cx + p.x * s, y: cy + p.y * s) }
        func path(_ pts: [CGPoint]) -> Path { var p = Path(); p.addLines(pts.map(map)); return p }
        let style = StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round)
        let l = lines(strands)
        for st in l.full { g.stroke(path(st), with: .color(.white), style: style) }
        var m = Path()
        m.addLines(mask(extra: Double(lineWidth) / Double(s) * 2).map(map))
        m.closeSubpath()
        if background == .clear {
            // 透明底（小组件、锁屏用的图）：交叉处是挖空，不是涂黑
            var c = g
            c.blendMode = .destinationOut
            c.fill(m, with: .color(.white))
        } else {
            g.fill(m, with: .color(background))
        }
        for st in l.over { g.stroke(path(st), with: .color(.white), style: style) }
        // 右端收成的那个点
        let r = max(2.2 * s, lineWidth * 1.3)
        let tip = map(CGPoint(x: a, y: 0))
        g.fill(Path(ellipseIn: CGRect(x: tip.x - r, y: tip.y - r, width: r * 2, height: r * 2)), with: .color(.white))
        // 回复中：一个白点沿环走
        if let ph = runner {
            let p = map(point(ph * 2 * .pi))
            let rr = max(1.8, lineWidth * 1.6)
            g.fill(Path(ellipseIn: CGRect(x: p.x - rr * 2.4, y: p.y - rr * 2.4, width: rr * 4.8, height: rr * 4.8)),
                   with: .color(.white.opacity(0.16)))
            g.fill(Path(ellipseIn: CGRect(x: p.x - rr, y: p.y - rr, width: rr * 2, height: rr * 2)), with: .color(.white))
        }
    }
}

#if DEBUG
/// 生成 App 图标（-renderAppIcon）：和应用里的莫比乌斯头像同一套画法，黑底白细线。
/// 小尺寸（通知、设置里 ≤ 87px）用 2 根线、线稍粗，免得糊成一团。
@MainActor
enum AppIconRenderer {
    static func renderAll(to dir: URL) {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let sizes: [(String, Int)] = [
            ("icon_1024", 1024),
            ("icon_iphone_20x20@2x", 40), ("icon_iphone_20x20@3x", 60),
            ("icon_iphone_29x29@2x", 58), ("icon_iphone_29x29@3x", 87),
            ("icon_iphone_40x40@2x", 80), ("icon_iphone_40x40@3x", 120),
            ("icon_iphone_60x60@2x", 120), ("icon_iphone_60x60@3x", 180),
            ("icon_ipad_20x20@1x", 20), ("icon_ipad_20x20@2x", 40),
            ("icon_ipad_29x29@1x", 29), ("icon_ipad_29x29@2x", 58),
            ("icon_ipad_40x40@1x", 40), ("icon_ipad_40x40@2x", 80),
            ("icon_ipad_76x76@1x", 76), ("icon_ipad_76x76@2x", 152),
            ("icon_ipad_83.5x83.5@2x", 167),
        ]
        for (name, px) in sizes {
            let small = px <= 87
            let side = CGFloat(px)
            let markW = side * (small ? 0.80 : 0.68)
            let s = markW / 100                                  // 画法坐标：宽 100
            let lw = s * (small ? 3.4 : 1.7)                     // 线宽按图标大小等比
            let view = Canvas { g, size in
                g.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.black))
                var inner = g
                inner.translateBy(x: (size.width - markW) / 2, y: (size.height - markW / 2) / 2)
                MobiusGeometry.draw(in: &inner, size: CGSize(width: markW, height: markW / 2), lineWidth: lw,
                                    strands: small ? 2 : 4, background: .black, runner: nil)
            }
            .frame(width: side, height: side)
            let r = ImageRenderer(content: view)
            r.scale = 1
            r.isOpaque = true
            if let img = r.uiImage, let png = img.pngData() {
                try? png.write(to: dir.appendingPathComponent(name + ".png"))
            }
        }
        // 小组件标题前的小标记：20×10pt，透明底，2 根线
        for scale in [2, 3] {
            let w = CGFloat(20 * scale), h = CGFloat(10 * scale)
            let view = Canvas { g, size in
                MobiusGeometry.draw(in: &g, size: size, lineWidth: CGFloat(scale) * 1.15, strands: 2,
                                    background: .clear, runner: nil)
            }
            .frame(width: w, height: h)
            let r = ImageRenderer(content: view)
            r.scale = 1
            r.isOpaque = false
            if let img = r.uiImage, let png = img.pngData() {
                try? png.write(to: dir.appendingPathComponent("mark@\(scale)x.png"))
            }
        }
    }
}
#endif
