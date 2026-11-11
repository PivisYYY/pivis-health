import Foundation

// MARK: - 两条实时通道（逐句回复 / 授权与提问事件）共用的 WebSocket：登录、握手、发 open 帧、收消息、停。
// 每次开一个临时 URLSession，停的时候 invalidate（以前开了从不释放）。
@MainActor
final class DshSocket {
    private let name: String
    private var session: URLSession?
    private var task: URLSessionWebSocketTask?
    private var stopped = true
    var onText: (String) -> Void = { _ in }
    var onFailure: (String) -> Void = { _ in }

    init(name: String) { self.name = name }

    /// DSH 的多路复用通道地址：和 DshAPI.base 同一个地址、同一个路径前缀（经服务器转发时是 /dshp/api/remote.mux）
    private static var url: URL? {
        guard var c = URLComponents(url: DshAPI.base, resolvingAgainstBaseURL: false), let scheme = c.scheme else { return nil }
        let secure = scheme == "https"
        c.scheme = secure ? "wss" : "ws"
        if c.port == nil { c.port = secure ? 443 : 80 }
        var path = c.path
        while path.hasSuffix("/") { path.removeLast() }
        c.path = path + "/api/remote.mux"
        c.query = nil
        c.fragment = nil
        return c.url
    }

    func start(open frame: [String: Any], loginFailed: String, badAddress: String) async {
        if UserDefaults.standard.string(forKey: "dsh_cookie") == nil {
            guard await DshAPI.ensureAuth() else { onFailure(loginFailed); return }
        }
        guard let cookie = UserDefaults.standard.string(forKey: "dsh_cookie"), let socketURL = Self.url else {
            onFailure(badAddress)
            return
        }
        stop()
        stopped = false
        var request = URLRequest(url: socketURL)
        request.setValue(cookie, forHTTPHeaderField: "Cookie")
        PivisAPI.authorize(&request)      // 握手经 P-Health 服务器转发（/dshp）时带设备密钥；直连 DSH 不带
        let session = URLSession(configuration: .ephemeral)
        let task = session.webSocketTask(with: request)
        self.session = session
        self.task = task
        task.resume()
        guard let data = try? JSONSerialization.data(withJSONObject: frame),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { [weak self] error in
            Task { @MainActor in
                guard let self, !self.stopped, self.task === task else { return }
                if let error {
                    self.onFailure(error.localizedDescription)
                } else {
                    DshAPI.dbg("\(self.name) opened")
                    self.receive(task)
                }
            }
        }
    }

    func stop() {
        stopped = true
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        session?.invalidateAndCancel()
        session = nil
    }

    private func receive(_ task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, !self.stopped, self.task === task else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message { self.onText(text) }
                    self.receive(task)
                case .failure(let error):
                    self.onFailure(error.localizedDescription)
                }
            }
        }
    }
}


@MainActor
final class DshStreamClient {
    enum Event {
        case start(attemptId: String)
        case baseline(attemptId: String, text: String)
        case delta(String)
        case end(attemptId: String)
        case failure(String)
        /// 工具调用开始/结束（阶段性反馈：让用户看到 Agent 正在调用什么）
        /// key = 这次调用的唯一标识（同一个工具调好几次也各算一行）；label = 给老大看的动作
        case toolStart(key: String, label: String)
        case toolEnd(key: String, label: String)
    }

    private let sessionId: String
    private let onEvent: (Event) -> Void
    private let socket = DshSocket(name: "live stream")
    private var streamedTextBlocks: Set<Int> = []
    private var fallbackTextBlocks: [Int: String] = [:]
    private var attemptTextChars = 0
    private var loggedChunkTypes: Set<String> = []
    private var announcedToolIndices: Set<Int> = []
    private var toolNamesByIndex: [Int: String] = [:]
    private var completedBeforeAnnounce: Set<Int> = []
    private var toolArgsByIndex: [Int: String] = [:]
    private var attemptKey = ""

    init(sessionId: String, onEvent: @escaping (Event) -> Void) {
        self.sessionId = sessionId
        self.onEvent = onEvent
        socket.onText = { [weak self] text in self?.handle(text) }
        socket.onFailure = { [weak self] message in self?.emit(.failure(message)) }
    }

    func start() async {
        let open: [String: Any] = [
            "type": "open",
            "streamId": "ios-\(UUID().uuidString)",
            "endpoint": "session/follow",
            "payload": [
                "args": [
                    "request": [
                        "address": ["kind": "session", "sessionId": sessionId],
                        "assistantStream": true,
                    ],
                ],
            ],
        ]
        await socket.start(open: open, loginFailed: "无法登录 P-Health 实时通道", badAddress: "实时通道地址无效")
    }

    func stop() { socket.stop() }

    private func key(_ index: Int) -> String { "\(attemptKey)#\(index)" }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let frame = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              frame["type"] as? String == "item",
              let value = frame["value"] as? [String: Any] else { return }

        if value["type"] as? String == "snapshot",
           let stream = value["assistantStream"] as? [String: Any],
           let active = stream["activeAttempt"] as? [String: Any],
           let attemptId = active["attemptId"] as? String {
            let compact = active["stream"] as? [[String: Any]] ?? []
            emit(.baseline(attemptId: attemptId, text: Self.text(from: compact)))
            return
        }

        guard value["type"] as? String == "assistant-stream",
              let inner = value["frame"] as? [String: Any],
              let kind = inner["type"] as? String else { return }
        switch kind {
        case "start":
            if let attemptId = inner["attemptId"] as? String {
                streamedTextBlocks = []
                fallbackTextBlocks = [:]
                attemptTextChars = 0
                announcedToolIndices = []
                toolNamesByIndex = [:]
                toolArgsByIndex = [:]
                completedBeforeAnnounce = []
                attemptKey = attemptId
                DshAPI.dbg("live stream start")
                emit(.start(attemptId: attemptId))
            }
        case "chunk":
            guard let chunk = inner["chunk"] as? [String: Any],
                  let type = chunk["type"] as? String else { return }
            if loggedChunkTypes.insert(type).inserted {
                DshAPI.dbg("live stream chunk type=\(type)")
            }
            if type == "text-delta", let text = chunk["text"] as? String {
                attemptTextChars += text.count
                if !text.isEmpty, let index = chunk["index"] as? Int {
                    streamedTextBlocks.insert(index)
                }
                emit(.delta(text))
            } else if type == "tool-call-delta", let index = chunk["index"] as? Int {
                if let name = chunk["name"] as? String, !name.isEmpty {
                    toolNamesByIndex[index] = name
                }
                if let delta = chunk["argumentsDelta"] as? String {
                    toolArgsByIndex[index, default: ""] += delta
                }
                if announcedToolIndices.insert(index).inserted {
                    let name = toolNamesByIndex[index] ?? "工具"
                    emit(.toolStart(key: key(index), label: actionLabel(name)))
                    // 该工具的 block-end 可能先于 delta 到达（适配器缓冲后一次放出）
                    if completedBeforeAnnounce.contains(index) {
                        completedBeforeAnnounce.remove(index)
                        emit(.toolEnd(key: key(index), label: actionLabel(name, toolArgsByIndex[index])))
                    }
                }
            } else if type == "block-end",
                      let index = chunk["index"] as? Int,
                      let block = chunk["block"] as? [String: Any],
                      block["type"] as? String == "tool-call" {
                let name = (block["name"] as? String).flatMap { $0.isEmpty ? nil : $0 }
                    ?? toolNamesByIndex[index]
                    ?? "工具"
                toolNamesByIndex[index] = name
                if let args = block["arguments"] as? String, !args.isEmpty { toolArgsByIndex[index] = args }
                if announcedToolIndices.contains(index) {
                    emit(.toolEnd(key: key(index), label: actionLabel(name, toolArgsByIndex[index])))
                } else {
                    completedBeforeAnnounce.insert(index)
                }
            } else if type == "block-end",
                      let index = chunk["index"] as? Int,
                      let block = chunk["block"] as? [String: Any],
                      block["type"] as? String == "text",
                      let text = block["text"] as? String {
                fallbackTextBlocks[index] = text
            }
        case "end":
            if let attemptId = inner["attemptId"] as? String {
                let fallback = fallbackTextBlocks
                    .filter { !streamedTextBlocks.contains($0.key) }
                    .sorted { $0.key < $1.key }
                    .map(\.value)
                    .joined()
                if !fallback.isEmpty { emit(.delta(fallback)) }
                fallbackTextBlocks = [:]
                DshAPI.dbg("live stream end textChars=\(attemptTextChars) fallbackChars=\(fallback.count)")
                emit(.end(attemptId: attemptId))
            }
        default:
            break
        }
    }

    private static func text(from compact: [[String: Any]]) -> String {
        var result = ""
        var streamedTextBlocks: Set<Int> = []
        var fallbackTextBlocks: [Int: String] = [:]
        for entry in compact {
            switch entry["type"] as? String {
            case "text-delta":
                result += entry["text"] as? String ?? ""
            case "text-chunks":
                if let index = entry["index"] as? Int { streamedTextBlocks.insert(index) }
                result += (entry["texts"] as? [String] ?? []).joined()
            case "chunk":
                guard let chunk = entry["chunk"] as? [String: Any],
                      chunk["type"] as? String == "block-end",
                      let index = chunk["index"] as? Int,
                      let block = chunk["block"] as? [String: Any],
                      block["type"] as? String == "text" else { continue }
                fallbackTextBlocks[index] = block["text"] as? String ?? ""
            default:
                break
            }
        }
        result += fallbackTextBlocks
            .filter { !streamedTextBlocks.contains($0.key) }
            .sorted { $0.key < $1.key }
            .map(\.value)
            .joined()
        return result
    }

    private func emit(_ event: Event) {
        DispatchQueue.main.async { [onEvent] in
            onEvent(event)
        }
    }
}

// MARK: - DSH $events 远程事件客户端（授权请求 / 主动提问 → 客户端交互卡）
/// DSH 远端 waterfall 事件：approval/request、user-questions/request 映射到 App 内交互。
struct InteractionRequest: Identifiable {
    enum Kind {
        case approval(tool: String, reason: String)
        case questions(header: String?, items: [QuestionItem])
    }
    struct QuestionItem: Identifiable {
        let id: String
        let question: String
        let detail: String?
        let header: String?
        let options: [OptionItem]
        let multiSelect: Bool
        struct OptionItem: Identifiable, Hashable {
            let label: String
            let description: String?
            var id: String { label }
        }
    }
    let eventId: String
    let agentId: String
    let kind: Kind
    var id: String { eventId }
}

@MainActor
final class DshEventClient {
    enum Event {
        case request(InteractionRequest)
        case cancelled(eventId: String)
        case emit(event: String)
        case failure(String)
    }

    private let sessionId: String
    private let onEvent: (Event) -> Void
    private let socket = DshSocket(name: "events stream")
    private var clientId: String?

    init(sessionId: String, onEvent: @escaping (Event) -> Void) {
        self.sessionId = sessionId
        self.onEvent = onEvent
        socket.onText = { [weak self] text in self?.handle(text) }
        socket.onFailure = { [weak self] message in self?.emit(.failure(message)) }
    }

    func start() async {
        let open: [String: Any] = [
            "type": "open",
            "streamId": "ios-events-\(UUID().uuidString)",
            "endpoint": "$events",
            "payload": ["args": [:]],
        ]
        await socket.start(open: open, loginFailed: "无法登录 P-Health 事件通道", badAddress: "事件通道地址无效")
    }

    func stop() { socket.stop() }

    /// 应答一个 waterfall 事件。value 为 nil 表示不认识，next 交给其他端。
    func respond(eventId: String, value: Any?) {
        guard let clientId, !clientId.isEmpty else {
            DshAPI.dbg("events respond skipped: no clientId")
            return
        }
        let outcome: [String: Any] = value.map { ["kind": "result", "value": $0] } ?? ["kind": "next"]
        let body: [String: Any] = [
            "rpcId": "events-result-\(Int(Date().timeIntervalSince1970 * 1000))",
            "type": "client-request",
            "method": "$events/result",
            "payload": [
                "args": [
                    "clientId": clientId,
                    "eventId": eventId,
                    "outcome": outcome,
                ] as [String: Any],
            ],
        ]
        guard let url = URL(string: "\(DshAPI.base)/api/$events/result"),
              let data = try? JSONSerialization.data(withJSONObject: body) else { return }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let cookie = UserDefaults.standard.string(forKey: "dsh_cookie") {
            req.setValue(cookie, forHTTPHeaderField: "Cookie")
        }
        req.httpBody = data
        Task { @MainActor in
            do {
                let (_, resp) = try await PivisAPI.send(req, checkStatus: false)
                DshAPI.dbg("events result ok status=\(resp.statusCode)")
            } catch {
                DshAPI.dbg("events result error: \(error.localizedDescription)")
                self.emit(.failure(error.localizedDescription))
            }
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let frame = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        // 所有下行帧都包在 item.value 里（ready/waterfall/cancel/emit 均是）
        let value = (frame["type"] as? String == "item" ? frame["value"] : frame) as? [String: Any]
        guard let value else { return }
        let type = value["type"] as? String

        if type == "ready", let clientId = value["clientId"] as? String {
            self.clientId = clientId
            DshAPI.dbg("events ready clientId=\(clientId.prefix(8))")
            return
        }

        if type == "cancel", let eventId = value["eventId"] as? String {
            DshAPI.dbg("events cancel eventId=\(eventId.prefix(8))")
            emit(.cancelled(eventId: eventId))
            return
        }

        if type == "emit", let event = value["event"] as? String {
            DshAPI.dbg("events emit \(event)")
            emit(.emit(event: event))
            return
        }

        guard type == "waterfall",
              let event = value["event"] as? String,
              let eventId = value["eventId"] as? String,
              let agentId = value["agentId"] as? String else { return }

        // 只处理本 Session 的事件（agentId 即 session id）
        guard agentId == sessionId else { return }
        let request = value["request"] as? [String: Any] ?? [:]
        DshAPI.dbg("events waterfall \(event) eventId=\(eventId.prefix(8))")

        switch event {
        case "approval/request":
            let tool = request["toolName"] as? String ?? "工具"
            let reason = request["displayReason"] as? String
                ?? request["reason"] as? String
                ?? "请求你的允许"
            emit(.request(InteractionRequest(
                eventId: eventId, agentId: agentId,
                kind: .approval(tool: tool, reason: reason))))
        case "user-questions/request":
            let rawQuestions = request["questions"] as? [[String: Any]] ?? []
            let items = rawQuestions.map { q -> InteractionRequest.QuestionItem in
                let rawOptions = q["options"] as? [[String: Any]] ?? []
                return InteractionRequest.QuestionItem(
                    id: q["id"] as? String ?? UUID().uuidString,
                    question: q["question"] as? String ?? "",
                    detail: q["detail"] as? String,
                    header: q["header"] as? String,
                    options: rawOptions.map {
                        InteractionRequest.QuestionItem.OptionItem(
                            label: $0["label"] as? String ?? "",
                            description: $0["description"] as? String)
                    },
                    multiSelect: q["multiSelect"] as? Bool ?? false)
            }
            guard !items.isEmpty else {
                respond(eventId: eventId, value: nil)
                return
            }
            let header = items.compactMap(\.header).first
            emit(.request(InteractionRequest(
                eventId: eventId, agentId: agentId,
                kind: .questions(header: header, items: items))))
        default:
            // 不认识的 waterfall 事件：next 交给桌面端，避免手机端卡死
            DshAPI.dbg("events waterfall unknown \(event), pass next")
            respond(eventId: eventId, value: nil)
        }
    }

    private func emit(_ event: Event) {
        DispatchQueue.main.async { [onEvent] in
            onEvent(event)
        }
    }
}
