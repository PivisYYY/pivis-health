import Foundation
import WidgetKit
import AppIntents
import UserNotifications

// MARK: - 服务器 /api/v3/widget 的数据（App 存进 App Group 的 widget.json，小组件自己也会去拿）
struct WDoc: Codable {
    struct Hero: Codable {
        var label: String
        var value: String
        var unit: String
        var level: String
        var boardLabel: String
        var note: String
    }
    struct Todo: Codable, Identifiable, Hashable {
        var id: String
        var when: String
        var at: String?
        var title: String
        var note: String
        var board: String
        var boardLabel: String
        var kind: String
        var status: String
        var check: Bool
        var auto: Bool? = nil
        var play: Bool? = nil           // 练习（follow 出的片）：点了直接全屏播
        var durationMin: Double? = nil
        var atDate: Date? { at.flatMap(WDoc.parse) }
    }
    struct Bed: Codable {
        var title: String
        var when: String
        var at: String?
        var atDate: Date? { at.flatMap(WDoc.parse) }
    }
    struct Night: Codable, Hashable {
        var date: String
        var hours: Double
        var need: Double?
    }
    struct Sleep: Codable {
        var nights: [Night]
        var last: Double?
        var need: Double?
        var short: Double?
    }
    var now: String
    var date: String
    var hero: Hero
    var todos: [Todo]
    var count: Int
    var bed: Bed?
    var sleep: Sleep

    /// 服务器的时间（北京时间，到分钟）。格式器只建一次
    private static let minuteFormat: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.dateFormat = "yyyy-MM-dd'T'HH:mmXXXXX"
        return f
    }()
    static let isoFormat: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        return f
    }()

    static func parse(_ s: String) -> Date? { minuteFormat.date(from: s) }

    /// 参考时间：服务器的「现在」和手机差 3 小时以上（模拟回放 / 演示环境用的是固定时钟）就按服务器的算；正式环境两者一致
    func refNow(_ date: Date) -> Date {
        if let n = WDoc.parse(now), abs(n.timeIntervalSince(date)) > 3 * 3600 { return n }
        return date
    }

    /// 某个时刻「接下来」的几件：还没到点（过了 15 分钟内也算）的按时间排，再接没有时间的；已经过了的不放
    func upcoming(at at: Date, limit: Int = 3) -> [Todo] {
        let date = refNow(at)
        let timed = todos.filter { t in
            guard let d = t.atDate else { return false }
            return d >= date.addingTimeInterval(-15 * 60)
        }
        let untimed = todos.filter { $0.at == nil }
        return Array((timed + untimed).prefix(limit))
    }

    static let placeholder = WDoc(
        now: "", date: "",
        hero: Hero(label: "睡眠债", value: "10.0", unit: "小时", level: "act", boardLabel: "休息", note: "欠觉到顶了，今晚守住上床的时间窗"),
        todos: [
            Todo(id: "p1", when: "21:45", at: nil, title: "慢呼吸 5 分钟", note: "呼气比吸气长", board: "stress", boardLabel: "压力", kind: "follow", status: "scheduled", check: false),
            Todo(id: "p2", when: "21:50", at: nil, title: "把明天写下来", note: "写完合上纸", board: "sleep", boardLabel: "休息", kind: "done", status: "scheduled", check: true),
            Todo(id: "p3", when: "23:00", at: nil, title: "放下手机", note: "开勿扰，放远", board: "sleep", boardLabel: "休息", kind: "done", status: "scheduled", check: true),
        ],
        count: 3, bed: nil,
        sleep: Sleep(nights: [5.9, 7.3, 6.8, 5.8, 6.7, 6.6, 5.7].enumerated().map { Night(date: "11-0\($0.offset)", hours: $0.element, need: 9.4) },
                     last: 5.7, need: 9.4, short: 3.7))
}

// MARK: - 读写缓存、去服务器拿
enum WStore {
    static let group = "group.com.pivis.health"
    static var defaults: UserDefaults { UserDefaults(suiteName: group) ?? .standard }
    private static var file: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group)?.appendingPathComponent("widget.json")
    }
    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    static func cached() -> WDoc? {
        guard let f = file, let data = try? Data(contentsOf: f) else { return nil }
        return try? decoder.decode(WDoc.self, from: data)
    }

    static var base: URL? { defaults.string(forKey: "pivis_base").flatMap(URL.init(string:)) }

    /// 发往服务器 /api/ 的请求：带上 App 存进来的设备密钥（服务器不收没密钥的请求）
    static func request(_ path: String, timeout: TimeInterval = 8) -> URLRequest? {
        guard let base else { return nil }
        var req = URLRequest(url: base.appendingPathComponent(path), timeoutInterval: timeout)
        if let key = defaults.string(forKey: "pivis_app_key"), !key.isEmpty {
            req.setValue(key, forHTTPHeaderField: "X-Pivis-Key")
        }
        return req
    }

    /// 去服务器拿最新的（8 秒拿不到就用缓存）；拿到就写回缓存
    static func load() async -> WDoc? {
        if let req = request("api/v3/widget") {
            if let (data, resp) = try? await URLSession.shared.data(for: req),
               (resp as? HTTPURLResponse)?.statusCode == 200,
               let doc = try? decoder.decode(WDoc.self, from: data) {
                if let f = file { try? data.write(to: f, options: .atomic) }
                return doc
            }
        }
        return cached()
    }

    /// 小组件上打了勾：先从缓存里拿掉，画面立刻变
    static func removeFromCache(_ todoId: String) {
        guard let f = file, let data = try? Data(contentsOf: f),
              var obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let todos = obj["todos"] as? [[String: Any]] else { return }
        obj["todos"] = todos.filter { ($0["id"] as? String) != todoId }
        obj["count"] = max(0, ((obj["count"] as? Int) ?? 1) - 1)
        if let out = try? JSONSerialization.data(withJSONObject: obj) { try? out.write(to: f, options: .atomic) }
    }
}

// MARK: - 和 App 同一个发送队列（App Group 里的 todo_outbox_v1，格式和 App 的 TodoOutbox.Op 一样）
struct WOp: Codable {
    let id: String
    let todoId: String
    let action: String
    let values: Data
    let text: String?
    let summary: String?
    let at: Date
    var attempts = 0
}

enum WOutbox {
    static let key = "todo_outbox_v1"
    static func append(_ op: WOp) {
        let d = WStore.defaults
        var ops = (d.data(forKey: key).flatMap { try? JSONDecoder().decode([WOp].self, from: $0) }) ?? []
        ops.append(op)
        if let data = try? JSONEncoder().encode(ops) { d.set(data, forKey: key) }
    }
}

// MARK: - 小组件上的 ✓：直接完成，不用开 App；连不上就排进队列，App 下次打开时补发
struct CompleteTodoIntent: AppIntent {
    static var title: LocalizedStringResource = "完成待办"
    static var description = IntentDescription("在小组件上把这件事记成做了")
    static var openAppWhenRun = false

    @Parameter(title: "待办") var todoId: String

    init() {}
    init(todoId: String) { self.todoId = todoId }

    func perform() async throws -> some IntentResult {
        let op = WOp(id: UUID().uuidString, todoId: todoId, action: "done", values: Data("{}".utf8),
                     text: nil, summary: "做到了", at: Date())
        WStore.removeFromCache(todoId)
        await WReminders.cancel(todoId)
        var delivered = false
        if var req = WStore.request("api/v3/todo/\(todoId)") {
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: Any] = ["action": "done", "values": [String: Any](), "summary": "做到了",
                                       "op_id": op.id, "client_at": WDoc.isoFormat.string(from: op.at)]
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            if let (_, resp) = try? await URLSession.shared.data(for: req),
               let code = (resp as? HTTPURLResponse)?.statusCode, code == 200 || (400..<500).contains(code) {
                delivered = true      // 4xx：这条已经不在了，也不用再发
            }
        }
        if !delivered { WOutbox.append(op) }
        return .result()
    }
}

// MARK: - 打了勾就撤掉 App 排的到点提醒 / 催一次（标识里带「-<待办 id>-」）
// 两手准备：小组件里直接撤（扩展和 App 共用一个通知中心时就撤掉了）；
// 同时把 id 记进 App Group 的 widget_done_ids，App 下次回到前台再撤一遍（扩展碰不到 App 的通知中心时靠这个）
enum WReminders {
    static func cancel(_ todoId: String) async {
        let d = WStore.defaults
        var ids = d.stringArray(forKey: "widget_done_ids") ?? []
        if !ids.contains(todoId) { ids.append(todoId) }
        d.set(Array(ids.suffix(50)), forKey: "widget_done_ids")
        let center = UNUserNotificationCenter.current()
        let pending = await center.pendingNotificationRequests()
        let mine = pending.map(\.identifier).filter { $0.contains("-\(todoId)-") || $0 == "alarm-\(todoId)" }
        if !mine.isEmpty { center.removePendingNotificationRequests(withIdentifiers: mine) }
    }
}
