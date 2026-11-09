import SwiftUI

// MARK: - 开放画布：P-Health 用零件拼主卡 / 对话卡，服务器校验并算好数，App 只按规范画
// 零件和取值都是规范里的档位（颜色、字号、线宽没法自定义），所以画出来一定是这套黑白细线风格。

/// 在 JSON 里的位置（"layout.children.2.items.0"）当 id：同样的内容每次解码都是同一个 id，
/// 页面一轮轮重新拉取时视图不重建（以前每次 UUID()，整张主卡重建、图表画入动画每次重播）
extension Decoder {
    var structuralID: String {
        codingPath.map { $0.intValue.map(String.init) ?? $0.stringValue }.joined(separator: ".")
    }
}

/// 服务器算好的零件
struct CNode: Decodable, Identifiable {
    let id: String
    let t: String
    var gap: CGFloat?
    var align: String?
    var justify: String?
    var children: [CNode]?
    var text: String?
    var role: String?
    var tone: Int?
    var size: String?
    var unit: String?
    var zone: String?
    var label: String?
    var height: String?
    var viz: V3Page.Viz?
    var items: [CItem]?
    var caption: String?
    var fraction: Double?
    var marker: Double?
    var left: String?
    var right: String?
    var sub: String?
    var level: String?
    var style: String?
    var ref: Double?
    var refLabel: String?
    var max: Double?
    /// 新零件（pie、hypnogram、scatter…）各自的字段，见 CanvasParts.swift
    var x = CPart()

    private enum CodingKeys: String, CodingKey {
        case t, gap, align, justify, children, text, role, tone, size, unit, zone, label, height, viz, items, caption
        case fraction, marker, left, right, sub, level, style, ref, refLabel, max
    }

    /// App 自己拼的零件（对话里的老卡片换成画布零件来画）：id 由调用方按位置给
    init(_ t: String, id: String) {
        self.t = t
        self.id = id
    }

    // 宽松解码：某个字段类型不对只丢这个字段，不让整张卡画不出来（size 既可能是 "xl" 也可能是 16）
    init(from decoder: Decoder) throws {
        id = decoder.structuralID
        let c = try decoder.container(keyedBy: CodingKeys.self)
        t = (try? c.decode(String.self, forKey: .t)) ?? ""
        gap = try? c.decodeIfPresent(CGFloat.self, forKey: .gap)
        align = try? c.decodeIfPresent(String.self, forKey: .align)
        justify = try? c.decodeIfPresent(String.self, forKey: .justify)
        children = try? c.decodeIfPresent([CNode].self, forKey: .children)
        text = try? c.decodeIfPresent(String.self, forKey: .text)
        role = try? c.decodeIfPresent(String.self, forKey: .role)
        tone = try? c.decodeIfPresent(Int.self, forKey: .tone)
        if let s = try? c.decodeIfPresent(String.self, forKey: .size) { size = s }
        else if let n = try? c.decodeIfPresent(Double.self, forKey: .size) { size = String(Int(n)) }
        unit = try? c.decodeIfPresent(String.self, forKey: .unit)
        zone = try? c.decodeIfPresent(String.self, forKey: .zone)
        label = try? c.decodeIfPresent(String.self, forKey: .label)
        height = try? c.decodeIfPresent(String.self, forKey: .height)
        viz = try? c.decodeIfPresent(V3Page.Viz.self, forKey: .viz)
        items = c.lenientList(CItem.self, .items)
        caption = try? c.decodeIfPresent(String.self, forKey: .caption)
        fraction = try? c.decodeIfPresent(Double.self, forKey: .fraction)
        marker = try? c.decodeIfPresent(Double.self, forKey: .marker)
        left = try? c.decodeIfPresent(String.self, forKey: .left)
        right = try? c.decodeIfPresent(String.self, forKey: .right)
        sub = try? c.decodeIfPresent(String.self, forKey: .sub)
        level = try? c.decodeIfPresent(String.self, forKey: .level)
        style = try? c.decodeIfPresent(String.self, forKey: .style)
        ref = try? c.decodeIfPresent(Double.self, forKey: .ref)
        refLabel = try? c.decodeIfPresent(String.self, forKey: .refLabel)
        max = try? c.decodeIfPresent(Double.self, forKey: .max)
        x = CPart(from: decoder)
    }
}

extension CNode {
    /// 一张表（主卡的老式小表、对话里的表格卡都换成画布的 table 零件画）
    static func table(_ columns: [String], _ rows: [[String]], id: String) -> CNode {
        var n = CNode("table", id: id)
        n.x.columnNames = columns
        n.x.tableRows = rows
        return n
    }
}

/// 零件里的一条：dots 的点、list 的条目、timeline 的待办，以及新零件的块 / 行 / 天 / 段 / 箱都用这一个形状。
/// 可以是裸字符串（tag、stepper）、裸布尔（waffle）、裸数，或者对象；对象里哪个字段类型不对只丢那个字段。
struct CItem: Decodable, Identifiable {
    let id: String
    var on: Bool?
    var now: Bool?
    var label: String?
    var text: String?
    var when: String?
    var title: String?
    var note: String?
    var value: Double?
    var ref: Double?
    // 新零件
    var valueText: String?   // kv 的 value 是字符串（"08:30"）
    var nowValue: Double?    // compare 的 now 是数（未来日 null）
    var prev: Double?
    var pct: Double?
    var frac: Double?
    var fraction: Double?
    var done: Bool?
    var state: String?       // done / missed / skipped / today / future / rest；milestones 的 done / now / next
    var sub: String?
    var minutes: Double?
    var today: Bool?
    var level: Int?          // calendar：3 最好 → 0 最差，nil = 没数据 / 未来
    var d: Int?
    var count: Double?
    var peak: Bool?
    var parts: [Double]?
    var start: String?
    var end: String?
    var from: Double?
    var to: Double?
    var at: Double?
    var kind: String?
    var stage: String?
    /// dots / columns 超过 30 天时按周给：这一条是一周（label 是那周第一天，如 11/3）
    var week: Bool?
    /// split 一行的单位；split / dotstrip 里「这一条是好的那一组 / 那天结果好」
    var unit: String?
    var hi: Bool?

    private enum CodingKeys: String, CodingKey {
        case on, now, label, text, when, title, note, value, ref
        case prev, pct, frac, fraction, done, state, sub, minutes, today, level, d, count, peak, parts
        case start, end, from, to, at, kind, stage, week, unit, hi
    }

    /// App 自己拼的条目
    init(id: String, text: String? = nil, note: String? = nil, value: Double? = nil, label: String? = nil, on: Bool? = nil) {
        self.id = id
        self.text = text
        self.note = note
        self.value = value
        self.label = label
        self.on = on
    }

    init(from decoder: Decoder) throws {
        id = decoder.structuralID
        if let s = try? decoder.singleValueContainer() {
            if let v = try? s.decode(String.self) { text = v; return }
            if let v = try? s.decode(Bool.self) { on = v; return }
            if let v = try? s.decode(Double.self) { value = v; return }
        }
        guard let c = try? decoder.container(keyedBy: CodingKeys.self) else { return }   // null → 空条目
        on = c.lenient(Bool.self, .on)
        if let b = c.lenient(Bool.self, .now) { now = b } else { nowValue = c.lenient(Double.self, .now) }
        label = c.string(.label)
        text = c.string(.text)
        when = c.string(.when)
        title = c.string(.title)
        note = c.string(.note)
        if let v = c.lenient(Double.self, .value) { value = v } else { valueText = c.lenient(String.self, .value) }
        ref = c.lenient(Double.self, .ref)
        prev = c.lenient(Double.self, .prev)
        pct = c.lenient(Double.self, .pct)
        frac = c.lenient(Double.self, .frac)
        fraction = c.lenient(Double.self, .fraction)
        done = c.lenient(Bool.self, .done)
        state = c.lenient(String.self, .state)
        sub = c.string(.sub)
        minutes = c.lenient(Double.self, .minutes)
        today = c.lenient(Bool.self, .today)
        level = c.lenient(Double.self, .level).map { Int($0.rounded()) }
        d = c.lenient(Double.self, .d).map { Int($0.rounded()) }
        count = c.lenient(Double.self, .count)
        peak = c.lenient(Bool.self, .peak)
        parts = c.lenientNumbers(.parts)?.map { $0 ?? 0 }
        start = c.string(.start)
        end = c.string(.end)
        from = c.lenient(Double.self, .from)
        to = c.lenient(Double.self, .to)
        at = c.lenient(Double.self, .at)
        kind = c.lenient(String.self, .kind)
        stage = c.lenient(String.self, .stage)
        week = c.lenient(Bool.self, .week)
        unit = c.string(.unit)
        hi = c.lenient(Bool.self, .hi)
    }

    /// 读屏用的日期：按周给的读成「11/3 那周」
    var spokenLabel: String { week == true ? "\(label ?? "") 那周" : (label ?? "") }
}

struct CanvasView: View {
    let node: CNode
    var today: String = ""

    var body: some View { part(node) }

    private func part(_ n: CNode) -> AnyView {
        switch n.t {
        case "v":
            let a: HorizontalAlignment = n.align == "center" ? .center : (n.align == "trailing" ? .trailing : .leading)
            return AnyView(VStack(alignment: a, spacing: n.gap ?? 12) {
                ForEach(n.children ?? []) { part($0) }
            }.frame(maxWidth: .infinity, alignment: Alignment(horizontal: a, vertical: .center)))
        case "h":
            let a: VerticalAlignment = n.align == "top" ? .top : (n.align == "bottom" ? .bottom
                : (n.align == "baseline" ? .firstTextBaseline : .center))
            let kids = n.children ?? []
            return AnyView(HStack(alignment: a, spacing: n.gap ?? 16) {
                ForEach(Array(kids.enumerated()), id: \.element.id) { i, k in
                    if n.justify == "between" && i > 0 { Spacer(minLength: 8) }
                    part(k)
                }
            }.frame(maxWidth: .infinity, alignment: .leading))
        case "text":
            return AnyView(Text(n.text ?? "")
                .font(textFont(n.role))
                .kerning(n.role == "label" ? 0.6 : 0)
                .foregroundStyle(tone(n.tone))
                .lineSpacing(n.role == "body" ? 4 : 2)
                .fixedSize(horizontal: false, vertical: true))
        case "value":
            return AnyView(valueView(n))
        case "stat":
            return AnyView(VStack(alignment: .leading, spacing: 3) {
                Text(n.label ?? "").font(E.body(12)).foregroundStyle(E.text3).lineLimit(1)
                HStack(alignment: .firstTextBaseline, spacing: 3) {
                    Text(n.text ?? "").font(E.light(24)).foregroundStyle(E.text).monospacedDigit()
                        .minimumScaleFactor(0.6).lineLimit(1)
                    if let u = n.unit, !u.isEmpty { Text(displayUnit(u)).font(E.body(12)).foregroundStyle(E.text2) }
                }
            })
        case "chart":
            guard let v = n.viz else { return AnyView(EmptyView()) }
            // 数一样就是同一张图（不重播画入）；数变了换一张，画入动画再播一次
            return AnyView(RiskViz(viz: v, level: v.zone ?? "steady", today: today).id(v))
        case "dots":
            return AnyView(dotsView(n))
        case "bar":
            return AnyView(barView(n))
        case "columns":
            return AnyView(columnsView(n))
        case "ring":
            return AnyView(ringView(n))
        case "level":
            return AnyView(HStack(spacing: 2) {
                LevelDot(level: n.level ?? "steady", size: 8)
                Text(n.text ?? "").font(E.body(13)).foregroundStyle(E.text)
            })
        case "rule":
            return AnyView(Hairline(color: E.line2))
        case "list":
            return AnyView(VStack(alignment: .leading, spacing: 6) {
                ForEach(Array((n.items ?? []).enumerated()), id: \.element.id) { i, it in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(n.style == "number" ? "\(i + 1)" : "·").font(E.body(13)).foregroundStyle(E.text3)
                            .frame(width: 12, alignment: .leading)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(it.text ?? "").font(E.body(15)).foregroundStyle(E.text)
                                .fixedSize(horizontal: false, vertical: true)
                            if let note = it.note, !note.isEmpty {
                                Text(note).font(E.body(12)).foregroundStyle(E.text3)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
            })
        case "timeline":
            return AnyView(VStack(alignment: .leading, spacing: 0) {
                ForEach(n.items ?? []) { it in
                    TimeTitleRow(when: it.when ?? "", title: it.title ?? "", note: it.note)
                        .frame(minHeight: 46)
                }
            })
        case "spacer":
            return AnyView(Color.clear.frame(height: CGFloat(n.size.flatMap { Double($0) } ?? 16)))
        // 占比与构成
        case "pie", "donut": return AnyView(PiePart(n: n))
        case "stack": return AnyView(StackPart(n: n))
        case "stack_columns": return AnyView(StackColumnsPart(n: n))
        case "waffle": return AnyView(WafflePart(n: n))
        case "zones": return AnyView(ZonesPart(n: n))
        case "radar": return AnyView(RadarPart(n: n))
        case "split": return AnyView(SplitPart(n: n))
        // 时间与作息
        case "hypnogram": return AnyView(HypnogramPart(n: n))
        case "sleep_window": return AnyView(SleepWindowPart(n: n))
        case "clock24": return AnyView(Clock24Part(n: n))
        case "calendar": return AnyView(CalendarPart(n: n))
        case "weekgrid": return AnyView(WeekGridPart(n: n))
        case "streak": return AnyView(StreakPart(n: n))
        case "countdown": return AnyView(CountdownPart(n: n))
        case "time_range": return AnyView(TimeRangePart(n: n))
        case "milestones": return AnyView(MilestonesPart(n: n))
        case "response": return AnyView(ResponsePart(n: n))
        case "dotstrip": return AnyView(DotStripPart(n: n))
        // 趋势与对比
        case "sparkline": return AnyView(SparklinePart(n: n))
        case "stat_spark": return AnyView(StatSparkPart(n: n))
        case "delta": return AnyView(DeltaPart(n: n))
        case "compare": return AnyView(ComparePart(n: n))
        case "dual_line": return AnyView(DualLinePart(n: n))
        case "diverging": return AnyView(DivergingPart(n: n))
        case "lollipop": return AnyView(LollipopPart(n: n))
        case "scatter": return AnyView(ScatterPart(n: n))
        case "histogram": return AnyView(HistogramPart(n: n))
        case "spread": return AnyView(SpreadPart(n: n))
        case "bullet": return AnyView(BulletPart(n: n))
        // 进度与信息
        case "segments": return AnyView(SegmentsPart(n: n))
        case "stepper": return AnyView(StepperPart(n: n))
        case "progress_list": return AnyView(ProgressListPart(n: n))
        case "checklist": return AnyView(ChecklistPart(n: n))
        case "kv": return AnyView(KVPart(n: n))
        case "table": return AnyView(TablePart(n: n))
        case "tag": return AnyView(TagPart(n: n))
        case "quote": return AnyView(QuotePart(n: n))
        case "media": return AnyView(MediaPart(n: n))
        case "photo": return AnyView(PhotoPart(n: n))
        default:
            return AnyView(EmptyView())
        }
    }

    private func textFont(_ role: String?) -> Font {
        switch role {
        case "title": return E.body(17)
        case "caption": return E.body(13)
        case "label": return E.body(12)
        default: return E.body(15)
        }
    }

    private func tone(_ t: Int?) -> Color { t == 3 ? E.text3 : (t == 2 ? E.text2 : E.text) }

    @ViewBuilder
    private func valueView(_ n: CNode) -> some View {
        let big: CGFloat = n.size == "xl" ? 80 : (n.size == "m" ? 32 : 52)
        VStack(alignment: .leading, spacing: 2) {
            if let l = n.label, !l.isEmpty { Text(l).font(E.body(12)).foregroundStyle(E.text3) }
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Text(n.text ?? "")
                    .font(n.size == "m" ? E.light(big) : E.thin(big))
                    .kerning(n.size == "xl" ? -3 : -1)
                    .foregroundStyle(E.text)
                    .minimumScaleFactor(0.5).lineLimit(1)
                if let u = n.unit, !u.isEmpty {
                    Text(displayUnit(u)).font(E.light(n.size == "xl" ? 24 : 17)).foregroundStyle(E.text)
                }
            }
        }
    }

    private func dotsView(_ n: CNode) -> some View {
        let items = n.items ?? []
        return VStack(alignment: .leading, spacing: 6) {
            if items.count > 14 {
                // 15–30 天：点变小、间距收窄，一排放得下（≤ 14 天和按周给的 ≤ 13 条还是原来的样子）
                DenseDots(items: items)
            } else {
                HStack(spacing: 7) {
                    ForEach(items) { it in
                        ZStack {
                            if it.on == true {
                                Circle().fill(E.text)
                            } else {
                                Circle().strokeBorder(it.now == true ? E.text : E.text3, lineWidth: 1)
                            }
                            if it.now == true && it.on != true { Circle().fill(E.text).frame(width: 3, height: 3) }
                        }
                        .frame(width: 10, height: 10)
                    }
                }
            }
            if let c = n.caption { Text(c).font(E.body(11)).foregroundStyle(E.text3) }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(n.caption ?? "")
    }

    private func barView(_ n: CNode) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Rectangle().fill(E.line).frame(height: 1)
                    Rectangle().fill(E.text).frame(width: g.size.width * CGFloat(n.fraction ?? 0), height: 2)
                    if let m = n.marker {
                        Rectangle().fill(E.text2).frame(width: 1, height: 10).offset(x: g.size.width * CGFloat(m))
                    }
                }
                .frame(height: 10)
            }
            .frame(height: 10)
            HStack {
                Text(n.left ?? "").font(E.body(12)).foregroundStyle(E.text2)
                Spacer()
                Text(n.right ?? "").font(E.body(12)).foregroundStyle(E.text3)
            }
        }
    }

    /// 竖柱图：每天一根，从 0 起画。实心 = 达标（睡够、走够）或最后一根；空心 = 没达标。
    /// 睡眠每根柱上有一道短横线标当晚需要多少；步数有一条虚线目标线。最后一根柱顶写数。
    private func columnsView(_ n: CNode) -> some View {
        let items = n.items ?? []
        let h: CGFloat = n.height == "m" ? 124 : 84
        let top = Swift.max(n.max ?? 0, items.compactMap(\.value).max() ?? 0, 0.0001) * 1.12
        let every = items.count > 8 ? 2 : 1
        // 15–30 天：柱子细一点，日期只写第一天 / 中间 / 最后一天（每隔一个写也挤不下）
        let dense = items.count > 14
        return VStack(alignment: .leading, spacing: 6) {
            GeometryReader { g in
                let W = g.size.width
                let slot = W / CGFloat(Swift.max(items.count, 1))
                let bw = Swift.min(14, slot * (dense ? 0.5 : 0.42))
                let y: (Double) -> CGFloat = { v in h - CGFloat(v / top) * h }
                ZStack(alignment: .topLeading) {
                    Rectangle().fill(E.line).frame(width: W, height: 1).offset(y: h - 1)
                    if let r = n.ref {
                        Path { p in p.move(to: CGPoint(x: 0, y: y(r))); p.addLine(to: CGPoint(x: W, y: y(r))) }
                            .stroke(E.text3, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    }
                    ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                        let cx = slot * (CGFloat(i) + 0.5)
                        let v = it.value ?? 0
                        let bh = Swift.max(1, h - y(v))
                        Group {
                            if it.on == true {
                                RoundedRectangle(cornerRadius: 2, style: .continuous).fill(E.text)
                            } else {
                                RoundedRectangle(cornerRadius: 2, style: .continuous).strokeBorder(E.text3, lineWidth: 1)
                            }
                        }
                        .frame(width: bw, height: bh)
                        .position(x: cx, y: h - bh / 2)
                        if let r = it.ref {
                            Rectangle().fill(E.text2).frame(width: Swift.min(bw + 6, slot - 2), height: 1).position(x: cx, y: y(r))
                        }
                        if i == items.count - 1, let t = it.text {
                            // 柱子密的时候数字比一根柱宽，会盖到旁边几根：放到最后三根里最高的那根上面
                            let under = dense ? items.suffix(3).map { $0.value ?? 0 }.max() ?? v : v
                            Text(t).font(E.body(10)).foregroundStyle(E.text2).monospacedDigit()
                                .fixedSize()
                                .padding(.horizontal, 3)
                                .background(E.bg)          // 盖住穿过去的目标虚线，数字不和线叠在一起
                                .position(x: Swift.min(cx, W - 14), y: Swift.max(6, y(Swift.max(under, v)) - 9))
                        }
                    }
                }
            }
            .frame(height: h)
            if dense {
                sparseColumnLabels(items)
            } else {
                HStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { i, it in
                        // 隔一个写一个时（9–14 条，含按周给的）字伸进旁边的空位，不再缩小
                        Text((items.count - 1 - i) % every == 0 ? (it.label ?? "") : "")
                            .font(E.body(9)).foregroundStyle(it.now == true ? E.text2 : E.text3)
                            .lineLimit(1).minimumScaleFactor(every > 1 ? 1 : 0.7)
                            .fixedSize(horizontal: every > 1, vertical: false)
                            .frame(maxWidth: .infinity)
                    }
                }
            }
            HStack {
                if let c = n.caption { Text(c).font(E.body(11)).foregroundStyle(E.text3) }
                Spacer()
                if let r = n.refLabel { Text(r).font(E.body(11)).foregroundStyle(E.text3) }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(([n.caption, n.refLabel] + items.map { "\($0.spokenLabel) \($0.text ?? "")" })
            .compactMap { $0 }.joined(separator: "，"))
    }

    /// 柱子多（> 14）时的日期：只写第一根（左对齐）、中间一根（居中）、最后一根（右对齐），字不缩小、不出界
    private func sparseColumnLabels(_ items: [CItem]) -> some View {
        let n = items.count
        let picks = Array(Set([0, (n - 1) / 2, n - 1])).sorted()
        return GeometryReader { g in
            let slot = g.size.width / CGFloat(Swift.max(n, 1))
            ZStack(alignment: .topLeading) {
                ForEach(picks, id: \.self) { i in
                    let it = items[i]
                    let anchor: Alignment = i == 0 ? .leading : (i == n - 1 ? .trailing : .center)
                    // 每个字放在一个和整行一样宽的框里，按对齐方式贴左 / 居中到那根柱 / 贴右
                    Text(it.label ?? "")
                        .font(E.body(9)).foregroundStyle(it.now == true ? E.text2 : E.text3)
                        .lineLimit(1).fixedSize()
                        .frame(width: anchor == .center ? nil : g.size.width, alignment: anchor)
                        .position(x: anchor == .center ? slot * (CGFloat(i) + 0.5) : g.size.width / 2, y: 6)
                }
            }
        }
        .frame(height: 12)
    }

    private func ringView(_ n: CNode) -> some View {
        ZStack {
            Circle().stroke(E.line, lineWidth: 1.5)
            Circle().trim(from: 0, to: CGFloat(n.fraction ?? 0))
                .stroke(E.text, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: 0) {
                Text(n.text ?? "").font(E.light(24)).foregroundStyle(E.text).monospacedDigit()
                    .minimumScaleFactor(0.5).lineLimit(1)
                if let s = n.sub { Text(s).font(E.body(10)).foregroundStyle(E.text3).lineLimit(1) }
            }
            .padding(.horizontal, 8)
        }
        .frame(width: 84, height: 84)
    }
}

/// 对话里的画布卡：把 P-Health 写的零件树交给服务器校验、现算，拿回来再画。
/// 算好的结果按「零件树 + 位置」缓存在内存和磁盘：再打开对话直接画出原高度，不再先显示细线、加载完把页面顶走
struct CanvasCard: View {
    let raw: Data
    var slot: String = "chat"
    @State private var node: CNode?
    @State private var failed: String?

    init(raw: Data, slot: String = "chat") {
        self.raw = raw
        self.slot = slot
        _node = State(initialValue: CanvasCache.node(raw: raw, slot: slot))
    }

    var body: some View {
        Group {
            if let node { CanvasView(node: node) }
            else if let failed { Text(failed).font(E.body(13)).foregroundStyle(E.text3) }
            else { WorkingLine().padding(.vertical, 24) }
        }
        .task(id: raw) { if node == nil { await load() } }
        // 容器：只给自己加标识，里面的零件保留各自的标识和朗读（不加 .contain 会把标识盖到每个子元素上）
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("canvas-card")
    }

    private func load() async {
        let body: [String: Any] = ["layout": (try? JSONSerialization.jsonObject(with: raw)) ?? [:], "slot": slot]
        let data: Data
        do {
            (data, _) = try await PivisAPI.send(PivisAPI.request("api/v3/canvas", method: "POST", json: body))
        } catch PivisAPI.Failure.http(_, let msg) {
            failed = "这张卡不合规范，没画" + (msg.map { "：\($0)" } ?? "")
            return
        } catch {
            failed = "这张卡暂时画不出来（连不上服务器）"
            return
        }
        node = CanvasCache.decode(data)
        if node == nil { failed = "这张卡暂时画不出来" } else { CanvasCache.store(data, raw: raw, slot: slot) }
    }
}

/// 画布卡结果缓存：内存 + Caches/canvas/<hash>.json（服务器原样返回的数据）
enum CanvasCache {
    private struct R: Decodable { let layout: CNode }
    private static let memory: NSCache<NSString, MemoBox<CNode>> = { let c = NSCache<NSString, MemoBox<CNode>>(); c.countLimit = 120; return c }()
    private static let dir: URL = {
        let d = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("canvas", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }()

    private static func key(raw: Data, slot: String) -> String {
        // FNV-1a：稳定、跨启动一致（Swift 的 hashValue 每次启动都不同）
        var h: UInt64 = 0xcbf29ce484222325
        for b in raw { h = (h ^ UInt64(b)) &* 0x100000001b3 }
        for b in slot.utf8 { h = (h ^ UInt64(b)) &* 0x100000001b3 }
        return String(h, radix: 16)
    }

    static func decode(_ data: Data) -> CNode? { (try? PivisAPI.decoder.decode(R.self, from: data))?.layout }

    static func node(raw: Data, slot: String) -> CNode? {
        let k = key(raw: raw, slot: slot)
        if let hit = memory.object(forKey: k as NSString) { return hit.value }
        guard let data = try? Data(contentsOf: dir.appendingPathComponent(k + ".json")), let n = decode(data) else { return nil }
        memory.setObject(MemoBox(n), forKey: k as NSString)
        return n
    }

    static func store(_ data: Data, raw: Data, slot: String) {
        let k = key(raw: raw, slot: slot)
        if let n = decode(data) { memory.setObject(MemoBox(n), forKey: k as NSString) }
        try? data.write(to: dir.appendingPathComponent(k + ".json"), options: .atomic)
    }
}


// MARK: - 验收用：一次只画一张画布卡（模拟器回放下 -canvasGallery <json 文件> -galleryIndex N）
// 条目里有 "layout" 就交给服务器校验现算；有 "resolved"（服务器算好的零件树）就在本地直接画，不连服务器。
struct CanvasGallery: View {
    struct Item: Decodable { let title: String; let slot: String?; let label: String?; let level: String? }
    let path: String
    let index: Int
    @State private var item: Item?
    @State private var raw: Data?
    @State private var resolved: CNode?

    @ViewBuilder
    private func card(slot: String) -> some View {
        if let resolved { CanvasView(node: resolved) }
        else if let raw { CanvasCard(raw: raw, slot: slot) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let item {
                    Text(item.title).font(E.body(12)).foregroundStyle(E.text3)
                    if item.slot == "hero" {
                        VStack(alignment: .leading, spacing: 0) {
                            Hairline()
                            HStack(alignment: .firstTextBaseline) {
                                Text(item.label ?? "主卡").font(E.body(15)).foregroundStyle(E.text2)
                                Spacer()
                                LevelTag(level: item.level ?? "watch", label: ["act": "需要处理", "watch": "留意", "steady": "平稳"][item.level ?? "watch"] ?? "")
                            }
                            .padding(.top, 18)
                            card(slot: "hero").padding(.top, 14)
                        }
                    } else if raw != nil || resolved != nil {
                        HStack(alignment: .top, spacing: 8) {
                            EAvatar().padding(.top, 2)
                            card(slot: "chat")
                                .padding(.vertical, 14).padding(.horizontal, 16)
                                .frame(maxWidth: 312, alignment: .leading)
                                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(E.line, lineWidth: 1))
                        }
                    }
                }
            }
            .padding(.horizontal, E.gutter)
            .padding(.top, 60)
        }
        .background(E.bg.ignoresSafeArea())
        .task {
            guard let data = FileManager.default.contents(atPath: path),
                  let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]], index < arr.count else { return }
            let obj = arr[index]
            if let lay = obj["layout"] { raw = try? JSONSerialization.data(withJSONObject: lay) }
            if let res = obj["resolved"], let d = try? JSONSerialization.data(withJSONObject: res) {
                resolved = try? PivisAPI.decoder.decode(CNode.self, from: d)
            }
            item = Item(title: obj["title"] as? String ?? "", slot: obj["slot"] as? String,
                        label: obj["label"] as? String, level: obj["level"] as? String)
        }
    }
}
