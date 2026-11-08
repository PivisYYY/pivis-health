import WidgetKit
import SwiftUI
import AppIntents

// MARK: - 时间线：到每件待办的点自动换下一件；离上床 6 小时内每 5 分钟换一次倒计时；其余约 30 分钟向服务器拿一次
struct PHEntry: TimelineEntry {
    let date: Date
    let doc: WDoc?
}

struct PHProvider: TimelineProvider {
    func placeholder(in context: Context) -> PHEntry { PHEntry(date: Date(), doc: .placeholder) }

    func getSnapshot(in context: Context, completion: @escaping (PHEntry) -> Void) {
        if context.isPreview { completion(PHEntry(date: Date(), doc: WStore.cached() ?? .placeholder)); return }
        Task { completion(PHEntry(date: Date(), doc: await WStore.load() ?? .placeholder)) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<PHEntry>) -> Void) {
        Task {
            let doc = await WStore.load()
            let now = Date()
            var dates: Set<Date> = [now]
            for t in doc?.todos ?? [] {
                // 过点 15 分钟后从「接下来」里换掉
                if let d = t.atDate?.addingTimeInterval(15 * 60 + 1), d > now, d < now.addingTimeInterval(12 * 3600) { dates.insert(d) }
            }
            if let bed = doc?.bed?.atDate, bed > now {
                var d = now
                while d < min(bed, now.addingTimeInterval(6 * 3600)) {
                    d = d.addingTimeInterval(300)
                    dates.insert(d)
                }
            }
            let entries = dates.sorted().prefix(120).map { PHEntry(date: $0, doc: doc) }
            completion(Timeline(entries: Array(entries), policy: .after(now.addingTimeInterval(30 * 60))))
        }
    }
}

// MARK: - 小组件
struct NowWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PHNow", provider: PHProvider()) { e in NowView(entry: e) }
            .configurationDisplayName("此刻")
            .description("P-Health 判断现在最值得注意的那一件")
            .supportedFamilies([.systemSmall])
    }
}

struct NextWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PHNext", provider: PHProvider()) { e in NextView(entry: e) }
            .configurationDisplayName("接下来")
            .description("今天接下来的 3 件事，打勾类直接点 ✓")
            .supportedFamilies([.systemMedium])
    }
}

struct SleepWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PHSleep", provider: PHProvider()) { e in SleepView(entry: e) }
            .configurationDisplayName("近 7 晚")
            .description("睡了多久、那晚需要多少")
            .supportedFamilies([.systemMedium])
    }
}

struct NextLockWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PHNextLock", provider: PHProvider()) { e in NextLockView(entry: e) }
            .configurationDisplayName("下一件事")
            .description("锁屏上看下一件要做的事")
            .supportedFamilies([.accessoryRectangular, .accessoryInline])
    }
}

struct BedWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PHBed", provider: PHProvider()) { e in BedView(entry: e) }
            .configurationDisplayName("到上床")
            .description("离上床时间窗还有多久")
            .supportedFamilies([.accessoryCircular])
    }
}

@main
struct PivisWidgets: WidgetBundle {
    var body: some Widget {
        NowWidget()
        NextWidget()
        SleepWidget()
        NextLockWidget()
        BedWidget()
    }
}
