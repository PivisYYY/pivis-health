import Foundation

// 老界面（RootShell / TodayView / PagesView，build 42 删掉）留下的共用部分。
// 颜色、字号只有 E 一套（V3Theme.swift）；旧的蓝色 Theme、PressScale、PStyle 已删掉（没人用了）。

extension Notification.Name {
    /// 点了 APNs 通知：userInfo 带 page（now/rest/sport/stress）、todo、pending（问句，只放进输入框当草稿）
    static let pivisPushTapped = Notification.Name("pivisPushTapped")
}

/// 现在开着哪个对话（"" 主对话 / 休息 / 运动 / 压力）：正看着这个对话时，P-Health 的回复通知不再弹横幅
@MainActor enum ChatPresence {
    static var openContext: String?
}
