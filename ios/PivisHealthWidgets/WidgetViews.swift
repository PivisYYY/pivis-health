import WidgetKit
import SwiftUI
import AppIntents

// 和 App 同一套：黑底、白字、细线。值和 App 的 E（PivisHealth/V3Theme.swift）一模一样，改一边要两边一起改
private enum W {
    static let text = Color.white
    static let text2 = Color(white: 0.604)   // #9A9A9A = E.text2
    static let text3 = Color(white: 0.478)   // #7A7A7A = E.text3
    static let stroke = Color(white: 0.2)    // #333333 = E.stroke
    static let line = Color(white: 0.149)    // #262626 = E.line
    static func pageId(_ board: String) -> String { ["sleep": "sleep", "sport": "sport", "stress": "stress"][board] ?? "now" }
    /// 点一行：切到那一页展开那张卡；练习带 play=1，App 直接全屏播
    static func todoURL(_ t: WDoc.Todo) -> URL {
        URL(string: "phealth://todo/\(t.id)?board=\(pageId(t.board))" + (t.play == true ? "&play=1" : ""))!
    }
    static func minutes(_ m: Double?) -> String {
        guard let m, m > 0 else { return "" }
        return "\(Int(m.rounded())) 分钟"
    }
}

private struct MarkHeader: View {
    let title: String
    var body: some View {
        HStack(spacing: 6) {
            Image("Mark").resizable().renderingMode(.template).aspectRatio(contentMode: .fit).frame(width: 18, height: 9)
                .foregroundStyle(W.text)
            Text(title).font(.system(size: 12)).foregroundStyle(W.text2)
        }
    }
}

private struct EmptyNote: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 12)).foregroundStyle(W.text3).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

// MARK: ① 此刻 · 小号
struct NowView: View {
    let entry: PHEntry
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            MarkHeader(title: "此刻")
            if let h = entry.doc?.hero {
                Spacer(minLength: 6)
                if !h.value.isEmpty {
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(h.value).font(.system(size: 40, weight: .thin)).monospacedDigit()
                            .minimumScaleFactor(0.5).lineLimit(1)
                        Text(h.unit).font(.system(size: 12)).foregroundStyle(W.text2)
                    }
                    .foregroundStyle(W.text)
                }
                Text([h.label, h.boardLabel].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.system(size: 11)).foregroundStyle(W.text3).lineLimit(1)
                Spacer(minLength: 6)
                Text(h.note).font(.system(size: 12)).foregroundStyle(W.text).lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                EmptyNote(text: "打开 P-Health 一次，这里就会有内容")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .containerBackground(for: .widget) { Color.black }
        .widgetURL(URL(string: "phealth://page/now"))
    }
}

// MARK: ② 接下来 · 中号
struct NextView: View {
    let entry: PHEntry
    var body: some View {
        let items = entry.doc?.upcoming(at: entry.date) ?? []
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("接下来").font(.system(size: 12)).foregroundStyle(W.text2)
                Spacer()
                if let doc = entry.doc { Text("\(doc.upcoming(at: entry.date, limit: 99).count) 件").font(.system(size: 12)).foregroundStyle(W.text3) }
            }
            .padding(.bottom, 4)
            if entry.doc == nil {
                EmptyNote(text: "打开 P-Health 一次，这里就会有内容")
            } else if items.isEmpty {
                EmptyNote(text: "今天没有要做的了")
            } else {
                ForEach(Array(items.enumerated()), id: \.element.id) { i, t in
                    row(t)
                    if i < items.count - 1 { Rectangle().fill(W.stroke).frame(height: 0.5) }
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .containerBackground(for: .widget) { Color.black }
        .widgetURL(URL(string: "phealth://page/now"))
    }

    private func row(_ t: WDoc.Todo) -> some View {
        HStack(spacing: 10) {
            Link(destination: W.todoURL(t)) {
                HStack(spacing: 10) {
                    Text(t.when.isEmpty ? "—" : t.when).font(.system(size: 15, weight: .light)).monospacedDigit()
                        .foregroundStyle(t.when.isEmpty ? W.text3 : W.text).frame(width: 44, alignment: .leading)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(t.title).font(.system(size: 14)).foregroundStyle(W.text).lineLimit(1)
                        let sub = [t.boardLabel, t.play == true ? W.minutes(t.durationMin) : t.note].filter { !$0.isEmpty }.joined(separator: " · ")
                        if !sub.isEmpty { Text(sub).font(.system(size: 10.5)).foregroundStyle(W.text3).lineLimit(1) }
                    }
                    Spacer(minLength: 4)
                }
            }
            if t.check {
                Button(intent: CompleteTodoIntent(todoId: t.id)) {
                    Image(systemName: "checkmark").font(.system(size: 10, weight: .light)).foregroundStyle(W.text)
                        .frame(width: 26, height: 26)
                        .overlay(Circle().strokeBorder(W.text2, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("做了：\(t.title)")
            } else if t.play == true {
                // 练习：点 ▶ 直接进 App 全屏播
                Link(destination: W.todoURL(t)) {
                    Image(systemName: "play.fill").font(.system(size: 9)).foregroundStyle(W.text)
                        .frame(width: 26, height: 26)
                        .overlay(Circle().strokeBorder(W.text2, lineWidth: 1))
                }
                .accessibilityLabel("播放：\(t.title)")
            } else {
                // 每条都有一个细线圆圈图标（和 App 里一样）：设备自动记 = 波形，计时 = 开始，要选 = 问号，要填 = 笔；点了进 App 这张卡
                let glyph = t.auto == true ? "waveform"
                    : (t.kind == "follow" || t.kind == "timer") ? "play"
                    : ["options", "proposal", "scale"].contains(t.kind) ? "questionmark" : "pencil"
                Link(destination: W.todoURL(t)) {
                    Image(systemName: glyph).font(.system(size: 10, weight: .light)).foregroundStyle(t.auto == true ? W.text2 : W.text)
                        .frame(width: 26, height: 26)
                        .overlay(Circle().strokeBorder(W.text2, lineWidth: 1))
                }
                .accessibilityLabel(t.auto == true ? "设备会自动记：\(t.title)" : "打开：\(t.title)")
            }
        }
        .frame(maxHeight: .infinity)
    }
}

// MARK: ④ 近 7 晚 · 中号
struct SleepView: View {
    let entry: PHEntry
    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(alignment: .leading, spacing: 0) {
                Text("近 7 晚").font(.system(size: 12)).foregroundStyle(W.text2)
                Spacer(minLength: 4)
                if let s = entry.doc?.sleep, let last = s.last {
                    Text("昨晚").font(.system(size: 11)).foregroundStyle(W.text3)
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(String(format: "%.1f", last)).font(.system(size: 34, weight: .thin)).monospacedDigit()
                        Text("小时").font(.system(size: 11)).foregroundStyle(W.text2)
                    }
                    .foregroundStyle(W.text)
                    Spacer(minLength: 4)
                    if let n = s.need { Text("需要 \(String(format: "%.1f", n))").font(.system(size: 11)).foregroundStyle(W.text3) }
                    if let sh = s.short, sh > 0 { Text("昨晚缺 \(String(format: "%.1f", sh))").font(.system(size: 11)).foregroundStyle(W.text3) }
                } else {
                    EmptyNote(text: "还没有睡眠数据")
                }
            }
            .frame(width: 104, alignment: .leading)
            if let nights = entry.doc?.sleep.nights, !nights.isEmpty { bars(nights) }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .containerBackground(for: .widget) { Color.black }
        .widgetURL(URL(string: "phealth://page/sleep"))
    }

    /// 和休息页同一张竖柱：空心柱 = 睡了多久，短横线 = 那晚需要多少，最右实心是昨晚
    private func bars(_ nights: [WDoc.Night]) -> some View {
        let top = max(1, (nights.map(\.hours) + nights.compactMap(\.need)).max() ?? 1) * 1.08
        return GeometryReader { g in
            let labelH: CGFloat = 14
            let h = g.size.height - labelH - 4
            let n = CGFloat(nights.count)
            let slot = g.size.width / n
            let barW = min(14, slot * 0.5)
            ZStack(alignment: .topLeading) {
                ForEach(Array(nights.enumerated()), id: \.offset) { i, night in
                    let x = slot * CGFloat(i) + slot / 2
                    let bh = max(2, h * CGFloat(night.hours / top))
                    let last = i == nights.count - 1
                    Group {
                        if last {
                            RoundedRectangle(cornerRadius: 2).fill(W.text)
                        } else {
                            RoundedRectangle(cornerRadius: 2).strokeBorder(W.text, lineWidth: 1)
                        }
                    }
                    .frame(width: barW, height: bh)
                    .position(x: x, y: h - bh / 2)
                    if let need = night.need {
                        Rectangle().fill(W.text3).frame(width: slot * 0.72, height: 1)
                            .position(x: x, y: h - h * CGFloat(need / top))
                    }
                    Text(label(nights, i)).font(.system(size: 9, weight: last ? .semibold : .regular))
                        .foregroundStyle(last ? W.text : W.text3)
                        .fixedSize()
                        .position(x: x, y: h + 4 + labelH / 2)
                }
            }
        }
    }

    /// 第一天和每月 1 号写「月/日」，其余只写日
    private func label(_ nights: [WDoc.Night], _ i: Int) -> String {
        let p = nights[i].date.split(separator: "-")
        guard p.count >= 3, let m = Int(p[1]), let d = Int(p[2]) else { return nights[i].date }
        return i == 0 || d == 1 ? "\(m)/\(d)" : "\(d)"
    }
}

// MARK: ③ 锁屏 · 长方形 + 顶上一行
struct NextLockView: View {
    let entry: PHEntry
    @Environment(\.widgetFamily) private var family
    var body: some View {
        let t = entry.doc?.upcoming(at: entry.date, limit: 1).first
        Group {
            if family == .accessoryInline {
                if let t {
                    Text("\(Image("Mark")) \(t.when.isEmpty ? "" : t.when + " ")\(t.title)")
                } else {
                    Text("\(Image("Mark")) 今天没有待办了")
                }
            } else {
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 4) {
                        Image("Mark").resizable().renderingMode(.template).aspectRatio(contentMode: .fit).frame(width: 16, height: 8)
                        Text(t.map { [$0.when, $0.boardLabel].filter { !$0.isEmpty }.joined(separator: " · ") } ?? "P-Health")
                            .font(.system(size: 12))
                    }
                    Text(t?.title ?? "今天没有待办了").font(.system(size: 15, weight: .semibold)).lineLimit(1)
                    if let note = t?.note, !note.isEmpty { Text(note).font(.system(size: 12)).lineLimit(1) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .containerBackground(for: .widget) { Color.clear }
        .widgetURL(t.map { W.todoURL($0) } ?? URL(string: "phealth://page/now"))
    }
}

// MARK: ③ 锁屏 · 圆形：离上床时间窗还有多久
struct BedView: View {
    let entry: PHEntry
    var body: some View {
        Group {
            if let doc = entry.doc, let bed = doc.bed?.atDate, bed > doc.refNow(entry.date) {
                let left = bed.timeIntervalSince(doc.refNow(entry.date))
                let window: Double = 6 * 3600
                Gauge(value: min(left, window), in: 0...window) {
                    Text("到上床")
                } currentValueLabel: {
                    VStack(spacing: 0) {
                        Text(hm(left)).font(.system(size: 14, weight: .semibold)).monospacedDigit()
                        Text("到上床").font(.system(size: 8))
                    }
                }
                .gaugeStyle(.accessoryCircularCapacity)
            } else {
                ZStack {
                    AccessoryWidgetBackground()
                    Image("Mark").resizable().renderingMode(.template).aspectRatio(contentMode: .fit).padding(12)
                }
            }
        }
        .containerBackground(for: .widget) { Color.clear }
        .widgetURL(URL(string: "phealth://page/sleep"))
    }

    private func hm(_ s: Double) -> String {
        let m = Int(s / 60)
        return String(format: "%d:%02d", m / 60, m % 60)
    }
}
