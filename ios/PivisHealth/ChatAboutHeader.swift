import SwiftUI

// MARK: - 对话顶部：带进来的习惯卡 / 待办卡
// 习惯卡：本周完成点 + 每套训练「标题 → 视频」（和对话里的视频卡一样，就地播放，没有别的按钮）。
// 视频先只放封面，点了才建播放器；播放器由对话页拿着，卡收成一行时正在放的视频不断（行上有暂停钮）。
// 往上翻聊天记录、或者发了消息，卡收成一行；点那一行再展开。P-Health 不会因为打开对话就说话。
struct ChatAboutHeader: View {
    let about: ChatAbout
    let habit: V3HabitDoc?
    @Binding var expanded: Bool
    let maxHeight: CGFloat
    /// 只传下去、不在这里观察：播放进度每半秒一变，只让视频框和暂停钮跟着重画
    let player: PracticePlayer

    var body: some View {
        Group {
            if expanded { full } else { collapsed }
        }
        .padding(.horizontal, 14)
        .padding(.top, 10)
        .padding(.bottom, 8)
        .background(Color.black)
    }

    // MARK: 收成一行
    private var collapsed: some View {
        HStack(spacing: 6) {
            Button {
                withAnimation(.easeOut(duration: 0.25)) { expanded = true }
            } label: {
                HStack(spacing: 10) {
                    Text(title).font(E.body(15)).foregroundStyle(E.text).lineLimit(1)
                    Text(summary).font(E.body(12)).foregroundStyle(E.text2).lineLimit(1)
                    Spacer(minLength: 4)
                    Image(systemName: "chevron.down").font(.system(size: 11, weight: .light)).foregroundStyle(E.text2)
                        .frame(width: 32, height: 32)
                        .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                }
                .padding(.leading, 18)
                .frame(maxHeight: .infinity)
                .contentShape(Rectangle())
            }
            .buttonStyle(EPress())
            .accessibilityLabel(about.kind == .habit ? "展开习惯卡" : "展开待办")
            .accessibilityIdentifier("chat-about-collapsed")
            // 卡收起来时视频还在放：行尾给一个暂停 / 继续
            AboutPlayPause(player: player)
        }
        .padding(.trailing, 8)
        .frame(height: 48)
        .overlay(Capsule().strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
    }

    // MARK: 展开
    private var full: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if about.kind == .habit { habitBody } else { todoBody }
                }
                .padding(.horizontal, 16)
                .padding(.top, 16)
            }
            .scrollIndicators(.hidden)
            .frame(maxHeight: maxHeight)
            .fixedSize(horizontal: false, vertical: true)
            Button {
                withAnimation(.easeOut(duration: 0.25)) { expanded = false }
            } label: {
                Image(systemName: "chevron.up").font(.system(size: 11, weight: .light)).foregroundStyle(E.text3)
                    .frame(maxWidth: .infinity, minHeight: 30)
                    .contentShape(Rectangle())
            }
            .buttonStyle(EPress())
            .accessibilityLabel(about.kind == .habit ? "收起习惯卡" : "收起待办")
            .accessibilityIdentifier("chat-about-collapse")
        }
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(about.kind == .habit ? "habit-card" : "todo-about-card")
    }

    private var title: String { habit?.name ?? about.name }

    private var summary: String {
        if about.kind == .habit { return habit?.summary ?? "" }
        guard let t = about.todo else { return "" }
        return todoMeta(t)
    }

    // MARK: 习惯卡
    @ViewBuilder
    private var habitBody: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(E.body(17)).foregroundStyle(E.text)
            Spacer()
            if let h = habit {
                Text(h.state == "active" ? "第 \(h.day) 天 / \(h.days)" : h.summary)
                    .font(E.body(12)).foregroundStyle(E.text2)
            }
        }
        if let h = habit {
            HabitWeek(days: h.week).padding(.top, 14)
            VStack(alignment: .leading, spacing: 26) {
                ForEach(h.sessions) { s in
                    VStack(alignment: .leading, spacing: 10) {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 8) {
                                Text(s.title).font(E.body(16)).foregroundStyle(E.text)
                                if s.today {
                                    Text("今天").font(E.body(11)).foregroundStyle(Color.black)
                                        .padding(.horizontal, 8).frame(height: 20)
                                        .background(Capsule().fill(E.text))
                                }
                            }
                            if !s.meta.isEmpty { Text(s.meta).font(E.body(12)).foregroundStyle(E.text3) }
                        }
                        if let v = s.video { PracticeVideoView(media: v.media, player: player) }
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("habit-session-\(s.key)")
                }
            }
            .padding(.top, 20)
            .padding(.bottom, 8)
        } else {
            WorkingLine().frame(width: 90, height: 18).padding(.vertical, 20)
        }
    }

    // MARK: 待办卡（练习就是标题 + 视频）
    @ViewBuilder
    private var todoBody: some View {
        if let t = about.todo {
            VStack(alignment: .leading, spacing: 2) {
                Text(t.title).font(E.body(17)).foregroundStyle(E.text)
                let meta = todoMeta(t)
                if !meta.isEmpty { Text(meta).font(E.body(12)).foregroundStyle(E.text3) }
                if !t.note.isEmpty { Text(t.note).font(E.body(13)).foregroundStyle(E.text2).padding(.top, 4) }
            }
            if let v = t.practiceVideo {
                PracticeVideoView(media: v, player: player).padding(.top, 12).padding(.bottom, 8)
            } else {
                Color.clear.frame(height: 8)
            }
        } else {
            Text(about.name).font(E.body(17)).foregroundStyle(E.text).padding(.bottom, 8)
        }
    }

    private func todoMeta(_ t: V3Todo) -> String {
        var parts: [String] = []
        if !t.when.isEmpty { parts.append("今天 \(t.when)") }
        if let d = t.durationMin ?? t.practiceVideo?.durationMin, d > 0 { parts.append("\(Int(d.rounded())) 分钟") }
        return parts.joined(separator: " · ")
    }
}

/// 收成一行时的暂停 / 继续（有视频在放或暂停着才出现）
private struct AboutPlayPause: View {
    @ObservedObject var player: PracticePlayer
    var body: some View {
        if player.player != nil {
            Button { player.toggle() } label: {
                Image(systemName: player.playing ? "pause" : "play")
                    .font(.system(size: 11, weight: .light)).foregroundStyle(E.text)
                    .frame(width: 32, height: 32)
                    .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                    .hitArea(6, 6)
            }
            .buttonStyle(EPress())
            .accessibilityLabel(player.playing ? "暂停视频" : "继续播放视频")
            .accessibilityIdentifier("chat-about-playpause")
        }
    }
}

/// 本周 7 天：做完是实心点；今天一个白圈；以后要练的写那一套的字（B / C）；休息是一个小灰点
struct HabitWeek: View {
    let days: [V3HabitDoc.Day]
    var body: some View {
        HStack(spacing: 0) {
            ForEach(days, id: \.date) { d in
                VStack(spacing: 6) {
                    Text(d.wd).font(E.body(10)).foregroundStyle(E.text3)
                    ZStack {
                        Circle().strokeBorder(d.today ? E.text : Color.clear, lineWidth: 1)
                        switch d.state {
                        case "done": Circle().fill(E.text).frame(width: 10, height: 10)
                        case "part": Circle().fill(E.text2).frame(width: 6, height: 6)
                        case "missed": Circle().strokeBorder(E.stroke, lineWidth: 1).frame(width: 10, height: 10)
                        case "rest": Circle().fill(E.stroke).frame(width: 3, height: 3)
                        default:
                            if !d.label.isEmpty {
                                Text(d.label).font(E.body(11)).foregroundStyle(d.today ? E.text : E.text3)
                            } else if !d.today {
                                Circle().strokeBorder(E.stroke, lineWidth: 1).frame(width: 6, height: 6)
                            }
                        }
                    }
                    .frame(width: 24, height: 24)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(days.map { "\($0.wd)\(Self.spoken($0.state))" }.joined(separator: "，"))
        .accessibilityIdentifier("habit-week")
    }

    private static func spoken(_ s: String) -> String {
        ["done": "做完", "part": "做了一部分", "missed": "没做", "today": "今天", "plan": "要练", "rest": "休息"][s] ?? ""
    }
}
