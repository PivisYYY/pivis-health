import SwiftUI

// MARK: - 对话里带进来的习惯卡 / 待办卡
// 卡是对话内容的一部分：放在这次对话开始的位置（以前的聊天记录在它上面），打开时顶在屏幕上方，
// 跟着对话一起滚走，不再钉在顶上、也没有自己的滚动区（以前两个滚动区抢一块屏幕，聊天从卡底下露出来）。
// 卡划出屏幕后，顶上出一行（ChatAboutCapsule），点它滚回卡。卡头的收起钮把卡收成同样的一行，点那一行再展开。
// 视频先只放封面，点了才建播放器；播放器由对话页拿着，卡划走、收成一行时正在放的视频不断（那一行上有暂停钮）。
// P-Health 不会因为打开对话就说话；它在忙的时候，卡头 / 那一行的名字下面一条细线在走（不写字）。
// 左右边、圆角、内边距都用 E 里的对话版式（chatGutter / cardRadius / cardPad），和消息、输入栏贴同一组边。

/// 对话里的那张卡（展开 = 整张卡；收起 = 一行）
struct ChatAboutCard: View {
    let about: ChatAbout
    let habit: V3HabitDoc?
    /// 习惯还没取回来时，图标按对话所在的板块画
    let board: String
    @Binding var expanded: Bool
    /// P-Health 正在忙（这个对话里）
    var working = false
    /// 只传下去、不在这里观察：播放进度每半秒一变，只让视频框和暂停钮跟着重画
    let player: PracticePlayer

    var body: some View {
        if expanded {
            full
        } else {
            ChatAboutLine(about: about, habit: habit, board: board, working: working, player: player,
                          chevron: "chevron.down",
                          actionLabel: about.kind == .habit ? "展开习惯卡" : "展开待办",
                          actionId: "chat-about-collapsed") {
                withAnimation(.easeOut(duration: 0.25)) { expanded = true }
            }
        }
    }

    // MARK: 展开
    private var full: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if about.kind == .habit { habitBody } else { todoBody }
        }
        .padding(E.cardPad)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: E.cardRadius, style: .continuous)
            .strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(about.kind == .habit ? "habit-card" : "todo-about-card")
    }

    /// 卡头：图标、名字（忙时名字下一条细线在走）、右边第几天、收起钮。收起后那一行就是这个卡头
    private var header: some View {
        HStack(spacing: 12) {
            AboutGlyph(about: about, habit: habit, board: board)
            Text(aboutTitle(about, habit)).font(E.body(17)).foregroundStyle(E.text).lineLimit(1)
                .overlay(alignment: .bottomLeading) { AboutWorking(on: working).offset(y: 7) }
            Spacer(minLength: 8)
            if let h = habit {
                Text(h.state == "active" ? "第 \(h.day) 天 / \(h.days)" : h.summary)
                    .font(E.body(12)).foregroundStyle(E.text2).lineLimit(1)
            }
            Button {
                withAnimation(.easeOut(duration: 0.25)) { expanded = false }
            } label: {
                Image(systemName: "chevron.up").font(.system(size: 11, weight: .light)).foregroundStyle(E.text2)
                    .frame(width: 32, height: 32)
                    .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                    .hitArea(6, 6)
            }
            .buttonStyle(EPress())
            .accessibilityLabel(about.kind == .habit ? "收起习惯卡" : "收起待办")
            .accessibilityIdentifier("chat-about-collapse")
        }
    }

    // MARK: 习惯卡：本周 7 天 + 每套训练「时间 → 视频」
    @ViewBuilder
    private var habitBody: some View {
        if let h = habit {
            HabitWeek(days: h.week).padding(.top, 16)
            VStack(alignment: .leading, spacing: 24) {
                ForEach(h.sessions) { s in
                    VStack(alignment: .leading, spacing: 10) {
                        VStack(alignment: .leading, spacing: 2) {
                            // 只有一套、和习惯同名：卡头已经写了名字，这里不再重复，只留时间
                            if s.title != h.name || s.today {
                                HStack(spacing: 8) {
                                    Text(s.title).font(E.body(15)).foregroundStyle(E.text)
                                    if s.today {
                                        Text("今天").font(E.body(11)).foregroundStyle(Color.black)
                                            .padding(.horizontal, 8).frame(height: 20)
                                            .background(Capsule().fill(E.text))
                                    }
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
        } else {
            WorkingLine().frame(width: 90, height: 18).padding(.top, 20)
        }
    }

    // MARK: 待办卡（练习就是标题 + 视频）
    @ViewBuilder
    private var todoBody: some View {
        if let t = about.todo {
            let meta = todoMeta(t)
            if !meta.isEmpty || !t.note.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    if !meta.isEmpty { Text(meta).font(E.body(12)).foregroundStyle(E.text3) }
                    if !t.note.isEmpty { Text(t.note).font(E.body(13)).foregroundStyle(E.text2) }
                }
                .padding(.top, 12)
            }
            if let v = t.practiceVideo {
                PracticeVideoView(media: v, player: player).padding(.top, 12)
            }
        }
    }
}

/// 卡划出屏幕后顶上那一行：和收起的卡同一个样子；点了滚回卡（箭头指着卡在哪边）
struct ChatAboutCapsule: View {
    let about: ChatAbout
    let habit: V3HabitDoc?
    let board: String
    var working = false
    /// 卡在屏幕上方（往回滚是往上）
    var cardAbove = true
    let player: PracticePlayer
    let onTap: () -> Void

    var body: some View {
        ChatAboutLine(about: about, habit: habit, board: board, working: working, player: player,
                      chevron: cardAbove ? "chevron.up" : "chevron.down",
                      actionLabel: about.kind == .habit ? "回到习惯卡" : "回到待办",
                      actionId: "chat-about-capsule", action: onTap)
    }
}

/// 一行：图标、名字（忙时下面一条细线在走）、一句摘要、箭头；有视频在放或暂停着，行尾一个暂停 / 继续
private struct ChatAboutLine: View {
    let about: ChatAbout
    let habit: V3HabitDoc?
    let board: String
    let working: Bool
    let player: PracticePlayer
    let chevron: String
    let actionLabel: String
    let actionId: String
    let action: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            Button(action: action) {
                HStack(spacing: 10) {
                    AboutGlyph(about: about, habit: habit, board: board)
                    Text(aboutTitle(about, habit)).font(E.body(15)).foregroundStyle(E.text).lineLimit(1)
                        .layoutPriority(1)
                        .overlay(alignment: .bottomLeading) { AboutWorking(on: working).offset(y: 6) }
                    Text(aboutSummary(about, habit)).font(E.body(12)).foregroundStyle(E.text2).lineLimit(1)
                    Spacer(minLength: 4)
                    Image(systemName: chevron).font(.system(size: 11, weight: .light)).foregroundStyle(E.text2)
                        .frame(width: 32, height: 32)
                        .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                }
                .padding(.leading, 10)      // 28 的图标在 48 高的胶囊里同心
                .frame(maxHeight: .infinity)
                .contentShape(Rectangle())
            }
            .buttonStyle(EPress())
            .accessibilityLabel(actionLabel)
            .accessibilityIdentifier(actionId)
            AboutPlayPause(player: player)
        }
        .padding(.trailing, 8)
        .frame(height: 48)
        .background(Capsule().fill(Color.black))
        .overlay(Capsule().strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
    }
}

/// 卡的图标：习惯带了图标就画它，否则画板块图标；待办画它所在板块的图标
private struct AboutGlyph: View {
    let about: ChatAbout
    let habit: V3HabitDoc?
    let board: String
    var body: some View {
        if about.kind == .habit {
            ProjectGlyph(icon: habit?.icon, board: habit?.board ?? board)
        } else {
            ProjectGlyph(icon: nil, board: about.todo?.board ?? board)
        }
    }
}

/// P-Health 在忙时对话里的卡不动（Psir 11-11：同时动的东西太多了，对话里的待办单可以不动）。
/// 忙不忙只看头像那一行；这里只留给读屏一句话。
private struct AboutWorking: View {
    let on: Bool
    var body: some View {
        if on {
            Color.clear.frame(width: 1, height: 1).accessibilityLabel("P-Health 在处理")
        }
    }
}

private func aboutTitle(_ about: ChatAbout, _ habit: V3HabitDoc?) -> String { habit?.name ?? about.name }

private func aboutSummary(_ about: ChatAbout, _ habit: V3HabitDoc?) -> String {
    if about.kind == .habit { return habit?.summary ?? "" }
    guard let t = about.todo else { return "" }
    return todoMeta(t)
}

private func todoMeta(_ t: V3Todo) -> String {
    var parts: [String] = []
    if !t.when.isEmpty { parts.append("今天 \(t.when)") }
    if let d = t.durationMin ?? t.practiceVideo?.durationMin, d > 0 { parts.append("\(Int(d.rounded())) 分钟") }
    return parts.joined(separator: " · ")
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
