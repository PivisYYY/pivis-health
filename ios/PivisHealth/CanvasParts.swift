import SwiftUI

// MARK: - 开放画布的新零件（39 个）：服务器 resolve 之后的 JSON 按这里画（规格见 parts-spec.md）
// 只用灰阶：白 #FFF / 灰 #9A9A9A / 浅灰 #7A7A7A / 深灰 #4A4A4A / 线 #262626；细线、细体数字。
// 所有数都是服务器算好的，App 只决定颜色和位置。这些零件都不循环动（不用管 motionPaused）。

// MARK: - 解码

/// 跳过数组里一个坏元素用
struct CSkip: Decodable { init(from decoder: Decoder) throws {} }

extension KeyedDecodingContainer {
    /// 类型不对就当没有
    func lenient<T: Decodable>(_ type: T.Type, _ key: Key) -> T? {
        try? decodeIfPresent(T.self, forKey: key)
    }

    /// 字符串；写成数的也收（表格里的 7.0）
    func string(_ key: Key) -> String? {
        if let s = try? decodeIfPresent(String.self, forKey: key) { return s }
        if let v = try? decodeIfPresent(Double.self, forKey: key) { return pnum(v) }
        return nil
    }

    /// 数组：坏的元素丢掉，其余照用
    func lenientList<T: Decodable>(_ type: T.Type, _ key: Key) -> [T]? {
        guard var u = try? nestedUnkeyedContainer(forKey: key) else { return nil }
        var out: [T] = []
        while !u.isAtEnd {
            if let v = try? u.decode(T.self) { out.append(v) }
            else if (try? u.decode(CSkip.self)) == nil { break }
        }
        return out
    }

    /// 字符串数组：数也收，对象丢掉；一个都没有就当没有
    func lenientStrings(_ key: Key) -> [String]? {
        guard var u = try? nestedUnkeyedContainer(forKey: key) else { return nil }
        var out: [String] = []
        while !u.isAtEnd {
            if let s = try? u.decode(String.self) { out.append(s) }
            else if let v = try? u.decode(Double.self) { out.append(pnum(v)) }
            else if (try? u.decode(CSkip.self)) == nil { break }
        }
        return out.isEmpty ? nil : out
    }

    /// 数列：位置要对齐（雷达的维度、走势的天），坏的 / null 记成 nil
    func lenientNumbers(_ key: Key) -> [Double?]? {
        guard var u = try? nestedUnkeyedContainer(forKey: key) else { return nil }
        var out: [Double?] = []
        while !u.isAtEnd {
            if let v = try? u.decode(Double.self) { out.append(v) }
            else {
                out.append(nil)
                if (try? u.decode(CSkip.self)) == nil { break }
            }
        }
        return out
    }
}

/// table 的一行：格子是字符串，数也收
struct CRow: Decodable {
    var cells: [String] = []
    init(from decoder: Decoder) throws {
        var u = try decoder.unkeyedContainer()   // 不是数组（比如 zones 的行对象）就抛，交给 CItem
        while !u.isAtEnd {
            if let s = try? u.decode(String.self) { cells.append(s) }
            else if let v = try? u.decode(Double.self) { cells.append(pnum(v)) }
            else { cells.append(""); if (try? u.decode(CSkip.self)) == nil { break } }
        }
    }
}

/// dual_line 的一条线
struct CLine: Decodable {
    var label: String?
    var points: [Double?] = []
    var text: String?
    var unit: String?
    private enum K: String, CodingKey { case label, points, text, unit }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        label = c.string(.label)
        points = c.lenientNumbers(.points) ?? []
        text = c.string(.text)
        unit = c.lenient(String.self, .unit)
    }
}

/// dotstrip 的图例：{"on": "做了拉伸", "hi": "睡够 7 小时"}，哪个没给就不画哪个
struct CLegendPair: Decodable {
    var on: String?
    var hi: String?
    private enum K: String, CodingKey { case on, hi }
    init(from decoder: Decoder) {
        guard let c = try? decoder.container(keyedBy: K.self) else { return }
        on = c.string(.on)
        hi = c.string(.hi)
    }
}

/// 新零件的字段（和 CNode 读同一个 JSON 对象）。同名不同型的键分两个字段放：
/// rows（table 是二维字符串，其余是对象）、columns（table 是表头，stack_columns 是对象）、
/// points（sparkline 是数列，scatter 是点对）、from/to（time_range 是小时数，delta 是字符串）、
/// now（clock24 是数，radar 是数列）。
struct CPart {
    var title: String?
    var centerText: String?
    var centerSub: String?
    var keys: [String]?
    var axes: [String]?
    var legend: [String]?
    var legendPair: CLegendPair?   // dotstrip：legend 是对象（stack_columns 的是字符串数组）
    var subs: [String]?
    var columnNames: [String]?
    var columns: [CItem]?
    var tableRows: [[String]]?
    var rows: [CItem]?
    var pairs: [CItem]?
    var segments: [CItem]?
    var arcs: [CItem]?
    var dots: [CItem]?
    var ticks: [CItem]?
    var days: [CItem]?
    var bins: [CItem]?
    var band: CItem?
    var bands: [Double]?
    var marks: [Bool]?
    var points: [Double?]?
    var pointPairs: [[Double]]?
    var fit: [[Double]]?
    var last: [Double]?
    var xRange: [Double]?
    var yRange: [Double]?
    var xLabel: String?
    var yLabel: String?
    var a: CLine?
    var b: CLine?
    var start: String?
    var end: String?
    var totalMin: Double?
    var axisStart: Double?
    var axisHours: Double?
    var firstWeekday: Int?
    var count: Double?
    var best: Double?
    var direction: String?
    var moved: Bool?
    var good: Bool?
    var from: Double?
    var to: Double?
    var fromText: String?
    var toText: String?
    var maxAbs: Double?
    var target: Double?
    var targetLabel: String?
    var min: Double?
    var q1: Double?
    var median: Double?
    var q3: Double?
    var today: Double?
    var todayText: String?
    var value: Double?
    var total: Double?
    var done: Double?
    var current: Int?
    var strong: Int?
    var source: String?
    var url: String?
    var poster: String?
    var kind: String?
    var now: Double?
    var nowSeries: [Double?]?
    var prevSeries: [Double?]?
    var r: Double?           // scatter 的相关系数（只读给 VoiceOver）
    var asof: String?        // sparkline / stat_spark 最后一个点的日期
    var startMin: Double?    // response：轴从第几分钟开始（start 是数）
    var span: Double?        // response：轴有多少分钟
    var remind: Double?      // response：提醒在第几分钟

    private enum K: String, CodingKey {
        case title, centerText, centerSub, keys, axes, legend, subs, columns, rows, pairs, segments, arcs, dots, ticks
        case days, bins, band, bands, marks, points, fit, last, xRange, yRange, xLabel, yLabel, a, b, start, end
        case totalMin, axisStart, axisHours, firstWeekday, count, best, direction, moved, good, from, to
        case maxAbs, target, targetLabel, min, q1, median, q3, today, todayText, value, total, done, current
        case strong, source, url, poster, kind, now, prev, r, asof, span, remind
    }

    init() {}

    init(from decoder: Decoder) {
        guard let c = try? decoder.container(keyedBy: K.self) else { return }
        title = c.string(.title)
        centerText = c.string(.centerText)
        centerSub = c.string(.centerSub)
        keys = c.lenientStrings(.keys)
        axes = c.lenientStrings(.axes)
        legend = c.lenientStrings(.legend)
        if legend == nil { legendPair = c.lenient(CLegendPair.self, .legend) }
        subs = c.lenientStrings(.subs)
        columnNames = c.lenientStrings(.columns)
        if columnNames == nil { columns = c.lenientList(CItem.self, .columns) }
        tableRows = c.lenientList(CRow.self, .rows).flatMap { $0.isEmpty ? nil : $0.map(\.cells) }
        if tableRows == nil { rows = c.lenientList(CItem.self, .rows) }
        pairs = c.lenientList(CItem.self, .pairs)
        segments = c.lenientList(CItem.self, .segments)
        arcs = c.lenientList(CItem.self, .arcs)
        dots = c.lenientList(CItem.self, .dots)
        ticks = c.lenientList(CItem.self, .ticks)
        days = c.lenientList(CItem.self, .days)
        bins = c.lenientList(CItem.self, .bins)
        band = c.lenient(CItem.self, .band)
        bands = c.lenientNumbers(.bands)?.compactMap { $0 }
        marks = c.lenientList(Bool.self, .marks)
        pointPairs = c.lenientList([Double].self, .points).flatMap { $0.isEmpty ? nil : $0 }
        if pointPairs == nil { points = c.lenientNumbers(.points) }
        fit = c.lenientList([Double].self, .fit)
        last = c.lenient([Double].self, .last)
        xRange = c.lenient([Double].self, .xRange)
        yRange = c.lenient([Double].self, .yRange)
        xLabel = c.string(.xLabel)
        yLabel = c.string(.yLabel)
        a = c.lenient(CLine.self, .a)
        b = c.lenient(CLine.self, .b)
        start = c.string(.start)
        end = c.string(.end)
        totalMin = c.lenient(Double.self, .totalMin)
        axisStart = c.lenient(Double.self, .axisStart)
        axisHours = c.lenient(Double.self, .axisHours)
        firstWeekday = c.lenient(Double.self, .firstWeekday).map { Int($0.rounded()) }
        count = c.lenient(Double.self, .count)
        best = c.lenient(Double.self, .best)
        direction = c.lenient(String.self, .direction)
        moved = c.lenient(Bool.self, .moved)
        good = c.lenient(Bool.self, .good)
        if let v = c.lenient(Double.self, .from) { from = v } else { fromText = c.lenient(String.self, .from) }
        if let v = c.lenient(Double.self, .to) { to = v } else { toText = c.lenient(String.self, .to) }
        maxAbs = c.lenient(Double.self, .maxAbs)
        target = c.lenient(Double.self, .target)
        targetLabel = c.string(.targetLabel)
        min = c.lenient(Double.self, .min)
        q1 = c.lenient(Double.self, .q1)
        median = c.lenient(Double.self, .median)
        q3 = c.lenient(Double.self, .q3)
        today = c.lenient(Double.self, .today)
        todayText = c.string(.todayText)
        value = c.lenient(Double.self, .value)
        total = c.lenient(Double.self, .total)
        done = c.lenient(Double.self, .done)
        current = c.lenient(Double.self, .current).map { Int($0.rounded()) }
        strong = c.lenient(Double.self, .strong).map { Int($0.rounded()) }
        source = c.string(.source)
        url = c.lenient(String.self, .url)
        poster = c.lenient(String.self, .poster)
        kind = c.lenient(String.self, .kind)
        if let v = c.lenient(Double.self, .now) { now = v } else { nowSeries = c.lenientNumbers(.now) }
        prevSeries = c.lenientNumbers(.prev)
        r = c.lenient(Double.self, .r)
        asof = c.string(.asof)
        startMin = c.lenient(Double.self, .start)
        span = c.lenient(Double.self, .span)
        remind = c.lenient(Double.self, .remind)
    }
}

// MARK: - 共用

/// 整数不带小数，其余一位
func pnum(_ v: Double) -> String {
    abs(v - v.rounded()) < 0.005 ? String(Int(v.rounded())) : String(format: "%.1f", v)
}

/// 小时数 → HH:MM（21.17 → 21:10）
func phhmm(_ h: Double) -> String {
    let m = ((Int((h * 60).rounded()) % 1440) + 1440) % 1440
    return String(format: "%02d:%02d", m / 60, m % 60)
}

private func clamp(_ v: Double, _ lo: Double, _ hi: Double) -> Double { Swift.min(Swift.max(v, lo), hi) }

/// 占比零件依次用的档：实心几档灰，或只描边
enum Shade {
    case fill(Color), outline(Color)
    /// pie / donut：白、灰、深灰、线色、描边（规格写死的顺序）
    static let pie: [Shade] = [.fill(E.text), .fill(E.text2), .fill(E.grey4A), .fill(E.line), .outline(E.text3)]
    /// stack / stack_columns：细条上 #262626 几乎看不见，第四档改描边（设计稿）
    static let bar: [Shade] = [.fill(E.text), .fill(E.text2), .fill(E.grey4A), .outline(E.text3), .fill(E.line)]
    static func at(_ list: [Shade], _ i: Int) -> Shade { list[Swift.min(Swift.max(i, 0), list.count - 1)] }
}

/// 图例小方块
struct ShadeSwatch: View {
    let shade: Shade
    var size: CGFloat = 8
    var body: some View {
        switch shade {
        case .fill(let c):
            Rectangle().fill(c).frame(width: size, height: size)
                .overlay(Rectangle().strokeBorder(c == E.line ? E.grey4A : .clear, lineWidth: 1))
        case .outline(let c):
            Rectangle().strokeBorder(c, lineWidth: 1).frame(width: size, height: size)
        }
    }
}

private struct PTitle: View {
    let text: String?
    var body: some View {
        if let t = text, !t.isEmpty {
            Text(t).font(E.body(15)).foregroundStyle(E.text).fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct PCaption: View {
    let text: String?
    var body: some View {
        if let t = text, !t.isEmpty {
            Text(t).font(E.body(12)).foregroundStyle(E.text2).fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// 小一号的说明字（11pt #7A7A7A，和 dots / columns 的说明同一个样子）：split、dotstrip 用
private struct PNote: View {
    let text: String?
    var body: some View {
        if let t = text, !t.isEmpty {
            Text(t).font(E.body(11)).foregroundStyle(E.text3).fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct PLabel: View {
    let text: String?
    var body: some View {
        if let t = text, !t.isEmpty {
            Text(t).font(E.body(12)).foregroundStyle(E.text2).lineLimit(1).minimumScaleFactor(0.8)
        }
    }
}

private extension View {
    /// 整张图读成一句话
    func partLabel(_ head: [String?], _ body: [String] = [], _ tail: [String?] = []) -> some View {
        let all = head.compactMap { $0 } + body + tail.compactMap { $0 }
        return accessibilityElement(children: .ignore)
            .accessibilityLabel(all.filter { !$0.isEmpty }.joined(separator: "，"))
    }
}

private extension GraphicsContext {
    func fillRect(_ r: CGRect, _ c: Color) { fill(Path(r), with: .color(c)) }
    /// 描边画在矩形里面
    func strokeRect(_ r: CGRect, _ c: Color, _ w: CGFloat = 1, dash: [CGFloat] = []) {
        stroke(Path(r.insetBy(dx: w / 2, dy: w / 2)), with: .color(c), style: StrokeStyle(lineWidth: w, dash: dash))
    }
    func line(_ a: CGPoint, _ b: CGPoint, _ c: Color, _ w: CGFloat = 1, dash: [CGFloat] = [], cap: CGLineCap = .butt) {
        var p = Path()
        p.move(to: a)
        p.addLine(to: b)
        stroke(p, with: .color(c), style: StrokeStyle(lineWidth: w, lineCap: cap, dash: dash))
    }
    func dot(_ p: CGPoint, _ r: CGFloat, fill f: Color? = nil, stroke s: Color? = nil, _ w: CGFloat = 1, dash: [CGFloat] = []) {
        let rect = CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)
        if let f { fill(Path(ellipseIn: rect), with: .color(f)) }
        if let s { stroke(Path(ellipseIn: rect), with: .color(s), style: StrokeStyle(lineWidth: w, dash: dash)) }
    }
    func label(_ s: String, _ p: CGPoint, _ anchor: UnitPoint = .center, size: CGFloat = 9, color: Color = E.text3) {
        draw(Text(s).font(E.body(size)).monospacedDigit().foregroundStyle(color), at: p, anchor: anchor)
    }
    func shadeRect(_ r: CGRect, _ shade: Shade) {
        switch shade {
        case .fill(let c): fillRect(r, c)
        case .outline(let c): strokeRect(r, c)
        }
    }
}

/// 小折线：每天一个点，缺的天跳过去连上；返回路径和最后一个点。
/// 纵向至少按「数值水平 × minRel」的跨度画，55–57 这种几乎没动的线就画得几乎平，不会被拉成满格锯齿。
private func seriesPath(_ vals: [Double?], in r: CGRect, minRel: Double = 0.1) -> (Path, CGPoint?) {
    let nums = vals.compactMap { $0 }
    guard let lo = nums.min(), let hi = nums.max() else { return (Path(), nil) }
    let mid = (lo + hi) / 2
    let span = Swift.max(hi - lo, abs(mid) * minRel, 1e-9)
    let step = vals.count > 1 ? r.width / CGFloat(vals.count - 1) : 0
    var p = Path()
    var last: CGPoint?
    for (i, v) in vals.enumerated() {
        guard let v else { continue }
        let pt = CGPoint(x: r.minX + CGFloat(i) * step, y: r.midY + CGFloat((mid - v) / span) * r.height)
        if last == nil { p.move(to: pt) } else { p.addLine(to: pt) }
        last = pt
    }
    return (p, last)
}

/// 横排 x 轴标签：条目多就隔一个写一个（从最后一个往回数，保证最近那天有字）
private func showLabel(_ i: Int, _ count: Int, every: Int) -> Bool { (count - 1 - i) % every == 0 }

private struct AxisLabels: View {
    let labels: [String]
    var highlight: [Bool] = []
    var every = 1
    var hi: Color = E.text2
    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(labels.enumerated()), id: \.offset) { i, l in
                Text(showLabel(i, labels.count, every: every) ? l : "")
                    .font(E.body(9)).monospacedDigit()
                    .foregroundStyle(i < highlight.count && highlight[i] ? hi : E.text3)
                    .lineLimit(1)
                    .fixedSize()                 // 隔一个写一个时字可以伸进旁边的空位，字号统一
                    .frame(maxWidth: .infinity)
            }
        }
    }
}

/// 按比例分列宽的一行（table：第一列宽一点）
struct WeightedRow: Layout {
    var weights: [CGFloat]
    var spacing: CGFloat = 8

    private func widths(_ total: CGFloat, _ n: Int) -> [CGFloat] {
        let ws = (0..<n).map { $0 < weights.count ? weights[$0] : 1 }
        let sum = ws.reduce(0, +)
        let avail = Swift.max(0, total - spacing * CGFloat(Swift.max(n - 1, 0)))
        return ws.map { sum > 0 ? avail * $0 / sum : 0 }
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let total = proposal.width ?? 280
        let cw = widths(total, subviews.count)
        let h = subviews.indices.map { subviews[$0].sizeThatFits(ProposedViewSize(width: cw[$0], height: nil)).height }.max() ?? 0
        return CGSize(width: total, height: h)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let cw = widths(bounds.width, subviews.count)
        var x = bounds.minX
        for i in subviews.indices {
            subviews[i].place(at: CGPoint(x: x, y: bounds.minY), anchor: .topLeading,
                              proposal: ProposedViewSize(width: cw[i], height: nil))
            x += cw[i] + spacing
        }
    }
}

// MARK: - 占比与构成

/// pie / donut：几块各占多少。donut（或带 center_text 的 pie）画成环，中间放最重要那块。
struct PiePart: View {
    let n: CNode

    var body: some View {
        let items = Array((n.items ?? []).prefix(5))
        let vals = items.map { Swift.max(0, $0.value ?? $0.pct ?? 0) }
        let sum = vals.reduce(0, +)
        let fracs = vals.map { sum > 0 ? $0 / sum : 0 }
        let ring = n.t == "donut" || n.x.centerText != nil
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 20) {
                ZStack {
                    Canvas { ctx, size in
                        if ring { Self.drawRing(ctx, size, fracs) } else { Self.drawPie(ctx, size, fracs) }
                    }
                    if ring {
                        VStack(spacing: 0) {
                            if let t = n.x.centerText {
                                Text(t).font(E.light(24)).foregroundStyle(E.text).monospacedDigit()
                                    .lineLimit(1).minimumScaleFactor(0.6)
                            }
                            if let s = n.x.centerSub {
                                Text(s).font(E.body(12)).foregroundStyle(E.text2).lineLimit(1).minimumScaleFactor(0.8)
                            }
                        }
                        .frame(width: 70)
                    }
                }
                .frame(width: 120, height: 120)
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                        HStack(spacing: 6) {
                            ShadeSwatch(shade: Shade.at(Shade.pie, i))
                            Text(legend(it, fracs[i])).font(E.body(12)).foregroundStyle(E.text2).monospacedDigit()
                                .lineLimit(1).minimumScaleFactor(0.8)
                        }
                    }
                }
            }
            PCaption(text: n.caption)
        }
        .partLabel([n.x.centerText.map { "中间 \($0) \(n.x.centerSub ?? "")" }],
                   items.enumerated().map { "\($1.label ?? "") \(pctText($1, fracs[$0])) \($1.text ?? "")" },
                   [n.caption])
    }

    private func pctText(_ it: CItem, _ f: Double) -> String { "\(Int((it.pct ?? f * 100).rounded()))%" }
    private func legend(_ it: CItem, _ f: Double) -> String { "\(it.label ?? "") \(pctText(it, f))" }

    private static func drawPie(_ ctx: GraphicsContext, _ size: CGSize, _ fracs: [Double]) {
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let r = Swift.min(size.width, size.height) / 2 - 8
        var a = -90.0
        var wedges: [(Path, Shade)] = []
        for (i, f) in fracs.enumerated() where f > 0 {
            var p = Path()
            p.move(to: c)
            p.addArc(center: c, radius: r, startAngle: .degrees(a), endAngle: .degrees(a + f * 360), clockwise: false)
            p.closeSubpath()
            wedges.append((p, Shade.at(Shade.pie, i)))
            a += f * 360
        }
        for (p, s) in wedges {
            if case .fill(let col) = s { ctx.fill(p, with: .color(col)) }
        }
        if wedges.count > 1 {
            for (p, _) in wedges { ctx.stroke(p, with: .color(.black), lineWidth: 2) }
        }
        for (p, s) in wedges {
            if case .outline(let col) = s { ctx.stroke(p, with: .color(col), lineWidth: 1) }
        }
    }

    private static func drawRing(_ ctx: GraphicsContext, _ size: CGSize, _ fracs: [Double]) {
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let r = Swift.min(size.width, size.height) / 2 - 14
        let lw: CGFloat = 9
        let gap = fracs.filter { $0 > 0 }.count > 1 ? 1.5 : 0
        var a = -90.0
        for (i, f) in fracs.enumerated() where f > 0 {
            let s = a + gap, e = a + f * 360 - gap
            a += f * 360
            guard e > s else { continue }
            switch Shade.at(Shade.pie, i) {
            case .fill(let col):
                var p = Path()
                p.addArc(center: c, radius: r, startAngle: .degrees(s), endAngle: .degrees(e), clockwise: false)
                ctx.stroke(p, with: .color(col), lineWidth: lw)
            case .outline(let col):
                for rr in [r - lw / 2 + 0.5, r + lw / 2 - 0.5] {
                    var p = Path()
                    p.addArc(center: c, radius: rr, startAngle: .degrees(s), endAngle: .degrees(e), clockwise: false)
                    ctx.stroke(p, with: .color(col), lineWidth: 1)
                }
            }
        }
    }
}

/// stack：一条横向堆叠条讲清一个整体的构成，下面一排数
struct StackPart: View {
    let n: CNode

    var body: some View {
        let items = Array((n.items ?? []).prefix(5))
        let vals = items.map { Swift.max(0, $0.value ?? 0) }
        let sum = vals.reduce(0, +)
        let raw = items.enumerated().map { i, it in it.frac ?? (sum > 0 ? vals[i] / sum : 0) }
        let fsum = raw.reduce(0, +)
        let fracs = raw.map { fsum > 1 ? $0 / fsum : $0 }
        VStack(alignment: .leading, spacing: 6) {
            PTitle(text: n.x.title)
            Canvas { ctx, size in
                let gap: CGFloat = 2
                let usable = size.width - gap * CGFloat(Swift.max(fracs.count - 1, 0))
                var x: CGFloat = 0
                for (i, f) in fracs.enumerated() {
                    let w = usable * CGFloat(f)
                    if w > 0.5 { ctx.shadeRect(CGRect(x: x, y: 1, width: w, height: 10), Shade.at(Shade.bar, i)) }
                    x += w + gap
                }
            }
            .frame(height: 12)
            HStack(alignment: .top, spacing: 8) {
                ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(it.text ?? pnum(vals[i])).font(E.light(18)).foregroundStyle(E.text).monospacedDigit()
                            .lineLimit(1).minimumScaleFactor(0.6)
                        Text(it.label ?? "").font(E.body(12)).foregroundStyle(E.text2).lineLimit(1).minimumScaleFactor(0.7)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            PCaption(text: n.caption)
        }
        .partLabel([n.x.title], items.map { "\($0.label ?? "") \($0.text ?? "")" }, [n.caption])
    }
}

/// stack_columns：每天一根柱，柱里自下而上是各部分；短横线 = 当晚参照（需要睡多久）
struct StackColumnsPart: View {
    let n: CNode

    var body: some View {
        let cols = n.x.columns ?? []
        let keys = n.x.keys ?? []
        let h: CGFloat = n.height == "m" ? 150 : 110
        let peak = cols.map { c in Swift.max((c.parts ?? []).reduce(0, +), c.ref ?? 0) }.max() ?? 0
        let top = Swift.max(n.max ?? 0, peak, 0.0001) * 1.06
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let W = size.width
                let base = h - 0.5
                ctx.line(CGPoint(x: 0, y: base), CGPoint(x: W, y: base), E.line)
                let slot = W / CGFloat(Swift.max(cols.count, 1))
                let bw = Swift.min(14, slot * 0.42)
                let scale = (h - 2) / CGFloat(top)
                for (i, col) in cols.enumerated() {
                    let cx = slot * (CGFloat(i) + 0.5)
                    var y = h - 1
                    for (k, v) in (col.parts ?? []).enumerated() where v > 0 {
                        let ph = CGFloat(v) * scale
                        let r = CGRect(x: cx - bw / 2, y: y - ph + (k > 0 ? 1 : 0), width: bw, height: Swift.max(0.5, ph - (k > 0 ? 1 : 0)))
                        ctx.shadeRect(r, Shade.at(Shade.bar, k))
                        y -= ph
                    }
                    if let ref = col.ref {
                        let ry = h - 1 - CGFloat(ref) * scale
                        let half = Swift.min(10, slot * 0.36)
                        ctx.line(CGPoint(x: cx - half, y: ry), CGPoint(x: cx + half, y: ry), col.now == true ? E.text : E.text2)
                    }
                }
            }
            .frame(height: h)
            AxisLabels(labels: cols.map { $0.label ?? "" }, highlight: cols.map { $0.now == true },
                       every: cols.count > 5 ? 2 : 1)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    PCaption(text: n.caption).fixedSize()
                    Spacer(minLength: 8)
                    legend(keys)
                }
                VStack(alignment: .leading, spacing: 4) {
                    legend(keys)
                    PCaption(text: n.caption)
                }
            }
        }
        .partLabel([n.caption], cols.map { c in
            "\(c.label ?? "") " + zip(keys, c.parts ?? []).map { "\($0) \(pnum($1))" }.joined(separator: " ")
                + (c.ref.map { "，参照 \(pnum($0))" } ?? "")
        })
    }

    private func legend(_ keys: [String]) -> some View {
        HStack(spacing: 8) {
            ForEach(Array(keys.enumerated()), id: \.offset) { i, k in
                HStack(spacing: 4) {
                    ShadeSwatch(shade: Shade.at(Shade.bar, i), size: 7)
                    Text(k).font(E.body(10)).foregroundStyle(E.text3).lineLimit(1)
                }
                .fixedSize()
            }
        }
    }
}

/// waffle：每格一天，实心 = 做到了；每行 10 格
struct WafflePart: View {
    let n: CNode

    var body: some View {
        let cells = (n.items ?? []).map { $0.on == true }
        let rows = Swift.max(1, Int((Double(cells.count) / 10).rounded(.up)))
        VStack(alignment: .leading, spacing: 8) {
            Canvas { ctx, _ in
                for (i, on) in cells.enumerated() {
                    let r = CGRect(x: CGFloat(i % 10) * 24, y: CGFloat(i / 10) * 24, width: 18, height: 18)
                    if on { ctx.fillRect(r, E.text) } else { ctx.strokeRect(r, E.grey3A) }
                }
            }
            .frame(width: 234, height: CGFloat(rows) * 24 - 6)
            PCaption(text: n.caption)
        }
        .partLabel([n.caption ?? "\(cells.filter { $0 }.count) / \(cells.count) 天做到了"])
    }
}

/// zones：一次训练在 5 个心率区间各停了多久
struct ZonesPart: View {
    let n: CNode

    var body: some View {
        let rows = n.x.rows ?? []
        let top = Swift.max(n.max ?? 0, rows.compactMap(\.minutes).max() ?? 0, 0.0001)
        VStack(alignment: .leading, spacing: 10) {
            PTitle(text: n.x.title)
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { i, r in
                    HStack(spacing: 10) {
                        Text(r.label ?? "").font(E.body(12)).foregroundStyle(E.text2)
                            .lineLimit(1).minimumScaleFactor(0.7)
                            .frame(width: 58, alignment: .leading)
                        Canvas { ctx, size in
                            let w = size.width * CGFloat((r.minutes ?? 0) / top)
                            if w > 0 { ctx.fillRect(CGRect(x: 0, y: 0, width: Swift.max(1, w), height: 6), Self.shade(i)) }
                        }
                        .frame(height: 6)
                        Text(r.text ?? r.minutes.map { "\(pnum($0))′" } ?? "")
                            .font(E.body(12)).foregroundStyle(E.text).monospacedDigit()
                            .lineLimit(1).frame(width: 30, alignment: .leading)
                    }
                }
            }
        }
        .partLabel([n.x.title], rows.map { "\($0.label ?? "") \($0.text ?? "")" })
    }

    /// 越吃力越亮：Z1 深灰、Z2 灰、Z3 起白
    private static func shade(_ i: Int) -> Color { i == 0 ? E.grey4A : (i == 1 ? E.text2 : E.text) }
}

/// split：两组（最多三组）比一比，比如平常的恢复 vs 外宿后的恢复。
/// 每行：名字（52）| 条（剩下的宽度）| 数（44，右对齐）；hi 那组条和字是白的，其余条 #555、字灰
struct SplitPart: View {
    let n: CNode

    var body: some View {
        let rows = Array((n.x.rows ?? []).prefix(3))
        VStack(alignment: .leading, spacing: 10) {
            ForEach(rows) { r in
                let hi = r.hi == true
                HStack(spacing: 10) {
                    Text(r.label ?? "").font(E.body(12)).foregroundStyle(hi ? E.text : E.text2)
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .frame(width: 52, alignment: .leading)
                    Canvas { ctx, size in
                        let track = CGRect(x: 0, y: 0, width: size.width, height: 6)
                        ctx.fill(Path(roundedRect: track, cornerRadius: 3), with: .color(E.line2))
                        if let f = r.frac ?? r.fraction, f > 0 {
                            let w = size.width * CGFloat(clamp(f, 0, 1))
                            ctx.fill(Path(roundedRect: CGRect(x: 0, y: 0, width: w, height: 6), cornerRadius: Swift.min(3, w / 2)),
                                     with: .color(hi ? E.text : E.grey55))
                        }
                    }
                    .frame(height: 6)
                    Text((r.text ?? "") + (r.text == nil ? "" : (r.unit ?? "")))
                        .font(E.body(12)).foregroundStyle(hi ? E.text : E.text2).monospacedDigit()
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .frame(width: 44, alignment: .trailing)
                }
            }
            PNote(text: n.caption)
        }
        .partLabel([], rows.map { "\($0.label ?? "") \($0.text ?? "")\($0.text == nil ? "" : ($0.unit ?? ""))" }, [n.caption])
    }
}

/// radar：五维这周（实线）vs 上周（虚线）；缺的那维画虚点
struct RadarPart: View {
    let n: CNode

    var body: some View {
        let axes = n.x.axes ?? ["睡眠", "恢复", "运动", "压力", "习惯"]
        let now = n.x.nowSeries ?? []
        let prev = n.x.prevSeries ?? []
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let k = axes.count
                guard k >= 3 else { return }
                let c = CGPoint(x: size.width / 2, y: 90)
                let R: CGFloat = 66
                func pt(_ i: Int, _ f: Double) -> CGPoint {
                    let a = (-90 + 360 * Double(i) / Double(k)) * .pi / 180
                    return CGPoint(x: c.x + R * CGFloat(f * cos(a)), y: c.y + R * CGFloat(f * sin(a)))
                }
                func poly(_ vals: [Double?]) -> Path {
                    var p = Path()
                    let pts = (0..<k).compactMap { i in i < vals.count ? vals[i].map { pt(i, clamp($0, 0, 100) / 100) } : nil }
                    if let f = pts.first { p.move(to: f); p.addLines(pts); p.closeSubpath() }
                    return p
                }
                for f in [1.0, 0.5] {
                    var g = Path()
                    g.move(to: pt(0, f))
                    for i in 1..<k { g.addLine(to: pt(i, f)) }
                    g.closeSubpath()
                    ctx.stroke(g, with: .color(E.line), lineWidth: 1)
                }
                for i in 0..<k { ctx.line(c, pt(i, 1), E.line) }
                if !prev.isEmpty {
                    ctx.stroke(poly(prev), with: .color(E.text3), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                }
                let p = poly(now)
                ctx.fill(p, with: .color(Color.white.opacity(0.12)))
                ctx.stroke(p, with: .color(E.text), style: StrokeStyle(lineWidth: 1.2, lineJoin: .round))
                for i in 0..<k where i >= now.count || now[i] == nil {
                    ctx.dot(pt(i, 0.5), 3, fill: .black, stroke: E.text3, 1, dash: [1.5, 1.5])
                }
                for (i, name) in axes.enumerated() {
                    let a = (-90 + 360 * Double(i) / Double(k)) * .pi / 180
                    let lp = CGPoint(x: c.x + (R + 15) * CGFloat(cos(a)), y: c.y + (R + 13) * CGFloat(sin(a)) + (i == 0 ? 2 : 0))
                    let missing = i >= now.count || now[i] == nil
                    ctx.label(name, lp, .center, size: 10, color: missing ? E.text3 : E.text2)
                }
            }
            .frame(height: 172)
            PCaption(text: n.caption)
        }
        .partLabel([], axes.enumerated().map { i, a in
            let v = i < now.count ? now[i].map { pnum($0) } ?? "没数据" : "没数据"
            let p = i < prev.count ? prev[i].map { "，上周 \(pnum($0))" } ?? "" : ""
            return "\(a) 这周 \(v)\(p)"
        }, [n.caption])
    }
}

// MARK: - 时间与作息

/// hypnogram：一整晚在清醒 / REM / 浅睡 / 深睡之间怎么走
struct HypnogramPart: View {
    let n: CNode

    static func level(_ s: String?) -> Int? {
        switch s?.lowercased() {
        case "wake", "awake": return 0
        case "rem": return 1
        case "light", "core", "asleep": return 2
        case "deep": return 3
        default: return nil
        }
    }

    var body: some View {
        let segs = (n.x.segments ?? []).filter { Self.level($0.stage) != nil && $0.from != nil && $0.to != nil }
            .sorted { ($0.from ?? 0) < ($1.from ?? 0) }
        let total = Swift.max(n.x.totalMin ?? segs.compactMap(\.to).max() ?? 1, 1)
        Canvas { ctx, size in
            let x0: CGFloat = 28
            let pw = size.width - x0
            let ys: [CGFloat] = [9, 31, 53, 75]
            for (i, name) in ["清醒", "REM", "浅睡", "深睡"].enumerated() {
                ctx.label(name, CGPoint(x: 0, y: ys[i]), .leading)
            }
            ctx.line(CGPoint(x: x0, y: 86.5), CGPoint(x: size.width, y: 86.5), E.line)
            func x(_ m: Double) -> CGFloat { x0 + CGFloat(clamp(m / total, 0, 1)) * pw }
            var p = Path()
            var prevY: CGFloat?
            for s in segs {
                guard let lv = Self.level(s.stage), let f = s.from, let t = s.to else { continue }
                let y = ys[lv]
                if let py = prevY {
                    p.addLine(to: CGPoint(x: x(f), y: py))
                    p.addLine(to: CGPoint(x: x(f), y: y))
                } else {
                    p.move(to: CGPoint(x: x(f), y: y))
                }
                p.addLine(to: CGPoint(x: x(t), y: y))
                prevY = y
            }
            ctx.stroke(p, with: .color(E.text), style: StrokeStyle(lineWidth: 1.4, lineJoin: .round))
            if let s = n.x.start { ctx.label(s, CGPoint(x: x0, y: 99), .leading) }
            if let e = n.x.end { ctx.label(e, CGPoint(x: size.width, y: 99), .trailing) }
        }
        .frame(height: 106)
        .partLabel(["睡眠阶梯 \(n.x.start ?? "")–\(n.x.end ?? "")",
                    n.x.totalMin.map { "共 \(Int($0) / 60) 小时 \(Int($0) % 60) 分" },
                    "醒了 \(segs.filter { Self.level($0.stage) == 0 }.count) 次"])
    }
}

/// sleep_window：每晚一条从上床到起床；浅色带 = 窗口（CBT-I）
struct SleepWindowPart: View {
    let n: CNode

    var body: some View {
        let rows = n.x.rows ?? []
        let hours = Swift.max(n.x.axisHours ?? 12, 1)
        let plotH = CGFloat(rows.count) * 14 + 4
        let ticks: [CItem] = n.x.ticks ?? []
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let x0: CGFloat = 32
                let pw = size.width - x0 - 2
                func x(_ h: Double) -> CGFloat { x0 + CGFloat(clamp(h, 0, hours) / hours) * pw }
                if let b = n.x.band, let f = b.from, let t = b.to {
                    ctx.fillRect(CGRect(x: x(f), y: 2, width: x(t) - x(f), height: plotH - 2), Color.white.opacity(0.06))
                    for v in [f, t] {
                        ctx.line(CGPoint(x: x(v), y: 2), CGPoint(x: x(v), y: plotH), E.text3, dash: [2, 3])
                    }
                }
                let band: (Double, Double)? = n.x.band.flatMap { b in b.from.flatMap { f in b.to.map { (f, $0) } } }
                for (i, r) in rows.enumerated() {
                    let y = 10 + CGFloat(i) * 14
                    ctx.label(r.label ?? "", CGPoint(x: 0, y: y), .leading, color: r.now == true ? E.text2 : E.text3)
                    guard let f = r.from, let t = r.to else { continue }
                    if let (bf, bt) = band {
                        // 有窗口（CBT-I）：窗口里的那段是灰的细线，出了窗口的那截（早上床 / 起晚）是白的粗线，破例一眼看得到
                        ctx.line(CGPoint(x: x(f), y: y), CGPoint(x: x(t), y: y), E.text3, 3, cap: .round)
                        // 服务器标了 early / late 就按它（起床晚 15 分钟内算守住）；没标就按出没出窗口
                        if r.early ?? (f < bf), f < bf { ctx.line(CGPoint(x: x(f), y: y), CGPoint(x: x(Swift.min(t, bf)), y: y), E.text, 4, cap: .round) }
                        if r.late ?? (t > bt), t > bt { ctx.line(CGPoint(x: x(Swift.max(f, bt)), y: y), CGPoint(x: x(t), y: y), E.text, 4, cap: .round) }
                    } else {
                        ctx.line(CGPoint(x: x(f), y: y), CGPoint(x: x(t), y: y), E.text, 4, cap: .round)
                    }
                }
                for (i, t) in ticks.enumerated() {
                    guard let at = t.at else { continue }
                    let anchor: UnitPoint = i == 0 ? .leading : (i == ticks.count - 1 ? .trailing : .center)
                    ctx.label(t.label ?? "", CGPoint(x: x(at), y: plotH + 9), anchor)
                }
            }
            .frame(height: plotH + 16)
            PCaption(text: n.x.band?.label.map { "浅色带 = \($0)" })
            PCaption(text: n.caption)
        }
        .partLabel([n.x.band?.label], rows.map { "\($0.label ?? "") \($0.start ?? "") 到 \($0.end ?? "")" }, [n.caption])
    }
}

/// response：提醒发出后几点真去做了。虚线 = 提醒的时刻，每个白点 = 一次真去做的时刻。
/// 所有值都是同一条轴上的分钟（过了午夜接着往上数，可以超过 1440）；轴 = start 起 span 分钟
struct ResponsePart: View {
    let n: CNode

    var body: some View {
        let start = n.x.startMin ?? 0
        let span = Swift.max(n.x.span ?? 0, 1)
        let points = (n.x.points ?? []).compactMap { $0 }
        let ticks: [CItem] = n.x.ticks ?? []
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let W = size.width
                func x(_ m: Double) -> CGFloat { 6 + CGFloat(clamp((m - start) / span, 0, 1)) * (W - 12) }
                // 底线
                ctx.line(CGPoint(x: 0, y: 54.5), CGPoint(x: W, y: 54.5), E.stroke)
                // 提醒：一条竖虚线，上面写 label（靠边时往里挪，不出界）
                if let r = n.x.remind {
                    let rx = x(r)
                    ctx.line(CGPoint(x: rx, y: 14), CGPoint(x: rx, y: 50), E.text2, dash: [3, 3])
                    if let l = n.label, !l.isEmpty {
                        let rt = ctx.resolve(Text(l).font(E.body(10.5)).foregroundStyle(E.text2))
                        let w = rt.measure(in: size).width
                        ctx.draw(rt, at: CGPoint(x: Swift.min(Swift.max(rx, w / 2), W - w / 2), y: 7.5), anchor: .center)
                    }
                }
                // 每次真去做的时刻
                for p in points { ctx.dot(CGPoint(x: x(p), y: 32), 3.5, fill: E.text) }
                // 刻度：第一个左对齐，其余居中（最后一个出界就贴右）
                for (i, t) in ticks.enumerated() {
                    guard let at = t.at, let l = t.label, !l.isEmpty else { continue }
                    let rt = ctx.resolve(Text(l).font(E.body(10.5)).monospacedDigit().foregroundStyle(E.text3))
                    let tx = x(at)
                    if i == 0 {
                        ctx.draw(rt, at: CGPoint(x: tx, y: 65), anchor: .leading)
                    } else {
                        let w = rt.measure(in: size).width
                        if tx + w / 2 > W { ctx.draw(rt, at: CGPoint(x: W, y: 65), anchor: .trailing) }
                        else { ctx.draw(rt, at: CGPoint(x: tx, y: 65), anchor: .center) }
                    }
                }
            }
            .frame(height: 74)
            PCaption(text: n.caption)
        }
        .partLabel([n.x.remind.map { "\(n.label ?? "提醒") \(Self.hhmm($0))" }],
                   points.isEmpty ? [] : ["\(points.count) 次：" + points.map(Self.hhmm).joined(separator: "、")],
                   [n.caption])
    }

    /// 轴上的分钟 → HH:MM（1445 → 00:05）
    private static func hhmm(_ m: Double) -> String { phhmm(m / 60) }
}

/// dots 超过 14 个（15–30 天）：点变小、间距收窄，一排铺得下。实心 = 做到了；空心 = 没做到；今天 = 白圈 + 中间一点
struct DenseDots: View {
    let items: [CItem]

    var body: some View {
        let n = items.count
        let base: CGFloat = n <= 21 ? 8 : 6
        Canvas { ctx, size in
            // 先按原来的比例排（间距 = 点的 0.7）；放不下就收间距，还放不下再缩点
            var d = base
            var gap = n > 1 ? Swift.min(d * 0.7, (size.width - CGFloat(n) * d) / CGFloat(n - 1)) : 0
            if gap < 1.5 {
                gap = 1.5
                d = Swift.max(3, (size.width - gap * CGFloat(n - 1)) / CGFloat(n))
            }
            let r = d / 2
            for (i, it) in items.enumerated() {
                let c = CGPoint(x: r + CGFloat(i) * (d + gap), y: size.height / 2)
                if it.on == true {
                    ctx.dot(c, r, fill: E.text)
                } else {
                    ctx.dot(c, r - 0.5, stroke: it.now == true ? E.text : E.text3)     // 描边画在圈里面
                    if it.now == true { ctx.dot(c, Swift.max(1, d * 0.15), fill: E.text) }
                }
            }
        }
        .frame(height: base)
        .frame(maxWidth: .infinity)
    }
}

/// dotstrip：每天一个点（最多 90 天），一行最多 14 个、满了换行。
/// 实心白点 = 那天做了（on）；空心 #555 圈 = 没做；点下面一道白短线 = 那天结果好（hi）。每行下面写这一行的第一天和最后一天
struct DotStripPart: View {
    let n: CNode
    private static let perRow = 14
    private static let d: CGFloat = 8

    var body: some View {
        let items = Array((n.items ?? []).prefix(90))
        let rows = stride(from: 0, to: items.count, by: Self.perRow).map { Array(items[$0..<Swift.min($0 + Self.perRow, items.count)]) }
        let legOn = n.x.legendPair?.on.flatMap { $0.isEmpty ? nil : $0 }
        let legHi = n.x.legendPair?.hi.flatMap { $0.isEmpty ? nil : $0 }
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    stripRow(row)
                }
            }
            if legOn != nil || legHi != nil {
                HStack(spacing: 14) {
                    if let legOn {
                        HStack(spacing: 6) {
                            Circle().fill(E.text).frame(width: Self.d, height: Self.d)
                            PNote(text: legOn)
                        }
                    }
                    if let legHi {
                        HStack(spacing: 6) {
                            Rectangle().fill(E.text).frame(width: Self.d, height: 2)
                            PNote(text: legHi)
                        }
                    }
                }
            }
            PNote(text: n.caption)
        }
        .partLabel([n.caption],
                   [legOn.map { "\($0) \(items.filter { $0.on == true }.count) 天" } ?? "做了 \(items.filter { $0.on == true }.count) 天",
                    legHi.map { "\($0) \(items.filter { $0.hi == true }.count) 天" } ?? ""],
                   ["共 \(items.count) 天"])
    }

    /// 一行：点 + 短线 + 这一行的头尾日期。点的位置按一行 14 个排（不满 14 个的行也对齐上一行的列）
    private func stripRow(_ row: [CItem]) -> some View {
        let first = row.first?.label.flatMap { $0.isEmpty ? nil : $0 }
        let last = row.count > 1 ? row.last?.label.flatMap { $0.isEmpty ? nil : $0 } : nil
        let labeled = first != nil || last != nil
        let d = Self.d
        return Canvas { ctx, size in
            let step = (size.width - d) / CGFloat(Self.perRow - 1)
            func cx(_ i: Int) -> CGFloat { d / 2 + CGFloat(i) * step }
            for (i, it) in row.enumerated() {
                let c = CGPoint(x: cx(i), y: d / 2)
                if it.on == true { ctx.dot(c, d / 2, fill: E.text) }
                else { ctx.dot(c, d / 2 - 0.5, stroke: E.grey55) }        // 1pt 的圈画在点的范围里面
                if it.hi == true { ctx.fillRect(CGRect(x: c.x - d / 2, y: d + 3, width: d, height: 2), E.text) }
            }
            guard labeled else { return }
            let y: CGFloat = d + 3 + 2 + 10
            var firstEnd: CGFloat = -1
            if let first {
                let rt = ctx.resolve(Text(first).font(E.body(11)).monospacedDigit().foregroundStyle(E.text3))
                firstEnd = rt.measure(in: size).width
                ctx.draw(rt, at: CGPoint(x: 0, y: y), anchor: .leading)
            }
            if let last {
                // 最后一天写在最后一个点下面（贴右边不出界）；和第一天挤到一起就不写
                let rt = ctx.resolve(Text(last).font(E.body(11)).monospacedDigit().foregroundStyle(E.text3))
                let w = rt.measure(in: size).width
                let x = Swift.min(cx(row.count - 1), size.width - w / 2)
                if x - w / 2 >= firstEnd + 6 { ctx.draw(rt, at: CGPoint(x: x, y: y), anchor: .center) }
            }
        }
        .frame(height: labeled ? d + 3 + 2 + 18 : d + 3 + 2)
    }
}

/// clock24：一天 24 小时一圈，睡眠 / 训练是弧，待办是点，指针 = 现在
struct Clock24Part: View {
    let n: CNode

    var body: some View {
        let arcs = n.x.arcs ?? []
        let dots = n.x.dots ?? []
        HStack(alignment: .center, spacing: 16) {
            Canvas { ctx, size in
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                let r: CGFloat = 56
                func ang(_ h: Double) -> Angle { .degrees(h / 24 * 360 - 90) }
                func pt(_ h: Double, _ rr: CGFloat) -> CGPoint {
                    let a = ang(h).radians
                    return CGPoint(x: c.x + rr * CGFloat(cos(a)), y: c.y + rr * CGFloat(sin(a)))
                }
                ctx.stroke(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r)),
                           with: .color(E.line), lineWidth: 6)
                for a in arcs {
                    guard let f = a.from, var t = a.to else { continue }
                    if t < f { t += 24 }
                    var p = Path()
                    p.addArc(center: c, radius: r, startAngle: ang(f), endAngle: ang(t), clockwise: false)
                    ctx.stroke(p, with: .color(Self.color(a.kind)), lineWidth: 6)
                }
                for d in dots {   // 待办：做了实心，没做空心
                    guard let at = d.at else { continue }
                    ctx.dot(pt(at, r), 3, fill: d.done == true ? E.text : .black, stroke: E.text, 1.2)
                }
                if let now = n.x.now {
                    ctx.line(c, pt(now, r - 12), E.text)
                    ctx.dot(c, 2, fill: E.text)
                }
                for h in [0.0, 6, 12, 18] { ctx.label(pnum(h), pt(h, r + 11)) }
            }
            .frame(width: 148, height: 148)
            VStack(alignment: .leading, spacing: 6) {
                ForEach(arcs) { a in
                    arcLegend(a.label ?? "")
                }
                ForEach(dots) { d in
                    Text((d.done == true ? "● " : "○ ") + (d.label ?? "")).font(E.body(12)).foregroundStyle(E.text2).monospacedDigit()
                        .lineLimit(1).minimumScaleFactor(0.75)
                }
                if let now = n.x.now {
                    Text("指针 = 现在 \(phhmm(now))").font(E.body(12)).foregroundStyle(E.text2).monospacedDigit()
                        .lineLimit(1).minimumScaleFactor(0.75)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
        .partLabel(arcs.map(\.label) + dots.map { d in d.label.map { $0 + (d.done == true ? "，做了" : "") } }
                   + [n.x.now.map { "现在 \(phhmm($0))" }])
    }

    /// 「睡眠 00:08–07:12」：名字白，时间灰
    private func arcLegend(_ s: String) -> some View {
        let parts = s.split(separator: " ", maxSplits: 1).map(String.init)
        let name = Text(parts.first ?? "").foregroundStyle(E.text)
        let rest = Text(parts.count > 1 ? " " + parts[1] : "").foregroundStyle(E.text2)
        return (name + rest).font(E.body(12)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.75)
    }

    private static func color(_ kind: String?) -> Color {
        switch kind { case "sleep": return E.text; case "workout": return E.text2; default: return E.grey4A }
    }
}

/// calendar：一个月每天一格，亮 = 好（level 3）→ 暗 = 差（0），虚框 = 没数据 / 还没到
struct CalendarPart: View {
    let n: CNode

    var body: some View {
        let days = n.x.days ?? []
        let lead = clampInt((n.x.firstWeekday ?? 1) - 1, 0, 6)
        let maxDay = days.enumerated().map { $1.d ?? ($0 + 1) }.max() ?? 30
        let weeks = Swift.max(1, Int((Double(lead + maxDay) / 7).rounded(.up)))
        let legend = n.x.legend ?? []
        VStack(alignment: .leading, spacing: 8) {
            PTitle(text: n.x.title)
            Canvas { ctx, size in
                let pitch = size.width / 7
                let cw = pitch - 6
                for (i, w) in ["一", "二", "三", "四", "五", "六", "日"].enumerated() {
                    ctx.label(w, CGPoint(x: CGFloat(i) * pitch + cw / 2, y: 5))
                }
                for (k, day) in days.enumerated() {
                    let slot = lead + (day.d ?? (k + 1)) - 1
                    let r = CGRect(x: CGFloat(slot % 7) * pitch, y: 16 + CGFloat(slot / 7) * 26, width: cw, height: 20)
                    switch day.level {
                    case .some(let lv) where lv >= 3: ctx.fillRect(r, E.text)
                    case .some(2): ctx.fillRect(r, E.text2)
                    case .some(1): ctx.fillRect(r, E.grey4A)
                    case .some: ctx.fillRect(r, E.line); ctx.strokeRect(r, E.grey3A)
                    case .none: ctx.strokeRect(r, E.line, dash: [2, 2])
                    }
                    if day.today == true { ctx.strokeRect(r.insetBy(dx: -2.5, dy: -2.5), E.text) }
                }
            }
            .frame(height: 16 + CGFloat(weeks) * 26 - 4)
            FlowLayout(spacing: 8) {
                ForEach(Array(legend.prefix(4).enumerated()), id: \.offset) { i, l in
                    HStack(spacing: 4) {
                        ShadeSwatch(shade: [Shade.fill(E.text), .fill(E.text2), .fill(E.grey4A), .fill(E.line)][i])
                        Text(l).font(E.body(11)).foregroundStyle(E.text2).lineLimit(1)
                    }
                }
            }
        }
        .partLabel([n.x.title,
                    legend.enumerated().map { i, l in
                        "\(l) \(days.filter { $0.level == 3 - i }.count) 天"
                    }.joined(separator: "，")])
    }

    private func clampInt(_ v: Int, _ lo: Int, _ hi: Int) -> Int { Swift.min(Swift.max(v, lo), hi) }
}

/// weekgrid：本周一到周日七格，每格最多两个字
struct WeekGridPart: View {
    let n: CNode

    var body: some View {
        let days = n.x.days ?? []
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                ForEach(days) { d in
                    VStack(spacing: 6) {
                        Text(d.label ?? "").font(E.body(12)).foregroundStyle(d.state == "today" ? E.text : E.text2)
                        cell(d).frame(height: 40)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            PCaption(text: n.caption ?? Self.legend(days))
        }
        .partLabel([], days.map { "周\($0.label ?? "") \($0.text ?? "") \(Self.stateName($0.state))" }, [n.caption])
    }

    @ViewBuilder
    private func cell(_ d: CItem) -> some View {
        let shape = RoundedRectangle(cornerRadius: 4, style: .continuous)
        let t = d.text ?? ""
        switch d.state {
        case "done":
            Text(t).font(E.body(11)).foregroundStyle(Color.black)
                .frame(maxWidth: .infinity, maxHeight: .infinity).background(shape.fill(E.text))
        case "today":
            Text(t).font(E.body(11)).foregroundStyle(E.text)
                .frame(maxWidth: .infinity, maxHeight: .infinity).overlay(shape.strokeBorder(E.text, lineWidth: 1))
        case "skipped":
            Text(t).font(E.body(11)).foregroundStyle(E.text2)
                .frame(maxWidth: .infinity, maxHeight: .infinity).overlay(shape.strokeBorder(E.text2, lineWidth: 1))
        case "missed":
            Text(t).font(E.body(11)).strikethrough(true, color: E.text3).foregroundStyle(E.text3)
                .frame(maxWidth: .infinity, maxHeight: .infinity).overlay(shape.strokeBorder(E.grey4A, lineWidth: 1))
        case "rest":
            Text(t).font(E.body(11)).foregroundStyle(E.text3)
                .frame(maxWidth: .infinity, maxHeight: .infinity).overlay(shape.strokeBorder(E.grey3A, lineWidth: 1))
        default:   // future
            Text(t).font(E.body(11)).foregroundStyle(E.text3)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .overlay(shape.strokeBorder(E.grey3A, style: StrokeStyle(lineWidth: 1, dash: [3, 3])))
        }
    }

    /// 服务器没写说明时，App 按出现的状态补一句图例（画法是 App 定的）
    private static func legend(_ days: [CItem]) -> String? {
        let has = Set(days.compactMap(\.state))
        let parts = [("done", "实心 = 做了"), ("today", "白框 = 今天"), ("future", "虚线 = 还没到")]
            .filter { has.contains($0.0) }.map(\.1)
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private static func stateName(_ s: String?) -> String {
        ["done": "做了", "missed": "没做", "skipped": "跳过", "today": "今天", "future": "还没到", "rest": "休息"][s ?? ""] ?? ""
    }
}

/// streak：连续天数的大数字 + 近两周每天一根短竖线（断掉那天是一个短点）
struct StreakPart: View {
    let n: CNode

    var body: some View {
        let marks = n.x.marks ?? []
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(n.x.count.map { pnum($0) } ?? n.text ?? "").font(E.thin(56)).kerning(-2)
                    .foregroundStyle(E.text).monospacedDigit().lineLimit(1)
                if let u = n.unit { Text(u).font(E.light(17)).foregroundStyle(E.text) }
            }
            .padding(.top, -6)
            if let l = n.label { Text(l).font(E.body(15)).foregroundStyle(E.text2) }
            Canvas { ctx, size in
                guard !marks.isEmpty else { return }
                let lastBreak = marks.lastIndex(of: false) ?? -1
                let step = marks.count > 1 ? (size.width - 2) / CGFloat(marks.count - 1) : 0
                for (i, on) in marks.enumerated() {
                    let x = CGFloat(i) * step
                    if !on {
                        ctx.fillRect(CGRect(x: x, y: 6, width: 2, height: 4), E.text3)
                    } else if i == marks.count - 1 {
                        ctx.fillRect(CGRect(x: x, y: 0, width: 2, height: 16), E.text)
                    } else {
                        ctx.fillRect(CGRect(x: x, y: 2, width: 2, height: 12), i < lastBreak ? E.grey4A : E.text)
                    }
                }
            }
            .frame(height: 16)
            PCaption(text: n.caption ?? n.x.best.map { "最长 \(pnum($0)) \(n.unit ?? "天")" })
        }
        .partLabel(["\(n.label ?? "") \(n.x.count.map { pnum($0) } ?? "") \(n.unit ?? "")", n.caption])
    }
}

/// countdown：离某个时间点还有多久，下面一条细进度线
struct CountdownPart: View {
    let n: CNode

    var body: some View {
        let f = clamp(n.fraction ?? 0, 0, 1)
        VStack(alignment: .leading, spacing: 8) {
            PLabel(text: n.label)
            Text(n.text ?? "").font(E.thin(56)).kerning(-2).foregroundStyle(E.text).monospacedDigit()
                .lineLimit(1).minimumScaleFactor(0.5)
                .padding(.vertical, -6)
            if let s = n.sub {
                Text(s).font(E.body(15)).foregroundStyle(E.text2).fixedSize(horizontal: false, vertical: true)
            }
            Canvas { ctx, size in
                ctx.fillRect(CGRect(x: 0, y: 1.5, width: size.width, height: 1), E.line)
                ctx.fillRect(CGRect(x: 0, y: 1, width: size.width * CGFloat(f), height: 2), E.text)
            }
            .frame(height: 4)
            .padding(.top, 2)
        }
        .partLabel([n.label, n.text, n.x.toText.map { "到 \($0)" }, n.sub])
    }
}

/// time_range：一个时间段本身就是重点（睡眠窗口、训练时段），下面 0–24 小时轴
struct TimeRangePart: View {
    let n: CNode

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            PLabel(text: n.label)
            Text(n.text ?? "").font(E.thin(32)).kerning(-1).foregroundStyle(E.text).monospacedDigit()
                .lineLimit(1).minimumScaleFactor(0.6)
            if let s = n.sub {
                Text(s).font(E.body(15)).foregroundStyle(E.text2).fixedSize(horizontal: false, vertical: true)
            }
            Canvas { ctx, size in
                let W = size.width
                func x(_ h: Double) -> CGFloat { CGFloat(clamp(h, 0, 24) / 24) * W }
                ctx.fillRect(CGRect(x: 0, y: 5, width: W, height: 1), E.line)
                if let f = n.x.from, let t = n.x.to {
                    let spans = t >= f ? [(f, t)] : [(f, 24.0), (0.0, t)]
                    for (a, b) in spans { ctx.fillRect(CGRect(x: x(a), y: 2, width: x(b) - x(a), height: 7), E.text) }
                }
                for (i, h) in [0.0, 6, 12, 18, 24].enumerated() {
                    ctx.label(pnum(h), CGPoint(x: x(h), y: 17), i == 0 ? .leading : (i == 4 ? .trailing : .center))
                }
            }
            .frame(height: 22)
            .padding(.top, 4)
        }
        .partLabel([n.label, n.text, n.sub])
    }
}

/// milestones：长期项目的阶段和复盘点（竖排），白圈 = 现在，实心 = 过了，空心 = 还没到
struct MilestonesPart: View {
    let n: CNode

    var body: some View {
        let items = Array((n.items ?? []).prefix(5))
        VStack(alignment: .leading, spacing: 12) {
            PTitle(text: n.x.title)
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                    row(it, last: i == items.count - 1)
                }
            }
        }
        .partLabel([n.x.title], items.map {
            "\($0.title ?? "") \($0.sub ?? "") \(["done": "过了", "now": "现在", "next": "还没到"][$0.state ?? ""] ?? "")"
        })
    }

    private func row(_ it: CItem, last: Bool) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 0) {
                Group {
                    switch it.state {
                    case "now": Circle().strokeBorder(E.text, lineWidth: 1.5).frame(width: 10, height: 10)
                    case "done": Circle().fill(E.text2).frame(width: 9, height: 9)
                    default: Circle().strokeBorder(E.grey4A, lineWidth: 1).frame(width: 9, height: 9)
                    }
                }
                .padding(.top, 4)
                if !last {
                    Rectangle().fill(E.grey3A).frame(width: 1).frame(minHeight: 22, maxHeight: .infinity)
                }
            }
            .frame(width: 12)
            VStack(alignment: .leading, spacing: 2) {
                (Text(it.title ?? "").font(E.body(14)).foregroundStyle(it.state == "now" ? E.text : E.text2)
                 + Text(it.state == "now" ? "  现在" : "").font(E.body(12)).foregroundStyle(E.text2))
                    .fixedSize(horizontal: false, vertical: true)
                if let s = it.sub, !s.isEmpty {
                    Text(s).font(E.body(12)).foregroundStyle(it.state == "now" ? E.text2 : E.text3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.bottom, last ? 0 : 10)
            Spacer(minLength: 0)
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - 趋势与对比

/// sparkline：一个数后面跟一条小线，看方向不看细节
struct SparklinePart: View {
    let n: CNode

    var body: some View {
        let pts = n.x.points ?? []
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 0) {
                PLabel(text: n.label)
                HStack(alignment: .firstTextBaseline, spacing: 3) {
                    Text(n.text ?? "").font(E.thin(32)).foregroundStyle(E.text).monospacedDigit()
                        .lineLimit(1).minimumScaleFactor(0.6)
                    if let u = n.unit, !u.isEmpty {
                        Text(displayUnit(u)).font(E.body(12)).foregroundStyle(E.text2)
                    }
                }
            }
            Spacer(minLength: 0)
            Canvas { ctx, size in
                let (p, last) = seriesPath(pts, in: CGRect(x: 2, y: 2, width: size.width - 4, height: size.height - 4))
                let col = n.x.direction == "flat" ? E.text2 : E.text
                ctx.stroke(p, with: .color(col), style: StrokeStyle(lineWidth: 1.2, lineJoin: .round))
                if let last { ctx.dot(last, 2, fill: col) }
            }
            .frame(width: 120, height: 28)
        }
        .partLabel([n.label, "\(n.text ?? "")\(unitSuffix(n.unit))",
                    ["down": "近来往下", "up": "近来往上", "flat": "基本没变"][n.x.direction ?? ""],
                    n.x.asof.map { "截至 \($0)" }])
    }
}

/// stat_spark：stat 加一条小线（放在 h 里横排 2–3 个）；动了的线白，没动的灰
struct StatSparkPart: View {
    let n: CNode

    var body: some View {
        let pts = n.x.points ?? []
        VStack(alignment: .leading, spacing: 3) {
            PLabel(text: n.label)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(n.text ?? "").font(E.light(24)).foregroundStyle(E.text).monospacedDigit()
                    .lineLimit(1).minimumScaleFactor(0.6)
                if let u = n.unit, !u.isEmpty {
                    Text(displayUnit(u)).font(E.body(11)).foregroundStyle(E.text2).lineLimit(1)
                }
            }
            Canvas { ctx, size in
                let (p, _) = seriesPath(pts, in: CGRect(x: 2, y: 2, width: size.width - 4, height: size.height - 4))
                ctx.stroke(p, with: .color(n.x.moved == true ? E.text : E.text2),
                           style: StrokeStyle(lineWidth: 1.1, lineJoin: .round))
            }
            .frame(maxWidth: 120)
            .frame(height: 20)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .partLabel([n.label, "\(n.text ?? "")\(unitSuffix(n.unit))", n.x.moved == true ? "近 3 天有变化" : "近 3 天没怎么动",
                    n.x.asof.map { "截至 \($0)" }])
    }
}

/// delta：只讲「变了多少」；下面一根哑铃：空心 = 之前，实心 = 现在
struct DeltaPart: View {
    let n: CNode

    var body: some View {
        let f = n.x.fromText ?? n.x.from.map(pnum)
        let t = n.x.toText ?? n.x.to.map(pnum)
        let fv = f.flatMap { Double($0) }
        let tv = t.flatMap { Double($0) }
        let down = (fv != nil && tv != nil) ? tv! < fv! : n.x.direction == "down"
        let sub = (f != nil && t != nil) ? (down ? "\(t!) ← \(f!)" : "\(f!) → \(t!)") + unitSuffix(n.unit) : nil
        VStack(alignment: .leading, spacing: 4) {
            PLabel(text: n.label)
            Text(n.text ?? "").font(E.thin(48)).foregroundStyle(E.text).monospacedDigit()
                .lineLimit(1).minimumScaleFactor(0.5)
                .padding(.vertical, -4)
            if let sub { Text(sub).font(E.body(15)).foregroundStyle(E.text2).monospacedDigit() }
            Canvas { ctx, size in
                let W = size.width
                let y: CGFloat = 9.5
                ctx.fillRect(CGRect(x: 0, y: 9, width: W, height: 1), E.line)
                var r = 0.0
                if let fv, let tv, fv != 0 { r = (tv - fv) / abs(fv) }
                var d = CGFloat(clamp(r * 3, -0.4, 0.4)) * W
                if r != 0 && abs(d) < 12 { d = d < 0 ? -12 : 12 }
                let fx = W / 2 - d / 2, tx = W / 2 + d / 2
                if abs(d) > 9 {
                    let s: CGFloat = d < 0 ? -1 : 1
                    ctx.line(CGPoint(x: fx + 4 * s, y: y), CGPoint(x: tx - 4.5 * s, y: y), E.text)
                }
                ctx.dot(CGPoint(x: fx, y: y), 3.5, stroke: E.text3)
                ctx.dot(CGPoint(x: tx, y: y), 3.5, fill: E.text)
            }
            .frame(height: 20)
            .padding(.top, 2)
        }
        .partLabel([n.label, n.text, f.map { "从 \($0)" }, t.map { "到 \($0)\(unitSuffix(n.unit))" },
                    n.x.good.map { $0 ? "往好的方向" : "往不好的方向" }])
    }
}

/// compare：按星期对齐两周，实心 = 这周，空心 = 上周同一天
struct ComparePart: View {
    let n: CNode

    var body: some View {
        let pairs = n.x.pairs ?? []
        let peak = pairs.flatMap { [$0.nowValue ?? 0, $0.prev ?? 0] }.max() ?? 0
        let top = Swift.max(n.max ?? 0, peak, 0.0001) * 1.08
        let h: CGFloat = 78
        VStack(alignment: .leading, spacing: 6) {
            PTitle(text: n.x.title).padding(.bottom, 2)
            Canvas { ctx, size in
                let W = size.width
                ctx.line(CGPoint(x: 0, y: h - 0.5), CGPoint(x: W, y: h - 0.5), E.line)
                let slot = W / CGFloat(Swift.max(pairs.count, 1))
                let k = Swift.min(1, slot / 40)
                func y(_ v: Double) -> CGFloat { h - 1 - CGFloat(v / top) * (h - 2) }
                for (i, p) in pairs.enumerated() {
                    let cx = slot * (CGFloat(i) + 0.5)
                    if let pv = p.prev, pv > 0 {
                        ctx.strokeRect(CGRect(x: cx - 9 * k, y: y(pv), width: 7 * k, height: h - 1 - y(pv)), E.text3)
                    }
                    if let nv = p.nowValue, nv > 0 {
                        ctx.fillRect(CGRect(x: cx + 2 * k, y: y(nv), width: 7 * k, height: h - 1 - y(nv)), E.text)
                    }
                }
            }
            .frame(height: h)
            AxisLabels(labels: pairs.map { $0.label ?? "" }, highlight: pairs.map { $0.today == true }, hi: E.text)
            PCaption(text: n.caption ?? "实心 = 这周 · 空心 = 上周同一天").padding(.top, 2)
        }
        .partLabel([n.x.title], pairs.map { p in
            "周\(p.label ?? "") 这周 \(p.nowValue.map { pnum($0) } ?? "还没到")，上周 \(p.prev.map { pnum($0) } ?? "没数据")\(unitSuffix(n.unit))"
        })
    }
}

/// dual_line：两条线各用各的刻度，一起动才算数
struct DualLinePart: View {
    let n: CNode

    var body: some View {
        let a = n.x.a, b = n.x.b
        VStack(alignment: .leading, spacing: 8) {
            PTitle(text: n.x.title)
            Canvas { ctx, size in
                let r = CGRect(x: 6, y: 6, width: size.width - 12, height: size.height - 12)
                if let b {
                    let (p, _) = seriesPath(b.points, in: r, minRel: 0.2)
                    ctx.stroke(p, with: .color(E.text2), style: StrokeStyle(lineWidth: 1.2, lineJoin: .round, dash: [4, 3]))
                }
                if let a {
                    let (p, _) = seriesPath(a.points, in: r, minRel: 0.2)
                    ctx.stroke(p, with: .color(E.text), style: StrokeStyle(lineWidth: 1.4, lineJoin: .round))
                }
            }
            .frame(height: 112)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 16) { legend(a, dashed: false); legend(b, dashed: true) }
                VStack(alignment: .leading, spacing: 4) { legend(a, dashed: false); legend(b, dashed: true) }
            }
        }
        .partLabel([n.x.title, a.map { "实线 \($0.label ?? "") \($0.text ?? "")" }, b.map { "虚线 \($0.label ?? "") \($0.text ?? "")" }])
    }

    @ViewBuilder
    private func legend(_ l: CLine?, dashed: Bool) -> some View {
        if let l {
            HStack(spacing: 6) {
                Canvas { ctx, size in
                    ctx.line(CGPoint(x: 0, y: size.height / 2), CGPoint(x: size.width, y: size.height / 2),
                             dashed ? E.text2 : E.text, dashed ? 1.2 : 1.4, dash: dashed ? [4, 3] : [])
                }
                .frame(width: 16, height: 4)
                Text([l.label, l.text.map { $0 + unitSuffix(l.unit) }].compactMap { $0 }.joined(separator: " "))
                    .font(E.body(12)).foregroundStyle(E.text2).monospacedDigit().lineLimit(1)
            }
            .fixedSize()
        }
    }
}

/// diverging：和一条线比，多了往上、少了往下
struct DivergingPart: View {
    let n: CNode

    var body: some View {
        let items = n.items ?? []
        let vals = items.map { $0.value ?? 0 }
        let pos = Swift.max(0, vals.max() ?? 0), neg = Swift.max(0, -(vals.min() ?? 0))
        let plotH: CGFloat = 84
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let W = size.width
                let padTop: CGFloat = neg > 0 ? 13 : 6
                let padBot: CGFloat = pos > 0 ? 13 : 6
                let span = Swift.max(pos + neg, n.x.maxAbs ?? 0, 0.0001)
                let s = (plotH - padTop - padBot) / CGFloat(pos + neg > 0 ? pos + neg : span)
                let zero = padTop + CGFloat(pos) * s
                ctx.line(CGPoint(x: 0, y: zero + 0.5), CGPoint(x: W, y: zero + 0.5), E.text3)
                let slot = W / CGFloat(Swift.max(items.count, 1))
                let bw = Swift.min(14, slot * 0.42)
                let every = items.count > 5 ? 2 : 1
                for (i, it) in items.enumerated() {
                    let cx = slot * (CGFloat(i) + 0.5)
                    let v = vals[i]
                    let bh = Swift.max(1, CGFloat(abs(v)) * s)
                    ctx.fillRect(CGRect(x: cx - bw / 2, y: v < 0 ? zero + 1 : zero - bh, width: bw, height: bh), E.text)
                    if showLabel(i, items.count, every: every) {
                        let txt = it.text ?? pnum(v)
                        let col = i == items.count - 1 ? E.text : E.text2
                        if v < 0 { ctx.label(txt, CGPoint(x: cx, y: zero - 6), color: col) }
                        else { ctx.label(txt, CGPoint(x: cx, y: zero + 8), color: col) }
                    }
                }
                if let f = items.first?.label { ctx.label(f, CGPoint(x: slot / 2, y: plotH + 7), color: E.text2) }
                if items.count > 1, let l = items.last?.label {
                    ctx.label(l, CGPoint(x: slot * (CGFloat(items.count) - 0.5), y: plotH + 7), color: E.text2)
                }
            }
            .frame(height: plotH + 14)
            PCaption(text: n.caption)
        }
        .partLabel([], items.map { "\($0.label ?? "") \($0.text ?? "")" }, [n.caption])
    }
}

/// lollipop：每天一个量，比柱子轻；空心 = 那天没做；虚线 = 目标
struct LollipopPart: View {
    let n: CNode

    var body: some View {
        let items = n.items ?? []
        let peak = items.compactMap(\.value).max() ?? 0
        let top = Swift.max(n.max ?? 0, peak, n.x.target ?? 0, 0.0001) * 1.06
        let base: CGFloat = 84
        let missed = items.contains { $0.done == false }
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let W = size.width
                func y(_ v: Double) -> CGFloat { base - CGFloat(v / top) * (base - 6) }
                ctx.line(CGPoint(x: 0, y: base + 0.5), CGPoint(x: W, y: base + 0.5), E.line)
                let slot = W / CGFloat(Swift.max(items.count, 1))
                if let t = n.x.target {
                    ctx.line(CGPoint(x: 0, y: y(t)), CGPoint(x: W, y: y(t)), E.text3, dash: [3, 3])
                    if let tl = n.x.targetLabel {
                        // 目标字默认在右上；被哪根棒子穿过就依次试左上、右下、左下
                        let stems = items.enumerated().map { i, it in
                            let cx = slot * (CGFloat(i) + 0.5), hy = y(it.value ?? 0)
                            return CGRect(x: cx - 5, y: hy - 5, width: 10, height: base - hy + 10)
                        }
                        Self.placeLabel(ctx, tl, lineY: y(t), width: W, avoid: stems)
                    }
                }
                for (i, it) in items.enumerated() {
                    let cx = slot * (CGFloat(i) + 0.5)
                    let v = it.value ?? 0
                    let hy = y(v)
                    if it.done == false && v <= 0 {
                        ctx.dot(CGPoint(x: cx, y: base), 3.5, fill: .black, stroke: E.text3)
                        continue
                    }
                    ctx.line(CGPoint(x: cx, y: base), CGPoint(x: cx, y: hy + 3.5), E.text2)
                    if it.done == false { ctx.dot(CGPoint(x: cx, y: hy), 3.5, fill: .black, stroke: E.text3) }
                    else { ctx.dot(CGPoint(x: cx, y: hy), 3.5, fill: E.text) }
                }
            }
            .frame(height: base + 2)
            AxisLabels(labels: items.map { $0.label ?? "" }, every: items.count > 5 ? 2 : 1)
            PCaption(text: n.caption ?? (missed ? "空心 = 那天没做" : nil))
        }
        .partLabel([n.x.targetLabel], items.map { "\($0.label ?? "") \($0.text ?? "")\($0.done == false ? " 没做" : "")" })
    }

    private static func placeLabel(_ ctx: GraphicsContext, _ s: String, lineY: CGFloat, width W: CGFloat, avoid: [CGRect]) {
        let rt = ctx.resolve(Text(s).font(E.body(9)).foregroundStyle(E.text3))
        let sz = rt.measure(in: CGSize(width: W, height: 40))
        let tries: [(CGFloat, CGFloat)] = [(W - sz.width, lineY - 2 - sz.height), (0, lineY - 2 - sz.height),
                                           (W - sz.width, lineY + 2), (0, lineY + 2)]
        let rects = tries.map { CGRect(x: $0.0, y: $0.1, width: sz.width, height: sz.height) }
        let pick = rects.first { r in avoid.allSatisfy { !$0.intersects(r) } }
        let r = pick ?? rects[0]
        if pick == nil { ctx.fillRect(r.insetBy(dx: -3, dy: 0), .black) }   // 实在躲不开就垫一块黑底
        ctx.draw(rt, in: r)
    }
}

/// scatter：两件事有没有关系；虚线 = 拟合，圈 = 最近一次
struct ScatterPart: View {
    let n: CNode

    var body: some View {
        let pts = (n.x.pointPairs ?? []).filter { $0.count >= 2 }
        let xr = Self.range(n.x.xRange, pts.map { $0[0] })
        let yr = Self.range(n.x.yRange, pts.map { $0[1] })
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let W = size.width, H = size.height
                let axisY = H - 14.5
                ctx.line(CGPoint(x: 0.5, y: 0), CGPoint(x: 0.5, y: axisY + 0.5), E.line)
                ctx.line(CGPoint(x: 0, y: axisY), CGPoint(x: W, y: axisY), E.line)
                let plot = CGRect(x: 8, y: 16, width: W - 16, height: axisY - 22)
                func map(_ p: [Double]) -> CGPoint {
                    CGPoint(x: plot.minX + CGFloat(clamp((p[0] - xr[0]) / (xr[1] - xr[0]), -0.03, 1.03)) * plot.width,
                            y: plot.maxY - CGFloat(clamp((p[1] - yr[0]) / (yr[1] - yr[0]), -0.05, 1.05)) * plot.height)
                }
                if let fit = n.x.fit, fit.count >= 2, fit[0].count >= 2, fit[1].count >= 2 {
                    ctx.line(map(fit[0]), map(fit[1]), E.text3, dash: [3, 3])
                }
                for p in pts { ctx.dot(map(p), 2.5, fill: Color.white.opacity(0.85)) }
                if let l = n.x.last, l.count >= 2 { ctx.dot(map(l), 4.5, fill: .black, stroke: E.text) }
                if let yl = n.x.yLabel { ctx.label(yl, CGPoint(x: 6, y: 6), .leading) }
                if let xl = n.x.xLabel { ctx.label(xl + " →", CGPoint(x: W, y: H - 5), .trailing) }
            }
            .frame(height: 138)
            PCaption(text: n.caption)
        }
        .partLabel(["散点：\(n.x.xLabel ?? "") 和 \(n.x.yLabel ?? "")，\(pts.count) 个点",
                    n.x.r.map { String(format: "相关系数 %.2f", $0) }, n.caption])
    }

    /// 服务器给的范围优先，没给就用点自己的最小 / 最大
    private static func range(_ given: [Double]?, _ vals: [Double]) -> [Double] {
        if let g = given, g.count == 2, g[1] > g[0] { return g }
        let lo = vals.min() ?? 0
        return [lo, Swift.max(vals.max() ?? lo + 1, lo + 0.0001)]
    }
}

/// histogram：一个量平时落在哪；最常见那一箱白色
struct HistogramPart: View {
    let n: CNode

    var body: some View {
        let bins = Array((n.x.bins ?? []).prefix(8))
        let top = Swift.max(bins.compactMap(\.count).max() ?? 0, 0.0001)
        let base: CGFloat = 92
        VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let W = size.width
                ctx.line(CGPoint(x: 0, y: base + 0.5), CGPoint(x: W, y: base + 0.5), E.line)
                let slot = W / CGFloat(Swift.max(bins.count, 1))
                let bw = Swift.max(2, slot - 8)
                let all = slot >= 44
                for (i, b) in bins.enumerated() {
                    let bh = CGFloat((b.count ?? 0) / top) * (base - 2)
                    let x = slot * CGFloat(i) + (slot - bw) / 2
                    if bh > 0 { ctx.fillRect(CGRect(x: x, y: base - bh, width: bw, height: bh), b.peak == true ? E.text : E.grey4A) }
                    if all || i % 2 == 0 || b.peak == true {
                        ctx.label(b.label ?? "", CGPoint(x: x + bw / 2, y: base + 11), color: b.peak == true ? E.text : E.text3)
                    }
                }
            }
            .frame(height: base + 18)
            PCaption(text: n.caption)
        }
        .partLabel([n.caption], bins.map { "\($0.label ?? "") \(pnum($0.count ?? 0))" })
    }
}

/// spread：近 N 天的范围盒（最小、四分位、中位数、最大），点 = 今天
struct SpreadPart: View {
    let n: CNode

    var body: some View {
        let x = n.x
        VStack(alignment: .leading, spacing: 8) {
            PTitle(text: n.label)
            Canvas { ctx, size in
                guard let mn = x.min, let mx = n.max else { return }
                let lo = Swift.min(mn, x.today ?? mn), hi = Swift.max(mx, x.today ?? mx)
                let W = size.width
                func px(_ v: Double) -> CGFloat { 10 + CGFloat(hi > lo ? (v - lo) / (hi - lo) : 0.5) * (W - 20) }
                let mid: CGFloat = 26.5
                ctx.line(CGPoint(x: px(mn), y: mid), CGPoint(x: px(mx), y: mid), E.text3)
                ctx.line(CGPoint(x: px(mn) + 0.5, y: 20), CGPoint(x: px(mn) + 0.5, y: 33), E.text3)
                ctx.line(CGPoint(x: px(mx) - 0.5, y: 20), CGPoint(x: px(mx) - 0.5, y: 33), E.text3)
                if let a = x.q1, let b = x.q3 {
                    let r = CGRect(x: px(a), y: 16, width: Swift.max(1, px(b) - px(a)), height: 21)
                    ctx.fillRect(r, .black)
                    ctx.strokeRect(r, E.text)
                }
                if let m = x.median { ctx.line(CGPoint(x: px(m), y: 16), CGPoint(x: px(m), y: 37), E.text, 1.5) }
                if let t = x.today {
                    ctx.dot(CGPoint(x: px(t), y: mid), 4, fill: E.text)
                    if let tt = x.todayText {
                        ctx.label(tt, CGPoint(x: Swift.min(Swift.max(px(t), 24), W - 24), y: 6), color: E.text)
                    }
                }
                // 数值标签：中位数、两端优先，挤在一起的就不写
                var placed: [CGFloat] = []
                for v in [x.median, mn, mx, x.q1, x.q3].compactMap({ $0 }) {
                    let p = px(v)
                    guard placed.allSatisfy({ abs($0 - p) >= 22 }) else { continue }
                    placed.append(p)
                    ctx.label(pnum(v), CGPoint(x: p, y: 49))
                }
            }
            .frame(height: 56)
            PCaption(text: n.caption)
        }
        .partLabel([n.label, x.todayText,
                    x.min.map { "最低 \(pnum($0))" }, x.median.map { "中位数 \(pnum($0))" },
                    n.max.map { "最高 \(pnum($0))\(unitSuffix(n.unit))" },
                    (x.q1 != nil && x.q3 != nil) ? "中间一半在 \(pnum(x.q1!))–\(pnum(x.q3!))" : nil])
    }
}

/// bullet：一个值放进「差 / 一般 / 好」几段里，竖线 = 目标
struct BulletPart: View {
    let n: CNode

    var body: some View {
        let x = n.x
        VStack(alignment: .leading, spacing: 4) {
            PLabel(text: n.label)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(n.text ?? x.value.map(pnum) ?? "").font(E.thin(40)).foregroundStyle(E.text).monospacedDigit()
                    .lineLimit(1)
                    .padding(.vertical, -3)
                if let u = n.unit, !u.isEmpty { Text(displayUnit(u)).font(E.body(12)).foregroundStyle(E.text2) }
            }
            Canvas { ctx, size in
                let W = size.width
                let mn = x.min ?? 0, mx = Swift.max(n.max ?? 100, mn + 0.0001)
                func px(_ v: Double) -> CGFloat { CGFloat(clamp((v - mn) / (mx - mn), 0, 1)) * W }
                let bands = (x.bands ?? []).sorted()
                let shades: [Color] = [E.line2, E.line, E.grey3A, E.grey4A]
                var edges = [mn] + bands + [mx]
                edges = edges.map { clamp($0, mn, mx) }
                for i in 0..<(edges.count - 1) {
                    ctx.fillRect(CGRect(x: px(edges[i]), y: 4, width: px(edges[i + 1]) - px(edges[i]), height: 16),
                                 shades[Swift.min(i, shades.count - 1)])
                }
                if let v = x.value { ctx.fillRect(CGRect(x: 0, y: 10, width: px(v), height: 4), E.text) }
                var labels: [(CGFloat, String)] = []
                if let t = x.target {
                    ctx.line(CGPoint(x: px(t), y: 0), CGPoint(x: px(t), y: 22), E.text, 1.5)
                    labels.append((px(t), "目标 \(pnum(t))"))
                }
                for b in bands where labels.allSatisfy({ abs($0.0 - px(b)) >= 30 }) { labels.append((px(b), pnum(b))) }
                for (p, s) in labels {
                    let anchor: UnitPoint = p < 14 ? .leading : (p > W - 14 ? .trailing : .center)
                    ctx.label(s, CGPoint(x: p, y: 29), anchor)
                }
            }
            .frame(height: 34)
            PCaption(text: n.caption)
        }
        .partLabel([n.label, "\(n.text ?? "")\(unitSuffix(n.unit))", x.target.map { "目标 \(pnum($0))" }, n.caption])
    }
}

// MARK: - 进度与信息

/// segments：按周数的进度，一段一周
struct SegmentsPart: View {
    let n: CNode

    var body: some View {
        let total = Swift.min(Swift.max(Int((n.x.total ?? 1).rounded()), 1), 52)
        let done = Swift.max(0, n.x.done ?? 0)
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(n.text ?? "").font(E.thin(40)).foregroundStyle(E.text).monospacedDigit().lineLimit(1)
                    .minimumScaleFactor(0.6)
                if let s = n.sub { Text(s).font(E.body(12)).foregroundStyle(E.text2) }
            }
            if let l = n.label { Text(l).font(E.body(15)).foregroundStyle(E.text2) }
            Canvas { ctx, size in
                let gap: CGFloat = total > 20 ? 2 : 4
                let sw = (size.width - gap * CGFloat(total - 1)) / CGFloat(total)
                for i in 0..<total {
                    let x = CGFloat(i) * (sw + gap)
                    ctx.fillRect(CGRect(x: x, y: 2, width: sw, height: 4), E.grey3A)
                    let f = clamp(done - Double(i), 0, 1)
                    if f > 0 { ctx.fillRect(CGRect(x: x, y: 2, width: sw * CGFloat(f), height: 4), E.text) }
                }
            }
            .frame(height: 8)
            .padding(.top, 2)
        }
        .partLabel([n.label, "\(n.text ?? "") \(n.sub ?? "")", "过了 \(pnum(done)) / \(total)"])
    }
}

/// stepper：横向的几个阶段，白圈 = 现在
struct StepperPart: View {
    let n: CNode

    var body: some View {
        let items = Array((n.items ?? []).prefix(5))
        let subs = n.x.subs ?? []
        let cur = n.x.current ?? 0
        VStack(alignment: .leading, spacing: 8) {
            Canvas { ctx, size in
                let k = items.count
                guard k > 0 else { return }
                let slot = size.width / CGFloat(k)
                func cx(_ i: Int) -> CGFloat { slot * (CGFloat(i) + 0.5) }
                let y: CGFloat = 14
                if k > 1 {
                    ctx.line(CGPoint(x: cx(0), y: y), CGPoint(x: cx(k - 1), y: y), E.grey3A)
                    let end = Swift.min(cx(Swift.min(Swift.max(cur, 0), k - 1)) + slot / 2, cx(k - 1))
                    ctx.line(CGPoint(x: cx(0), y: y), CGPoint(x: end, y: y), E.text)
                }
                for i in 0..<k {
                    let p = CGPoint(x: cx(i), y: y)
                    if i < cur { ctx.dot(p, 4, fill: E.text) }
                    else if i == cur { ctx.dot(p, 6, fill: .black, stroke: E.text, 1.5); ctx.dot(p, 2.5, fill: E.text) }
                    else { ctx.dot(p, 5, fill: .black, stroke: E.grey4A) }
                }
            }
            .frame(height: 28)
            HStack(alignment: .top, spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                    VStack(spacing: 3) {
                        Text(it.text ?? "").font(E.body(11)).foregroundStyle(i == cur ? E.text : E.text2)
                            .lineLimit(1).minimumScaleFactor(0.7)
                        if i < subs.count {
                            Text(subs[i]).font(E.body(9)).foregroundStyle(E.text3).monospacedDigit()
                                .lineLimit(1).minimumScaleFactor(0.7)
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
            }
        }
        .padding(.vertical, 6)
        .partLabel([], items.enumerated().map { i, it in
            "\(it.text ?? "") \(i < subs.count ? subs[i] : "")\(i == cur ? "，现在" : (i < cur ? "，过了" : ""))"
        })
    }
}

/// progress_list：几件事各做到多少
struct ProgressListPart: View {
    let n: CNode

    var body: some View {
        let rows = Array((n.x.rows ?? []).prefix(4))
        VStack(alignment: .leading, spacing: 12) {
            ForEach(rows) { r in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(r.label ?? "").font(E.body(13)).foregroundStyle(E.text).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(r.text ?? "").font(E.body(12)).foregroundStyle(E.text2).monospacedDigit()
                    }
                    Canvas { ctx, size in
                        ctx.fillRect(CGRect(x: 0, y: 1.5, width: size.width, height: 1), E.line)
                        let f = clamp(r.fraction ?? r.frac ?? 0, 0, 1)
                        ctx.fillRect(CGRect(x: 0, y: 1, width: size.width * CGFloat(f), height: 2), E.text)
                    }
                    .frame(height: 4)
                }
            }
        }
        .partLabel([], rows.map { "\($0.label ?? "") \($0.text ?? "")" })
    }
}

/// checklist：只读的完成状态（要打勾去待办卡）。state：done / processing / skipped / pending
struct ChecklistPart: View {
    let n: CNode

    static func state(_ it: CItem) -> String { it.done == true ? "done" : (it.state ?? "pending") }

    var body: some View {
        let items = n.items ?? []
        let firstOpen = items.firstIndex { ["pending", "processing"].contains(Self.state($0)) }
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                let st = Self.state(it)
                HStack(spacing: 10) {
                    icon(st, first: i == firstOpen).frame(width: 16, height: 16)
                    Text(it.text ?? "").font(E.body(14)).monospacedDigit()
                        .strikethrough(st == "done", color: E.text3)
                        .foregroundStyle(st == "done" || st == "skipped" ? E.text3 : E.text)
                        .lineLimit(1).minimumScaleFactor(0.8)
                }
                .frame(minHeight: 20)
            }
        }
        .partLabel([], items.map {
            "\($0.text ?? "") \(["done": "做了", "processing": "在处理", "skipped": "跳过了"][Self.state($0)] ?? "还没做")"
        })
    }

    @ViewBuilder
    private func icon(_ st: String, first: Bool) -> some View {
        switch st {
        case "done":
            ZStack {
                Circle().fill(E.text)
                Path { p in
                    p.move(to: CGPoint(x: 4.5, y: 8.2))
                    p.addLine(to: CGPoint(x: 7, y: 10.5))
                    p.addLine(to: CGPoint(x: 11.5, y: 5.8))
                }
                .stroke(Color.black, lineWidth: 1.5)
            }
        case "processing":
            ZStack {
                Circle().strokeBorder(E.text, lineWidth: 1)
                Circle().fill(E.text).frame(width: 5, height: 5)
            }
        case "skipped":
            Circle().strokeBorder(E.text3, style: StrokeStyle(lineWidth: 1, dash: [2, 2]))
        default:
            Circle().strokeBorder(first ? E.text : E.text3, lineWidth: 1)
        }
    }
}

/// kv：几条设置或事实，左标签右值
struct KVPart: View {
    let n: CNode

    var body: some View {
        let items = n.items ?? []
        VStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                HStack(alignment: .firstTextBaseline) {
                    Text(it.label ?? "").font(E.body(13)).foregroundStyle(E.text2).lineLimit(1)
                    Spacer(minLength: 12)
                    Text(Self.value(it)).font(E.body(14)).foregroundStyle(E.text).monospacedDigit().lineLimit(1)
                }
                .padding(.vertical, 10)
                if i < items.count - 1 { Rectangle().fill(E.grey1E).frame(height: 1) }
            }
        }
        .partLabel([], items.map { "\($0.label ?? "") \(Self.value($0))" })
    }

    static func value(_ it: CItem) -> String { it.valueText ?? it.value.map(pnum) ?? it.text ?? "" }
}

/// table：最多 4 列 × 6 行，数字对齐，不画格线
struct TablePart: View {
    let n: CNode

    var body: some View {
        let cols = n.x.columnNames ?? []
        let rows = n.x.tableRows ?? []
        let k = Swift.max(cols.count, rows.map(\.count).max() ?? 0)
        let weights: [CGFloat] = (0..<k).map { $0 == 0 ? 1.2 : 1 }
        VStack(alignment: .leading, spacing: 11) {
            if !cols.isEmpty {
                WeightedRow(weights: weights) {
                    ForEach(0..<k, id: \.self) { j in
                        Text(j < cols.count ? cols[j] : "").font(E.body(12)).foregroundStyle(E.text2).lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                WeightedRow(weights: weights) {
                    ForEach(0..<k, id: \.self) { j in
                        Text(j < r.count ? r[j] : "").font(E.body(13)).foregroundStyle(E.text).monospacedDigit()
                            .lineLimit(1).minimumScaleFactor(0.8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
        .partLabel([], rows.map { r in zip(cols, r).map { "\($0) \($1)" }.joined(separator: " ") })
    }
}

/// tag：给标题或一条信息加个状态；strong 那个用白框
struct TagPart: View {
    let n: CNode

    var body: some View {
        let items = Array((n.items ?? []).prefix(4))
        let strong = n.x.strong
        FlowLayout(spacing: 8) {
            ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                Text(it.text ?? "").font(E.body(12)).lineLimit(1)
                    .foregroundStyle(i == strong || i == 0 ? E.text : E.text2)
                    .padding(.horizontal, 10)
                    .frame(height: 24)
                    .overlay(Capsule().strokeBorder(i == strong ? E.text : E.grey4A, lineWidth: 1))
            }
        }
        .padding(.vertical, 4)
        .partLabel(items.map(\.text))
    }
}

/// quote：一条规则或结论单独放大
struct QuotePart: View {
    let n: CNode

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(n.text ?? "").font(E.light(22)).foregroundStyle(E.text).lineSpacing(7)
                .fixedSize(horizontal: false, vertical: true)
            PCaption(text: n.x.source)
        }
        .partLabel([n.text, n.x.source])
    }
}

/// media：卡片里的跟练入口。跟练视频、音视频文件在 App 里全屏放（和待办卡同一个播放器）；网页链接才交给浏览器
struct MediaPart: View {
    let n: CNode
    @Environment(\.openURL) private var openURL
    @State private var playing: V3Media?

    private var media: V3Media? {
        guard let raw = n.x.url, !raw.isEmpty else { return nil }
        return V3Media(kind: n.x.kind ?? "video", url: raw, title: n.x.title, durationMin: nil, poster: n.x.poster)
    }

    var body: some View {
        let url = PivisAPI.resolve(n.x.url)
        Button {
            guard let url, let m = media else { return }
            if m.isVideoFile || m.isAudioFile { playing = m } else { openURL(url) }
        } label: {
            HStack(spacing: 14) {
                ZStack {
                    Circle().strokeBorder(E.text, lineWidth: 1)
                    Path { p in
                        p.move(to: CGPoint(x: 20, y: 16))
                        p.addLine(to: CGPoint(x: 32, y: 24))
                        p.addLine(to: CGPoint(x: 20, y: 32))
                        p.closeSubpath()
                    }
                    .fill(E.text)
                }
                .frame(width: 48, height: 48)
                VStack(alignment: .leading, spacing: 3) {
                    Text(n.x.title ?? "").font(E.body(15)).foregroundStyle(E.text).lineLimit(2)
                    if let s = n.sub { Text(s).font(E.body(12)).foregroundStyle(E.text2).lineLimit(1) }
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(EPress())
        .disabled(url == nil)
        .accessibilityLabel([n.x.kind == "audio" ? "播放音频" : "播放视频", n.x.title, n.sub]
            .compactMap { $0 }.joined(separator: "，"))
        .fullScreenCover(item: $playing) { m in ExecView(media: m, title: n.x.title) }
    }
}

/// photo：拍的照片和一句点评
struct PhotoPart: View {
    let n: CNode

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Color.clear
                .frame(maxWidth: .infinity)
                .frame(height: 140)
                .overlay {
                    // /api/ 下的照片要带设备密钥：不用 AsyncImage
                    // 动作库示意动图：完整显示（白底小图，不裁切）；Psir 拍的照片铺满
                    ServerImage(url: PivisAPI.resolve(n.x.url), contentMode: n.x.kind == "exercise" ? .fit : .fill) { failed in
                        placeholder(failed ? (n.x.kind == "exercise" ? "动图暂时打不开" : "照片暂时打不开") : nil)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            if let c = n.caption {
                Text(c).font(E.body(15)).foregroundStyle(E.text).fixedSize(horizontal: false, vertical: true)
            }
            if n.x.kind == "exercise" {
                // 动图的版权标注（Gym visual 的使用条件：每次使用都带上）
                Text("© Gym visual — gymvisual.com").font(E.body(11)).foregroundStyle(E.text3)
            }
        }
        .partLabel([n.x.kind == "exercise" ? "动作示意" : "照片", n.caption])
    }

    private func placeholder(_ s: String?) -> some View {
        ZStack {
            E.grey14
            if let s { Text(s).font(E.body(12)).foregroundStyle(E.text3) }
        }
    }
}
