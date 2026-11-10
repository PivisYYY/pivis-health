import SwiftUI
import UIKit

// MARK: - 回复下面的 👍 / 👎（build 52）
// P-Health 每一轮回完的那条下面两只细线小手：👍 = 有用（再点撤回）；👎 = 弹一张小单子（哪里不好 + 可选写一句）。
// 写了那一句，服务器会把它转给同一个对话里的 P-Health（以「【反馈」开头，对话里不显示），它当场改，回复照常流进来。
// 评价按「对话 context + 那条回复的 time（服务器给的原样）」记：手机上先生效、存一份（重开对话还在），
// 再发服务器（断网进 PostOutbox 排队补发）；打开对话时拉一次服务器的，以服务器为准（手机上刚改、还没发出去的除外）。

enum FeedbackRating: String { case up, down, none }

@MainActor
final class FeedbackStore: ObservableObject {
    static let shared = FeedbackStore()
    static let reasons = ["不专业", "没结合我的数据", "太空泛", "说错了", "没照做", "太长"]
    private static let path = "api/v3/feedback"

    /// context → (回复的 time → "up" / "down")
    @Published private(set) var ratings: [String: [String: String]] = [:]
    /// 手机上什么时候改的：拉取开始之后才改的，服务器那份还没算上它，以手机为准
    private var touched: [String: Date] = [:]
    /// 正式 / 模拟回放各存各的
    private let storeKey = "feedback_ratings_v1_\(Profile.isSim ? "sim" : "real")"

    private init() {
        ratings = UserDefaults.standard.dictionary(forKey: storeKey) as? [String: [String: String]] ?? [:]
    }

    func rating(_ context: String, _ time: String) -> String? { ratings[context]?[time] }

    /// 👍 / 撤回 / 不写字的 👎：本地先变，再排队发（断网也算点上了）
    func set(_ rating: FeedbackRating, context: String, msg: ChatMsg, reasons: [String] = []) {
        mark(rating, context: context, time: msg.time)
        PostOutbox.shared.enqueue(Self.path, json: Self.body(rating, context: context, msg: msg, reasons: reasons, note: ""))
    }

    /// 只改手机上的（点踩带一句话那次由对话页直接发，要等服务器转给 P-Health）
    func mark(_ rating: FeedbackRating, context: String, time: String) {
        guard !time.isEmpty else { return }
        var m = ratings[context] ?? [:]
        m[time] = rating == .none ? nil : rating.rawValue
        // 每个对话最多留 500 条（time 是 ISO 字符串，按字符串排就是按时间排）
        if m.count > 500 { for k in m.keys.sorted().prefix(m.count - 500) { m.removeValue(forKey: k) } }
        ratings[context] = m
        touched[Self.key(context, time)] = Date()
        UserDefaults.standard.set(ratings, forKey: storeKey)
    }

    enum SendResult {
        /// 记上了，那句话也转给 P-Health 了：等它回
        case forwarded
        /// 记上了，但没转过去（DSH 没接上）
        case notForwarded
        /// 连不上服务器：进了发送队列，连上再发（那时服务器再转）
        case queued
        /// 等太久没回：服务器多半收到了、还在转，不重发（重发会转两遍）
        case unknown
        /// 服务器不收（4xx）
        case rejected
    }

    /// 点踩并写了一句：直接发，等服务器说转没转给 P-Health
    func sendNow(context: String, msg: ChatMsg, reasons: [String], note: String) async -> SendResult {
        let body = Self.body(.down, context: context, msg: msg, reasons: reasons, note: note)
        // 服务器同步把那句话发进对话后才回：给足时间
        let req = PivisAPI.request(Self.path, method: "POST", json: body, timeout: 40)
        do {
            let obj = try await PivisAPI.json(req)
            return obj["forwarded"] as? Bool == true ? .forwarded : .notForwarded
        } catch PivisAPI.Failure.http(let code, _) where (400..<500).contains(code) {
            return .rejected
        } catch PivisAPI.Failure.offline(let e as URLError) where e.code == .timedOut {
            return .unknown
        } catch {
            DshAPI.dbg("feedback send failed: \(error.localizedDescription)")
            PostOutbox.shared.enqueue(Self.path, json: body)
            return .queued
        }
    }

    /// 打开对话 / 回到前台：拉服务器上这个对话的评价，填满小手
    func refresh(_ context: String) async {
        let started = Date()
        guard let obj = try? await PivisAPI.json(PivisAPI.request(Self.path, ["context": context], timeout: 15)) else { return }
        var merged: [String: String] = [:]
        for (t, v) in obj["ratings"] as? [String: Any] ?? [:] {
            if let s = v as? String, s == "up" || s == "down" { merged[t] = s }
        }
        // 拉取开始后才改的、或者还在发送队列里没发出去的：以手机为准
        let local = ratings[context] ?? [:]
        let queued = queuedTimes(context)
        let prefix = Self.key(context, "")
        for (k, at) in touched where k.hasPrefix(prefix) {
            let t = String(k.dropFirst(prefix.count))
            if at >= started || queued.contains(t) { merged[t] = local[t] }
        }
        for t in queued where touched[Self.key(context, t)] == nil { merged[t] = local[t] }
        guard merged != local else { return }
        ratings[context] = merged
        UserDefaults.standard.set(ratings, forKey: storeKey)
    }

    /// 发送队列里还没发出去的、这个对话的评价（按回复 time）
    private func queuedTimes(_ context: String) -> Set<String> {
        var out: Set<String> = []
        for it in PostOutbox.shared.items where it.path == Self.path {
            guard let o = PivisAPI.object(it.body), (o["context"] as? String ?? "") == context,
                  let t = o["reply_time"] as? String else { continue }
            out.insert(t)
        }
        return out
    }

    private static func key(_ context: String, _ time: String) -> String { context + "\u{1F}" + time }

    private static func body(_ rating: FeedbackRating, context: String, msg: ChatMsg, reasons: [String], note: String) -> [String: Any] {
        ["context": context, "reply_time": msg.time, "rating": rating.rawValue, "reasons": reasons,
         "note": String(note.prefix(500)), "text": String(msg.text.prefix(200))]
    }
}

// MARK: - 一轮回复下面的两只小手（画出来 13pt 细线，点的范围 32）
struct ReplyThumbs: View {
    let context: String
    let msg: ChatMsg
    /// 一轮的最后一条：一直放；别的只在评过时放
    var always = true
    /// 每日推荐下的小灰字：和字一样居中；平常和气泡的字左边对齐
    var centered = false
    /// 点 👎（还没点过）：对话页弹「哪里不好？」
    let onDown: (ChatMsg) -> Void
    @ObservedObject private var store = FeedbackStore.shared

    var body: some View {
        let r = store.rating(context, msg.time)
        if always || r != nil {
            HStack(spacing: 2) {
                thumb("hand.thumbsup", on: r == "up", label: "有用", id: "fb-up") {
                    store.set(r == "up" ? .none : .up, context: context, msg: msg)
                }
                thumb("hand.thumbsdown", on: r == "down", label: "不好", id: "fb-down") {
                    if r == "down" { store.set(.none, context: context, msg: msg) } else { onDown(msg) }
                }
            }
            // 图标本身和字的左边对齐（点的范围往左、往上下让出去）
            .padding(.leading, centered ? 0 : -9)
            .padding(.top, centered ? -2 : -8)
            .padding(.bottom, centered ? 0 : -6)
        }
    }

    private func thumb(_ name: String, on: Bool, label: String, id: String, action: @escaping () -> Void) -> some View {
        Button {
            Haptic.tap()
            action()
        } label: {
            Image(systemName: on ? name + ".fill" : name)
                .font(.system(size: 13, weight: .light))
                .foregroundStyle(on ? E.text : E.text3)
                .frame(width: 32, height: 32)
                .contentShape(Rectangle())
        }
        .buttonStyle(EPress())
        .accessibilityLabel(label)
        .accessibilityIdentifier(id)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

// MARK: - 👎 的小单子：哪里不好（可多选）+ 可选写一句「应该是……」（写了会转给 P-Health 当场改）
// 不用系统 sheet：对话本身就是 sheet，再叠一层时 iOS 26 会把对话整个压到下面，被评的那条就看不见了。
// 这里是对话页底部的一块面板（换掉输入栏），上面的对话变暗但看得见；点暗处、点 ×、往下划都是不评了。
struct FeedbackPanel: View {
    let onSubmit: (_ reasons: [String], _ note: String) -> Void
    let onClose: () -> Void
    @State private var picked: Set<String> = []
    @State private var note = ""
    @State private var noteHeight: CGFloat = 38
    @State private var dragY: CGFloat = 0

    private var canSubmit: Bool { !picked.isEmpty || !note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("哪里不好？").font(E.light(20)).foregroundStyle(E.text)
                Spacer()
                Button(action: onClose) {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .light)).foregroundStyle(E.text2)
                        .frame(width: 32, height: 32)
                        .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                        .hitArea(6, 6)
                }
                .buttonStyle(EPress())
                .accessibilityLabel("不评了")
                .accessibilityIdentifier("fb-close")
            }
            FlowLayout(spacing: 8) {
                ForEach(FeedbackStore.reasons, id: \.self) { r in
                    ChoiceChip(label: r, selected: picked.contains(r)) {
                        if picked.contains(r) { picked.remove(r) } else { picked.insert(r) }
                    }
                    .accessibilityIdentifier("fb-reason-\(r)")
                }
            }
            // 和对话输入框同一个 UITextView 封装：中文组字时不吞拼音；return = 提交
            ChatInputField(text: $note, height: $noteHeight, identifier: "fb-note", returnKey: .done) { submit($0) }
                .frame(height: noteHeight)
                .background(RoundedRectangle(cornerRadius: 19, style: .continuous).fill(Color.black))
                .overlay(RoundedRectangle(cornerRadius: 19, style: .continuous)
                    .strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
                .overlay(alignment: .leading) {
                    Text("应该是……（可选，写了会转给 P-Health 当场改）")
                        .font(E.body(14)).foregroundStyle(E.hint)
                        .lineLimit(1).minimumScaleFactor(0.8)
                        .padding(.horizontal, 14)
                        .opacity(note.isEmpty ? 1 : 0)
                        .allowsHitTesting(false)
                }
            Button { submit() } label: {
                Text("提交")
                    .font(E.body(15))
                    .foregroundStyle(canSubmit ? E.text : E.text3)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .overlay(Capsule().strokeBorder(canSubmit ? E.text : E.stroke, lineWidth: 1))
                    .contentShape(Capsule())
            }
            .buttonStyle(EPress())
            .disabled(!canSubmit)
            .accessibilityIdentifier("fb-submit")
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
        .padding(.bottom, 10)
        // 黑底铺到屏幕底边，上沿一条细线
        .background(Color.black.ignoresSafeArea(edges: .bottom).overlay(alignment: .top) { Hairline(color: E.line) })
        .offset(y: max(0, dragY))
        .gesture(
            DragGesture(minimumDistance: 12)
                .onChanged { g in dragY = g.translation.height }
                .onEnded { g in
                    if g.translation.height > 70 || g.predictedEndTranslation.height > 220 { onClose() }
                    withAnimation(.easeOut(duration: 0.2)) { dragY = 0 }
                }
        )
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("fb-sheet")
    }

    /// typed：在框里按 return 提交时那一刻框里的字（绑定可能还没回写）
    private func submit(_ typed: String? = nil) {
        let n = String((typed ?? note).trimmingCharacters(in: .whitespacesAndNewlines).prefix(500))
        guard !picked.isEmpty || !n.isEmpty else { return }
        // 原因按固定顺序发（服务器、复盘里好对照）
        onSubmit(FeedbackStore.reasons.filter { picked.contains($0) }, n)
    }
}
