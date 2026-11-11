import SwiftUI

/// 页面和 P-Health 同步：轮询服务器的 /api/v3/status，
/// - rev 变了（页面、待办、偏好、健康数据任一变化）→ 通知所有页面重新拉取；
/// - P-Health 正在对话里处理 → 页面顶部显示「在处理」；
/// - 某页正在后台重排 → 那页的主卡进入加载态，排好自动换上。
/// 有事在进行时 2 秒一轮，平时 15 秒一轮，App 在后台时停。
@MainActor
final class PageSync: ObservableObject {
    static let shared = PageSync()

    @Published private(set) var agentBusy = false
    @Published private(set) var agentLabel: String?
    @Published private(set) var updating: Set<String> = []
    /// 有没看过的 P-Health 回复的对话（"" 主对话 / 休息 / 运动 / 压力）：入口上亮个点
    @Published private(set) var unread: Set<String> = []
    private var lastReply: [String: Date] = [:]
    /// P-Health 看出几件事、等老大点开聊（status.insight）：主对话浮条 + 中间圆钮的点。
    /// 本地点过「聊聊」/ 划掉的那条不再显示，哪怕服务器的状态还没跟上
    @Published private(set) var insight: PendingInsight?
    private var serverInsight: PendingInsight?
    private lazy var handledInsights: [String] = UserDefaults.standard.stringArray(forKey: insightKey) ?? []
    private var insightKey: String { "insight_handled_\(Profile.isSim ? "sim" : "real")" }

    private var rev: String?
    private var loop: Task<Void, Never>?
    private var active = true
    private var wake: CheckedContinuation<Void, Never>?
    /// 正在同步时又来了 poke：这一轮完了不睡，马上再同步一次（以前直接丢掉，推送刚到时可能还是旧状态）
    private var pokeAgain = false

    private struct Status: Decodable {
        let rev: String
        let agent: Agent
        let updating: [String]
        let replies: [String: String]?
        let insight: PendingInsight?
        /// build 55：服务器怎么提醒（apns = 它自己推；local = 推不了，手机排本地提醒）。老服务器没有这一项
        let push: String?
        struct Agent: Decodable { let busy: Bool; let tool: String?; let args: String? }
    }

    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.poll()
                let busy = self.agentBusy || !self.updating.isEmpty
                await self.sleep(seconds: self.active ? (busy ? 2 : 15) : 3600)
            }
        }
    }

    /// 前后台切换：回到前台立刻同步一次
    func setActive(_ on: Bool) {
        active = on
        if on { poke() }
    }

    /// 马上同步一次（关掉对话、下拉刷新、提交待办之后）
    func poke() {
        guard let w = wake else { pokeAgain = true; return }
        wake = nil
        w.resume()
    }

    func isUpdating(_ page: String) -> Bool { updating.contains(page) }

    /// 换了一台电脑（配对、断开、进出演示）：上一台的状态全不算，马上对一次
    func reset() {
        rev = nil
        lastReply = [:]
        serverInsight = nil
        if agentBusy { agentBusy = false }
        if agentLabel != nil { agentLabel = nil }
        if !updating.isEmpty { updating = [] }
        if !unread.isEmpty { unread = [] }
        if insight != nil { insight = nil }
        poke()
    }

    @discardableResult
    func poll() async -> Bool {
        guard !ServerConfig.isDemo,
              let s = try? await PivisAPI.fetch(Status.self, PivisAPI.request("api/v3/status", timeout: 8)) else { return false }
        let changed = rev != nil && rev != s.rev
        rev = s.rev
        // 提醒方式变了（比如电脑上刚配好推送）：页面重拉一次，本地提醒跟着排或撤
        if let p = s.push.flatMap(PushMode.init(rawValue:)), ServerConfig.setPush(p), !changed {
            NotificationCenter.default.post(name: .pivisPagesDirty, object: nil)
        }
        let label = s.agent.busy ? actionLabel(s.agent.tool ?? "", s.agent.args) : nil
        // 动作名直接换（不做淡入淡出，免得两段字叠在一起）；出现 / 消失和加载态才带动画
        if agentLabel != label { agentLabel = label }
        withAnimation(.easeOut(duration: 0.3)) {
            if agentBusy != s.agent.busy { agentBusy = s.agent.busy }
            let u = Set(s.updating)
            if updating != u { updating = u }
        }
        if changed { NotificationCenter.default.post(name: .pivisPagesDirty, object: nil) }
        lastReply = Dictionary(uniqueKeysWithValues: (s.replies ?? [:]).compactMap { k, v in
            PTime.parse(v).map { (k == "main" ? "" : k, $0) }
        })
        if let open = ChatPresence.openContext { markSeen(open) } else { refreshUnread() }
        serverInsight = s.insight
        refreshInsight()
        PostOutbox.shared.networkBack()  // 连得上服务器了：断网时没发出去的推送回报 / 划掉洞察马上补发
        return changed
    }

    // MARK: 洞察
    /// 点了「聊聊」或划掉（或从推送直接点开）：马上收起浮条、灭掉圆钮的点，同一条以后不再出现
    func insightHandled(_ id: String) {
        guard !id.isEmpty else { return }
        if !handledInsights.contains(id) {
            handledInsights = Array((handledInsights + [id]).suffix(30))
            UserDefaults.standard.set(handledInsights, forKey: insightKey)
        }
        refreshInsight()
    }

    /// 点「聊聊」没连上服务器：放回去，等会儿再点
    func insightUnhandled(_ id: String) {
        guard handledInsights.contains(id) else { return }
        handledInsights.removeAll { $0 == id }
        UserDefaults.standard.set(handledInsights, forKey: insightKey)
        refreshInsight()
    }

    /// 洞察的推送在前台到了：不等下一轮状态，先按推送显示出来，再马上同步一次（以服务器为准）
    func noteInsightPush(id: String, text: String) {
        if !id.isEmpty, !handledInsights.contains(id), serverInsight?.id != id {
            serverInsight = PendingInsight(id: id, text: text)
            refreshInsight()
        }
        poke()
    }

    private func refreshInsight() {
        let v = serverInsight.flatMap { $0.id.isEmpty || handledInsights.contains($0.id) ? nil : $0 }
        if insight != v { withAnimation(.easeOut(duration: 0.25)) { insight = v } }
    }

    // MARK: 没看过的回复
    private func seenKey(_ ctx: String) -> String { "chat_seen_\(Profile.isSim ? "sim-" : "")\(ctx.isEmpty ? "main" : ctx)" }

    /// 上次看到哪儿；第一次（刚装这一版）就当现在都看过了，免得一打开四个入口全亮
    private func lastSeen(_ ctx: String) -> Date {
        let v = UserDefaults.standard.double(forKey: seenKey(ctx))
        if v > 0 { return Date(timeIntervalSince1970: v) }
        let now = Date()
        UserDefaults.standard.set(now.timeIntervalSince1970, forKey: seenKey(ctx))
        return now
    }

    /// 打开 / 关上 / 开着某个对话时：这个对话的回复都算看过了
    func markSeen(_ ctx: String) {
        let t = max(Date(), lastReply[ctx] ?? .distantPast)
        UserDefaults.standard.set(t.timeIntervalSince1970, forKey: seenKey(ctx))
        refreshUnread()
    }

    private func refreshUnread() {
        let u = Set(lastReply.compactMap { ctx, at in at > lastSeen(ctx) ? ctx : nil })
        if unread != u { withAnimation(.easeOut(duration: 0.3)) { unread = u } }
    }

    private var generation = 0

    private func sleep(seconds: Double) async {
        if pokeAgain { pokeAgain = false; return }
        generation += 1
        let mine = generation
        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            wake = c
            Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                // 只叫醒自己这一轮：被 poke 提前叫醒后，新一轮的 generation 已经变了
                guard let self, self.generation == mine, let w = self.wake else { return }
                self.wake = nil
                w.resume()
            }
        }
    }
}

// MARK: - 一页的数据
// 只在看得见时马上拉；看不见的页只记「脏了」，切过去再拉（此刻页例外：它的待办含所有板块，提醒按它排，看不见也照拉）。
// 同一时间只有一个请求在路上，期间再来的刷新合并成一次（等这个回来再补拉一次）；
// 每轮请求带一个号，回来时号已经不是最新的就丢掉，旧数据不会盖掉新数据。
@MainActor
final class PageLoader: ObservableObject {
    let page: String
    @Published private(set) var doc: V3Page?
    @Published private(set) var failed = false
    /// 每换上一份新数据加一（页面据此展开待办、排提醒）
    @Published private(set) var version = 0
    /// 这份数据开始拉取的时间（和发送队列对账用）
    private(set) var fetchedAt = Date.distantPast
    /// 看不见时来过刷新信号，还没拉
    private(set) var dirty = true
    private var running: Task<Void, Never>?
    private var again = false
    private var generation = 0

    init(page: String) { self.page = page }

    func markDirty() { dirty = true }

    /// 拉一次。已经有请求在路上：不再并发，等它回来后补拉一次；返回时最新的数据已经换上
    func load() async {
        dirty = false
        if let running {
            again = true
            await running.value
            return
        }
        let task = Task { await self.run() }
        running = task
        await task.value
    }

    private func run() async {
        defer { running = nil }
        repeat {
            again = false
            generation += 1
            let mine = generation
            let started = Date()
            do {
                let d = try await V3API.page(page)
                guard mine == generation else { continue }      // 已经有更新的一轮：这份旧的不用
                PTime.noteServerNow(d.now)
                doc = d
                fetchedAt = started
                failed = false
                version &+= 1
            } catch {
                guard mine == generation else { continue }
                dirty = true                 // 没拉到：下次看见这页时再拉
                if doc == nil { failed = true }
            }
        } while again
    }
}
