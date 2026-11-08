import SwiftUI
import UIKit
import Security

@main
struct PivisHealthApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate

    init() {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-renderAppIcon") {
            let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("appicon")
            MainActor.assumeIsolated { AppIconRenderer.renderAll(to: dir) }
            exit(0)
        }
        #endif
        // 注意：不要用 UIView.appearance() 全局代理，会破坏 SwiftUI 颜色方案传播和渲染
        let navAppearance = UINavigationBarAppearance()
        navAppearance.configureWithOpaqueBackground()
        navAppearance.backgroundColor = .black
        navAppearance.titleTextAttributes = [.foregroundColor: UIColor(E.text)]
        navAppearance.largeTitleTextAttributes = [.foregroundColor: UIColor(E.text)]
        UINavigationBar.appearance().standardAppearance = navAppearance
        UINavigationBar.appearance().scrollEdgeAppearance = navAppearance
        UINavigationBar.appearance().compactAppearance = navAppearance
    }

    var body: some Scene {
        WindowGroup {
            V3Root()
                .preferredColorScheme(.dark)
                .tint(.white)
        }
    }
}

// MARK: - AppDelegate
class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        purgeLegacyDebugData()
        WidgetBridge.shareConfig()
        if Profile.uploadsDeviceData {
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
            application.registerForRemoteNotifications()
            DeviceDataReporter.shared.bootstrap()
        }
        return true
    }

    func application(_ application: UIApplication,
                     didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        UserDefaults.standard.set(token, forKey: "apns_token")
        uploadAPNSToken(token)
    }

    /// 上报 APNs token 到 pivis-health 后端（供主动触达）
    private func uploadAPNSToken(_ token: String) {
        // 推送环境跟着签名走：开发签名（安装页装的）是 development，TestFlight / App Store 是 production
        #if DEBUG
        let env = "development"
        #else
        let env = AppUpdater.fromTestFlight ? "production" : "development"
        #endif
        let req = PivisAPI.request("api/v2/apns-token", method: "POST", json: ["token": token, "env": env])
        Task {
            do { try await PivisAPI.send(req) } catch { DshAPI.dbg("apns token upload failed: \(error.localizedDescription)") }
        }
    }

    /// 老版本留下的调试痕迹：UserDefaults 里存过完整回复，Release 包还一直往 Documents 里写日志（含 Cookie 片段）
    private func purgeLegacyDebugData() {
        UserDefaults.standard.removeObject(forKey: "dsh_debug")
        UserDefaults.standard.removeObject(forKey: "dsh_token")
        #if !DEBUG
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        try? FileManager.default.removeItem(at: docs.appendingPathComponent("dsh_debug.log"))
        #endif
    }

    /// 点通知：userInfo 带 page（now/rest/sport/stress）与 pending（问句）→ 交给 RootShell 切页并开对话
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse) async {
        var info = response.notification.request.content.userInfo
        if let todoId = info["todo"] as? String {
            switch response.actionIdentifier {
            case "TODO_LATER":
                // 进发送队列：断网也先记在手机上，连上自动补发
                await MainActor.run { TodoOutbox.shared.enqueue(todoId, action: "later", values: ["minutes": 10]) }
                return
            case "TODO_START", UNNotificationDefaultActionIdentifier:
                if (info["kind"] as? String) == "follow" { info["action"] = "start" }
            default: break
            }
        }
        let payload = info
        await MainActor.run {
            NotificationCenter.default.post(name: .pivisPushTapped, object: nil, userInfo: payload)
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        // P-Health 的回复：正开着那个对话就不弹了（消息已经在眼前）
        let info = notification.request.content.userInfo
        if info["why"] as? String == "reply", let ctx = info["context"] as? String {
            let open = await MainActor.run { ChatPresence.openContext }
            if open == ctx { return [] }
        }
        return [.banner, .sound, .list]
    }
}

// MARK: - 根布局：系统 TabView（四个板块）+ 独立 P-Health 入口 + 对话抽屉
struct ChatTarget: Identifiable {
    let id = UUID()
    let context: String
    let pendingText: String?   // 打开抽屉后自动发送的消息（只用于老大自己点出来的动作；推送里带的问句一律走 draft）
    var draft: String? = nil   // 打开抽屉后放进输入框、等老大补完再发（推送里的 pending、「记录不对：…实际是」）
    var photo: PendingPhoto? = nil   // 打开抽屉后直接发这张照片（待办卡上拍的）
    var about: ChatAbout? = nil      // 带着一个习惯 / 一张待办进来：顶部是那张卡，输入框上方「关于：X」
}

// MARK: - 设备数据授权与上报（健康 / 位置 / 蓝牙 → 后端 /api/v2/device-data）
// 样本格式与后端 vault samples 表约定一致（类型名、单位、category 取值）
import HealthKit
import CoreLocation
import CoreBluetooth

/// 全在主线程上：HealthKit 回调、定位 / 蓝牙委托都切回主线程再动 pendingObservations（以前几处同时改，没加锁）
@MainActor
final class DeviceDataReporter: NSObject {
    static let shared = DeviceDataReporter()

    private let health = HKHealthStore()
    private var locationManager: CLLocationManager?
    private var central: CBCentralManager?
    private var btDevices: [[String: Any]] = []
    private var pendingObservations: [[String: Any]] = []
    private var hasBootstrapped = false


    /// 下拉刷新时调：马上把近 7 天的 Apple 健康数据再传一次。返回是否传成功（没授权、测试模式算没传）
    @discardableResult
    func syncNow() async -> Bool {
        guard hasBootstrapped, HKHealthStore.isHealthDataAvailable() else { return false }
        return await collectHealthAndUpload()
    }

    /// 启动时调用一次：申请三类授权 → 采集近 7 天健康聚合 + 单次定位 + 5 秒蓝牙扫描 → 上报
    func bootstrap() {
        guard !hasBootstrapped else { return }
        hasBootstrapped = true
        requestHealthAuthorization()
        requestLocation()
        startBluetoothScan()
    }

    /// 设备 id 放钥匙串：重装 App 还是同一个 id（之前放 UserDefaults，每装一次换一个，服务器把同一份步数算了好几遍）
    private var deviceId: String {
        if let id = Keychain.get("pivis_device_id") {
            UserDefaults.standard.set(id, forKey: "pivis_device_id")
            return id
        }
        let id = UserDefaults.standard.string(forKey: "pivis_device_id") ?? ("iphone-" + UUID().uuidString)
        Keychain.set("pivis_device_id", id)
        UserDefaults.standard.set(id, forKey: "pivis_device_id")
        return id
    }

    // MARK: 健康
    private func requestHealthAuthorization() {
        let specs: [HKQuantityTypeIdentifier] = [
            .heartRateVariabilitySDNN, .restingHeartRate, .heartRate,
            .respiratoryRate, .oxygenSaturation, .stepCount,
            .activeEnergyBurned, .bodyMass,
        ]
        var read: Set<HKObjectType> = [HKObjectType.categoryType(forIdentifier: .sleepAnalysis)!,
                                       HKObjectType.workoutType()]
        for s in specs {
            if let t = HKObjectType.quantityType(forIdentifier: s) { read.insert(t) }
        }
        health.requestAuthorization(toShare: [], read: read) { _, _ in
            Task { @MainActor in await DeviceDataReporter.shared.collectHealthAndUpload() }
        }
    }

    @discardableResult
    private func collectHealthAndUpload() async -> Bool {
        let cal = PTime.calendar
        let now = Date()
        guard let start = cal.date(byAdding: .day, value: -7, to: cal.startOfDay(for: now)) else { return false }
        var samples: [[String: Any]] = []

        if let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
            for (cat, s, e, id) in await querySleepSegments(type: sleepType, start: start, end: now) {
                samples.append([
                    "sample_id": "hkslp-\(id.uuidString)",
                    "type": "sleep_analysis",
                    "start_at": PTime.iso(s), "end_at": PTime.iso(e),
                    "unit": "category", "category_value": cat,
                ])
            }
        }

        let daily: [(String, HKQuantityTypeIdentifier, HKUnit, HKStatisticsOptions)] = [
            ("heart_rate", .heartRate, HKUnit.count().unitDivided(by: .minute()), .discreteAverage),
            ("heart_rate_variability_sdnn", .heartRateVariabilitySDNN, HKUnit(from: "ms"), .discreteAverage),
            ("resting_heart_rate", .restingHeartRate, HKUnit.count().unitDivided(by: .minute()), .discreteAverage),
            ("respiratory_rate", .respiratoryRate, HKUnit.count().unitDivided(by: .minute()), .discreteAverage),
            ("oxygen_saturation", .oxygenSaturation, .percent(), .discreteAverage),
            ("step_count", .stepCount, .count(), .cumulativeSum),
            ("active_energy_burned", .activeEnergyBurned, .kilocalorie(), .cumulativeSum),
            ("body_mass", .bodyMass, .gramUnit(with: .kilo), .discreteAverage),
        ]
        for (typeName, ident, unit, options) in daily {
            guard let qt = HKObjectType.quantityType(forIdentifier: ident) else { continue }
            for (dayStart, value) in await queryDailyStats(type: qt, start: start, options: options, unit: unit) {
                guard let dayEnd = cal.date(byAdding: .day, value: 1, to: dayStart) else { continue }
                samples.append([
                    "sample_id": "hkagg-\(typeName)-\(PTime.compactDay(dayStart))",
                    "type": typeName,
                    "start_at": PTime.iso(dayStart), "end_at": PTime.iso(dayEnd),
                    "unit": unitString(typeName), "numeric_value": value,
                ])
            }
        }
        let obs = pendingObservations
        pendingObservations.removeAll()
        return await upload(samples: samples, observations: obs)
    }

    private func unitString(_ type: String) -> String {
        ["heart_rate": "count/min", "heart_rate_variability_sdnn": "ms",
         "resting_heart_rate": "count/min", "respiratory_rate": "count/min",
         "oxygen_saturation": "%", "step_count": "count",
         "active_energy_burned": "kcal", "body_mass": "kg"][type] ?? ""
    }

    private func querySleepSegments(type: HKCategoryType, start: Date, end: Date) async -> [(String, Date, Date, UUID)] {
        let health = self.health
        return await withCheckedContinuation { cont in
            let q = HKSampleQuery(sampleType: type,
                                  predicate: HKQuery.predicateForSamples(withStart: start, end: end),
                                  limit: HKObjectQueryNoLimit, sortDescriptors: nil) { _, results, _ in
                var out: [(String, Date, Date, UUID)] = []
                for s in (results as? [HKCategorySample]) ?? [] {
                    let cat: String
                    switch s.value {
                    case HKCategoryValueSleepAnalysis.asleepCore.rawValue: cat = "asleep_core"
                    case HKCategoryValueSleepAnalysis.asleepDeep.rawValue: cat = "asleep_deep"
                    case HKCategoryValueSleepAnalysis.asleepREM.rawValue: cat = "asleep_rem"
                    case HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue: cat = "asleep_unspecified"
                    case HKCategoryValueSleepAnalysis.awake.rawValue: cat = "awake"
                    case HKCategoryValueSleepAnalysis.inBed.rawValue: cat = "in_bed"
                    default: continue
                    }
                    out.append((cat, s.startDate, s.endDate, s.uuid))
                }
                cont.resume(returning: out)
            }
            health.execute(q)
        }
    }

    private func queryDailyStats(type: HKQuantityType, start: Date,
                                 options: HKStatisticsOptions, unit: HKUnit) async -> [(Date, Double)] {
        let health = self.health
        return await withCheckedContinuation { cont in
            let anchor = PTime.calendar.startOfDay(for: start)
            let q = HKStatisticsCollectionQuery(quantityType: type, quantitySamplePredicate: nil,
                                                anchorDate: anchor,
                                                intervalComponents: DateComponents(day: 1))
            q.initialResultsHandler = { _, results, _ in
                var out: [(Date, Double)] = []
                results?.enumerateStatistics(from: anchor, to: Date()) { stat, _ in
                    if let v = stat.sumQuantity() ?? stat.averageQuantity() {
                        out.append((stat.startDate, v.doubleValue(for: unit)))
                    }
                }
                cont.resume(returning: out)
            }
            health.execute(q)
        }
    }

    // MARK: 位置
    private func requestLocation() {
        let m = CLLocationManager()
        m.delegate = self
        m.desiredAccuracy = kCLLocationAccuracyHundredMeters
        locationManager = m
        locationManagerDidChangeAuthorization(m)
    }

    // MARK: 蓝牙
    private func startBluetoothScan() {
        central = CBCentralManager(delegate: self, queue: nil)
    }

    private func finishBluetoothScan() {
        central?.stopScan()
        appendObservation(kind: "bluetooth_scan", data: ["devices": btDevices])
        Task { await upload(samples: [], observations: drainObservations()) }
    }

    private func appendObservation(kind: String, data: [String: Any]) {
        pendingObservations.append(["kind": kind, "data": data])
    }

    private func drainObservations() -> [[String: Any]] {
        let obs = pendingObservations
        pendingObservations.removeAll()
        return obs
    }

    // MARK: 上报
    @discardableResult
    private func upload(samples: [[String: Any]], observations: [[String: Any]]) async -> Bool {
        let body: [String: Any] = ["device_id": deviceId, "samples": samples, "observations": observations]
        let req = PivisAPI.request("api/v2/device-data", method: "POST", json: body, timeout: 30)
        do {
            let (_, resp) = try await PivisAPI.send(req)
            DshAPI.dbg("device-data uploaded status=\(resp.statusCode) samples=\(samples.count) observations=\(observations.count)")
            return true
        } catch {
            DshAPI.dbg("device-data 上报失败: \(error.localizedDescription)")
            return false
        }
    }
}

// 定位、蓝牙管理器都在主线程上建（蓝牙 queue: nil = 主队列），委托回调也在主线程：直接切回主 actor
extension DeviceDataReporter: CLLocationManagerDelegate {
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        let data: [String: Any] = [
            "lat": loc.coordinate.latitude,
            "lon": loc.coordinate.longitude,
            "accuracy_m": loc.horizontalAccuracy,
            "ts": PTime.iso(loc.timestamp),
        ]
        MainActor.assumeIsolated {
            appendObservation(kind: "location", data: data)
            Task { await self.upload(samples: [], observations: self.drainObservations()) }
        }
    }
    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        DshAPI.dbg("定位失败: \(error.localizedDescription)")
    }
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        MainActor.assumeIsolated { handleAuthorization(manager) }
    }

    fileprivate func handleAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedWhenInUse, .authorizedAlways:
            manager.requestLocation()
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        case .denied, .restricted:
            // 权限撤销后显式停止定位链路并记录状态：不再产生新位置数据。
            locationManager = nil
            appendObservation(kind: "location_permission", data: [
                "status": "revoked",
                "ts": PTime.iso(Date()),
            ])
            Task { await self.upload(samples: [], observations: self.drainObservations()) }
        @unknown default:
            break
        }
    }
}

extension DeviceDataReporter: CBCentralManagerDelegate {
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        MainActor.assumeIsolated {
            if central.state == .poweredOn {
                btDevices = []
                central.scanForPeripherals(withServices: nil,
                                           options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
                Task { @MainActor [weak self] in
                    try? await Task.sleep(nanoseconds: 5_000_000_000)
                    self?.finishBluetoothScan()
                }
            } else {
                // 蓝牙不可用（模拟器/未开启）也记录状态，便于排查与后续产品功能感知环境
                DshAPI.dbg("蓝牙状态非 poweredOn: \(central.state.rawValue)")
                appendObservation(kind: "bluetooth_state", data: ["state": central.state.rawValue])
                Task { await upload(samples: [], observations: drainObservations()) }
            }
        }
    }
    nonisolated func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                                    advertisementData: [String: Any], rssi RSSI: NSNumber) {
        let device: [String: Any] = [
            "name": peripheral.name ?? "",
            "uuid": peripheral.identifier.uuidString,
            "rssi": RSSI.intValue,
        ]
        MainActor.assumeIsolated { btDevices.append(device) }
    }
}


/// 极简钥匙串读写（只存设备 id 这类不敏感但要跨重装保留的值）
enum Keychain {
    private static let service = "com.pivis.health"

    static func get(_ key: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: key, kSecReturnData as String: true,
                                kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func set(_ key: String, _ value: String) {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                   kSecAttrAccount as String: key]
        SecItemDelete(base as CFDictionary)
        var add = base
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(add as CFDictionary, nil)
    }
}
