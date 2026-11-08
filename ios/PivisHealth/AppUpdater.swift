import SwiftUI
import UIKit

// MARK: - 应用内更新
// 打开 App / 回到前台时看一眼安装页上的 build 号，比自己新就弹一个系统提示「现在更新」：
// 点了直接走 iOS 无线安装（系统会再确认一次「安装」），装完自动替换，不用再去开安装链接。
@MainActor @Observable
final class AppUpdater {
    static let shared = AppUpdater()

    /// 有比自己新的版本时是那个 build 号（弹提示用）
    var available: Int?
    private var checking = false
    private let snoozeKey = "update_snooze"     // [build: 到什么时候之前不再问]

    var current: Int { Int(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "") ?? 0 }

    /// 从 TestFlight（或 App Store）装的：包里没有开发描述文件。这时更新归 TestFlight 管，自己不再弹安装页
    static var fromTestFlight: Bool { Bundle.main.path(forResource: "embedded", ofType: "mobileprovision") == nil }

    func check() {
        #if targetEnvironment(simulator)
        return       // 模拟器装不了真机安装包
        #else
        guard !checking, !LocalConfig.installHost.isEmpty, !Self.fromTestFlight else { return }
        checking = true
        Task { @MainActor in
            defer { checking = false }
            guard let obj = try? await PivisAPI.json(PivisAPI.request("api/v3/app-version", timeout: 8)),
                  let build = obj["build"] as? Int, build > current else { return }
            let snoozed = (UserDefaults.standard.dictionary(forKey: snoozeKey) as? [String: Double])?[String(build)] ?? 0
            guard Date().timeIntervalSince1970 > snoozed else { return }
            available = build
        }
        #endif
    }

    /// 「稍后」：这个版本 6 小时内不再问
    func snooze() {
        guard let b = available else { return }
        var d = (UserDefaults.standard.dictionary(forKey: snoozeKey) as? [String: Double]) ?? [:]
        d[String(b)] = Date().addingTimeInterval(6 * 3600).timeIntervalSince1970
        UserDefaults.standard.set(d, forKey: snoozeKey)
        available = nil
    }

    func install() {
        available = nil
        let manifest = "https://\(LocalConfig.installHost)/install/manifest.plist"
        guard let enc = manifest.addingPercentEncoding(withAllowedCharacters: .alphanumerics),
              let url = URL(string: "itms-services://?action=download-manifest&url=\(enc)") else { return }
        UIApplication.shared.open(url)
    }
}
