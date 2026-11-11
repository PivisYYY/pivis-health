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
            // 没配对：引导页；配对过 / 演示：主界面（换服务器时整个重建）
            AppGate()
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
        Reminders.shared.registerCategories()     // 通知按钮在后台把 App 叫醒时，类别要已经登记好
        purgeLegacyDebugData()
        WidgetBridge.shareConfig()
        Self.startDeviceServices()
        return true
    }

    /// 通知授权、推送 token、健康 / 位置 / 蓝牙：连上一台电脑以后才开始（引导页、演示里不弹一串授权）。
    /// 刚配对好也调一次：把推送 token 报给新电脑（registerForRemoteNotifications 每次都会回调 didRegister → 上报），
    /// 健康数据马上传一次
    @MainActor
    static func startDeviceServices(afterPairing: Bool = false) {
        guard Profile.uploadsDeviceData, ServerConfig.hasServer, !ServerConfig.isDemo else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
        UIApplication.shared.registerForRemoteNotifications()
        DeviceDataReporter.shared.bootstrap()
        if afterPairing { Task { await DeviceDataReporter.shared.syncNow() } }
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
        // 点了哪条推送都告诉服务器（每条推送都带 push_id）：点开 = open，点通知上的按钮 = 按钮的标识；断网先排队
        if let pushId = info["push_id"] as? String, !pushId.isEmpty {
            let action = response.actionIdentifier == UNNotificationDefaultActionIdentifier ? "open" : response.actionIdentifier
            let at = Date()
            await MainActor.run { PushTaps.report(pushId: pushId, action: action, at: at) }
        }
        if let todoId = info["todo"] as? String {
            let draftTime = response.notification.request.content.categoryIdentifier == "TODO_TIME"
                || (info["why"] as? String) == "draft"
            switch response.actionIdentifier {
            case "TODO_LATER":
                // 进发送队列：断网也先记在手机上，连上自动补发
                await MainActor.run { TodoOutbox.shared.enqueue(todoId, action: "later", values: ["minutes": 10]) }
                return
            case "ok" where draftTime:
                // 拟的时间点「好」：App 不打开，在后台确认；等这一轮真的发完再告诉系统（断网就留在队列里，下次打开补发）
                await MainActor.run { TodoOutbox.shared.enqueue(todoId, action: "confirm_time", values: [:]) }
                await TodoOutbox.shared.flushAndWait()
                let left = await MainActor.run { TodoOutbox.shared.pending.filter { $0.todoId == todoId }.count }
                DshAPI.dbg("通知「好」→ confirm_time \(todoId)：\(left == 0 ? "已送到（或被拒）" : "还在队列里，等网络")")
                return
            case "change" where draftTime:
                info["timeSheet"] = true       // 打开 App → 展开这张卡 → 弹出时间轮
            case "TODO_START", UNNotificationDefaultActionIdentifier:
                if draftTime { info["timeSheet"] = true }      // 点「行吗？」这条通知本身：也是问时间，直接给时间轮
                else if (info["kind"] as? String) == "follow" { info["action"] = "start" }
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
        let info = notification.request.content.userInfo
        if info["why"] as? String == "insight" {
            // 洞察：主对话正开着 → 不弹横幅，输入框上方的浮条马上出来；不在主对话 → 照常弹（点开直接聊）。
            // 两种情况都先按推送把圆钮的点亮上，再马上同步一次状态
            let id = info["insight"] as? String ?? ""
            let body = notification.request.content.body
            let hosted = await MainActor.run { () -> Bool in
                PageSync.shared.noteInsightPush(id: id, text: body)
                return ChatPresence.insightHost != nil
            }
            return hosted ? [] : [.banner, .sound, .list]
        }
        // P-Health 的回复：正开着那个对话就不弹了（消息已经在眼前）
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
    var insight: String? = nil       // 点洞察推送进来：打开主对话后直接点开这条洞察（不经过浮条）
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
    /// 后台推送（HKObserverQuery + enableBackgroundDelivery）只注册一次：授权回调每次启动都会走
    private var observersRegistered = false
    /// 正在查 + 传的那一轮：启动、下拉、两个观察者回调同时来时合成一轮，不并发查 HealthKit
    private var uploadTask: Task<Bool, Never>?
    private var uploadStartedAt = Date.distantPast
    private var uploadAgain = false


    /// 下拉刷新时调：马上把近 7 天的 Apple 健康数据再传一次。返回是否传成功（没授权、测试模式、服务器一条没收都算没传）
    @discardableResult
    func syncNow() async -> Bool {
        guard hasBootstrapped, HKHealthStore.isHealthDataAvailable() else { return false }
        return await uploadHealth()
    }

    /// 查 HealthKit + 上传，同一时间只跑一轮：已经在跑就等它；开跑 3 秒后才来的（新数据可能没查到）跑完再补一轮
    @discardableResult
    private func uploadHealth() async -> Bool {
        if let t = uploadTask {
            if Date().timeIntervalSince(uploadStartedAt) > 3 { uploadAgain = true }
            return await t.value
        }
        uploadStartedAt = Date()
        let t = Task { @MainActor () -> Bool in
            var ok = await self.collectHealthAndUpload()
            while self.uploadAgain {
                self.uploadAgain = false
                self.uploadStartedAt = Date()
                ok = await self.collectHealthAndUpload()
            }
            self.uploadTask = nil
            return ok
        }
        uploadTask = t
        return await t.value
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
        // 系统只在第一次弹授权页（之后每次启动直接回调）；回调里注册后台推送，再传一次
        health.requestAuthorization(toShare: [], read: read) { _, error in
            if let error { DshAPI.dbg("HealthKit 授权出错: \(error.localizedDescription)") }
            Task { @MainActor in
                let me = DeviceDataReporter.shared
                me.registerBackgroundDelivery()
                await me.uploadHealth()
            }
        }
    }

    /// 步数、睡眠有新数据时系统在后台叫醒 App（最多每小时一次），查一遍传上去再告诉系统做完了。
    /// 要在每次启动时注册（后台被叫醒时也是走 didFinishLaunching → bootstrap → 这里）；同一进程只注册一次。
    private func registerBackgroundDelivery() {
        guard !observersRegistered else { return }
        observersRegistered = true
        let types: [HKSampleType] = [HKObjectType.quantityType(forIdentifier: .stepCount),
                                     HKObjectType.categoryType(forIdentifier: .sleepAnalysis)].compactMap { $0 }
        for type in types {
            let q = HKObserverQuery(sampleType: type, predicate: nil) { _, completion, error in
                if let error {
                    DshAPI.dbg("HealthKit 观察 \(type.identifier) 出错: \(error.localizedDescription)")
                    completion()
                    return
                }
                Task { @MainActor in
                    await DeviceDataReporter.shared.uploadFromObserver()
                    completion()
                }
            }
            health.execute(q)
            health.enableBackgroundDelivery(for: type, frequency: .hourly) { ok, error in
                if !ok { DshAPI.dbg("后台推送 \(type.identifier) 没开成: \(error?.localizedDescription ?? "")") }
            }
        }
    }

    /// 观察者回调：在后台的话多要一点时间，传完（或者时间到）再结束
    private func uploadFromObserver() async {
        let app = UIApplication.shared
        var bg = UIBackgroundTaskIdentifier.invalid
        bg = app.beginBackgroundTask(withName: "healthkit-upload") {
            if bg != .invalid { app.endBackgroundTask(bg); bg = .invalid }
        }
        let ok = await uploadHealth()
        DshAPI.dbg("HealthKit 后台推送触发上传 ok=\(ok) state=\(app.applicationState.rawValue)")
        if bg != .invalid { app.endBackgroundTask(bg); bg = .invalid }
    }

    @discardableResult
    private func collectHealthAndUpload() async -> Bool {
        let cal = PTime.calendar
        let now = Date()
        guard let start = cal.date(byAdding: .day, value: -7, to: cal.startOfDay(for: now)) else { return false }
        // 告诉服务器这次是在前台还是后台查的、查到几条、有没有报错：前台查到 0 条才可能是权限关了
        let foreground = UIApplication.shared.applicationState == .active
        var samples: [[String: Any]] = []
        var queryError: String?

        if let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
            let (segments, err) = await querySleepSegments(type: sleepType, start: start, end: now)
            if let err, queryError == nil { queryError = "sleep_analysis: \(err)" }
            for (cat, s, e, id) in segments {
                samples.append([
                    "sample_id": "hkslp-\(id.uuidString)",
                    "type": "sleep_analysis",
                    "start_at": PTime.isoUTC(s), "end_at": PTime.isoUTC(e),
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
            let (days, err) = await queryDailyStats(type: qt, start: start, options: options, unit: unit)
            if let err, queryError == nil { queryError = "\(typeName): \(err)" }
            for (dayStart, value) in days {
                guard let dayEnd = cal.date(byAdding: .day, value: 1, to: dayStart) else { continue }
                samples.append([
                    "sample_id": "hkagg-\(typeName)-\(PTime.compactDay(dayStart))",
                    "type": typeName,
                    "start_at": PTime.isoUTC(dayStart), "end_at": PTime.isoUTC(dayEnd),
                    "unit": unitString(typeName), "numeric_value": value,
                ])
            }
        }
        let obs = pendingObservations
        pendingObservations.removeAll()
        let health: [String: Any] = ["foreground": foreground, "samples": samples.count,
                                     "error": queryError.map { $0 as Any } ?? NSNull()]
        let ok = await upload(samples: samples, observations: obs, health: health)
        return ok && !samples.isEmpty      // 一条都没查到（权限关了 / 新手机）不算「传上去了」
    }

    private func unitString(_ type: String) -> String {
        ["heart_rate": "count/min", "heart_rate_variability_sdnn": "ms",
         "resting_heart_rate": "count/min", "respiratory_rate": "count/min",
         "oxygen_saturation": "%", "step_count": "count",
         "active_energy_burned": "kcal", "body_mass": "kg"][type] ?? ""
    }

    /// 返回睡眠分段和查询出错时的错误描述（以前把错误丢掉了，服务器分不清「没数据」和「查不了」）
    private func querySleepSegments(type: HKCategoryType, start: Date, end: Date) async -> ([(String, Date, Date, UUID)], String?) {
        let health = self.health
        return await withCheckedContinuation { cont in
            let q = HKSampleQuery(sampleType: type,
                                  predicate: HKQuery.predicateForSamples(withStart: start, end: end),
                                  limit: HKObjectQueryNoLimit, sortDescriptors: nil) { _, results, error in
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
                cont.resume(returning: (out, error?.localizedDescription))
            }
            health.execute(q)
        }
    }

    private func queryDailyStats(type: HKQuantityType, start: Date,
                                 options: HKStatisticsOptions, unit: HKUnit) async -> ([(Date, Double)], String?) {
        let health = self.health
        return await withCheckedContinuation { cont in
            let anchor = PTime.calendar.startOfDay(for: start)
            let q = HKStatisticsCollectionQuery(quantityType: type, quantitySamplePredicate: nil,
                                                options: options,
                                                anchorDate: anchor,
                                                intervalComponents: DateComponents(day: 1))
            q.initialResultsHandler = { _, results, error in
                var out: [(Date, Double)] = []
                results?.enumerateStatistics(from: anchor, to: Date()) { stat, _ in
                    if let v = stat.sumQuantity() ?? stat.averageQuantity() {
                        out.append((stat.startDate, v.doubleValue(for: unit)))
                    }
                }
                cont.resume(returning: (out, error?.localizedDescription))
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
    /// health：这次查 HealthKit 的情况（只有健康上报带；位置 / 蓝牙这类只带观察的不带，免得服务器以为「前台查到 0 条」）。
    /// 服务器回 {accepted, rejected, reject_reasons}；发了样本却一条没收（HTTP 422）、或者别的非 2xx，都算没传成
    @discardableResult
    private func upload(samples: [[String: Any]], observations: [[String: Any]],
                        health: [String: Any]? = nil) async -> Bool {
        var body: [String: Any] = ["device_id": deviceId, "samples": samples, "observations": observations]
        if let health { body["health"] = health }
        let req = PivisAPI.request("api/v2/device-data", method: "POST", json: body, timeout: 30)
        do {
            let (data, resp) = try await PivisAPI.send(req, checkStatus: false)
            let obj = PivisAPI.object(data) ?? [:]
            let accepted = (obj["accepted"] as? Int) ?? 0
            let reasons = ((obj["reject_reasons"] as? [[String: Any]]) ?? []).compactMap { $0["reason"] as? String }
            let reasonText = Array(Set(reasons)).sorted().joined(separator: ",")
            DshAPI.dbg("device-data status=\(resp.statusCode) samples=\(samples.count) accepted=\(accepted) "
                       + "rejected=\((obj["rejected"] as? Int) ?? 0) observations=\(observations.count)"
                       + (reasonText.isEmpty ? "" : " reasons=\(reasonText)"))
            guard (200..<300).contains(resp.statusCode) else { return false }
            if !samples.isEmpty && accepted == 0 { return false }
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


/// 极简钥匙串读写（设备 id 这类要跨重装保留的值；build 55 起还有配对电脑的设备密钥）
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

    static func delete(_ key: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: key]
        SecItemDelete(q as CFDictionary)
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
