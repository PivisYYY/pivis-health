import Foundation
import SwiftUI
import UIKit

// MARK: - 和 P-Health 服务器说话的唯一入口
// 地址（DshAPI.pivisBase → ServerConfig）、设备密钥（X-Pivis-Key，配对时存进钥匙串）、解码（snake_case）、状态码检查、错误都在这里。
// 服务器只放行带密钥的 /api/*（/install、/media/* 不用）；密钥按地址判断，发给别的服务（DSH）的请求不带。
enum PivisAPI {
    static var base: URL { DshAPI.pivisBase }

    /// 一个解码器，全 App 共用（服务器的字段是 snake_case）
    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    enum Failure: Error, LocalizedError {
        /// 连不上（断网、超时、服务器没开）
        case offline(Error)
        /// 服务器回了非 2xx；message = 服务器 JSON 里的 message
        case http(Int, String?)
        /// 回来的数据不是约定的样子
        case decoding(Error)

        var status: Int? { if case .http(let s, _) = self { return s }; return nil }
        var serverMessage: String? { if case .http(_, let m) = self { return m }; return nil }
        var errorDescription: String? {
            switch self {
            case .offline: return "连不上服务器"
            case .http(let s, let m): return m.flatMap { $0.isEmpty ? nil : $0 } ?? "服务器出错（\(s)）"
            case .decoding: return "服务器回的数据看不懂"
            }
        }
    }

    // MARK: 地址

    /// 服务器上的路径 + 查询参数。参数值严格转义（时间里的 + 也转成 %2B，不会被服务器当成空格）
    static func url(_ path: String, _ query: KeyValuePairs<String, String?> = [:]) -> URL {
        let u = base.appendingPathComponent(path)
        let q = query.compactMap { k, v in v.map { "\(k)=\(escape($0))" } }
        guard !q.isEmpty, var c = URLComponents(url: u, resolvingAgainstBaseURL: false) else { return u }
        c.percentEncodedQuery = q.joined(separator: "&")
        return c.url ?? u
    }

    private static let unreserved = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    private static func escape(_ s: String) -> String { s.addingPercentEncoding(withAllowedCharacters: unreserved) ?? "" }

    /// 服务器给的地址 → 能直接用的 URL：/media/…、/api/… 这类相对路径按当前服务地址补全；完整 http(s) 地址照用。
    /// 全 App 只用这一个（视频、海报、照片、链接）
    static func resolve(_ s: String?) -> URL? {
        guard let raw = s?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
        if raw.contains("://") { return URL(string: raw) }
        var b = base.absoluteString
        while b.hasSuffix("/") { b.removeLast() }
        return URL(string: b + (raw.hasPrefix("/") ? raw : "/" + raw))
    }

    // MARK: 请求

    static func request(_ path: String, _ query: KeyValuePairs<String, String?> = [:], method: String = "GET",
                        json: [String: Any]? = nil, body: Data? = nil, contentType: String? = nil,
                        timeout: TimeInterval = 20) -> URLRequest {
        var req = URLRequest(url: url(path, query), timeoutInterval: timeout)
        req.httpMethod = method
        if let json {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: json)
        } else if let body {
            req.httpBody = body
            if let contentType { req.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        }
        return req
    }

    /// 发往本服务器 /api/ 和 /dshp（服务器转发的 DSH）的请求带上设备密钥（WebSocket 握手也用这个）
    static func authorize(_ req: inout URLRequest) {
        let key = ServerConfig.appKey
        guard let u = req.url, isPivisAPI(u), !key.isEmpty else { return }
        req.setValue(key, forHTTPHeaderField: "X-Pivis-Key")
    }

    /// 本服务器的接口：/api/…，或者它转发的 DSH（/dshp…，HTTP 和 WebSocket）。
    /// 模拟回放 / 开发版直连 DSH 的 8960 端口不算（端口不同），照旧不带密钥
    static func isPivisAPI(_ u: URL) -> Bool {
        let b = base
        func port(_ x: URL) -> Int? { x.port ?? (x.scheme == "https" || x.scheme == "wss" ? 443 : 80) }
        guard u.host == b.host, port(u) == port(b) else { return false }
        let p = ServerConfig.dshProxyPath
        return u.path.hasPrefix("/api/") || u.path == p || u.path.hasPrefix(p + "/")
    }

    /// 发请求。checkStatus：非 2xx 抛 .http（带服务器的 message）；发给 DSH 这类自己看状态码的传 false
    @discardableResult
    static func send(_ req: URLRequest, checkStatus: Bool = true) async throws -> (Data, HTTPURLResponse) {
        // 演示 / 没配对：不连任何服务器
        if ServerConfig.isDemo || !ServerConfig.hasServer { throw Failure.offline(URLError(.notConnectedToInternet)) }
        var r = req
        authorize(&r)
        let data: Data
        let resp: URLResponse
        do { (data, resp) = try await URLSession.shared.data(for: r) } catch {
            ServerLink.connectionFailed(error)     // 连不上：隔一会儿把配对链接里的几个地址重新试一遍
            throw Failure.offline(error)
        }
        guard let http = resp as? HTTPURLResponse else { throw Failure.http(0, nil) }
        // 服务器不认这个密钥了（换过密钥 / 重置过）：重新试一遍配对的地址，确认了就提示重新扫码
        if http.statusCode == 401 || http.statusCode == 403, let u = r.url, isPivisAPI(u) {
            Task { @MainActor in ServerLink.shared.reprobe() }
        }
        if checkStatus, !(200..<300).contains(http.statusCode) {
            throw Failure.http(http.statusCode, object(data)?["message"] as? String)
        }
        return (data, http)
    }

    /// 发请求并按约定解码
    static func fetch<T: Decodable>(_ type: T.Type, _ req: URLRequest) async throws -> T {
        let (data, _) = try await send(req)
        return try decode(type, data)
    }

    static func get<T: Decodable>(_ type: T.Type, _ path: String, _ query: KeyValuePairs<String, String?> = [:],
                                  timeout: TimeInterval = 20) async throws -> T {
        try await fetch(type, request(path, query, timeout: timeout))
    }

    static func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try decoder.decode(type, from: data) } catch { throw Failure.decoding(error) }
    }

    /// 回来的 JSON 对象（字段不固定的接口用）
    static func object(_ data: Data) -> [String: Any]? {
        (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    /// 发请求、拿回 JSON 对象
    static func json(_ req: URLRequest) async throws -> [String: Any] {
        let (data, _) = try await send(req)
        guard let o = object(data) else { throw Failure.decoding(URLError(.cannotParseResponse)) }
        return o
    }
}

// MARK: - 服务器上的图（海报、照片）：/api/ 的图要带密钥，所以不用 AsyncImage
@MainActor
enum ServerImageCache {
    private static let memory: NSCache<NSURL, UIImage> = { let c = NSCache<NSURL, UIImage>(); c.countLimit = 60; return c }()

    static func cached(_ url: URL) -> UIImage? { memory.object(forKey: url as NSURL) }

    static func load(_ url: URL) async -> UIImage? {
        if let hit = cached(url) { return hit }
        // 本地文件（演示里的封面）直接读盘：演示模式不发任何网络请求
        let fetched: Data? = url.isFileURL ? try? Data(contentsOf: url)
            : try? await PivisAPI.send(URLRequest(url: url, timeoutInterval: 20)).0
        guard let data = fetched, let img = UIImage(data: data) else { return nil }
        memory.setObject(img, forKey: url as NSURL)
        return img
    }
}

struct ServerImage<Placeholder: View>: View {
    let url: URL?
    var contentMode: ContentMode = .fill
    @ViewBuilder let placeholder: (_ failed: Bool) -> Placeholder
    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().aspectRatio(contentMode: contentMode)
            } else {
                placeholder(failed)
            }
        }
        .task(id: url) {
            guard let url else { image = nil; failed = true; return }
            if let hit = ServerImageCache.cached(url) { image = hit; return }
            image = nil
            failed = false
            let img = await ServerImageCache.load(url)
            image = img
            failed = img == nil
        }
    }
}
