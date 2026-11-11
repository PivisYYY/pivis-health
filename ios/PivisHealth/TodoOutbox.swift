import SwiftUI
import UIKit

// MARK: - 待办动作的发送队列
// 点了先在本地生效（开始倒计时、记好了、挪到几点、+1……），再在后台发给服务器。
// 断网、服务器连不上时存在手机上，回到前台 / 隔一会儿自动补发；每个动作带 op_id，服务器重复收到只算一次。
// 页面显示 = 服务器给的待办 + 还没送到的动作；送到以后用服务器回的那条，直到页面重新拉到更新的数据。

@MainActor @Observable
final class TodoOutbox {
    static let shared = TodoOutbox()

    struct Op: Codable, Identifiable, Equatable {
        let id: String
        let todoId: String
        let action: String
        let values: Data          // JSON 对象
        let text: String?
        let summary: String?
        let at: Date              // 老大点下去的时间（服务器按它记，断网补发也不会错）
        var attempts = 0
    }

    private struct Confirmed { let todo: V3Todo; let at: Date; let opAt: Date }

    private(set) var pending: [Op] = []
    private var confirmed: [String: Confirmed] = [:]
    /// 定时刷新用：做完的卡留一下让「记好了」播完再收起；「等网络」过几秒再显示
    private(set) var tick = 0
    /// 服务器拒收的动作（比如这条已经被 P-Health 改掉 / 删掉），页面弹一句
    var rejected: String?
    /// 最近一次可能做完一张卡的时间：送到后页面晚一点再刷新，让「记好了」播完
    private(set) var lastFinishAt = Date.distantPast

    /// 正在发的那一轮（同一时间只有一轮；通知按钮在后台点的要等它发完）
    private var flushTask: Task<Void, Never>?
    private var retryTask: Task<Void, Never>?
    private let storeKey = "todo_outbox_v1"

    /// 存在 App Group 里：小组件上打的勾断网时也排进这个队列，App 回到前台时一起补发
    private var store: UserDefaults { SharedStore.defaults }

    private init() {
        // 旧版本存在 App 自己的 UserDefaults：搬过来
        if let old = UserDefaults.standard.data(forKey: storeKey) {
            if store.data(forKey: storeKey) == nil { store.set(old, forKey: storeKey) }
            UserDefaults.standard.removeObject(forKey: storeKey)
        }
        pending = loadStored()
        NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { _ in
            Task { @MainActor in
                TodoOutbox.shared.mergeStored()
                TodoOutbox.shared.flush()
            }
        }
        flush()
    }

    private func loadStored() -> [Op] {
        guard let d = store.data(forKey: storeKey), let ops = try? JSONDecoder().decode([Op].self, from: d) else { return [] }
        return ops
    }

    /// 小组件在 App 不在前台时排进来的动作：合进内存里的队列（按 id 去重）
    func mergeStored() {
        let known = Set(pending.map(\.id))
        let extra = loadStored().filter { !known.contains($0.id) }
        guard !extra.isEmpty else { return }
        pending.append(contentsOf: extra)
        pending.sort { $0.at < $1.at }
        save()
    }

    // MARK: 入队
    func enqueue(_ todoId: String, action: String, values: [String: Any] = [:], text: String? = nil, summary: String? = nil) {
        let data = (try? JSONSerialization.data(withJSONObject: values)) ?? Data("{}".utf8)
        pending.append(Op(id: UUID().uuidString, todoId: todoId, action: action, values: data, text: text, summary: summary, at: Date()))
        // 做完 / 跳过 / 挪时间：送到后页面晚 2 秒再刷新，先在原位显示「记好了」「挪到 几点」，再收起或挪位置
        if ["done", "skip", "inc", "check", "later"].contains(action) { lastFinishAt = Date() }
        save()
        flush()
        // 做完的卡 2.2 秒后从列表收起（先让卡片自己的「记好了」播完）；3.2 秒还没送到就标「等网络」
        for delay in [2.2, 3.2] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { self.tick &+= 1 }
        }
    }

    /// 送到后页面多久再刷新：刚做完一张卡的话等「记好了」播完（2.2 秒）
    var reloadDelay: Double { max(0, 2.2 - Date().timeIntervalSince(lastFinishAt)) }

    /// 这条有动作 3 秒还没送到服务器（断网 / 服务器连不上）
    func waiting(_ todoId: String) -> Bool {
        _ = tick
        return pending.contains { $0.todoId == todoId && Date().timeIntervalSince($0.at) > 3 }
    }

    // MARK: 发送
    func flush() { startFlush() }

    /// 发一轮并等它结束：送完、被拒、或者断网（断网的留在队列里，回到前台 / 隔一会儿再补发）。
    /// 通知上的「好」在后台点的：系统只给一小会儿，要在告诉系统「处理完了」之前真的发出去
    func flushAndWait() async {
        await startFlush()?.value
    }

    @discardableResult
    private func startFlush() -> Task<Void, Never>? {
        if let t = flushTask { return t }       // 正在发：新排进来的这条也会在这一轮里发
        guard !pending.isEmpty else { return nil }
        retryTask?.cancel()
        let task = Task { @MainActor in
            defer { flushTask = nil }
            while let op = pending.first {
                do {
                    let t = try await V3API.submit(op.todoId, action: op.action, values: Self.dict(op.values),
                                                   text: op.text, summary: op.summary, opId: op.id, clientAt: op.at)
                    confirmed[op.todoId] = Confirmed(todo: t, at: Date(), opAt: op.at)
                    pending.removeFirst()
                    save()
                    NotificationCenter.default.post(name: .pivisTodosChanged, object: op.todoId)
                } catch V3API.SubmitError.rejected(let message) {
                    // 服务器明确不收（不是网络问题）：不再重发，告诉老大，页面按服务器的样子刷新
                    pending.removeFirst()
                    save()
                    rejected = message.isEmpty ? "这条没记上" : "没记上：\(message)"
                    NotificationCenter.default.post(name: .pivisTodosChanged, object: op.todoId)
                } catch {
                    // 网络问题：留着，过一会儿再试（3、6、15、30、60 秒…），回到前台也会立刻再试
                    pending[0].attempts += 1
                    save()
                    let delays: [Double] = [3, 6, 15, 30, 60]
                    let wait = delays[min(pending[0].attempts - 1, delays.count - 1)]
                    retryTask = Task { @MainActor in
                        try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
                        if !Task.isCancelled { TodoOutbox.shared.flush() }
                    }
                    tick &+= 1
                    return
                }
            }
        }
        flushTask = task
        return task
    }

    private func save() {
        if let d = try? JSONEncoder().encode(pending) { store.set(d, forKey: storeKey) }
    }

    /// 换了一台电脑 / 断开：上一台的待办动作发不到新电脑上，丢掉
    func clearAll() {
        retryTask?.cancel()
        pending = []
        confirmed = [:]
        save()
    }

    nonisolated private static func dict(_ data: Data) -> [String: Any] {
        (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    // MARK: 页面显示用
    /// fetchedAt：这份页面数据开始拉取的时间。送到后服务器回的那条比它新，就用服务器回的
    func apply(_ todos: [V3Todo], fetchedAt: Date) -> [V3Todo] {
        _ = tick
        let now = Date()
        return todos.compactMap { t in
            var cur = t
            var finishedAt: Date?
            if let c = confirmed[t.id], c.at > fetchedAt {
                cur = c.todo
                if ["done", "skipped"].contains(cur.status) { finishedAt = c.opAt }
            }
            for op in pending where op.todoId == t.id {
                cur = Self.apply(op, to: cur)
                if ["done", "skipped"].contains(cur.status) { finishedAt = op.at }
            }
            if ["done", "skipped"].contains(cur.status) {
                // 刚点的留 2 秒（卡片在原位显示「记好了」），之后收起
                if let f = finishedAt, now.timeIntervalSince(f) < 2 { return cur }
                return nil
            }
            return cur
        }
    }

    nonisolated static func apply(_ op: Op, to todo: V3Todo) -> V3Todo {
        var t = todo
        let v = dict(op.values)
        var rec = t.record ?? V3Record()
        switch op.action {
        case "start":
            t.status = "in_progress"
            if t.kind == "timer" {
                rec.startedAt = PTime.iso(op.at)
                t.record = rec
            }
        case "inc":
            let n = (v["n"] as? Int) ?? 1
            rec.count = max(0, (rec.count ?? 0) + n)
            t.record = rec
            if (rec.count ?? 0) >= max(1, t.target ?? 1) { t.status = "done" }
        case "check":
            var set = Set(rec.checked ?? [])
            if let i = v["index"] as? Int {
                if (v["on"] as? Bool) ?? true { set.insert(i) } else { set.remove(i) }
            }
            rec.checked = set.sorted()
            t.record = rec
            let total = t.items?.count ?? 0
            t.status = total > 0 && set.count == total ? "done" : (set.isEmpty ? "scheduled" : "in_progress")
        case "done":
            t.status = "done"
        case "skip":
            t.status = "skipped"
        case "later":
            t.when = laterTime(t.when, minutes: (v["minutes"] as? Int) ?? 10, from: op.at)
            t.status = t.kind == "proposal" ? "proposed" : "scheduled"
        case "agent":
            t.status = "processing"
        case "confirm_time":
            // 拟的时间：「好」不带 when（照原样），换了时间带 when；卡上马上变成普通时间
            if let w = v["when"] as? String, !w.isEmpty { t.when = w }
            t.timeDraft = false
            t.draftWhy = nil
        default:
            break
        }
        return t
    }

    /// 和服务器同一个算法：max(原定时间, 现在) + N 分钟（北京时间）
    nonisolated static func laterTime(_ when: String, minutes: Int, from: Date) -> String {
        let cal = PTime.calendar
        let nowM = cal.component(.hour, from: from) * 60 + cal.component(.minute, from: from)
        var base = nowM
        let p = when.split(separator: ":").compactMap { Int($0) }
        if p.count == 2 { base = max(base, p[0] * 60 + p[1]) }
        let m = (base + minutes) % (24 * 60)
        return String(format: "%02d:%02d", m / 60, m % 60)
    }
}

extension Notification.Name {
    /// 待办动作送到服务器 / 被拒：页面重新拉一次
    static let pivisTodosChanged = Notification.Name("pivisTodosChanged")
}
