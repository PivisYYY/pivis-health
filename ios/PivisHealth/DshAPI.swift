import Foundation
import SwiftUI

/// dsh web API 客户端（session/prompt 协议已破解）
enum DshAPI {
    static var base: URL {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if let index = args.firstIndex(of: "-dshBase"), index + 1 < args.count,
           let url = URL(string: args[index + 1]) {
            return url
        }
        #endif
        return ServerConfig.dshBase      // 配对过的电脑（或开发版的 LocalConfig）上的 DSH 网页端
    }
    static let sessionId = Profile.isSim ? "phealth-sim-r3-main" : "phealth-r3-main"
    /// 板块 → dsh 专项 session 的兜底表（与后端 dsh_chat.SESSION_BY_CONTEXT 一致）。
    /// 以服务器为准：每次读对话历史，服务器都会告诉我们这个板块现在用哪个 session，记在 serverSessions 里。
    static let sessionByContext: [String: String] = Profile.isSim ? [
        "": sessionId, "休息": "phealth-sim-r3-sleep", "运动": "phealth-sim-r3-sport", "压力": "phealth-sim-r3-stress",
    ] : [
        "": sessionId,
        "休息": "phealth-r3-sleep",
        "运动": "phealth-r3-sport",
        "压力": "phealth-r3-stress",
    ]
    private static let sessionLock = NSLock()
    nonisolated(unsafe) private static var serverSessions: [String: String] = [:]
    static func rememberSession(_ id: String, for context: String) {
        sessionLock.lock(); serverSessions[context] = id; sessionLock.unlock()
    }
    /// 换了一台电脑：上一台告诉过我们的会话不再用
    static func forgetSessions() {
        sessionLock.lock(); serverSessions.removeAll(); sessionLock.unlock()
    }
    static func sessionId(for context: String) -> String {
        sessionLock.lock(); defer { sessionLock.unlock() }
        return serverSessions[context] ?? sessionByContext[context] ?? sessionId
    }
    static var pivisBase: URL {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if let index = args.firstIndex(of: "-pivisBase"), index + 1 < args.count,
           let url = URL(string: args[index + 1]) {
            return url
        }
        #endif
        return ServerConfig.pivisBase    // 模拟回放 8944，正式 8943 / 配对链接里的端口（见 ServerConfig）
    }

    /// 调试日志：os.Logger（值是 private）；DEBUG 版另写 Documents/dsh_debug.log（后台写、有上限、不写令牌 / Cookie）
    static func dbg(_ s: String) { Log.debug(s) }

    /// 拦截 302：不跟随跳转，捕获第一个响应里的 Set-Cookie
    final class CookieCatcher: NSObject, URLSessionTaskDelegate {
        var setCookie: String?
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest) async -> URLRequest? {
            if setCookie == nil { setCookie = response.value(forHTTPHeaderField: "Set-Cookie") }
            return nil
        }
    }

    /// 获取 auth cookie（用 token 换 cookie，curl 验证通过的路径）
    static func ensureAuth() async -> Bool {
        dbg("ensureAuth start")
        do {
            // 从 pivis-health 后端拿 token（服务器只把令牌给带设备密钥的 App，密钥由 PivisAPI 统一带上）
            let json = try await PivisAPI.json(PivisAPI.request("api/dsh-token", timeout: 15))
            guard let token = json["token"] as? String else { dbg("no token in reply"); return false }
            dbg("token ok")
            // 用 token 获取 cookie（302 跳转会被 URLSession 吃掉 Set-Cookie，必须拦截）
            guard let authURL = URL(string: "\(base)/?token=\(token)") else { return false }
            var authReq = URLRequest(url: authURL, timeoutInterval: 15)
            PivisAPI.authorize(&authReq)      // 经服务器转发（/dshp）时要带设备密钥；直连 DSH 不带
            let catcher = CookieCatcher()
            let session = URLSession(configuration: .ephemeral, delegate: catcher, delegateQueue: nil)
            defer { session.finishTasksAndInvalidate() }     // 一次性的会话：用完就放掉（不然委托和会话一直留着）
            let (_, resp) = try await session.data(for: authReq)
            let cookie = catcher.setCookie ?? (resp as? HTTPURLResponse)?.value(forHTTPHeaderField: "Set-Cookie")
            guard let cookie else { dbg("no set-cookie header"); return false }
            // 只取第一段 name=value，属性段（Path/Expires/SameSite 等）不入 Cookie 头
            let firstPair = cookie.split(separator: ";").first.map(String.init) ?? ""
            guard firstPair.contains("=") else { dbg("bad cookie pair"); return false }
            UserDefaults.standard.set(firstPair, forKey: "dsh_cookie")
            dbg("cookie saved")
            return true
        } catch {
            dbg("auth error: \(error.localizedDescription)")
        }
        return false
    }

    /// 发送消息到 P-Health。nil=成功；否则返回可直接展示的真实错误。
    static func sendMessage(_ text: String, context: String = "") async -> String? {
        var result = await sendOnce(text, context: context)
        if result == "retry" { result = await sendOnce(text, context: context) }
        // 会话还没建（新环境、新开的专项对话）：改走服务器发，服务器会先把会话建好
        if result == "session-missing" { result = await sendViaServer(text, context: context) }
        return result
    }

    /// 刚由服务器建好会话：对话页要重新订阅实时回复（之前订阅的是还不存在的会话）
    nonisolated(unsafe) private static var createdSession = false
    private static func markSessionCreated() {
        sessionLock.lock(); createdSession = true; sessionLock.unlock()
    }
    static func consumeSessionCreated() -> Bool {
        sessionLock.lock(); defer { sessionLock.unlock() }
        let v = createdSession; createdSession = false; return v
    }

    /// 经 P-Health 服务器发（/api/chat/send）：会话不存在时服务器先建好再发
    private static func sendViaServer(_ text: String, context: String) async -> String? {
        let req = PivisAPI.request("api/chat/send", method: "POST", json: ["text": text, "context": context], timeout: 45)
        do {
            let json = try await PivisAPI.json(req)
            dbg("sendViaServer ok=\(json["ok"] as? Bool ?? false)")
            if json["ok"] as? Bool == true {
                markSessionCreated()
                return nil
            }
            return "P-Health 暂时没接上这段对话，请稍后再发一次"
        } catch PivisAPI.Failure.offline(let error) {
            dbg("sendViaServer offline: \(error.localizedDescription)")
            return "网络连接失败，请检查网络后重试"
        } catch {
            dbg("sendViaServer failed: \(error.localizedDescription)")
            return "P-Health 暂时没接上这段对话，请稍后再发一次"
        }
    }

    /// DSH 的错误码 → 给老大看的中文
    private static func friendly(_ code: String) -> String {
        switch code {
        case "session/writer-held": return "这段对话正被桌面端占用，请在桌面端关掉对应会话后重试"
        default: return "P-Health 没收到这句，请再发一次"
        }
    }

    /// 无 cookie 先换 cookie；仅认证刷新需要重试，writer-held 等业务错误直接呈现。
    private static func sendOnce(_ text: String, context: String = "") async -> String? {
        if UserDefaults.standard.string(forKey: "dsh_cookie") == nil {
            guard await ensureAuth() else { dbg("sendOnce abort: no auth"); return "无法登录 P-Health 服务" }
        }
        dbg("sendOnce POST, cookie=\(UserDefaults.standard.string(forKey: "dsh_cookie") == nil ? "no" : "yes")")
        let requestId = "ios-\(Int(Date().timeIntervalSince1970 * 1000))-\(Int.random(in: 0...9999))"
        let body: [String: Any] = [
            "rpcId": "send-\(requestId)",
            "type": "client-request",
            "method": "session/prompt",
            "payload": [
                "args": [
                    "request": [
                        "requestId": requestId,
                        "sessionId": sessionId(for: context),
                        "mode": "queue",
                        "content": [["type": "text", "text": text]],
                        "clientTimeZone": "Asia/Shanghai"
                    ]
                ] as [String: Any]
            ]
        ]

        guard let url = URL(string: "\(base)/api/session/prompt") else { return "服务地址无效" }
        var req = URLRequest(url: url, timeoutInterval: 30)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let cookie = UserDefaults.standard.string(forKey: "dsh_cookie") {
            req.setValue(cookie, forHTTPHeaderField: "Cookie")
        }
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)

        do {
            // DSH 的接口：经服务器转发（/dshp）时 PivisAPI 按地址带上设备密钥，直连 DSH 不带；状态码这里自己看
            let (data, http) = try await PivisAPI.send(req, checkStatus: false)
            dbg("resp status=\(http.statusCode)")
            if http.statusCode == 401 {
                UserDefaults.standard.removeObject(forKey: "dsh_cookie")
                return await ensureAuth() ? "retry" : "登录已过期，请检查网络后重试"
            }
            let json = PivisAPI.object(data)
            let result = json?["result"] as? [String: Any]
            let ok = result?["ok"] as? Bool ?? false
            if ok { dbg("result ok"); return nil }
            let error = result?["error"] as? [String: Any]
            let code = error?["code"] as? String ?? "unknown"
            dbg("result failed code=\(code) status=\(http.statusCode)")
            if code == "session/not-found" { return "session-missing" }
            return friendly(code)
        } catch {
            dbg("send error: \(error.localizedDescription)")
            return "网络连接失败，请检查网络后重试"
        }
    }

    /// 读取会话消息（通过 pivis-health 后端中转）；after = 增量轮询（ISO 时间），session = 板块标签。
    /// busy = dsh 回合还在进行（阶段性回复用）；lastTool = 本轮最近一次动作，已换成给老大看的话（进度提示）。
    static func fetchMessages(limit: Int = 15, after: String? = nil, session: String = "") async -> (msgs: [ChatMsg], latest: String?, busy: Bool, lastTool: String?, sessionId: String?) {
        let req = PivisAPI.request("api/chat", ["limit": String(limit),
                                                "after": (after?.isEmpty ?? true) ? nil : after,
                                                "session": session.isEmpty ? nil : session])
        do {
            let (data, _) = try await PivisAPI.send(req)
            let json = PivisAPI.object(data)
            if let sid = json?["session"] as? String, !sid.isEmpty { rememberSession(sid, for: session) }
            let messages = json?["messages"] as? [[String: Any]] ?? []
            let msgs = messages.compactMap { m -> ChatMsg? in
                guard let text = m["text"] as? String, let role = m["role"] as? String else { return nil }
                let time = m["time"] as? String ?? ""
                // 带着习惯 / 待办发的：服务器已把标记拆成 context，气泡下写「带着：名字」
                let carried = (m["context"] as? [String: Any])?["name"] as? String
                return ChatMsg(role: role, text: text, time: time, about: carried)
            }
            return (msgs,
                    json?["latest_time"] as? String ?? msgs.last?.time,
                    json?["busy"] as? Bool ?? false,
                    (json?["last_tool"] as? String).map { actionLabel($0, json?["last_args"] as? String) },
                    json?["session"] as? String)
        } catch {
            dbg("chat fetch error: \(error.localizedDescription)")
            return ([], nil, false, nil, nil)
        }
    }
}

struct ChatMsg: Identifiable, Equatable {
    private let localId = UUID()
    let role: String
    var text: String
    let time: String
    let stableId: String?
    /// 带着哪个习惯 / 哪张待办发的（气泡下「带着：X」）
    var about: String? = nil

    init(role: String, text: String, time: String, stableId: String? = nil, about: String? = nil) {
        self.role = role
        self.text = text
        self.time = time
        self.stableId = stableId
        self.about = about
    }

    var key: String {
        if let stableId { return stableId }
        return time.isEmpty ? "local-\(localId.uuidString)" : "\(role)|\(time)|\(text.hashValue)"
    }
    var id: String { key }

    var isMe: Bool { role == "me" }
}
