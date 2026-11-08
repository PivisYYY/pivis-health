import XCTest

/// 待办卡全动作验收：每种动作点下去 1 秒内要有反应（不等服务器），断网也一样，连上后自动补发。
/// 只连封版测试环境（-pivisProfile sim，8944）；测试卡由 ~/Tools/pivis-qa/bin/ui_fixtures.py 事先建好（固定 id：ui-*）。
@MainActor
final class TodoCardsUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    override func tearDown() {
        app?.terminate()
        app = nil
        super.tearDown()
    }

    private func launch(_ extra: [String] = []) {
        app = XCUIApplication()
        app.launchArguments = ["-pivisProfile", "sim", "-uiTestDisableDeviceData", "-noSplash"] + extra
        app.launch()
        app.buttons["休息"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["接下来"].waitForExistence(timeout: 15), "休息页没加载出来")
    }

    private func card(_ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "todo-\(id)").firstMatch
    }

    private let ids = ["UI 打勾": "ui-check", "UI 计数": "ui-counter", "UI 计时": "ui-timer", "UI 清单": "ui-checklist",
                       "UI 确认": "ui-confirm", "UI 数值": "ui-number", "UI 单选": "ui-options", "UI 练习视频": "ui-follow",
                       "UI 断网打勾": "ui-off-check", "UI 断网计时": "ui-off-timer", "UI 断网计数": "ui-off-counter"]

    /// 用待办深链定位：切到休息页、展开这张卡并滚到屏幕中间（页面卡多时靠滑动定位会被底栏挡住）
    private func focus(_ title: String) {
        guard let id = ids[title] else { return XCTFail("没有这张测试卡 \(title)") }
        app.open(URL(string: "phealth://todo/\(id)?board=sleep")!)
        XCTAssertTrue(row(title).waitForExistence(timeout: 5), "找不到卡片 \(title)")
        sleep(1)
    }

    private func expand(_ id: String, title: String) { focus(title) }

    /// 收起行上的按钮（✓、+1、开始）：滑到看得见、推到底栏上方即可，不用展开
    private func reveal(_ title: String) {
        let t = row(title)
        var tries = 0
        while !(t.exists && t.isHittable) && tries < 8 {
            app.swipeUp(velocity: .slow)
            tries += 1
        }
        XCTAssertTrue(t.exists, "找不到卡片 \(title)")
        liftAboveTabBar(t)
        sleep(1)      // 拖动后列表还在惯性滚：停稳再点，不然会点到别的卡
    }

    private func liftAboveTabBar(_ el: XCUIElement) {
        let bar = app.buttons["tab-now"].firstMatch
        var n = 0
        while el.exists && bar.exists && el.frame.maxY > bar.frame.minY - 70 && n < 6 {
            let w = app.windows.firstMatch
            w.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.6)).press(forDuration: 0.05, thenDragTo: w.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.42)))
            n += 1
        }
    }

    private func expectQuick(_ el: XCUIElement, _ what: String, timeout: TimeInterval = 1.0) {
        XCTAssertTrue(el.waitForExistence(timeout: timeout), "\(what)：\(timeout) 秒内没反应")
    }

    /// 待办行：build 44 起「时间 + 标题」这一块是一个按钮（标签 = 标题，值 = 时间 · 副标题 · 展开状态），标题不再是单独的文字
    private func row(_ title: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == %@", title)).firstMatch
    }

    /// 屏幕上的字：普通文字按标签找；待办行的副标题（「1 / 2 杯」「还剩 …」「等网络」）在行按钮的值里
    private func text(containing s: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(
            format: "(elementType == %@ AND label CONTAINS %@) OR (elementType == %@ AND value CONTAINS %@)",
            NSNumber(value: XCUIElement.ElementType.staticText.rawValue), s,
            NSNumber(value: XCUIElement.ElementType.button.rawValue), s)).firstMatch
    }

    /// 点了对勾：对勾变实心（todo-settled），原位停两秒再收起
    private func settled(_ id: String) -> XCUIElement {
        card(id).descendants(matching: .any).matching(identifier: "todo-settled").firstMatch
    }

    /// 做完的卡原位停两秒后收起：等它收完再点下一张（不然页面一挪，下一下会点空）
    private func waitGone(_ id: String) {
        XCTAssertTrue(card(id).waitForNonExistence(timeout: 8), "做完的卡 \(id) 没有收起")
        sleep(1)
    }

    // MARK: 在线：每种主动作（build 43：行尾一个主动作，没有晚点 / 算了 / 回复框）
    func test1_EveryActionRespondsInstantly() {
        launch()

        // 打勾：收起行的对勾
        reveal("UI 打勾")
        card("ui-check").buttons["做完了"].firstMatch.tap()
        expectQuick(settled("ui-check"), "打勾")
        waitGone("ui-check")

        // 计数：+1 两次，第二次到目标就算做完
        reveal("UI 计数")
        let inc = card("ui-counter").buttons["加一次"].firstMatch
        inc.tap()
        expectQuick(text(containing: "1 / 2"), "计数 +1")
        inc.tap()
        expectQuick(settled("ui-counter"), "计数到目标")
        waitGone("ui-counter")

        // 计时（只用于午睡）：开始 → 还剩 + 对勾（字由 P-Health 定，默认「好了」）→ 做完
        reveal("UI 计时")
        card("ui-timer").buttons["todo-timer-start"].firstMatch.tap()
        expectQuick(card("ui-timer").buttons["todo-timer-end"].firstMatch, "计时开始")
        XCTAssertTrue(text(containing: "还剩").exists, "开始后没有「还剩」倒计时")
        saveShot("timer-started")
        card("ui-timer").buttons["todo-timer-end"].firstMatch.tap()
        expectQuick(settled("ui-timer"), "计时结束")
        waitGone("ui-timer")

        // 确认时间：收起行的对勾直接记下现在的时间
        reveal("UI 确认")
        card("ui-confirm").buttons["todo-confirm"].firstMatch.tap()
        expectQuick(settled("ui-confirm"), "确认")
        waitGone("ui-confirm")

        // 数值：展开 → 步进器 → 行尾对勾（记下）
        focus("UI 数值")
        let plus = card("ui-number").buttons["加"].firstMatch
        XCTAssertTrue(plus.waitForExistence(timeout: 2), "数值步进器没出来")
        plus.tap()
        plus.tap()
        card("ui-number").buttons["todo-submit"].firstMatch.tap()
        expectQuick(settled("ui-number"), "数值提交")
        waitGone("ui-number")

        // 单选：收起时行尾是问号图标（build 45：每张卡都有图标），展开 → 点一个就交
        XCTAssertTrue(card("ui-options").buttons["todo-open"].firstMatch.exists, "单选卡收起时行尾没有图标")
        focus("UI 单选")
        XCTAssertTrue(card("ui-options").buttons["todo-chat"].firstMatch.exists, "展开后行尾没有 P-Health 图标")
        card("ui-options").buttons["有点"].firstMatch.tap()
        expectQuick(settled("ui-options"), "单选")
        waitGone("ui-options")

        // 旧子清单（只读兜底）：三步勾完
        focus("UI 清单")
        for i in 0..<3 { card("ui-checklist").buttons["todo-step-\(i)"].firstMatch.tap() }
        expectQuick(settled("ui-checklist"), "清单勾完")
        waitGone("ui-checklist")

        // 练习视频：展开是整宽视频，点了全屏播；「先到这」关掉不算做完；行尾对勾才算
        focus("UI 练习视频")
        let play = card("ui-follow").buttons["todo-play"].firstMatch
        XCTAssertTrue(play.waitForExistence(timeout: 2), "练习卡展开后没有视频")
        play.tap()
        let close = app.buttons["exec-close"].firstMatch
        expectQuick(close, "练习视频全屏播放", timeout: 3)
        XCTAssertFalse(app.buttons["exec-next"].exists, "全屏播放页不该有「做完了」")
        close.tap()
        XCTAssertTrue(close.waitForNonExistence(timeout: 2), "「先到这」后没关")
        XCTAssertTrue(row("UI 练习视频").exists, "「先到这」不该记做完")
        card("ui-follow").buttons["todo-done"].firstMatch.tap()
        expectQuick(settled("ui-follow"), "练习对勾")

        // 卡上没有回复框、没有晚点 / 算了
        XCTAssertFalse(app.textFields["todo-reply"].exists, "卡上还有回复框")
        XCTAssertFalse(app.buttons["晚点"].exists || app.buttons["算了"].exists, "卡上还有「晚点 / 算了」")
        saveShot("online-done")
    }

    // MARK: 断网：点了照样立刻生效，标「等网络」；重开 App（联网）后自动补发
    func test2_OfflineActionsApplyLocallyThenDeliver() {
        launch(["-todoOfflineTest"])

        reveal("UI 断网打勾")
        card("ui-off-check").buttons["做完了"].firstMatch.tap()
        expectQuick(settled("ui-off-check"), "断网打勾")

        reveal("UI 断网计时")
        card("ui-off-timer").buttons["todo-timer-start"].firstMatch.tap()
        expectQuick(card("ui-off-timer").buttons["todo-timer-end"].firstMatch, "断网计时开始")

        reveal("UI 断网计数")
        card("ui-off-counter").buttons["加一次"].firstMatch.tap()
        expectQuick(text(containing: "1 / 3"), "断网计数")

        // 3 秒还没送到：标出来
        XCTAssertTrue(text(containing: "等网络").waitForExistence(timeout: 6) || text(containing: "连上后自动发").exists,
                      "断网时没有提示「等网络」")
        saveShot("offline-waiting")
        // 打勾的卡 2 秒后收起，不会因为没送到又冒回来
        XCTAssertTrue(row("UI 断网打勾").waitForNonExistence(timeout: 4), "断网打勾的卡没有收起")

        // 联网重开：队列从手机上读出来，自动补发
        app.terminate()
        launch()
        sleep(4)
        reveal("UI 断网计时")
        XCTAssertTrue(card("ui-off-timer").buttons["todo-timer-end"].firstMatch.exists || text(containing: "还剩").exists,
                      "重开后计时没有保持进行中")
        XCTAssertFalse(row("UI 断网打勾").exists, "补发后打勾的卡又出现了")
        saveShot("offline-delivered")
    }

    private func saveShot(_ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }
}
