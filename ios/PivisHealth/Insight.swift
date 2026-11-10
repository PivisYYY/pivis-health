import SwiftUI
import UIKit

// MARK: - 洞察：P-Health 隔几天看出 1–3 件值得聊的事，等老大点开再聊
// status.insight 有它（还没点开、没划掉）时：主对话输入框上方一条浮条、底栏中间圆钮亮点。
// 点「聊聊」= open：服务器把那段话塞进主对话，P-Health 的回复像平常一样流进来；左右划掉 = dismiss。
// 只在主对话（context ""）里出现，板块 / 习惯 / 待办对话里都没有。

/// status.insight（宽松解码：字段不对也不能让整个 status 解不出来）
struct PendingInsight: Decodable, Equatable {
    var id = ""
    var n: Int?
    var text = ""
    /// 浮条右边按钮上的字（服务器按这次的事给，比如「看看」）；没给就是「聊聊」
    var button = ""

    private enum K: String, CodingKey { case id, n, text, button }

    init(id: String, n: Int? = nil, text: String, button: String = "") {
        self.id = id
        self.n = n
        self.text = text
        self.button = button
    }

    init(from decoder: Decoder) {
        guard let c = try? decoder.container(keyedBy: K.self) else { return }
        id = (try? c.decode(String.self, forKey: .id)) ?? ""
        n = (try? c.decode(Int.self, forKey: .n)) ?? (try? c.decode(Double.self, forKey: .n)).map { Int($0) }
        text = (try? c.decode(String.self, forKey: .text)) ?? ""
        button = ((try? c.decode(String.self, forKey: .button)) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var buttonLabel: String { button.isEmpty ? "聊聊" : button }

    /// 浮条上那句话：服务器给的为准，没给就按件数拼
    var line: String {
        if !text.isEmpty { return text }
        if let n, n > 0 { return "这几天看出 \(n) 件事，要聊聊吗？" }
        return "这几天看出几件事，要聊聊吗？"
    }
}

enum InsightAPI {
    enum OpenResult {
        /// 服务器已经把那段话塞进主对话，P-Health 的回复马上开始
        case opened
        /// 已经点开过 / 划掉了（别的地方），或者没有这条：不用等回复
        case notPending
        /// 服务器收下了，但那段话没发进对话（DSH 没接上）：这条已经算点开过，不再放回浮条
        case notDelivered
        /// 连不上服务器：没打开，浮条放回去
        case failed
    }

    static func open(_ id: String) async -> OpenResult {
        // 服务器同步把那段话发进主对话后才回：给足时间
        let req = PivisAPI.request("api/v3/insight/\(id)/open", method: "POST", json: [:], timeout: 30)
        do {
            let obj = try await PivisAPI.json(req)
            if obj["ok"] as? Bool == true { return .opened }
            return obj["error"] as? String == "not_pending" ? .notPending : .notDelivered
        } catch PivisAPI.Failure.http(let code, _) where (400..<500).contains(code) {
            return .notPending
        } catch {
            DshAPI.dbg("insight open failed: \(error.localizedDescription)")
            return .failed
        }
    }

    /// 划掉：断网也先记在手机上（浮条不再出现），连上再告诉服务器
    @MainActor
    static func dismiss(_ id: String) {
        PageSync.shared.insightHandled(id)
        PostOutbox.shared.enqueue("api/v3/insight/\(id)/dismiss", json: [:])
    }
}

/// 点了哪条推送：每条推送都带 push_id，点开（或点了通知上的按钮）就告诉服务器；断网先排队，连上补发
enum PushTaps {
    @MainActor
    static func report(pushId: String, action: String, at: Date) {
        guard !pushId.isEmpty else { return }
        PostOutbox.shared.enqueue("api/v3/push-tap", json: ["push_id": pushId, "action": action, "at": PTime.iso(at)])
    }
}

// MARK: - 发了就不用管的 POST（推送点开回报、划掉洞察）
// 和待办的发送队列（TodoOutbox）一个做法：先存在手机上，再在后台发；断网、服务器连不上时留着，
// 回到前台、下一次状态同步成功、或者隔一会儿（3、6、15、30、60 秒…）自动补发；服务器明确不收（4xx）就丢掉。
// 待办队列和页面显示绑在一起（本地先生效、对账），这里只是原样补发，所以单独一个。
@MainActor
final class PostOutbox {
    static let shared = PostOutbox()

    struct Item: Codable, Equatable {
        let id: String
        let path: String
        let body: Data
        let at: Date
        /// 试了几次（排重试间隔用）
        var attempts = 0
        /// 其中服务器出错（5xx、回的不对）几次：断网不算，断多久都留着
        var failures = 0
    }

    private(set) var items: [Item] = []
    private var flushing = false
    private var retryTask: Task<Void, Never>?
    /// 上一次没发出去是因为连不上（不是服务器出错）：状态同步一成功就马上补发
    private var waitingForNetwork = false
    /// 正式 / 模拟回放连的是两个服务器：各排各的队
    private let storeKey = "post_outbox_v1_\(Profile.isSim ? "sim" : "real")"

    private init() {
        if let d = UserDefaults.standard.data(forKey: storeKey), let saved = try? JSONDecoder().decode([Item].self, from: d) {
            items = saved
        }
        NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { _ in
            Task { @MainActor in PostOutbox.shared.flush() }
        }
    }

    func enqueue(_ path: String, json: [String: Any]) {
        guard let body = try? JSONSerialization.data(withJSONObject: json) else { return }
        items.append(Item(id: UUID().uuidString, path: path, body: body, at: Date()))
        // 一周前的不补了；最多攒 100 条
        let cutoff = Date().addingTimeInterval(-7 * 86400)
        items.removeAll { $0.at < cutoff }
        if items.count > 100 { items.removeFirst(items.count - 100) }
        save()
        flush()
    }

    /// 别的请求（状态同步）刚成功：之前是断网没发出去的，现在马上补发（服务器出错的照常按间隔重试，不跟着轮询狂发）
    func networkBack() {
        if waitingForNetwork { flush() }
    }

    /// 补发（有在发的就不再并发；排着的重试等不及了也直接发）
    func flush() {
        guard !flushing, !items.isEmpty else { return }
        flushing = true
        retryTask?.cancel()
        retryTask = nil
        Task { @MainActor in
            defer { flushing = false }
            while let it = items.first {
                let req = PivisAPI.request(it.path, method: "POST", body: it.body, contentType: "application/json", timeout: 12)
                do {
                    try await PivisAPI.send(req)
                    waitingForNetwork = false
                    items.removeAll { $0.id == it.id }
                    save()
                } catch PivisAPI.Failure.http(let code, _) where (400..<500).contains(code) {
                    // 服务器明确不收（比如那条洞察已经不在了）：不再重发
                    items.removeAll { $0.id == it.id }
                    save()
                } catch {
                    // 断网 / 服务器出错：留着，过一会儿再试（服务器出错 30 次还不行就算了；断网不算次数）
                    var offline = false
                    if case PivisAPI.Failure.offline = error { offline = true }
                    waitingForNetwork = offline
                    guard let i = items.firstIndex(where: { $0.id == it.id }) else { continue }
                    items[i].attempts += 1
                    if !offline { items[i].failures += 1 }
                    if items[i].failures >= 30 {
                        items.remove(at: i)
                        save()
                        continue
                    }
                    save()
                    let delays: [Double] = [3, 6, 15, 30, 60]
                    let wait = delays[min(items[i].attempts - 1, delays.count - 1)]
                    retryTask = Task { @MainActor in
                        try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
                        if !Task.isCancelled { PostOutbox.shared.flush() }
                    }
                    return
                }
            }
        }
    }

    private func save() {
        if let d = try? JSONEncoder().encode(items) { UserDefaults.standard.set(d, forKey: storeKey) }
    }
}

// MARK: - 浮条：主对话输入框上方，一行字 +「聊聊」（服务器可以换成别的字）；没有关闭按钮，左右划掉 = 不聊
struct InsightBar: View {
    @ObservedObject private var sync = PageSync.shared
    /// 点「聊聊」：对话页收起浮条、调 open、进入等回复的状态
    let onOpen: (String) -> Void
    /// 正在划的是哪一条、划到哪儿：换了一条新的洞察自动从原位开始
    @State private var dragId: String?
    @State private var dragX: CGFloat = 0

    var body: some View {
        if let ins = sync.insight {
            bar(ins)
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
                .transition(.opacity)
        }
    }

    private func bar(_ ins: PendingInsight) -> some View {
        let x = dragId == ins.id ? dragX : 0
        return HStack(spacing: 12) {
            MobiusMark(lineWidth: 1, strands: 2, background: E.surface)
                .frame(width: 20, height: 10)
            Text(ins.line)
                .font(E.body(15)).foregroundStyle(E.text)
                .lineLimit(1).truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button { onOpen(ins.id) } label: {
                Text(ins.buttonLabel)
                    .font(E.body(14)).foregroundStyle(E.text)
                    .lineLimit(1).fixedSize()
                    .padding(.horizontal, 14)
                    .frame(height: 36)
                    .overlay(Capsule().strokeBorder(E.text, lineWidth: 1))
                    .contentShape(Capsule())
            }
            .buttonStyle(EPress())
            .accessibilityIdentifier("insight-open")
        }
        .padding(.top, 10).padding(.trailing, 10).padding(.bottom, 10).padding(.leading, 14)
        .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(E.surface))
        .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).strokeBorder(E.stroke, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .offset(x: x)
        .opacity(1 - Double(min(abs(x) / 320, 0.7)))
        .gesture(
            DragGesture(minimumDistance: 14)
                .onChanged { g in
                    // 只认横着划；竖着拖（想拉抽屉）不动它
                    guard abs(g.translation.width) > abs(g.translation.height) else { return }
                    dragId = ins.id
                    dragX = g.translation.width
                }
                .onEnded { g in
                    let dx = g.translation.width
                    let flung = abs(g.predictedEndTranslation.width) > 200 && abs(dx) > 24
                    if abs(x) > 90 || (flung && abs(dx) > abs(g.translation.height)) {
                        let dir: CGFloat = (dx == 0 ? g.predictedEndTranslation.width : dx) < 0 ? -1 : 1
                        dragId = ins.id
                        withAnimation(.easeOut(duration: 0.2)) { dragX = dir * 480 }
                        InsightAPI.dismiss(ins.id)
                    } else {
                        withAnimation(.easeOut(duration: 0.2)) { dragX = 0 }
                    }
                }
        )
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("insight-bar")
        .accessibilityAction(named: "不聊了") { InsightAPI.dismiss(ins.id) }
    }
}
