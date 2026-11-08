import Foundation
import WidgetKit

// MARK: - App 和小组件共用的存储（App Group）
enum SharedStore {
    static let group = "group.com.pivis.health"
    static var defaults: UserDefaults { UserDefaults(suiteName: group) ?? .standard }
    static var container: URL? { FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group) }
}

// MARK: - 小组件数据：页面 / 待办变了就拿一份最新的存进 App Group，通知小组件重画
@MainActor
enum WidgetBridge {
    private static var pending: Task<Void, Never>?

    /// 小组件自己去服务器拿数据、提交打勾时用的地址和设备密钥（模拟回放连 8944，正式连 8943）
    static func shareConfig() {
        let d = SharedStore.defaults
        d.set(DshAPI.pivisBase.absoluteString, forKey: "pivis_base")
        if d.string(forKey: "pivis_app_key") != LocalConfig.appKey { d.set(LocalConfig.appKey, forKey: "pivis_app_key") }
    }

    /// 合并成一次（短时间里连着变好几次只拿一次）
    static func refresh(after delay: Double = 1.5) {
        shareConfig()
        pending?.cancel()
        pending = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled,
                  let (data, _) = try? await PivisAPI.send(PivisAPI.request("api/v3/widget", timeout: 10)),
                  let dir = SharedStore.container else { return }
            try? data.write(to: dir.appendingPathComponent("widget.json"), options: .atomic)
            WidgetCenter.shared.reloadAllTimelines()
        }
    }

    /// 小组件上打过勾的待办：App 回到前台时把它们还没响的本地提醒撤掉
    /// （小组件里也会撤一次；扩展进程碰不到 App 的通知中心时，靠这里兜底）
    static func clearWidgetDoneReminders() {
        let d = SharedStore.defaults
        guard let ids = d.stringArray(forKey: "widget_done_ids"), !ids.isEmpty else { return }
        d.removeObject(forKey: "widget_done_ids")
        Reminders.shared.cancelAll(todoIds: ids)
    }
}

extension Notification.Name {
    /// 从小组件点进来：展开那张待办卡
    static let pivisExpandTodo = Notification.Name("pivisExpandTodo")
}
