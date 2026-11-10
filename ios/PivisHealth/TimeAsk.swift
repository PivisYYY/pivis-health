import SwiftUI

// MARK: - P-Health 拟的时间（build 53）：卡上的时间是虚线的，点开一个时间轮 —「好」照这个时间，或者「改成这个时间」。
// 通知上的「换个时间」也走这里（打开 App、展开那张卡、弹出时间轮）。提交走待办的发送队列（断网先记在手机上）。

/// 问哪张卡的时间（卡上点的、或者从通知来的：通知里只带 id 和 when，标题可能没有）
struct TimeAsk: Identifiable, Equatable {
    let id: String
    var title: String = ""
    let when: String
    var date: String = ""
    var why: String? = nil

    init(id: String, title: String = "", when: String, date: String = "", why: String? = nil) {
        self.id = id
        self.title = title
        self.when = when
        self.date = date
        self.why = why
    }

    init(_ todo: V3Todo) {
        self.init(id: todo.id, title: todo.title, when: todo.when, date: todo.date, why: todo.draftWhy)
    }
}

extension Notification.Name {
    /// 弹出时间轮（object = TimeAsk）：根视图统一弹，四个板块页不会各弹一个
    static let pivisAskTime = Notification.Name("pivisAskTime")
}

struct TimeAskSheet: View {
    let ask: TimeAsk
    @State private var picked: Date
    @Environment(\.dismiss) private var dismiss

    init(ask: TimeAsk) {
        self.ask = ask
        _picked = State(initialValue: Self.start(ask))
    }

    /// 时间轮从卡上的时间开始（北京时间）；没有时间就从现在开始
    private static func start(_ ask: TimeAsk) -> Date {
        let day = ask.date.isEmpty ? String(PTime.iso(PTime.serverNow).prefix(10)) : ask.date
        return PTime.date(day: day, hm: ask.when) ?? PTime.serverNow
    }

    private var pickedHM: String { PTime.hhmm(picked) }
    private var changed: Bool { pickedHM != ask.when }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if !ask.title.isEmpty {
                Text(ask.title).font(E.body(15)).foregroundStyle(E.text).lineLimit(2)
                    .padding(.top, 24)
            }
            // 拟这个时间的依据（「按 23:30 上床倒推」）：是信息，小字留着
            if let why = ask.why, !why.isEmpty {
                Text(why).font(E.body(12)).foregroundStyle(E.text3).lineLimit(2)
                    .padding(.top, 4)
            }
            DatePicker("", selection: $picked, displayedComponents: .hourAndMinute)
                .datePickerStyle(.wheel)
                .labelsHidden()
                .environment(\.timeZone, PTime.zone)
                .environment(\.locale, Locale(identifier: "zh_CN"))
                .colorScheme(.dark)
                .frame(maxWidth: .infinity)
                .padding(.top, 8)
                .accessibilityIdentifier("time-ask-wheel")
            HStack(spacing: 12) {
                OutlinePill(title: "好", width: nil) { confirm(nil) }
                    .accessibilityIdentifier("time-ask-ok")
                OutlinePill(title: "改成这个时间", width: nil, filled: changed) { confirm(pickedHM) }
                    .disabled(!changed)
                    .opacity(changed ? 1 : 0.4)
                    .accessibilityIdentifier("time-ask-change")
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 8)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, E.gutter)
        .background(E.bg)
        .preferredColorScheme(.dark)
        // 容器自己一个标识，里面的按钮、时间轮保留各自的标识（不加 .contain 的话外层标识会盖掉里面的）
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("time-ask")
    }

    /// nil = 照原样（「好」）；HH:MM = 换成这个时间。进发送队列，卡上马上变成普通时间
    private func confirm(_ when: String?) {
        Haptic.tap()
        TodoOutbox.shared.enqueue(ask.id, action: "confirm_time", values: when.map { ["when": $0] } ?? [:])
        dismiss()
    }
}
