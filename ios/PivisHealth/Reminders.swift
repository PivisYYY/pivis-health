import Foundation
import UserNotifications
import SwiftUI
#if canImport(AlarmKit)
import AlarmKit
#endif

/// 到点提醒一次 + 错过再催一次（之后不再推）；午睡这类带 alarm 的用系统闹钟（静音也会响）。
/// 模拟回放时，按“模拟时钟与真实时钟的差”换算触发时间。
final class Reminders {
    static let shared = Reminders()
    private let center = UNUserNotificationCenter.current()
    private var authorized = false

    func requestAuthorization() {
        registerCategories()
        if ProcessInfo.processInfo.arguments.contains("-uiTestDisableDeviceData") { return }   // 模拟器验收：不弹通知授权
        center.requestAuthorization(options: [.alert, .sound, .badge]) { ok, _ in self.authorized = ok }
    }

    /// 通知上的按钮。启动时就登记（App 被通知按钮在后台叫醒时也要认得这些类别）。
    /// TODO：build 43 起没有「晚 10 分钟」，点开就进 App（练习直接全屏播），要改时间在对话里说。
    /// TODO_TIME（build 53）：P-Health 拟的时间 —「好」在后台直接确认；「换个时间」打开 App、展开这张卡、弹出时间轮
    func registerCategories() {
        let ok = UNNotificationAction(identifier: "ok", title: "好", options: [],
                                      icon: UNNotificationActionIcon(systemImageName: "checkmark"))
        let change = UNNotificationAction(identifier: "change", title: "换个时间", options: [.foreground],
                                          icon: UNNotificationActionIcon(systemImageName: "clock"))
        center.setNotificationCategories([
            UNNotificationCategory(identifier: "TODO", actions: [], intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: "TODO_TIME", actions: [ok, change], intentIdentifiers: [], options: []),
        ])
    }

    /// build 46 起，待办的到点提醒都由服务器推（到点前 10 分钟、到点、练习过点没做；App 没开也收得到，
    /// P-Health 后来加的卡也不会漏）。手机上不再排本地提醒，以前排下的撤掉，免得同一件事响两遍。午睡闹钟还在手机上。
    func sync(todos: [V3Todo], nowText: String, board: String) {
        let prefix = "todo-\(board)-"
        center.getPendingNotificationRequests { reqs in
            let mine = reqs.map(\.identifier).filter { $0.hasPrefix(prefix) }
            if !mine.isEmpty { self.center.removePendingNotificationRequests(withIdentifiers: mine) }
        }
    }

    /// 这些待办（小组件上打过勾的）还没响的到点提醒 / 催一次 / 闹钟通知全撤掉
    func cancelAll(todoIds: [String]) {
        guard !todoIds.isEmpty else { return }
        center.getPendingNotificationRequests { reqs in
            let ids = reqs.map(\.identifier).filter { rid in
                todoIds.contains { rid.contains("-\($0)-") || rid == "alarm-\($0)" }
            }
            if !ids.isEmpty { self.center.removePendingNotificationRequests(withIdentifiers: ids) }
        }
    }

    /// 午睡闹钟：iOS 26 用 AlarmKit（静音也响）；低版本退回带声音的通知
    /// 从现在起 N 分钟后叫醒（午睡：从真正躺下那一刻算，不按计划时间点）
    func scheduleAlarm(todo: V3Todo, afterMinutes minutes: Double) {
        Task { await scheduleAlarm(todo: todo, due: Date().addingTimeInterval(minutes * 60)) }
    }

    /// 计时卡点「开始」：卡上写了「几点叫你」（alarm）且还没过，就定在那个时刻；否则开始 + 时长。
    /// 服务器到同一时刻也会推一条带声音的通知兜底（notify.timer_end 用的是同一条规则）
    func scheduleTimerAlarm(todo: V3Todo) {
        Task {
            var offset: TimeInterval = 0
            if let sim = await V3API.clock() { offset = Date().timeIntervalSince(sim) }
            let now = Date()
            if let a = todo.alarm, let at = Self.date(todo.date, a)?.addingTimeInterval(offset), at > now.addingTimeInterval(30) {
                await scheduleAlarm(todo: todo, due: at)
            } else {
                await scheduleAlarm(todo: todo, due: now.addingTimeInterval((todo.durationMin ?? 20) * 60))
            }
        }
    }

    func scheduleAlarm(todo: V3Todo, at hhmm: String) {
        Task {
            var offset: TimeInterval = 0
            if let sim = await V3API.clock() { offset = Date().timeIntervalSince(sim) }
            guard let due = Self.date(todo.date, hhmm)?.addingTimeInterval(offset) else { return }
            await scheduleAlarm(todo: todo, due: due)
        }
    }

    /// 计时提前结束 / 不做了：撤掉还没响的闹钟
    func cancelAlarm(todoId: String) {
        DshAPI.dbg("alarm cancel \(todoId)")
        center.removePendingNotificationRequests(withIdentifiers: ["alarm-\(todoId)"])
        #if canImport(AlarmKit)
        if #available(iOS 26.0, *), let s = UserDefaults.standard.string(forKey: "alarmkit.\(todoId)"), let id = UUID(uuidString: s) {
            try? AlarmManager.shared.cancel(id: id)
            UserDefaults.standard.removeObject(forKey: "alarmkit.\(todoId)")
        }
        #endif
    }

    private func scheduleAlarm(todo: V3Todo, due: Date) async {
        cancelAlarm(todoId: todo.id)     // 同一条只留一个闹钟（重新开始计时就按新的时间）
        #if canImport(AlarmKit)
        if #available(iOS 26.0, *) {
            if await scheduleAlarmKit(todo: todo, at: due) { DshAPI.dbg("alarm set (AlarmKit) \(todo.id) at \(due)"); return }
        }
        #endif
        DshAPI.dbg("alarm set (notification) \(todo.id) at \(due)")
        // 文案由 P-Health 定：标题就是待办的标题，副标题是它的备注（App 不自己写「醒了」）
        let c = UNMutableNotificationContent()
        c.title = todo.title
        c.body = todo.note
        c.sound = UNNotificationSound.defaultCritical
        c.interruptionLevel = .timeSensitive
        let comps = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute, .second], from: due)
        try? await center.add(UNNotificationRequest(identifier: "alarm-\(todo.id)", content: c,
                                                   trigger: UNCalendarNotificationTrigger(dateMatching: comps, repeats: false)))
    }

    #if canImport(AlarmKit)
    @available(iOS 26.0, *)
    private func scheduleAlarmKit(todo: V3Todo, at date: Date) async -> Bool {
        do {
            let state = try await AlarmManager.shared.requestAuthorization()
            guard state == .authorized else { return false }
            let stop = LocalizedStringResource(stringLiteral: todo.submitLabel ?? "好了")
            let alert = AlarmPresentation.Alert(title: LocalizedStringResource(stringLiteral: todo.title),
                                                stopButton: AlarmButton(text: stop, textColor: .white, systemImageName: "checkmark"))
            let attrs = AlarmAttributes<PHAlarmMeta>(presentation: AlarmPresentation(alert: alert), tintColor: .white)
            let config = AlarmManager.AlarmConfiguration<PHAlarmMeta>(schedule: .fixed(date), attributes: attrs)
            let id = UUID()
            _ = try await AlarmManager.shared.schedule(id: id, configuration: config)
            UserDefaults.standard.set(id.uuidString, forKey: "alarmkit.\(todo.id)")
            return true
        } catch {
            DshAPI.dbg("alarmkit failed: \(error)")
            return false
        }
    }
    #endif

    /// 服务器的「现在」（2026-11-07T21:45+08:00 或不带时区）
    static func parse(_ s: String) -> Date? { PTime.parse(s) }

    static func date(_ day: String, _ hm: String) -> Date? {
        guard var d = PTime.date(day: day, hm: hm) else { return nil }
        // 00:xx–05:xx 的事属于当晚，落在第二天
        if let h = Int(hm.prefix(2)), h < 6 { d = d.addingTimeInterval(24 * 3600) }
        return d
    }
}

#if canImport(AlarmKit)
@available(iOS 26.0, *)
struct PHAlarmMeta: AlarmMetadata {}
#endif
