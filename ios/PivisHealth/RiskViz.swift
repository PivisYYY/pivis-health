import SwiftUI

// MARK: - 主卡图表：P-Health 决定画什么（metric / kind / days / show），内核填数，这里只按描述画。
// 档位靠动效强弱区分：需处理（act）快闪 + 外扩光圈；留意（watch）缓慢呼吸；平稳（steady）不动。系统「减少动态效果」时全部静止。

/// 0→1→0 的呼吸相位
private func beat(_ t: Double, _ period: Double) -> Double { 0.5 - 0.5 * cos(2 * .pi * t / period) }

func vfmt(_ v: Double?, _ nd: Int) -> String {
    guard let v else { return "" }
    return nd == 0 ? String(Int(v.rounded())) : String(format: "%.\(nd)f", v)
}

/// 参照线标签：整数就不带小数（老大说 28 就显示 28）
func lfmt(_ v: Double?, _ nd: Int) -> String {
    guard let v else { return "" }
    return abs(v - v.rounded()) < 0.05 ? String(Int(v.rounded())) : vfmt(v, nd)
}

func grouped(_ v: Double) -> String {
    let f = NumberFormatter()
    f.numberStyle = .decimal
    f.maximumFractionDigits = 0
    return f.string(from: NSNumber(value: v)) ?? String(Int(v))
}

private func mmdd(_ iso: String?) -> String {
    guard let iso, iso.count >= 10 else { return "" }
    return String(iso.dropFirst(5).prefix(5))
}

/// 问题那一段闪：act 1.4s 闪到很淡；watch 3.6s 慢慢淡一半；steady 不动
struct RiskBlink: ViewModifier {
    let level: String
    var delay: Double = 0
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Environment(\.motionPaused) private var paused
    @State private var start = Date()
    func body(content: Content) -> some View {
        if reduce || paused || level == "steady" || level == "nodata" {
            content
        } else {
            TimelineView(.animation(minimumInterval: ambientFrame)) { ctx in
                let t = ctx.date.timeIntervalSince(start) - delay
                let p = t < 0 ? 0 : beat(t, level == "act" ? 1.4 : 3.6)
                content.opacity(level == "act" ? 1 - 0.8 * p : 1 - 0.5 * p)
            }
        }
    }
}

/// 档位点：act 实心 + 两圈外扩；watch 线框呼吸；steady 灰线框
struct LevelDot: View {
    let level: String
    var size: CGFloat = 8
    var filled: Bool? = nil
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Environment(\.motionPaused) private var paused
    var body: some View {
        let still = reduce || paused || level == "steady"
        TimelineView(.animation(minimumInterval: ambientFrame, paused: still)) { ctx in
            let t = ctx.date.timeIntervalSinceReferenceDate
            ZStack {
                if level == "act" && !reduce {
                    ForEach(0..<2, id: \.self) { i in
                        let p = (t / 1.6 + Double(i) * 0.5).truncatingRemainder(dividingBy: 1)
                        Circle().stroke(E.text, lineWidth: 1)
                            .frame(width: size, height: size)
                            .scaleEffect(1 + 1.8 * p)
                            .opacity(0.75 * (1 - p))
                    }
                }
                let b = (level == "watch" && !reduce) ? beat(t, 3.6) : 0
                if filled ?? (level == "act") {
                    Circle().fill(E.text).frame(width: size, height: size)
                        .scaleEffect(1 + 0.35 * b)
                        .opacity(level == "watch" ? 0.5 + 0.5 * b : 1)
                } else {
                    Circle().strokeBorder(level == "steady" ? E.text3 : E.text, lineWidth: 1)
                        .frame(width: size, height: size)
                        .scaleEffect(1 + 0.35 * b)
                        .opacity(level == "watch" ? 0.5 + 0.5 * b : 1)
                }
            }
        }
        .frame(width: size * 3, height: size * 3)
        .accessibilityHidden(true)
    }
}

/// 线一笔画出来
private struct DrawIn: ViewModifier {
    @Binding var drawn: CGFloat
    var duration: Double = 1.4
    @Environment(\.accessibilityReduceMotion) private var reduce
    func body(content: Content) -> some View {
        content.onAppear {
            if reduce { drawn = 1 } else { withAnimation(.easeOut(duration: duration)) { drawn = 1 } }
        }
    }
}

private func polyline(_ pts: [CGPoint]) -> Path {
    var p = Path()
    if let f = pts.first { p.move(to: f); p.addLines(pts) }
    return p
}

private func hline(_ y: CGFloat, _ x0: CGFloat, _ x1: CGFloat) -> Path {
    var p = Path(); p.move(to: CGPoint(x: x0, y: y)); p.addLine(to: CGPoint(x: x1, y: y)); return p
}

private func vline(_ x: CGFloat, _ y0: CGFloat, _ y1: CGFloat) -> Path {
    var p = Path(); p.move(to: CGPoint(x: x, y: y0)); p.addLine(to: CGPoint(x: x, y: y1)); return p
}

private let dashed = StrokeStyle(lineWidth: 1, dash: [2, 4])
private let dotted = StrokeStyle(lineWidth: 2, lineCap: .round, dash: [0.5, 4])

private struct Caption: View {
    let text: String
    var body: some View { Text(text).font(E.body(11)).foregroundStyle(E.text3).lineLimit(1).fixedSize() }
}

// MARK: - 入口

struct RiskViz: View {
    let viz: V3Page.Viz
    let level: String
    let today: String
    var body: some View {
        Group {
            switch viz.kind {
            case "trend": TrendViz(viz: viz, level: level, today: today)
            case "gauge": GaugeViz(viz: viz, level: level)
            case "need": NeedViz(viz: viz, level: level)
            case "stack": StackViz(viz: viz, level: level)
            case "range": RangeViz(viz: viz, level: level)
            case "progress": ProgressViz(viz: viz, level: level)
            case "route": RouteViz(viz: viz, level: level)
            default: EmptyView()
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(viz.accessibilityText)
        .accessibilityIdentifier("hero-viz-\(viz.kind)")
    }
}

extension V3Page.Viz {
    func shows(_ mark: String) -> Bool { show?.contains(mark) ?? true }
    var digits: Int { nd ?? 1 }
    var accessibilityText: String {
        var s = "\(label ?? metric) \(valueText ?? "")\(unit ?? "")"
        if let w = warn, shows("warn") { s += "，警戒线 \(vfmt(w, digits))" }
        if let b = band, b.count == 2, shows("band") { s += "，常态 \(vfmt(b[0], digits)) 到 \(vfmt(b[1], digits))" }
        return s
    }
}

// MARK: - trend：折线 + 常态带 + 警戒线，跌破（或超过）警戒的那段加粗

struct TrendViz: View {
    let viz: V3Page.Viz
    let level: String
    let today: String
    @State private var drawn: CGFloat = 0
    private let h: CGFloat = 104
    private let pad: CGFloat = 6

    var body: some View {
        let vals = (viz.series ?? []).map(\.value)
        let nd = viz.digits
        let band = viz.shows("band") ? viz.band : nil
        let warn = viz.shows("warn") ? viz.warn : nil
        let need = viz.shows("need") ? viz.need : nil
        let refs = vals + (band ?? []) + [warn, need].compactMap { $0 }
        let lo = refs.min() ?? 0
        let hi = refs.max() ?? 1
        let span = max(hi - lo, 0.001)
        let vmin = lo - span * 0.12
        let vmax = hi + span * 0.12
        let lowBad = viz.direction != "high_bad"
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { geo in
                let W = geo.size.width
                let w = W - 12
                let y: (Double) -> CGFloat = { v in pad + CGFloat((vmax - v) / (vmax - vmin)) * (h - 2 * pad) }
                let step = vals.count > 1 ? w / CGFloat(vals.count - 1) : 0
                let pts = vals.enumerated().map { CGPoint(x: CGFloat($0.offset) * step, y: y($0.element)) }
                ZStack(alignment: .topLeading) {
                    if let b = band, b.count == 2 {
                        Rectangle().fill(Color.white.opacity(0.06))
                            .frame(width: W, height: max(0, y(b[0]) - y(b[1])))
                            .offset(y: y(b[1]))
                        // 常态带的字默认在带子顶边左侧；折线从那里穿过就依次试右侧、中间、带子上方
                        let top = y(b[1]) + 2
                        let spot = Self.place(pts, W: W, tries: [(.leading, top), (.trailing, top), (.center, top),
                                                                 (.leading, y(b[1]) - 16), (.trailing, y(b[1]) - 16)])
                        Caption(text: viz.bandLabel ?? "常态 \(lfmt(b[0], nd))–\(lfmt(b[1], nd))")
                            .frame(width: W - 8, alignment: spot.align)
                            .offset(x: 4, y: spot.y)
                    }
                    // 参照线的字默认在右端；折线或最后那颗点压到字时挪到左端
                    if let wv = warn {
                        let ly = lowBad ? y(wv) + 3 : y(wv) - 16
                        let spot = Self.place(pts, W: W, tries: [(.trailing, ly), (.leading, ly), (.center, ly)])
                        hline(y(wv), 0, W).stroke(E.text3, style: dashed)
                        Caption(text: viz.warnLabel ?? "警戒 \(lfmt(wv, nd))")
                            .frame(width: W - 8, alignment: spot.align)
                            .offset(x: 4, y: spot.y)
                    }
                    if let nv = need {
                        let ly = y(nv) - 16
                        let spot = Self.place(pts, W: W, tries: [(.trailing, ly), (.leading, ly), (.center, ly)])
                        hline(y(nv), 0, W).stroke(E.text3, style: dashed)
                        Caption(text: "需要 \(lfmt(nv, 1))")
                            .frame(width: W - 8, alignment: spot.align)
                            .offset(x: 4, y: spot.y)
                    }
                    polyline(pts).trim(from: 0, to: drawn)
                        .stroke(E.text.opacity(level == "steady" ? 0.6 : 1), style: StrokeStyle(lineWidth: 1.25, lineJoin: .round))
                    if let wv = warn {
                        let wy = y(wv)
                        polyline(pts).trim(from: 0, to: drawn)
                            .stroke(E.text, style: StrokeStyle(lineWidth: 3, lineJoin: .round))
                            .mask(alignment: .topLeading) {
                                Rectangle().frame(width: W, height: lowBad ? max(0, h - wy) : max(0, wy))
                                    .offset(y: lowBad ? wy : 0)
                            }
                    }
                    if let last = pts.last {
                        LevelDot(level: level, size: 6, filled: true).position(last)
                            .opacity(drawn >= 1 ? 1 : 0)
                    }
                }
            }
            .frame(height: h)
            .modifier(DrawIn(drawn: $drawn))
            HStack {
                Caption(text: mmdd(viz.series?.first?.date))
                Spacer()
                Caption(text: viz.asof == today ? "今天" : mmdd(viz.asof))
            }
            .padding(.trailing, 12)
        }
    }

    /// 给一行小字（约 96pt 宽、14pt 高）挑位置：按顺序试，第一个不被折线和末端点压到的就用；都不行用第一个。
    /// tries 里每项是（左 / 中 / 右，顶边 y）。折线按每段插 6 个点来查，末端点多留 6pt。
    static func place(_ pts: [CGPoint], W: CGFloat, tries: [(Alignment, CGFloat)]) -> (align: Alignment, y: CGFloat) {
        var samples: [CGPoint] = []
        for (a, b) in zip(pts, pts.dropFirst()) {
            for k in 0..<6 {
                let t = CGFloat(k) / 6
                samples.append(CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t))
            }
        }
        if let last = pts.last { samples.append(last) }
        let end = pts.last
        for (align, top) in tries {
            let x0: CGFloat = align == .trailing ? W - 100 : (align == .center ? W / 2 - 52 : 0)
            let x1: CGFloat = x0 + 104
            let hit = samples.contains { $0.x >= x0 && $0.x <= x1 && $0.y >= top - 3 && $0.y <= top + 17 }
            let dot = end.map { $0.x >= x0 - 6 && $0.x <= x1 + 6 && $0.y >= top - 9 && $0.y <= top + 23 } ?? false
            if !hit && !dot { return (align, top) }
        }
        return (tries.first?.0 ?? .trailing, tries.first?.1 ?? 0)
    }
}

// MARK: - gauge：0–100 半圆，数字在中间，警戒区虚线

struct GaugeViz: View {
    let viz: V3Page.Viz
    let level: String
    @State private var drawn: CGFloat = 0

    var body: some View {
        let f = min(1, max(0, (viz.value ?? 0) / 100))
        let warnF = min(1, max(0, (viz.warn ?? 33) / 100))
        GeometryReader { geo in
            let W = geo.size.width
            let r = min(W / 2 - 12, 150)
            let c = CGPoint(x: W / 2, y: r + 12)
            let pt: (Double, CGFloat) -> CGPoint = { fr, rr in
                let a = Double.pi * (1 - fr)
                return CGPoint(x: c.x + rr * CGFloat(cos(a)), y: c.y - rr * CGFloat(sin(a)))
            }
            let arcAt: (Double, Double, CGFloat) -> Path = { f0, f1, rr in
                polyline((0...64).map { i in pt(f0 + (f1 - f0) * Double(i) / 64, rr) })
            }
            let arc: (Double, Double) -> Path = { f0, f1 in arcAt(f0, f1, r) }
            ZStack(alignment: .topLeading) {
                arc(0, 1).stroke(E.stroke, lineWidth: 1)
                if viz.shows("warn") {
                    arcAt(0, warnF, r - 9).stroke(E.text.opacity(0.8), style: dotted)
                        .modifier(RiskBlink(level: level, delay: 1.4))
                    Caption(text: "警戒 \(vfmt(viz.warn ?? 33, 0))")
                        .position(x: pt(warnF, r + 16).x - 14, y: pt(warnF, r + 16).y)
                }
                arc(0, f).trim(from: 0, to: drawn)
                    .stroke(E.text, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                LevelDot(level: level, size: 7, filled: true).position(pt(f, r)).opacity(drawn >= 1 ? 1 : 0)
                VStack(spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(viz.valueText ?? "").font(E.thin(72)).kerning(-2).foregroundStyle(E.text)
                        Text("%").font(E.light(22)).foregroundStyle(E.text)
                    }
                    if let a = viz.aside { Caption(text: a.text) }
                }
                .position(x: c.x, y: c.y - 44)
                Caption(text: "0").position(x: pt(0, r).x, y: c.y + 14)
                Caption(text: "100").position(x: pt(1, r).x, y: c.y + 14)
            }
            .modifier(DrawIn(drawn: $drawn))
        }
        .frame(height: 196)
    }
}

// MARK: - need：睡了 vs 需要，缺口单独标出来 + 近 N 晚够不够

struct NeedViz: View {
    let viz: V3Page.Viz
    let level: String
    @State private var grown: CGFloat = 0

    var body: some View {
        let slept = viz.value ?? 0
        let need = viz.need ?? slept
        let maxH = max(need, slept) * 1.19
        let nights = viz.nights ?? []
        VStack(alignment: .leading, spacing: 8) {
            GeometryReader { geo in
                let W = geo.size.width
                let x: (Double) -> CGFloat = { v in CGFloat(v / max(maxH, 0.1)) * W }
                ZStack(alignment: .topLeading) {
                    Rectangle().fill(E.stroke).frame(width: W, height: 1).offset(y: 18)
                    Rectangle().fill(E.text).frame(width: x(slept), height: 3).offset(y: 17)
                        .scaleEffect(x: grown, anchor: .leading)
                    if slept < need {
                        hline(18.5, x(slept), x(need)).stroke(E.text.opacity(0.85), style: dotted)
                            .modifier(RiskBlink(level: level, delay: 1.2))
                        if viz.shows("need") {
                            Caption(text: "缺 \(vfmt(need - slept, 1))")
                                .position(x: (x(slept) + x(need)) / 2, y: 36)
                        }
                    }
                    if viz.shows("need") {
                        Rectangle().fill(E.text.opacity(0.6)).frame(width: 1, height: 21).offset(x: x(need), y: 8)
                    }
                }
            }
            .frame(height: 44)
            .onAppear { animateGrow() }
            if !nights.isEmpty {
                HStack(spacing: 6) {
                    ForEach(Array(nights.enumerated()), id: \.offset) { _, n in
                        Group {
                            if n.ok { Circle().fill(E.text) } else { Circle().strokeBorder(E.text3, lineWidth: 1) }
                        }
                        .frame(width: 10, height: 10)
                    }
                    let short = viz.shortNights ?? 0
                    Caption(text: short > 0 ? "近 \(nights.count) 晚 · \(short) 晚不够" : "近 \(nights.count) 晚都够")
                        .padding(.leading, 6)
                }
            }
        }
    }

    @Environment(\.accessibilityReduceMotion) private var reduce
    private func animateGrow() {
        if reduce { grown = 1 } else { withAnimation(.timingCurve(0.2, 0.7, 0.2, 1, duration: 1.2)) { grown = 1 } }
    }
}

// MARK: - stack：每晚欠的睡眠一块块叠起来，越近越亮

struct StackViz: View {
    let viz: V3Page.Viz
    let level: String
    @State private var shown = 0
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let blocks = (viz.blocks ?? []).filter { $0.short > 0 }
        let total = blocks.reduce(0) { $0 + $1.short }
        let warn = viz.warn ?? 10
        let scale = max(warn * 1.6, total * 1.15, 1)
        GeometryReader { geo in
            let W = geo.size.width
            let x: (Double) -> CGFloat = { v in CGFloat(v / scale) * W }
            ZStack(alignment: .topLeading) {
                Rectangle().fill(E.stroke).frame(width: W, height: 1).offset(y: 20)
                ForEach(Array(blocks.enumerated()), id: \.offset) { i, b in
                    let acc = blocks.prefix(i).reduce(0) { $0 + $1.short }
                    let isLast = i == blocks.count - 1
                    Rectangle().fill(E.text)
                        .frame(width: max(1, x(b.short) - 2), height: 12)
                        .opacity(0.35 + 0.65 * Double(i + 1) / Double(max(1, blocks.count)))
                        .modifier(RiskBlink(level: isLast ? level : "steady", delay: 0.25 * Double(blocks.count) + 0.4))
                        .scaleEffect(x: i < shown ? 1 : 0, anchor: .leading)
                        .offset(x: x(acc), y: 14)
                }
                if viz.shows("warn") {
                    vline(x(warn), 4, 34).stroke(E.text3, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    Caption(text: "警戒 \(lfmt(warn, 1))").position(x: x(warn), y: 44)
                }
            }
        }
        .frame(height: 52)
        .onAppear {
            if reduce { shown = blocks.count; return }
            for i in 0..<blocks.count {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25 * Double(i)) {
                    withAnimation(.easeOut(duration: 0.45)) { shown = i + 1 }
                }
            }
        }
    }
}

// MARK: - range：区间刻度，今天落在常态 / 警戒哪一段，带这几天的轨迹

struct RangeViz: View {
    let viz: V3Page.Viz
    let level: String
    @State private var arrived = false
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let nd = viz.digits
        let lo = viz.scale?.first ?? 0
        let hi = viz.scale?.last ?? 1
        let trail = viz.trail ?? []
        let value = viz.value ?? 0
        let first = trail.first?.value ?? value
        let highBad = viz.direction == "high_bad"
        GeometryReader { geo in
            let W = geo.size.width
            let x: (Double) -> CGFloat = { v in CGFloat((v - lo) / max(hi - lo, 0.001)) * W }
            ZStack(alignment: .topLeading) {
                Rectangle().fill(E.stroke).frame(width: W, height: 1).offset(y: 20)
                if viz.shows("band"), let b = viz.band, b.count == 2 {
                    Rectangle().fill(Color.white.opacity(0.35)).frame(width: max(0, x(b[1]) - x(b[0])), height: 3)
                        .offset(x: x(b[0]), y: 19)
                    Caption(text: "常态 \(lfmt(b[0], nd))–\(lfmt(b[1], nd))")
                        .position(x: (x(b[0]) + x(b[1])) / 2, y: 46)
                }
                if viz.shows("warn"), let wv = viz.warn {
                    let x0 = highBad ? x(wv) : 0
                    let x1 = highBad ? W : x(wv)
                    hline(20, x0, x1).stroke(E.text.opacity(0.7), style: dotted)
                        .modifier(RiskBlink(level: level))
                    Caption(text: highBad ? "警戒 \(lfmt(wv, nd)) 以上" : "警戒 \(lfmt(wv, nd)) 以下")
                        .frame(width: W, alignment: highBad ? .trailing : .leading)
                        .offset(y: 40)
                }
                ForEach(Array(trail.dropLast().enumerated()), id: \.offset) { i, t in
                    Rectangle().fill(E.text).frame(width: 1, height: 11)
                        .opacity(0.12 + Double(i) * 0.07)
                        .offset(x: x(t.value), y: 15)
                }
                ZStack(alignment: .top) {
                    Rectangle().fill(E.text).frame(width: 1, height: 29)
                    Circle().fill(E.text).frame(width: 7, height: 7).offset(y: 11)
                }
                .frame(width: 7)
                .modifier(RiskBlink(level: level, delay: 1.4))
                .offset(x: (arrived ? x(value) : x(first)) - 3, y: 6)
            }
        }
        .frame(height: 56)
        .onAppear {
            if reduce { arrived = true } else { withAnimation(.timingCurve(0.2, 0.7, 0.2, 1, duration: 1.4)) { arrived = true } }
        }
    }
}

// MARK: - progress：按此刻应走到的进度比

struct ProgressViz: View {
    let viz: V3Page.Viz
    let level: String
    @State private var grown: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let goal = max(viz.goal ?? 8000, 1)
        let done = min(viz.value ?? 0, goal)
        let pace = viz.pace ?? 0
        GeometryReader { geo in
            let W = geo.size.width
            let x: (Double) -> CGFloat = { v in CGFloat(min(v, goal) / goal) * W }
            ZStack(alignment: .topLeading) {
                Rectangle().fill(E.stroke).frame(width: W, height: 1).offset(y: 18)
                Rectangle().fill(E.text).frame(width: x(done), height: 3).offset(y: 17)
                    .scaleEffect(x: grown, anchor: .leading)
                if done < pace {
                    hline(18.5, x(done), x(pace)).stroke(E.text.opacity(0.85), style: dotted)
                        .modifier(RiskBlink(level: level, delay: 1.2))
                }
                if viz.shows("pace"), pace > 0, pace < goal {
                    vline(x(pace), 6, 30).stroke(E.text2, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    Caption(text: "\(viz.paceTime ?? "现在") 应到 \(grouped(pace))").position(x: min(max(x(pace), 60), W - 60), y: 40)
                }
                if viz.shows("goal") {
                    Rectangle().fill(E.text.opacity(0.6)).frame(width: 1, height: 17).offset(x: W - 1, y: 10)
                }
            }
        }
        .frame(height: 48)
        .onAppear {
            if reduce { grown = 1 } else { withAnimation(.timingCurve(0.2, 0.7, 0.2, 1, duration: 1.2)) { grown = 1 } }
        }
    }
}

// MARK: - route：朝目标的计划路线 vs 实际，落后计划的那段标出来

struct RouteViz: View {
    let viz: V3Page.Viz
    let level: String
    @State private var drawn: CGFloat = 0
    private let h: CGFloat = 120
    private let pad: CGFloat = 8

    var body: some View {
        let pts = viz.points ?? []
        let start = viz.start ?? pts.first?.value ?? 0
        let target = viz.target ?? start
        let weeks = max(viz.weeksTotal ?? 1, 1)
        let all = pts.map(\.value) + [start, target]
        let vmin = (all.min() ?? 0) - 1
        let vmax = (all.max() ?? 1) + 1
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { geo in
                let W = geo.size.width
                let w = W - 12
                let x: (Double) -> CGFloat = { wk in CGFloat(min(wk, weeks) / weeks) * w }
                let y: (Double) -> CGFloat = { v in pad + CGFloat((vmax - v) / (vmax - vmin)) * (h - 2 * pad) }
                let line = pts.map { CGPoint(x: x($0.week), y: y($0.value)) }
                ZStack(alignment: .topLeading) {
                    if viz.shows("target") {
                        hline(y(target), 0, W).stroke(E.grey4A, lineWidth: 1)
                        Caption(text: "目标 \(lfmt(target, 1))").frame(width: W, alignment: .trailing).offset(y: y(target) + 3)
                    }
                    if viz.shows("plan") {
                        Path { p in p.move(to: CGPoint(x: 0, y: y(start))); p.addLine(to: CGPoint(x: x(weeks), y: y(target))) }
                            .stroke(E.text3, style: StrokeStyle(lineWidth: 1, dash: [3, 4]))
                        Caption(text: "计划路线").offset(x: x(weeks * 0.45), y: y(start - (start - target) * 0.45) - 18)
                        if let last = line.last, let plan = viz.planNow, (viz.behind ?? 0) >= 1 {
                            vline(last.x, last.y, y(plan)).stroke(E.text, style: dotted)
                                .modifier(RiskBlink(level: level, delay: 1.4))
                            Caption(text: "落后 \(vfmt(viz.behind, 1))").offset(x: last.x + 8, y: (last.y + y(plan)) / 2 - 7)
                        }
                    }
                    polyline(line).trim(from: 0, to: drawn).stroke(E.text, style: StrokeStyle(lineWidth: 1.5, lineJoin: .round))
                    if let last = line.last {
                        LevelDot(level: level, size: 6, filled: true).position(last).opacity(drawn >= 1 ? 1 : 0)
                    }
                }
            }
            .frame(height: h)
            .modifier(DrawIn(drawn: $drawn))
            HStack {
                Caption(text: "第 0 周")
                Spacer()
                Caption(text: "第 \(Int(weeks)) 周")
            }
        }
    }
}


/// 对话里的「主卡同款」预览：P-Health 只给画法（metric / kind / days / show），
/// 数字和形状跟主卡走同一个服务器计算、同一个画图组件，所以对话里看到的就是页面上会出现的样子。
struct VizPreview: View {
    let metric: String
    let kind: String?
    let days: Int?
    let show: [String]?
    @State private var viz: V3Page.Viz?
    @State private var failed: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let v = viz {
                HStack(alignment: .firstTextBaseline) {
                    Text(v.label ?? metric).font(E.body(13)).foregroundStyle(E.text2)
                    Spacer()
                    if let asof = v.asof { Text(shortDay(asof)).font(E.body(11)).foregroundStyle(E.text3) }
                }
                if v.kind != "gauge" {
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        Text(v.valueText ?? "").font(E.thin(44)).kerning(-1.5).foregroundStyle(E.text)
                        if let u = v.unit { Text(displayUnit(u)).font(E.light(16)).foregroundStyle(E.text) }
                        if let a = v.aside {
                            Spacer(minLength: 6)
                            Text(a.text).font(E.body(13)).foregroundStyle(E.text)
                        }
                    }
                    .padding(.top, 4)
                }
                RiskViz(viz: v, level: v.zone ?? "steady", today: "").padding(.top, 10)
            } else if let failed {
                Text(failed).font(E.body(13)).foregroundStyle(E.text3)
            } else {
                WorkingLine().padding(.vertical, 30)
            }
        }
        .task(id: "\(metric)|\(kind ?? "")|\(days ?? 0)|\(show?.joined() ?? "")") { await load() }
        .accessibilityIdentifier("viz-preview")
    }

    private func shortDay(_ iso: String) -> String {
        let p = iso.split(separator: "-")
        return p.count == 3 ? "\(Int(p[1]) ?? 0)/\(Int(p[2]) ?? 0)" : iso
    }

    private func load() async {
        let req = PivisAPI.request("api/v3/viz", ["metric": metric, "kind": kind, "days": days.map(String.init),
                                                 "show": (show ?? []).isEmpty ? nil : show?.joined(separator: ",")])
        do {
            viz = try await PivisAPI.fetch(V3Page.Viz.self, req)
        } catch PivisAPI.Failure.http(_, let msg) {
            failed = "这种画法现在画不了" + (msg.map { "：\($0)" } ?? "")
        } catch PivisAPI.Failure.offline {
            failed = "图暂时画不出来（连不上服务器）"
        } catch {
            failed = "图暂时画不出来"
        }
    }
}
