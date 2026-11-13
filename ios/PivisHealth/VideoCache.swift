import CryptoKit
import Foundation
import Network

// MARK: - 视频存到手机上（Psir 11-08：局域网地址的视频在外面打不开，要能下到本地，同一个视频下次直接播）
// 服务器上的片（/media/...）第一次播就在后台下到 Caches/videos，下次直接播本地文件；
// 页面加载时，今天要练的、坚持习惯里的视频在 Wi-Fi 下先下好，出门在外也能放。
// 地址带 ?v= 版本号：出片改过（删动作、重剪）就是新地址，自动重新下。最多占 3 GB，超了先删最久没看的。
final class VideoCache: @unchecked Sendable {
    static let shared = VideoCache()

    private let dir: URL
    private let lock = NSLock()
    private var inflight: Set<String> = []
    private let maxBytes: Int64 = 3 * 1024 * 1024 * 1024
    private let monitor = NWPathMonitor()
    private var cheapNetwork = true

    private init() {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        dir = base.appendingPathComponent("videos", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        monitor.pathUpdateHandler = { [weak self] path in
            self?.lock.withLock { self?.cheapNetwork = !path.isExpensive && !path.isConstrained }
        }
        monitor.start(queue: DispatchQueue(label: "phealth.video-cache.net"))
    }

    /// 只缓存自己服务器上的片（B 站、外链不管）
    static func cacheable(_ url: URL) -> Bool {
        guard let base = PivisAPI.resolve("/media/"), url.host == base.host else { return false }
        return url.path.hasPrefix("/media/") && ["mp4", "m4v", "mov"].contains(url.pathExtension.lowercased())
    }

    private func file(for remote: URL) -> URL {
        let key = remote.path + "?" + (remote.query ?? "")
        let hash = SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined().prefix(32)
        return dir.appendingPathComponent(String(hash)).appendingPathExtension(remote.pathExtension.isEmpty ? "mp4" : remote.pathExtension)
    }

    /// 已经下好的本地文件（顺手记一下最近看过，清理时留着）
    func localURL(for remote: URL) -> URL? {
        guard Self.cacheable(remote) else { return nil }
        let f = file(for: remote)
        guard FileManager.default.fileExists(atPath: f.path) else { return nil }
        try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: f.path)
        return f
    }

    /// 播放用的地址：下好了用本地的，没下好先在线播、后台开始下（下次就是本地的）
    func playableURL(for remote: URL) -> URL {
        if let local = localURL(for: remote) { return local }
        prefetch(remote, force: true)
        return remote
    }

    /// 后台下一个。force=false 时只在 Wi-Fi（不计流量）下载
    func prefetch(_ remote: URL, force: Bool = false) {
        guard Self.cacheable(remote) else { return }
        let target = file(for: remote)
        let go: Bool = lock.withLock {
            guard (force || cheapNetwork), !inflight.contains(target.path),
                  !FileManager.default.fileExists(atPath: target.path) else { return false }
            inflight.insert(target.path)
            return true
        }
        guard go else { return }
        Task.detached(priority: .utility) { [self] in
            defer { _ = lock.withLock { inflight.remove(target.path) } }
            var req = URLRequest(url: remote, timeoutInterval: 600)
            PivisAPI.authorize(&req)
            guard let (tmp, resp) = try? await URLSession.shared.download(for: req),
                  (resp as? HTTPURLResponse)?.statusCode == 200 else { return }
            try? FileManager.default.removeItem(at: target)
            try? FileManager.default.moveItem(at: tmp, to: target)
            trim()
        }
    }

    /// 超过上限：先删最久没看的
    private func trim() {
        let keys: [URLResourceKey] = [.fileSizeKey, .contentModificationDateKey]
        guard let files = try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: keys) else { return }
        var items = files.compactMap { f -> (URL, Int64, Date)? in
            guard let v = try? f.resourceValues(forKeys: Set(keys)) else { return nil }
            return (f, Int64(v.fileSize ?? 0), v.contentModificationDate ?? .distantPast)
        }
        var total = items.reduce(0) { $0 + $1.1 }
        guard total > maxBytes else { return }
        items.sort { $0.2 < $1.2 }
        for (f, size, _) in items where total > maxBytes {
            try? FileManager.default.removeItem(at: f)
            total -= size
        }
    }
}
