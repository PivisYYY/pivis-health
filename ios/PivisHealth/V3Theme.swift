import SwiftUI

// MARK: - E 留白：黑底、白字、细线、圆形线框图标。只用灰阶，档位靠字重 / 实心 / 线框 / 虚线区分。
// App 唯一的一套颜色 / 字号（小组件 PivisHealthWidgets/WidgetViews.swift 里的 W 抄的是同样的值，改这里要一起改）。
enum E {
    static let bg = Color.black
    static let text = Color.white
    static let text2 = Color(white: 0.604)   // #9A9A9A
    static let text3 = Color(white: 0.478)   // #7A7A7A
    static let hint = Color(white: 0.43)     // #6E6E6E 输入框里的提示字
    static let grey4A = Color(white: 0.290)  // #4A4A4A 图里的深灰档
    static let grey3A = Color(white: 0.227)  // #3A3A3A 图里的虚框
    static let stroke = Color(white: 0.2)    // #333333 控件描边
    static let line = Color(white: 0.149)    // #262626 分区线
    static let grey1E = Color(white: 0.118)  // #1E1E1E 我的气泡、kv 行间线
    static let line2 = Color(white: 0.102)   // #1A1A1A 行间线
    static let grey14 = Color(white: 0.078)  // #141414 图片、视频还没出来时的底
    static let surface = Color(white: 0.05)  // #0D0D0D 视频框、照片占位的底

    static func light(_ size: CGFloat) -> Font { .system(size: size, weight: .light) }
    static func thin(_ size: CGFloat) -> Font { .system(size: size, weight: .ultraLight) }
    static func body(_ size: CGFloat = 15) -> Font { .system(size: size, weight: .regular) }
    static func medium(_ size: CGFloat = 15) -> Font { .system(size: size, weight: .medium) }
    static let gutter: CGFloat = 24

    /// 「时间 · 标题」一行：待办行、画布 timeline、对话里的方案卡同一套
    static let timeColumn: CGFloat = 52
    static let timeGap: CGFloat = 18
    static let timeFont: Font = .system(size: 17, weight: .light)
}

/// 「时间 · 标题 / 小字」一行（尺寸和待办行一样：时间列 52、间距 18、细体 17）
struct TimeTitleRow: View {
    let when: String
    let title: String
    var note: String? = nil
    var noteLines: Int? = 1
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: E.timeGap) {
            Text(when).font(E.timeFont).foregroundStyle(E.text).monospacedDigit()
                .frame(width: E.timeColumn, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(E.body(15)).foregroundStyle(E.text).fixedSize(horizontal: false, vertical: true)
                if let note, !note.isEmpty {
                    Text(note).font(E.body(12)).foregroundStyle(E.text3).lineLimit(noteLines)
                        .fixedSize(horizontal: false, vertical: noteLines == nil)
                }
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }
}

extension View {
    /// 点的范围往外扩到至少 44pt，画出来的大小和排版位置都不变（四周各扩 inset）
    func hitArea(_ dx: CGFloat, _ dy: CGFloat) -> some View {
        padding(.horizontal, dx).padding(.vertical, dy)
            .contentShape(Rectangle())
            .padding(.horizontal, -dx).padding(.vertical, -dy)
    }
}

/// 细分隔线
struct Hairline: View {
    var color: Color = E.line
    var body: some View { Rectangle().fill(color).frame(height: 1) }
}

/// 白色描边胶囊按钮（主行动）
struct OutlinePill: View {
    let title: String
    var width: CGFloat? = 112
    var filled = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title)
                .font(E.body(15))
                .foregroundStyle(filled ? Color.black : E.text)
                .lineLimit(1)
                .fixedSize()
                .padding(.horizontal, 20)
                .frame(minWidth: width ?? 88, minHeight: 44)   // 至少这么宽，字长就跟着变宽，不溢出
                .background(Capsule().fill(filled ? E.text : Color.clear))
                .overlay(Capsule().strokeBorder(E.text, lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(EPress())
    }
}

/// 灰色文字按钮（次要动作）
struct QuietButton: View {
    let title: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            // 不换行：位置不够时也不能挤成竖排的「晚/点」
            Text(title).font(E.body(13)).foregroundStyle(E.text2)
                .lineLimit(1).fixedSize()
                .padding(.horizontal, 10).frame(minHeight: 44).contentShape(Rectangle())
        }
        .buttonStyle(EPress())
    }
}

/// 选项胶囊（选中 = 白底黑字）
struct ChoiceChip: View {
    let label: String
    let selected: Bool
    var minWidth: CGFloat? = nil
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(label)
                .font(E.body(13))
                .foregroundStyle(selected ? Color.black : E.text)
                .padding(.horizontal, 12)
                .frame(minWidth: minWidth, minHeight: 36)
                .background(Capsule().fill(selected ? E.text : Color.clear))
                .overlay(Capsule().strokeBorder(selected ? E.text : E.stroke, lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(EPress())
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// 档位标签：需要处理 = 实心；留意 = 线框；平稳 = 纯文字；数据不足 = 虚线
struct LevelTag: View {
    let level: String
    let label: String
    var body: some View {
        if level == "nodata" || label.isEmpty {
            EmptyView()   // 不再给老大看「数据不足」档位
        } else {
            // 档位 = 一个会动的点 + 字：需处理外扩光圈，留意缓慢呼吸，平稳不动
            HStack(spacing: 6) {
                LevelDot(level: level, size: 8)
                    .frame(width: 14, height: 14)
                Text(label)
                    .font(E.body(12))
                    .foregroundStyle(level == "steady" ? E.text2 : E.text)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("档位：\(label)")
        }
    }
}

/// 圆形线框小图标（板块）
struct BoardGlyph: View {
    let board: String
    var size: CGFloat = 28
    var body: some View {
        ZStack {
            Circle().strokeBorder(E.text, lineWidth: 1)
            switch board {
            case "sleep":
                Image(systemName: "moon").font(.system(size: size * 0.42, weight: .light))
            case "sport":
                Image(systemName: "figure.tennis").font(.system(size: size * 0.42, weight: .light))
            case "stress":
                Image(systemName: "water.waves").font(.system(size: size * 0.38, weight: .light))
            default:
                Image(systemName: "circle.dotted").font(.system(size: size * 0.42, weight: .light))
            }
        }
        .foregroundStyle(E.text)
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// 整行当按钮（待办行）：按下不变样，和以前点整行一样
struct RowPress: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { configuration.label }
}

struct EPress: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.55 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// 等待态：标题下一条细线在走
struct WorkingLine: View {
    @State private var phase: CGFloat = -0.35
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Rectangle().fill(E.line)
                Rectangle().fill(E.text)
                    .frame(width: geo.size.width * 0.35)
                    .offset(x: geo.size.width * phase)
            }
            .clipped()
        }
        .frame(height: 1)
        .onAppear {
            withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: false)) { phase = 1.0 }
        }
        .accessibilityLabel("P-Health 正在处理")
    }
}
