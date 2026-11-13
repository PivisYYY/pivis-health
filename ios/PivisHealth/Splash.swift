import SwiftUI

// MARK: - 开屏：一条「反直觉、但是对的」健康观
// 打开 App 先看一句；点一下展开解释、怎么做和依据；不点 5 秒后自己进 App。
// 这次显示的是上次打开时预取好的那条（不用等网络）；同时预取下一条。第一次打开用内置的一条。

struct Truth: Codable, Equatable {
    let id: String
    let headline: String
    let lead: String
    let body: [String]
    let action: String?
    let sources: [String]

    private enum CodingKeys: String, CodingKey { case id, headline, lead, body, action = "do", sources }

    /// 第一次打开、还没预取过时用这条
    static let builtIn = Truth(
        id: "no-catch-up",
        headline: "没睡好，第二天反而别补觉",
        lead: "想把睡眠调规律，每天同一时间起床，比多睡一会儿更有用。",
        body: [
            "睡意来自两股力：醒着越久，大脑里积累的「睡眠压力」越大；生物钟则按起床和见光的时间来定时。",
            "早上赖床、下午睡很久，会把攒下的睡眠压力提前用掉，生物钟也被往后推，当晚更难睡着，第二天又想补，就成了循环。",
            "所以失眠的认知行为治疗（CBT-I）把「固定起床、白天不补觉」当作基本规则。偶尔熬夜的健康人多睡一点没关系；但如果目标是把作息调回来，就别补。",
        ],
        action: "明早照常时间起床，拉开窗帘见光；实在困，15:00 前小睡最多 20 分钟。",
        sources: ["美国睡眠医学会（AASM）慢性失眠行为与心理治疗临床实践指南，2021",
                  "中国睡眠研究会《中国失眠症诊断和治疗指南》，2017"])
}

enum TruthStore {
    private static let key = "pivis_next_truth"

    /// 这次开屏显示哪条：上次预取的；没有就用内置的
    static func forLaunch() -> Truth {
        if let d = UserDefaults.standard.data(forKey: key), let t = try? JSONDecoder().decode(Truth.self, from: d) {
            return t
        }
        return .builtIn
    }

    /// 预取下一次开屏的那条（服务器按 Psir 正在做的项目挑，最近看过的不重复）
    static func prefetch() async {
        guard let t = try? await PivisAPI.fetch(Truth.self, PivisAPI.request("api/v3/truth", timeout: 10)),
              let enc = try? JSONEncoder().encode(t) else { return }
        UserDefaults.standard.set(enc, forKey: key)
    }
}

struct SplashView: View {
    let truth: Truth
    let onDone: () -> Void
    @State private var markShown = false
    @State private var revealed = 0          // 标题写出到第几行
    @State private var leadShown = false
    @State private var expanded = false
    @State private var detailShown = false
    @State private var progress: CGFloat = 0
    @State private var lineShown = false
    @State private var leaving = false
    @State private var gone = false
    @State private var readTask: Task<Void, Never>?
    @Environment(\.accessibilityReduceMotion) private var reduce
    private let wait: Double = 5

    /// M2 一行行写出：标题按逗号断成几行，一行一行从左往右写出来
    private var lines: [String] {
        var out: [String] = [], cur = ""
        for ch in truth.headline {
            cur.append(ch)
            if ch == "，" || ch == "," { out.append(cur); cur = "" }
        }
        if !cur.isEmpty { out.append(cur) }
        return out.isEmpty ? [truth.headline] : out
    }

    /// 展开后的阅读时间：按字数估（约 9 字/秒），10–30 秒
    private var readTime: Double {
        let n = truth.body.reduce(0) { $0 + $1.count } + (truth.action?.count ?? 0)
        return min(30, max(10, Double(n) / 9))
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            E.bg.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    // build 53：不再有「反直觉 · 但是对的」那行标签，只留标记和这句话本身
                    MobiusMark(lineWidth: 1, strands: 4).frame(width: 34)
                    .opacity(markShown ? 1 : 0)
                    .padding(.top, expanded ? 24 : 140)
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(lines.enumerated()), id: \.offset) { i, line in
                            Text(line)
                                .font(E.light(30)).foregroundStyle(E.text)
                                .fixedSize(horizontal: false, vertical: true)
                                .mask(alignment: .leading) {
                                    Rectangle().scaleEffect(x: revealed > i ? 1 : 0.001, anchor: .leading)
                                }
                        }
                    }
                    .padding(.top, 22)
                    .accessibilityElement(children: .combine)
                    .accessibilityAddTraits(.isHeader)
                    Text(truth.lead)
                        .font(E.body(16)).foregroundStyle(E.text2)
                        .lineSpacing(5)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 16)
                        .opacity(leadShown ? 1 : 0)
                    if expanded { detail.opacity(detailShown ? 1 : 0) }
                }
                .padding(.horizontal, E.gutter)
                .padding(.bottom, 80)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                // 没有按钮：点一下展开为什么；展开后再点一下直接进入
                .onTapGesture { expanded ? leave() : open() }
            }
            .scrollIndicators(.hidden)
            .scrollDisabled(!expanded)
            timeLine
        }
        .opacity(gone ? 0 : 1)
        .preferredColorScheme(.dark)
        .task { await play() }
        .accessibilityIdentifier("splash")
        .accessibilityAction(named: "看为什么") { open() }
        .accessibilityAction(named: "进入应用") { leave() }
    }

    /// 底部一根细线：走完就离场
    private var timeLine: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Rectangle().fill(E.line)
                Rectangle().fill(E.text2).frame(width: g.size.width * progress)
            }
        }
        .frame(height: 1)
        .padding(.horizontal, E.gutter)
        .padding(.bottom, 24)
        .opacity(lineShown ? 1 : 0)
        .allowsHitTesting(false)
    }

    private func play() async {
        if reduce {
            markShown = true; revealed = lines.count; leadShown = true; lineShown = true
        } else {
            withAnimation(.easeOut(duration: 0.35)) { markShown = true }
            try? await Task.sleep(nanoseconds: 350_000_000)
            for i in 0..<lines.count {
                if expanded { break }
                withAnimation(.easeOut(duration: 0.5)) { revealed = i + 1 }
                try? await Task.sleep(nanoseconds: 550_000_000)
            }
            withAnimation(.easeOut(duration: 0.4)) { revealed = lines.count; leadShown = true; lineShown = true }
        }
        guard !expanded else { return }
        withAnimation(.linear(duration: wait)) { progress = 1 }
        try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
        if !expanded { leave() }
    }

    /// 离场：和入场反过来。导语、解释先淡掉，标题从最后一行起一行行从右往左收回，标记淡掉，再露出应用
    private func leave() {
        guard !leaving else { return }
        leaving = true
        readTask?.cancel()
        Task { @MainActor in
            if reduce {
                withAnimation(.easeIn(duration: 0.3)) { gone = true }
                try? await Task.sleep(nanoseconds: 300_000_000)
                onDone()
                return
            }
            withAnimation(.easeIn(duration: 0.3)) { leadShown = false; detailShown = false; lineShown = false }
            try? await Task.sleep(nanoseconds: 250_000_000)
            for i in stride(from: lines.count, to: 0, by: -1) {
                withAnimation(.easeIn(duration: 0.4)) { revealed = i - 1 }
                try? await Task.sleep(nanoseconds: 330_000_000)
            }
            withAnimation(.easeIn(duration: 0.3)) { markShown = false }
            try? await Task.sleep(nanoseconds: 300_000_000)
            withAnimation(.easeOut(duration: 0.35)) { gone = true }
            try? await Task.sleep(nanoseconds: 350_000_000)
            onDone()
        }
    }

    private var detail: some View {
        VStack(alignment: .leading, spacing: 0) {
            Hairline().padding(.top, 28)
            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(truth.body.enumerated()), id: \.offset) { _, p in
                    Text(p).font(E.body(15)).foregroundStyle(E.text)
                        .lineSpacing(6)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.top, 24)
            if let a = truth.action, !a.isEmpty {
                Text("怎么做").font(E.body(12)).kerning(1).foregroundStyle(E.text3).padding(.top, 28)
                Text(a).font(E.body(15)).foregroundStyle(E.text)
                    .lineSpacing(6)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)
            }
            Text("依据").font(E.body(12)).kerning(1).foregroundStyle(E.text3).padding(.top, 28)
            VStack(alignment: .leading, spacing: 6) {
                ForEach(truth.sources, id: \.self) { s in
                    Text(s).font(E.body(12)).foregroundStyle(E.text3)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.top, 8)
        }
    }

    /// 展开：解释淡入，底线重新走一遍阅读时间，走完自然离场
    private func open() {
        guard !expanded, !leaving else { return }
        withAnimation(.easeOut(duration: 0.35)) {
            expanded = true
            detailShown = true
            markShown = true
            revealed = lines.count
            leadShown = true
            lineShown = true
        }
        var t = Transaction()
        t.disablesAnimations = true
        withTransaction(t) { progress = 0 }
        let duration = readTime
        readTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 50_000_000)
            withAnimation(.linear(duration: duration)) { progress = 1 }
            try? await Task.sleep(nanoseconds: UInt64(duration * 1_000_000_000))
            if !Task.isCancelled { leave() }
        }
    }
}
