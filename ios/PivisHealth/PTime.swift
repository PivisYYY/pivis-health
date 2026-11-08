import Foundation
import os

// MARK: - 时间：一律按北京时间（服务器、待办、提醒都按它），格式器只建一次
// 模拟回放时服务器的「现在」可以是假的：页面顶上的钟按最近一次拿到的服务器时间和手机时间的差走。
enum PTime {
    static let zone = TimeZone(identifier: "Asia/Shanghai") ?? .current

    static let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = zone
        return c
    }()

    private static func formatter(_ pattern: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = zone
        f.dateFormat = pattern
        return f
    }

    private static func iso(_ options: ISO8601DateFormatter.Options) -> ISO8601DateFormatter {
        let f = ISO8601DateFormatter()
        f.formatOptions = options
        f.timeZone = zone
        return f
    }

    // DateFormatter / ISO8601DateFormatter 建好后只读，多线程用是安全的
    private static let hm = formatter("HH:mm")
    private static let dayClock = formatter("M/d · HH:mm")
    private static let dayMinute = formatter("yyyy-MM-dd HH:mm")
    private static let localMinute = formatter("yyyy-MM-dd'T'HH:mm")
    private static let zonedMinute = formatter("yyyy-MM-dd'T'HH:mmXXXXX")
    private static let compact = formatter("yyyyMMdd")
    private static let isoSeconds = iso([.withInternetDateTime])
    private static let isoFraction = iso([.withInternetDateTime, .withFractionalSeconds])

    /// 21:45
    static func hhmm(_ d: Date) -> String { hm.string(from: d) }
    /// 11/7 · 21:45（页面顶上的钟）
    static func dayAndClock(_ d: Date) -> String { dayClock.string(from: d) }
    /// 20261107（健康样本按天的 id）
    static func compactDay(_ d: Date) -> String { compact.string(from: d) }
    /// 2026-11-07T21:45:12+08:00（发给服务器的时间）
    static func iso(_ d: Date) -> String { isoSeconds.string(from: d) }
    static func isoFractional(_ d: Date) -> String { isoFraction.string(from: d) }

    /// 服务器的各种时间写法：完整 ISO（带不带毫秒）、只到分钟（带不带时区）
    static func parse(_ s: String) -> Date? {
        isoSeconds.date(from: s) ?? isoFraction.date(from: s) ?? zonedMinute.date(from: s) ?? localMinute.date(from: s)
    }

    /// 「2026-11-07」+「21:45」→ 那一刻（北京时间）
    static func date(day: String, hm: String) -> Date? { dayMinute.date(from: "\(day) \(hm)") }

    // MARK: 服务器时钟
    private static let lock = OSAllocatedUnfairLock(initialState: TimeInterval(0))

    /// 服务器时钟 − 手机时钟（秒）。正式环境两边一样（服务器只给到分钟，差一分钟以内当成 0）
    static var serverOffset: TimeInterval { lock.withLock { $0 } }

    /// 拿到页面时记一下服务器的「现在」（只到分钟：取这一分钟的中间）
    static func noteServerNow(_ text: String, receivedAt: Date = Date()) {
        guard let d = parse(text) else { return }
        let raw = d.timeIntervalSince(receivedAt)
        let off = abs(raw) < 90 ? 0 : raw + 30
        lock.withLock { $0 = off }
    }

    static var serverNow: Date { Date().addingTimeInterval(serverOffset) }
}

// MARK: - 日志：os.Logger（值一律 private）；DEBUG 版另写一份文件，在后台写、有上限、不写令牌
enum Log {
    private static let logger = Logger(subsystem: "com.pivis.health", category: "app")

    static func debug(_ s: String) {
        let clean = scrub(s)
        logger.debug("\(clean, privacy: .private)")
        #if DEBUG
        DebugFile.append(clean)
        #endif
    }

    /// 兜底：地址里的 token=…、Cookie 值不进日志（错误描述里会带完整地址）
    private static let secret = try? NSRegularExpression(pattern: #"(token=|[Cc]ookie[=:]\s*)[^&\s"]+"#)
    static func scrub(_ s: String) -> String {
        guard let re = secret else { return s }
        return re.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "$1…")
    }
}

#if DEBUG
/// Documents/dsh_debug.log：串行队列里追加，超过 512 KB 换成 .1 再从头写
private enum DebugFile {
    private static let queue = DispatchQueue(label: "com.pivis.health.debuglog", qos: .utility)
    private static let cap: UInt64 = 512 * 1024
    private static let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("dsh_debug.log")

    static func append(_ s: String) {
        let line = "\(PTime.isoFractional(Date())) \(s)\n"
        queue.async {
            let fm = FileManager.default
            if let size = (try? fm.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.uint64Value, size > cap {
                let old = url.appendingPathExtension("1")
                try? fm.removeItem(at: old)
                try? fm.moveItem(at: url, to: old)
            }
            guard let data = line.data(using: .utf8) else { return }
            if let h = try? FileHandle(forWritingTo: url) {
                _ = try? h.seekToEnd()
                try? h.write(contentsOf: data)
                try? h.close()
            } else {
                try? data.write(to: url, options: .atomic)
            }
        }
    }
}
#endif
