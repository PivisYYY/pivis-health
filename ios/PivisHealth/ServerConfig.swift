import Foundation
import os
import SwiftUI
import UIKit

// MARK: - 连哪台电脑（build 55）
// P-Health 跑在每个人自己的电脑上：App 扫电脑上出的配对二维码（phealth://pair?…）连过去。
// 用哪一份配置，按这个顺序：配对过的电脑 → LocalConfig（开发版本机编进去的，非空才算）→ 没配对（引导页）。
// 模拟回放（-pivisProfile sim）照旧连 LocalConfig 的地址 + 8944；配对记录按环境分开存，测试环境和正式环境互不影响。
// 设备密钥放钥匙串，其余放 UserDefaults；小组件要用的地址和密钥另抄一份进 App Group（WidgetBridge.shareConfig）。

/// 配对链接：phealth://pair?v=1&n=<电脑名>&h=<地址1,地址2,…>&p=<P-Health 端口>&d=<DSH 端口>&k=<设备密钥>
struct PairLink: Equatable, Identifiable {
    let name: String
    /// 按优先顺序：局域网 IPv4、Tailscale、Bonjour 名（XXX.local）
    let hosts: [String]
    let apiPort: Int
    let dshPort: Int
    let key: String
    var id: String { "\(name)|\(hosts.joined(separator: ","))|\(apiPort)|\(dshPort)" }

    init?(url: URL) {
        guard url.scheme?.lowercased() == "phealth", url.host?.lowercased() == "pair",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems else { return nil }
        func value(_ k: String) -> String? {
            items.first { $0.name == k }?.value?.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let hosts = (value("h") ?? "").split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter(Self.validHost)
        guard let key = value("k"), !key.isEmpty, !hosts.isEmpty else { return nil }
        var seen = Set<String>()
        self.hosts = hosts.filter { seen.insert($0.lowercased()).inserted }
        self.key = key
        self.apiPort = value("p").flatMap(Int.init).flatMap { (1...65535).contains($0) ? $0 : nil } ?? 8943
        self.dshPort = value("d").flatMap(Int.init).flatMap { (1...65535).contains($0) ? $0 : nil } ?? 8960
        let n = value("n") ?? ""
        self.name = n.isEmpty ? "我的电脑" : String(n.prefix(40))
    }

    /// 粘贴进来的一段字：里面有一条 phealth://pair 链接就认（前后带了别的字、换行也行）
    init?(text: String) {
        guard let r = text.range(of: #"phealth://pair\?[^\s"'<>，。；、）」』]+"#, options: [.regularExpression, .caseInsensitive]),
              let url = URL(string: String(text[r])) else { return nil }
        self.init(url: url)
    }

    /// 只收 IPv4 / IPv6 / 主机名，别的（带路径、用户名、空格）一律不要
    private static func validHost(_ h: String) -> Bool {
        guard !h.isEmpty, h.count <= 253 else { return false }
        return h.range(of: #"^[A-Za-z0-9.\-:]+$"#, options: .regularExpression) != nil
    }
}

/// 服务器的提醒方式：apns = 服务器自己推（有推送密钥）；local = 服务器推不了，手机自己排本地提醒
enum PushMode: String, Codable {
    case apns, local
}

enum ServerConfig {
    /// 配对过的电脑（地址、端口、上次连通的地址、提醒方式）；密钥不在这里，在钥匙串
    struct Record: Codable, Equatable {
        var name: String
        var hosts: [String]
        var apiPort: Int
        var dshPort: Int
        var activeHost: String?
        var push: PushMode?
        var pairedAt: Date
    }

    enum Source: Equatable { case paired, local, none }

    /// 解析后的一份：现在连哪、带什么密钥
    struct Resolved: Equatable {
        let source: Source
        let name: String
        let host: String
        let apiPort: Int
        let dshPort: Int
        let key: String
    }

    private struct State {
        var record: Record?
        var key: String?
        var demo: Bool
        /// 老大在开发版里点过「断开」：不再退回 LocalConfig（直到重新配对）
        var localOff: Bool
        var push: PushMode?
        /// -forceUnpaired：这次启动当作没配对；这次里配对成功后就照常
        var forcedUnpaired: Bool
    }

    // MARK: 存储
    private static var suffix: String { Profile.isSim ? "sim" : "real" }
    private static var recordKey: String { "pair_record_v1_\(suffix)" }
    private static var keychainKey: String { "pair_key_v1_\(suffix)" }
    private static var demoKey: String { "demo_mode_v1_\(suffix)" }
    private static var localOffKey: String { "local_config_off_v1_\(suffix)" }
    private static var pushKey: String { "server_push_v1_\(suffix)" }

    private static let args = ProcessInfo.processInfo.arguments

    /// 启动参数：-demoMode 直接进演示；-forceUnpaired（仅 Debug）当作没配对（不看存过的配对、不退回 LocalConfig），用来看引导页
    static let forcedDemo = args.contains("-demoMode")
    private static let forcedUnpairedArg: Bool = {
        #if DEBUG
        return args.contains("-forceUnpaired")
        #else
        return false
        #endif
    }()
    /// UI 测试（-uiTestDisableDeviceData）：只认 LocalConfig，不看这台模拟器上存过的配对，结果才稳定
    private static let testHarness = args.contains("-uiTestDisableDeviceData")

    private static let lock = OSAllocatedUnfairLock(initialState: load())

    private static func load() -> State {
        let d = UserDefaults.standard
        migrateLegacyIfNeeded()
        var record = d.data(forKey: recordKey).flatMap { try? JSONDecoder().decode(Record.self, from: $0) }
        var key = Keychain.get(keychainKey)
        if record == nil || (key ?? "").isEmpty { record = nil; key = nil }   // 两样都在才算配对过（重装 App 后钥匙串里会留着旧密钥）
        let push = d.string(forKey: pushKey).flatMap(PushMode.init(rawValue:)) ?? record?.push
        // UI 测试只认 -demoMode：这台模拟器上点过「先看看演示」也不能让别的用例掉进演示
        return State(record: record, key: key, demo: forcedDemo || (!testHarness && d.bool(forKey: demoKey)),
                     localOff: d.bool(forKey: localOffKey), push: push, forcedUnpaired: forcedUnpairedArg)
    }

    /// build 54 及以前：地址和密钥编在 App 里，App 每次启动抄一份进 App Group 给小组件。
    /// 第一次跑这一版、还没配对过：把那一份当成配对过的电脑接着用（老大自己的手机装上就能用，不用先扫码）。只做一次
    private static func migrateLegacyIfNeeded() {
        let d = UserDefaults.standard
        let flag = "pair_migrated_v1"
        guard !d.bool(forKey: flag) else { return }
        d.set(true, forKey: flag)
        guard !Profile.isSim, d.data(forKey: "pair_record_v1_real") == nil else { return }
        let shared = SharedStore.defaults
        guard let base = shared.string(forKey: "pivis_base").flatMap(URL.init(string:)),
              let host = base.host, !host.isEmpty, host != "127.0.0.1", host != "localhost",
              let key = shared.string(forKey: "pivis_app_key"), !key.isEmpty else { return }
        let rec = Record(name: "我的电脑", hosts: [host], apiPort: base.port ?? 8943, dshPort: 8960,
                         activeHost: host, push: nil, pairedAt: Date())
        guard let data = try? JSONEncoder().encode(rec) else { return }
        Keychain.set("pair_key_v1_real", key)
        d.set(data, forKey: "pair_record_v1_real")
    }

    private static func persist(_ s: State) {
        let d = UserDefaults.standard
        if let r = s.record, let data = try? JSONEncoder().encode(r) { d.set(data, forKey: recordKey) } else { d.removeObject(forKey: recordKey) }
        if let k = s.key, !k.isEmpty { if Keychain.get(keychainKey) != k { Keychain.set(keychainKey, k) } } else { Keychain.delete(keychainKey) }
        if !forcedDemo && !testHarness { d.set(s.demo, forKey: demoKey) }
        d.set(s.localOff, forKey: localOffKey)
        if let p = s.push { d.set(p.rawValue, forKey: pushKey) } else { d.removeObject(forKey: pushKey) }
    }

    private static func update(_ change: (inout State) -> Void) {
        let s = lock.withLock { st -> State in change(&st); return st }
        persist(s)
    }

    // MARK: 解析
    static var resolved: Resolved? {
        let s = lock.withLock { $0 }
        if s.forcedUnpaired { return nil }
        if !testHarness, let r = s.record, let k = s.key, !k.isEmpty {
            let host = r.activeHost.flatMap { r.hosts.contains($0) ? $0 : nil } ?? r.hosts.first ?? ""
            if !host.isEmpty {
                return Resolved(source: .paired, name: r.name, host: host, apiPort: r.apiPort, dshPort: r.dshPort, key: k)
            }
        }
        if Profile.isSim {
            // 模拟回放：和以前一模一样（LocalConfig 的地址，P-Health 8944、DSH 8960）
            let host = LocalConfig.serverHost.isEmpty ? "127.0.0.1" : LocalConfig.serverHost
            return Resolved(source: .local, name: "测试环境", host: host, apiPort: 8944, dshPort: 8960, key: LocalConfig.appKey)
        }
        if !s.localOff, !LocalConfig.serverHost.isEmpty, !LocalConfig.appKey.isEmpty {
            return Resolved(source: .local, name: "开发配置", host: LocalConfig.serverHost, apiPort: 8943, dshPort: 8960,
                            key: LocalConfig.appKey)
        }
        return nil
    }

    /// 演示模式：页面来自包里的样例，不连任何服务器
    static var isDemo: Bool { lock.withLock { $0.demo } }
    /// 有一台能连的电脑（配对过的，或者开发版编进去的）
    static var hasServer: Bool { resolved != nil }
    static var source: Source { resolved?.source ?? .none }
    static var record: Record? { lock.withLock { $0.record } }
    static var appKey: String { isDemo ? "" : (resolved?.key ?? "") }
    /// 服务器怎么提醒；还不知道（老服务器没说）就当它自己推，和 build 46 起一样
    static var pushMode: PushMode {
        #if DEBUG
        // 验收用：-pushMode local 当作服务器推不了（看本地提醒），-pushMode apns 反过来
        if let i = args.firstIndex(of: "-pushMode"), i + 1 < args.count, let m = PushMode(rawValue: args[i + 1]) { return m }
        #endif
        return lock.withLock { $0.push } ?? .apns
    }
    /// 手机自己排待办提醒：服务器说它推不了（push = local），而且真连着一台电脑（演示不排）
    static var localReminders: Bool { pushMode == .local && !isDemo && hasServer }

    /// 演示 / 没配对时的地址：.invalid 域名一定解析不了，请求马上失败，绝不会发到别人的服务器上
    static let nowhere = URL(string: "http://phealth-unpaired.invalid")!

    static func hostPart(_ h: String) -> String { h.contains(":") && !h.hasPrefix("[") ? "[\(h)]" : h }

    static var pivisBase: URL {
        guard !isDemo, let r = resolved else { return nowhere }
        return URL(string: "http://\(hostPart(r.host)):\(r.apiPort)") ?? nowhere
    }

    /// DSH 网页端（对话、实时回复）。配对过的电脑：走 P-Health 服务器转发的 /dshp（DSH 自己只听本机 127.0.0.1，
    /// 手机不直连 DSH 端口；每个请求、WebSocket 握手都带设备密钥）。模拟回放 / 开发版 LocalConfig：照旧直连 8960
    static var dshBase: URL {
        guard !isDemo, let r = resolved else { return nowhere }
        if r.source == .paired { return URL(string: "http://\(hostPart(r.host)):\(r.apiPort)\(dshProxyPath)") ?? nowhere }
        return URL(string: "http://\(hostPart(r.host)):\(r.dshPort)") ?? nowhere
    }

    /// 服务器转发 DSH 的路径前缀（HTTP 和 WebSocket 都是）
    static let dshProxyPath = "/dshp"

    // MARK: 改
    /// 配对成功：存下这台电脑。返回是不是换了一台（密钥变了 = 另一台电脑 / 服务器重置过）
    @discardableResult
    static func save(_ link: PairLink, activeHost: String, push: PushMode?) -> Bool {
        var changed = false
        update { s in
            changed = s.key != link.key
            s.record = Record(name: link.name, hosts: link.hosts, apiPort: link.apiPort, dshPort: link.dshPort,
                              activeHost: activeHost, push: push, pairedAt: Date())
            s.key = link.key
            s.demo = false
            s.localOff = false
            s.forcedUnpaired = false
            s.push = push ?? (changed ? nil : s.push)
        }
        return changed
    }

    static func setActiveHost(_ host: String) {
        update { s in s.record?.activeHost = host }
    }

    /// 服务器说了它怎么提醒（hello / status 里的 push）。返回有没有变
    @discardableResult
    static func setPush(_ mode: PushMode) -> Bool {
        var changed = false
        update { s in
            changed = s.push != mode
            s.push = mode
            s.record?.push = mode
        }
        return changed
    }

    /// 断开：忘掉这台电脑（开发版也不再退回编进去的那份）
    static func clearPairing() {
        update { s in
            s.record = nil
            s.key = nil
            s.push = nil
            s.demo = false
            s.localOff = !Profile.isSim             // 模拟回放永远退回测试环境，不用记
            s.forcedUnpaired = forcedUnpairedArg     // -forceUnpaired 启动的：断开后回到引导页（模拟器上看得到）
        }
    }

    static func setDemo(_ on: Bool) {
        update { s in s.demo = on }
    }
}

// MARK: - 试连：GET /api/v3/hello（带密钥），2.5 秒内没回就算不通
enum ServerProbe {
    struct Hello {
        var name: String?
        var push: PushMode?
        /// DSH 怎么连：build 55 起只有 "proxy"（经服务器的 /dshp）；只记下来，配对过的电脑一律走转发
        var dsh: String?
    }

    enum Outcome {
        case ok(Hello)
        /// 401 / 403：密钥不对（二维码过期、服务器换了密钥）
        case wrongKey
        /// 连不上（不在同一个网、电脑睡着了、服务没开）
        case unreachable
    }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 2.5
        c.timeoutIntervalForResource = 3
        c.waitsForConnectivity = false
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: c)
    }()

    static func hello(host: String, port: Int, key: String) async -> Outcome {
        guard let base = URL(string: "http://\(ServerConfig.hostPart(host)):\(port)") else { return .unreachable }
        func get(_ path: String) async -> (Int, [String: Any]?)? {
            var req = URLRequest(url: base.appendingPathComponent(path), timeoutInterval: 2.5)
            req.setValue(key, forHTTPHeaderField: "X-Pivis-Key")
            guard let (data, resp) = try? await session.data(for: req), let http = resp as? HTTPURLResponse else { return nil }
            return (http.statusCode, (try? JSONSerialization.jsonObject(with: data)) as? [String: Any])
        }
        guard let (code, obj) = await get("api/v3/hello") else { return .unreachable }
        switch code {
        case 200 where obj?["ok"] as? Bool == true:
            return .ok(Hello(name: obj?["name"] as? String,
                             push: (obj?["push"] as? String).flatMap(PushMode.init(rawValue:)),
                             dsh: obj?["dsh"] as? String))
        case 401, 403:
            return .wrongKey
        case 404:
            // 还没有 /hello 的老服务器（build 54 及以前）：用 /status 认一下密钥
            guard let (c2, _) = await get("api/v3/status") else { return .unreachable }
            if c2 == 200 { return .ok(Hello()) }
            return (c2 == 401 || c2 == 403) ? .wrongKey : .unreachable
        default:
            return .unreachable
        }
    }

    /// 几个地址一起试，按优先顺序取第一个通的（排在前面的还没回就等它，最多 2.5 秒）。
    /// 一个都不通：有密钥不对的就报密钥不对，不然报连不上
    static func probe(hosts: [String], port: Int, key: String) async -> (host: String?, outcome: Outcome) {
        guard !hosts.isEmpty else { return (nil, .unreachable) }
        return await withTaskGroup(of: (Int, Outcome).self) { group in
            for (i, h) in hosts.enumerated() {
                group.addTask { (i, await hello(host: h, port: port, key: key)) }
            }
            var results: [Int: Outcome] = [:]
            for await (i, o) in group {
                results[i] = o
                for j in hosts.indices {
                    guard let r = results[j] else { break }
                    if case .ok = r { group.cancelAll(); return (hosts[j], r) }
                }
            }
            let anyWrongKey = results.values.contains { if case .wrongKey = $0 { return true }; return false }
            return (nil, anyWrongKey ? .wrongKey : .unreachable)
        }
    }
}

// MARK: - 界面上的连接状态：引导页 / 演示 / 正常；配对、断开、换地址
@MainActor
final class ServerLink: ObservableObject {
    static let shared = ServerLink()

    enum Mode: Equatable { case ready, demo, unpaired }

    @Published private(set) var mode: Mode
    /// 每换一次服务器（配对、断开、进出演示）加一：整个主界面重建，页面、对话、小组件都重新拉
    @Published private(set) var generation = 0
    /// 配对相关的弹层：确认「连接到 X？」、粘贴链接、连接设置
    @Published var sheet: PairSheet?
    /// 扫码（全屏）
    @Published var scanning = false
    /// 「断开」前确认一次
    @Published var confirmUnpair = false
    /// 服务器不认这个密钥了（换过密钥 / 重置过）：页面连不上时提示重新扫码
    @Published private(set) var keyRejected = false

    /// 扫码页关上后要弹的（扫到的「连接到 X？」，或者点了「粘贴链接」）：全屏页和弹层不能同时出来
    var afterScanSheet: PairSheet?
    /// 粘贴框里先放的字（打开了一条看不懂的配对链接时放进去，让人看得到）
    var pasteDraft = ""

    private var probing = false
    private var lastProbe = Date.distantPast
    /// 试连通过、还没换上的那台（「已连接」显示一下再换）
    private var verified: (link: PairLink, host: String, hello: ServerProbe.Hello)?
    private var lastOpened: (url: String, at: Date)?

    private init() { mode = Self.currentMode() }

    private static func currentMode() -> Mode {
        if ServerConfig.isDemo { return .demo }
        return ServerConfig.hasServer ? .ready : .unpaired
    }

    // MARK: 弹层
    /// 从外面打开的 phealth://pair 链接（系统相机扫码、点链接）。根视图和主界面都会转过来，1 秒内同一条只认一次
    func handleOpenURL(_ url: URL) {
        guard url.scheme?.lowercased() == "phealth", url.host?.lowercased() == "pair" else { return }
        let s = url.absoluteString
        if let last = lastOpened, last.url == s, Date().timeIntervalSince(last.at) < 1 { return }
        lastOpened = (s, Date())
        // 主界面开着的抽屉 / 全屏页先收起来，弹层才出得来
        NotificationCenter.default.post(name: .pivisDismissForPairing, object: nil)
        let parsed = PairLink(url: url)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
            if let l = parsed {
                self.offer(l)
            } else {
                self.pasteDraft = s
                self.sheet = .paste
            }
        }
    }

    /// 收到一条配对链接（App 里扫到、粘贴、从外面打开）：先问「连接到 X？」
    func offer(_ link: PairLink) {
        if scanning {
            afterScanSheet = .confirm(link)
            scanning = false
        } else {
            sheet = .confirm(link)
        }
    }

    func startScan() {
        if sheet != nil {
            // 先收起弹层再出全屏页
            sheet = nil
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { self.scanning = true }
        } else {
            scanning = true
        }
    }

    func showPaste() { pasteDraft = ""; sheet = .paste }
    func showConnection() { sheet = .connection }

    /// 扫码页关掉了：扫到了就接着问；点了「粘贴链接」就出粘贴框
    func scanClosed() {
        guard let next = afterScanSheet else { return }
        afterScanSheet = nil
        if next == .paste { pasteDraft = "" }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { self.sheet = next }
    }

    // MARK: 配对
    enum PairError: Error {
        case wrongKey, unreachable(String)
        var message: String {
            switch self {
            case .wrongKey: return "配对码不对或已过期，在电脑上重新出一个码再扫"
            case .unreachable(let name): return "连不上 \(name)。手机和电脑要在同一个 Wi-Fi（或都开着 Tailscale），电脑别睡着"
            }
        }
    }

    /// 试连（几个地址一起试）。通了先记着，commitPair 才存下、换界面；不通什么都不存
    func pairProbe(_ link: PairLink) async -> PairError? {
        verified = nil
        let (host, outcome) = await ServerProbe.probe(hosts: link.hosts, port: link.apiPort, key: link.key)
        switch outcome {
        case .wrongKey: return .wrongKey
        case .unreachable: return .unreachable(link.name)
        case .ok(let hello):
            guard let host else { return .unreachable(link.name) }
            verified = (link, host, hello)
            return nil
        }
    }

    /// 存下试连通过的那台，整个界面换成它的（页面、对话、小组件都重新拉）
    func commitPair() {
        guard let v = verified else { return }
        verified = nil
        let changed = ServerConfig.save(v.link, activeHost: v.host, push: v.hello.push)
        if changed { forgetOldServer() }
        keyRejected = false
        lastProbe = Date()
        DshAPI.dbg("paired \(v.link.name) via \(v.host) push=\(v.hello.push?.rawValue ?? "?") dsh=\(v.hello.dsh ?? "?") changed=\(changed)")
        DemoStore.reset()
        reload()
        AppDelegate.startDeviceServices(afterPairing: true)
    }

    func unpair() {
        ServerConfig.clearPairing()
        forgetOldServer()
        keyRejected = false
        Reminders.shared.clearTodoReminders()
        reload()
    }

    func enterDemo() {
        ServerConfig.setDemo(true)
        reload()
    }

    func exitDemo() {
        ServerConfig.setDemo(false)
        DemoStore.reset()
        reload()
    }

    private func reload() {
        sheet = nil
        mode = Self.currentMode()
        generation &+= 1
        PageSync.shared.reset()
        WidgetBridge.shareConfig()
        WidgetBridge.refresh(after: 0.5)
    }

    /// 换了一台电脑（或断开）：上一台的登录、对话缓存、没送出去的待办动作、小组件缓存都不要了
    private func forgetOldServer() {
        let d = UserDefaults.standard
        d.removeObject(forKey: "dsh_cookie")
        for k in d.dictionaryRepresentation().keys where k.hasPrefix("chat_session_") || k.hasPrefix("chat_seen_") {
            d.removeObject(forKey: k)
        }
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        try? FileManager.default.removeItem(at: docs.appendingPathComponent("chat_cache"))
        DshAPI.forgetSessions()
        TodoOutbox.shared.clearAll()
        if let dir = SharedStore.container { try? FileManager.default.removeItem(at: dir.appendingPathComponent("widget.json")) }
    }

    // MARK: 换地址
    /// 回到前台、连接出错时：几个地址重新试一遍，换到现在最好的那个（在家走局域网，出门走 Tailscale）
    func reprobe(force: Bool = false) {
        guard ServerConfig.source == .paired, !ServerConfig.isDemo, !probing,
              let rec = ServerConfig.record, !Self.baseOverridden else { return }
        guard force || Date().timeIntervalSince(lastProbe) > 20 else { return }
        let key = ServerConfig.appKey
        guard !key.isEmpty else { return }
        probing = true
        lastProbe = Date()
        Task { @MainActor in
            defer { probing = false }
            let (host, outcome) = await ServerProbe.probe(hosts: rec.hosts, port: rec.apiPort, key: key)
            switch outcome {
            case .ok(let hello):
                keyRejected = false
                var dirty = false
                if let host, host != ServerConfig.resolved?.host {
                    DshAPI.dbg("server host → \(host)")
                    ServerConfig.setActiveHost(host)
                    WidgetBridge.shareConfig()
                    dirty = true
                }
                if let p = hello.push, ServerConfig.setPush(p) { dirty = true }
                if dirty {
                    NotificationCenter.default.post(name: .pivisPagesDirty, object: nil)
                    PageSync.shared.poke()
                }
            case .wrongKey:
                keyRejected = true
            case .unreachable:
                break
            }
        }
    }

    /// 请求连不上服务器：隔一会儿重新试地址（20 秒内只试一次）
    nonisolated static func connectionFailed(_ error: Error) {
        let codes: Set<URLError.Code> = [.cannotConnectToHost, .timedOut, .cannotFindHost, .networkConnectionLost,
                                         .dnsLookupFailed, .notConnectedToInternet]
        guard let e = error as? URLError, codes.contains(e.code) else { return }
        Task { @MainActor in ServerLink.shared.reprobe() }
    }

    /// Debug 的 -pivisBase 指定了地址：不去试别的
    private static let baseOverridden: Bool = {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-pivisBase")
        #else
        return false
        #endif
    }()
}

enum PairSheet: Identifiable, Equatable {
    case confirm(PairLink)
    case paste
    case connection
    var id: String {
        switch self {
        case .confirm(let l): return "confirm-\(l.id)"
        case .paste: return "paste"
        case .connection: return "connection"
        }
    }
}
