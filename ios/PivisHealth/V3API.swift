import Foundation

// MARK: - 运行环境：正式 / 模拟回放（-pivisProfile sim：连 8944 测试服务 + phealth-sim-* 会话，和真实数据隔离）
enum Profile {
    static let isSim: Bool = {
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "-pivisProfile"), i + 1 < args.count { return args[i + 1] == "sim" }
        #if targetEnvironment(simulator)
        // 模拟器上默认就是模拟回放：从主屏、小组件点开（不带启动参数）也绝不连正式服务器、不碰真实数据。
        // 真要在模拟器上连正式环境，必须明确带 -pivisProfile real
        return true
        #else
        return false
        #endif
    }()

    /// 上传设备数据（位置、蓝牙、健康样本）：真机才传；模拟器一律不传
    static var uploadsDeviceData: Bool {
        #if targetEnvironment(simulator)
        return false
        #else
        return !ProcessInfo.processInfo.arguments.contains("-uiTestDisableDeviceData")
        #endif
    }
}

// MARK: - v3 页面文档
struct V3Page: Decodable {
    let page: String
    let now: String
    let date: String
    let headline: Headline
    let hero: Hero
    var todos: [V3Todo]
    /// 此刻页只列前 3 张，其余的在这里（「另有 N 件」点开；提醒也照排）
    var more: [V3Todo]?
    /// 主卡下面的「坚持习惯」行（此刻页 = 所有板块）
    let habits: [Habit]?
    var done: [V3Todo]
    let hidden: Int?
    let details: [Detail]
    let notices: [Notice]
    let projects: [ProjectBrief]?
    /// 主卡是昨天编排的，服务器正在后台重排
    let stale: Bool?
    let publication: Publication?

    struct Publication: Decodable { let publishedAt: String? }

    struct Headline: Decodable { let text: String }
    struct Hero: Decodable {
        let level: String
        let board: String?
        let label: String
        let value: String
        let unit: String?
        let note: String?
        let others: [Other]?
        let fields: [Field]?
        let table: Table?
        let levelLabel: String?
        let boardLabel: String?
        let viz: Viz?
        /// 开放画布：P-Health 用零件拼的主卡正文（有它就不画 value / viz / fields / table）
        let layout: CNode?
    }
    /// 主卡图表：P-Health 定画什么（metric / kind / days / show），内核填数。Hashable：数没变就不重画、不重播动画
    struct Viz: Decodable, Hashable {
        let metric: String
        let kind: String
        let label: String?
        let unit: String?
        let direction: String?
        let nd: Int?
        let show: [String]?
        let value: Double?
        let valueText: String?
        let asof: String?
        let zone: String?
        let days: Int?
        let series: [Dated]?
        let band: [Double]?
        let warn: Double?
        /// 带子 / 参照线的字由服务器给时用它（比如 CBT-I 的「目标 ≥90」「减窗口 85」），不给就是「常态 a–b」「警戒 x」
        let bandLabel: String?
        let warnLabel: String?
        let mid: Double?
        let prev: Double?
        let need: Double?
        let short: Double?
        let nights: [Night]?
        let shortNights: Int?
        let blocks: [Block]?
        let scale: [Double]?
        let trail: [Dated]?
        let goal: Double?
        let pace: Double?
        let paceTime: String?
        let start: Double?
        let target: Double?
        let weeksTotal: Double?
        let weekNow: Double?
        let planNow: Double?
        let behind: Double?
        let points: [RoutePoint]?
        let aside: Aside?
        struct Dated: Decodable, Hashable { let date: String; let value: Double }
        struct Night: Decodable, Hashable { let nightOf: String; let slept: Double?; let need: Double?; let ok: Bool }
        struct Block: Decodable, Hashable { let nightOf: String; let short: Double }
        struct RoutePoint: Decodable, Hashable { let week: Double; let value: Double }
        struct Aside: Decodable, Hashable { let text: String; let sub: String? }
    }
    struct Other: Decodable, Hashable { let label: String; let value: String; let unit: String?; let board: String? }
    /// 主卡里支撑这个问题的字段（最多 3 个）或小表（最多 4 列 5 行），由 P-Health 生成
    struct Field: Decodable, Hashable { let label: String; let value: String; let unit: String? }
    struct Table: Decodable, Hashable { let columns: [String]; let rows: [[String]] }
    /// 一个习惯（进行中的项目）：主卡下面一行，点进去是这个板块的对话、顶部是习惯卡
    struct Habit: Decodable, Identifiable, Hashable {
        let id: String
        let name: String
        let board: String
        let boardLabel: String?
        let day: Int
        let days: Int
        let state: String         // active / not_started
        let label: String         // 力量训练 · 第 11 天 / 56
        let today: String         // 今天 20:00 / 今天做完了 / 11-23 开始
        var icon: String? = nil   // build 53：项目自己的线条图标（SF Symbol 名），没有就用板块图标
    }
    struct Detail: Decodable, Identifiable {
        var id: String { title + kind }
        let title: String
        let kind: String
        let points: [Point]?
        let items: [String]?
        let text: String?
        let target: Double?
    }
    struct Point: Decodable, Hashable { let label: String; let value: Double }
    struct Notice: Decodable, Hashable { let text: String }
    struct ProjectBrief: Decodable, Identifiable {
        let id: String
        let name: String
        let board: String
        let rules: [String]?
        let start: String
        let days: Int
        let reviews: [Review]?
        struct Review: Decodable, Hashable { let date: String?; let title: String? }
    }
}

struct V3Media: Decodable, Hashable, Identifiable {
    var id: String { url }
    let kind: String
    let url: String
    let title: String?
    let durationMin: Double?
    /// 跟练视频的封面（服务器给：/media/follow/<id>/poster.jpg）；没有就是一块深色框，不再按视频地址去猜
    var poster: String? = nil

    /// 去掉 ?v= 这类参数后的路径（/media/follow/<id>/out.mp4?v=2 也要认成视频文件）
    private var pathOnly: String { (url.split(separator: "?").first.map(String.init) ?? url).lowercased() }
    /// 能用原生播放器放的视频文件（可以完全控制：静音循环、蒙版）
    var isVideoFile: Bool { [".mp4", ".m4v", ".mov"].contains { pathOnly.hasSuffix($0) } }
    /// 能用原生播放器放的音频文件
    var isAudioFile: Bool { [".mp3", ".m4a", ".aac", ".wav"].contains { pathOnly.hasSuffix($0) } }
    /// P-Health 自己做的跟练视频（9:16，画面里自带计时 / 报数 / 教练配音）：全屏、默认有声音
    var isFollowVideo: Bool { isVideoFile && url.contains("/media/follow/") }
}

struct V3Step: Decodable, Hashable {
    let title: String
    let note: String?
    let durationMin: Double?
    let media: V3Media?
}

struct V3Input: Decodable, Hashable, Identifiable {
    let id: String
    let type: String
    let label: String
    let options: [Opt]?
    let min: Int?
    let max: Int?
    let minLabel: String?
    let maxLabel: String?
    let unit: String?
    let placeholder: String?
    let submit: String
    var allowText: Bool? = nil
    var step: Double? = nil
    var defaultValue: LooseValue? = nil      // "last" = 先填上次的值，或一个数
    struct Opt: Decodable, Hashable { let id: String; let label: String }
    private enum CodingKeys: String, CodingKey {
        case id, type, label, options, min, max, minLabel, maxLabel, unit, placeholder, submit, allowText, step
        case defaultValue = "default"
    }
}

/// 数字或文字都收（记录里的值、输入的默认值）
enum LooseValue: Decodable, Hashable {
    case num(Double), str(String)
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let d = try? c.decode(Double.self) { self = .num(d) }
        else if let b = try? c.decode(Bool.self) { self = .str(b ? "true" : "false") }
        else { self = .str((try? c.decode(String.self)) ?? "") }
    }
    var text: String {
        switch self {
        case .num(let d): return d == d.rounded() ? String(Int(d)) : String(format: "%g", d)
        case .str(let s): return s
        }
    }
}

/// 待办里 App 直接记的状态：计数到几、子清单勾了哪几步、计时从几点开始
struct V3Record: Decodable, Hashable {
    var count: Int? = nil
    var checked: [Int]? = nil
    var startedAt: String? = nil
}

/// 项目里同一项上一次的结果
struct V3Last: Decodable, Hashable {
    let date: String
    let summary: String
    let status: String?
    var values: [String: LooseValue]? = nil
}

struct V3Todo: Decodable, Identifiable, Hashable {
    let id: String
    let board: String
    let project: String?
    let date: String
    var when: String
    let title: String
    let note: String
    let kind: String
    var status: String
    let verbs: [String]
    let inputs: [V3Input]
    let media: V3Media?
    let steps: [V3Step]
    let durationMin: Double?
    let alarm: String?
    let auto: String?
    let submitLabel: String?
    let summary: String
    let escalate: String?
    let updatedAt: String?
    var target: Int? = nil          // counter：一天几次
    var unit: String? = nil         // counter：杯 / 次
    var items: [String]? = nil      // checklist：几小步
    var record: V3Record? = nil
    var last: V3Last? = nil
    var timeDraft: Bool? = nil      // build 53：服务器拟的时间，等老大确认（「好」/ 换个时间）
    var draftWhy: String? = nil     // 拟这个时间的依据，比如「按 23:30 上床倒推」
    var remind: V3Remind? = nil     // P-Health 改过的提醒方式；nil = 默认（提前 + 到点）

    /// 这张卡会不会提醒（卡上画铃铛用）：有时间、不是自动记的、没被关掉、还没开始（和服务器 notify.todos 同一条规则：
    /// 只提醒 scheduled / proposed 的卡，开始了的计时、做了一半的清单不再推）
    var reminds: Bool { !when.isEmpty && auto == nil && remind?.off != true && ["scheduled", "proposed"].contains(status) }

    var boardLabel: String { ["sleep": "休息", "sport": "运动", "stress": "压力", "life": "日常"][board] ?? "" }
    var allSteps: [V3Step] {
        if !steps.isEmpty { return steps }
        if let media { return [V3Step(title: media.title ?? title, note: nil, durationMin: media.durationMin ?? durationMin, media: media)] }
        return [V3Step(title: title, note: note.isEmpty ? nil : note, durationMin: durationMin, media: nil)]
    }
}

/// 这张卡怎么提醒（build 53，P-Health 可以改）
struct V3Remind: Decodable, Hashable {
    var off: Bool? = nil
    var leadMin: Int? = nil
    var extra: [String]? = nil
    var nudge: Bool? = nil
}

/// 习惯卡（对话顶部）：本周 7 天 + 每套训练「标题 → 视频」
struct V3HabitDoc: Decodable, Hashable {
    let id: String
    let name: String
    let board: String
    var icon: String? = nil   // build 53：项目图标（SF Symbol 名）
    let state: String
    let day: Int
    let days: Int
    let week: [Day]
    let sessions: [Session]
    let summary: String       // 收成一行时：第 11 天 · 下次 周五 20:00 全身力量 B
    struct Day: Decodable, Hashable {
        let date: String
        let wd: String
        let state: String      // done / part / missed / today / plan / rest
        let label: String
        let today: Bool
    }
    struct Session: Decodable, Hashable, Identifiable {
        let key: String
        let title: String
        let next: String
        let today: Bool
        let meta: String
        let video: Video?
        var id: String { key }
    }
    struct Video: Decodable, Hashable {
        let url: String
        let title: String?
        let durationMin: Double?
        let poster: String?
    }
}

/// 带着一个习惯 / 一张待办进对话：输入框上方「关于：X」，发出去的消息前面加一行标记
struct ChatAbout: Equatable {
    enum Kind: String { case habit, todo }
    let kind: Kind
    let id: String
    let name: String
    var todo: V3Todo? = nil
    /// 发给 P-Health 的标记：【习惯 <项目 id> · <名字>】/【待办 <待办 id> · <标题>】
    var marker: String { "【\(kind == .habit ? "习惯" : "待办") \(id) · \(name)】" }

    /// 收到的历史 / 实时消息里把标记拆出来（服务器的历史已经拆好，实时流里还带着）
    static func split(_ text: String) -> (String, ChatAbout?) {
        guard let r = text.range(of: #"^【(习惯|待办) (\S+?) · ([^】\n]*)】[ \t]*\n?"#, options: .regularExpression) else { return (text, nil) }
        let head = String(text[r])
        let inner = head.trimmingCharacters(in: .whitespacesAndNewlines).dropFirst().dropLast()   // 去掉【】
        let parts = inner.split(separator: " ", maxSplits: 1)
        guard parts.count == 2 else { return (text, nil) }
        let kind: Kind = parts[0] == "习惯" ? .habit : .todo
        let rest = parts[1].components(separatedBy: " · ")
        let id = rest.first ?? ""
        let name = rest.dropFirst().joined(separator: " · ")
        return (String(text[r.upperBound...]), ChatAbout(kind: kind, id: id, name: name))
    }
}

// MARK: - 网络（都走 PivisAPI：带设备密钥、查状态码、同一个解码器）
enum V3API {
    static func page(_ name: String) async throws -> V3Page {
        if ServerConfig.isDemo { return try DemoStore.page(name) }
        do { return try await PivisAPI.get(V3Page.self, "api/v3/page/\(name)", timeout: 30) }
        catch PivisAPI.Failure.decoding(let error) { DshAPI.dbg("v3 page decode \(name): \(error)"); throw PivisAPI.Failure.decoding(error) }
    }

    /// 下拉刷新：让服务器马上拉一次 WHOOP。返回给老大看的一句话和是否成功（连不上服务器算失败）
    /// build 53：服务器马上回（不再当场等 WHOOP）。whoop: fresh / late / needs_login / unknown；
    /// apple: fresh / quiet（手机没开 App）/ server（服务器的问题）/ blocked（权限关了）/ late。
    /// action 不为空才需要老大动手（这时 ok = false）；pulling = 服务器在后台补拉 WHOOP
    struct HealthSync: Decodable {
        let ok: Bool
        let whoop: String?
        let message: String?
        var whoopAgeMin: Int? = nil
        var apple: String? = nil
        var appleAgeH: Double? = nil
        var pulling: Bool? = nil
        var action: String? = nil
    }
    static func syncHealth() async -> HealthSync {
        // 服务器马上回，不用等 25 秒；连不上服务器时两个点都是空心，不说「没同步上」（页面自己会显示连不上）
        if ServerConfig.isDemo { return HealthSync(ok: true, whoop: "fresh", message: nil, apple: "fresh") }
        let req = PivisAPI.request("api/v3/sync-health", method: "POST", timeout: 12)
        do { return try await PivisAPI.fetch(HealthSync.self, req) }
        catch {
            DshAPI.dbg("sync-health failed: \(error.localizedDescription)")
            return HealthSync(ok: false, whoop: "unknown", message: nil)
        }
    }

    static func habit(_ id: String) async throws -> V3HabitDoc {
        if ServerConfig.isDemo { return try DemoStore.habit(id) }
        return try await PivisAPI.get(V3HabitDoc.self, "api/v3/habit/\(id)")
    }

    static func todo(_ id: String) async throws -> V3Todo {
        if ServerConfig.isDemo { return try DemoStore.todo(id) }
        return try await PivisAPI.get(V3Todo.self, "api/v3/todo/\(id)")
    }

    enum SubmitError: Error {
        /// 服务器明确拒收（4xx，比如这条待办已经不在了）：不要再重发
        case rejected(String)
    }

    /// 待办动作。opId：同一个动作重发时服务器只算一次；clientAt：老大点下去的时间
    @discardableResult
    static func submit(_ id: String, action: String, values: [String: Any] = [:], text: String? = nil,
                       summary: String? = nil, opId: String? = nil, clientAt: Date? = nil) async throws -> V3Todo {
        #if DEBUG
        // UI 测试：模拟断网（待办动作发不出去），验证本地先生效、连上后补发
        if ProcessInfo.processInfo.arguments.contains("-todoOfflineTest") { throw URLError(.notConnectedToInternet) }
        #endif
        // 演示：只在手机上生效
        if ServerConfig.isDemo { return try DemoStore.submit(id, action: action, values: values, text: text, summary: summary) }
        var body: [String: Any] = ["action": action, "values": values]
        if let text { body["text"] = text }
        if let summary { body["summary"] = summary }
        if let opId { body["op_id"] = opId }
        if let clientAt { body["client_at"] = PTime.iso(clientAt) }
        do {
            return try await PivisAPI.fetch(V3Todo.self, PivisAPI.request("api/v3/todo/\(id)", method: "POST", json: body, timeout: 12))
        } catch PivisAPI.Failure.http(let code, let message) where (400..<500).contains(code) {
            throw SubmitError.rejected(message ?? "")
        }
    }

    /// 待办卡上的照片：先传到服务器，拿回 P-Health 读图用的路径，再随提交一起发过去
    static func uploadPhoto(_ id: String, data: Data) async throws -> String {
        let req = PivisAPI.request("api/v3/todo/\(id)/photo", method: "POST", body: data, contentType: "image/jpeg", timeout: 40)
        guard let path = try await PivisAPI.json(req)["photo"] as? String else { throw PivisAPI.Failure.decoding(URLError(.badServerResponse)) }
        return path
    }

    /// 对话里拍的照片：传到服务器，拿回给 P-Health 读图用的路径和对话里显示用的文件名
    static func uploadChatPhoto(data: Data) async throws -> (path: String, name: String) {
        let req = PivisAPI.request("api/v3/photo", method: "POST", body: data, contentType: "image/jpeg", timeout: 40)
        let obj = try await PivisAPI.json(req)
        guard let path = obj["photo"] as? String, let name = obj["name"] as? String else {
            throw PivisAPI.Failure.decoding(URLError(.badServerResponse))
        }
        return (path, name)
    }

    static func clock() async -> Date? {
        guard let obj = try? await PivisAPI.json(PivisAPI.request("api/v3/clock", timeout: 10)),
              let s = obj["now"] as? String else { return nil }
        return PTime.parse(s)
    }
}

extension Notification.Name {
    static let pivisPagesDirty = Notification.Name("pivisPagesDirty")
    static let pivisOpenChat = Notification.Name("pivisOpenChat")
    static let pivisStartTodo = Notification.Name("pivisStartTodo")
}
