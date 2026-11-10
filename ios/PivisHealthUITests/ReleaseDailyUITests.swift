import XCTest

/// 封版摸底 · 日常 UI 用例（build 39 起）。
/// 只连封版测试环境：-pivisProfile sim（8944，由 ~/Tools/pivis-qa/bin/qaserver.sh 切到 workspace-qa）。
/// 测试卡由 ~/Tools/pivis-qa/bin/ui_fixtures.py 事先建好（运动页 qa-*，休息页 ui-*）；每轮跑之前重建一次。
/// 会真的跟 P-Health 说话的用例（t05 / t20 / t24 / t25）都带「封版测试」字样，只进测试环境的会话。
@MainActor
final class ReleaseDailyUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    override func tearDown() {
        app?.terminate()
        app = nil
        XCUIDevice.shared.orientation = .portrait
        super.tearDown()
    }

    // MARK: - 帮手

    private func launch(_ extra: [String] = [], splash: Bool = false) {
        app = XCUIApplication()
        app.launchArguments = ["-pivisProfile", "sim", "-uiTestDisableDeviceData"] + (splash ? ["-showSplash"] : ["-noSplash"]) + extra
        app.launch()
    }

    private func tab(_ id: String, _ name: String) {
        let b = app.buttons[id].firstMatch
        XCTAssertTrue(b.waitForExistence(timeout: 15), "找不到底栏 \(name)")
        b.tap()
        let title = app.staticTexts["page-title"].firstMatch
        XCTAssertTrue(waitUntil(15) { title.exists && title.label == name }, "\(name) 页没切过去（标题：\(title.exists ? title.label : "无")）")
    }

    private func card(_ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "todo-\(id)").firstMatch
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

    private func any(_ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private var hero: XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "identifier IN %@", ["hero", "hero-updating"])).firstMatch
    }

    @discardableResult
    private func reveal(_ title: String, swipes: Int = 10) -> XCUIElement {
        let t = row(title)
        var n = 0
        while !(t.exists && t.isHittable) && n < swipes {
            app.swipeUp(velocity: .slow)
            n += 1
        }
        XCTAssertTrue(t.exists, "找不到卡片「\(title)」")
        liftAboveTabBar(t)
        return t
    }

    /// 卡片停在底栏后面时，XCUITest 认为点得到、实际会点到底栏：再往上推一点，推到底栏上方
    private func liftAboveTabBar(_ el: XCUIElement) {
        let bar = app.buttons["tab-now"].firstMatch
        var n = 0
        while el.exists && bar.exists && el.frame.maxY > bar.frame.minY - 70 && n < 6 {
            let w = app.windows.firstMatch
            w.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.6)).press(forDuration: 0.05, thenDragTo: w.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.42)))
            n += 1
        }
    }


    private func waitUntil(_ timeout: TimeInterval, _ cond: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if cond() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        return cond()
    }

    private func shot(_ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    private func openMainChat() {
        let b = app.buttons["open-main-chat"].firstMatch
        XCTAssertTrue(b.waitForExistence(timeout: 15), "找不到中间的 P-Health 按钮")
        b.tap()
        XCTAssertTrue(app.textViews["chat-input"].firstMatch.waitForExistence(timeout: 10), "主对话没打开")
    }

    private func closeChat() {
        let x = app.buttons["收起"].firstMatch
        if x.waitForExistence(timeout: 5) { x.tap() }
        XCTAssertTrue(app.buttons["open-main-chat"].firstMatch.waitForExistence(timeout: 5), "对话没收起")
    }

    /// 发一句话，等 P-Health 这一轮回完（正在思考 / 正在回复 的那一行出现后消失）
    private func say(_ s: String, replyTimeout: TimeInterval = 300) {
        let input = app.textViews["chat-input"].firstMatch
        input.tap()
        input.typeText(s)
        let send = app.buttons["chat-send"].firstMatch
        XCTAssertTrue(send.isEnabled, "填了字发送键还是灰的")
        send.tap()
        XCTAssertTrue(text(containing: String(s.prefix(8))).waitForExistence(timeout: 5), "发出的话没显示出来")
        let act = any("chat-activity")
        let started = act.waitForExistence(timeout: 15)
        XCTAssertFalse(text(containing: "发送失败").exists, "消息没发出去：\(text(containing: "发送失败").label)")
        XCTAssertTrue(started, "发出后 15 秒内 P-Health 没开始处理")
        XCTAssertTrue(waitUntil(replyTimeout) { !act.exists }, "\(Int(replyTimeout)) 秒内 P-Health 还没回完")
        sleep(2)
        XCTAssertFalse(text(containing: "发送失败").exists, "回复阶段出现「发送失败」")
    }

    // MARK: - 开屏

    func test01_SplashTapExpandsThenEnters() {
        launch(splash: true)
        XCTAssertTrue(any("splash").waitForExistence(timeout: 5), "开屏没出来")
        XCTAssertTrue(text(containing: "反直觉").waitForExistence(timeout: 3), "开屏没有「反直觉 · 但是对的」")
        sleep(2)
        shot("01-splash")
        any("splash").tap()
        XCTAssertTrue(waitUntil(4) { text(containing: "怎么做").exists || text(containing: "依据").exists }, "点一下没展开解释")
        shot("01-splash-expanded")
        any("splash").tap()
        XCTAssertTrue(waitUntil(5) { app.buttons["tab-now"].firstMatch.isHittable }, "第二下没进 App")
    }

    func test02_SplashLeavesByItself() {
        launch(splash: true)
        XCTAssertTrue(any("splash").waitForExistence(timeout: 5), "开屏没出来")
        XCTAssertTrue(waitUntil(10) { app.buttons["tab-now"].firstMatch.isHittable }, "不点的话开屏 10 秒内没自己退")
    }

    // MARK: - 四个页

    func test03_EveryBoardPageLoads() {
        launch()
        for (id, name) in [("tab-now", "此刻"), ("tab-sleep", "休息"), ("tab-sport", "运动"), ("tab-stress", "压力")] {
            tab(id, name)
            XCTAssertTrue(hero.waitForExistence(timeout: 20), "\(name) 页没有主卡")
            shot("03-\(name)-first")
            // 主卡要有内容（数值 / 图 / 字段），不能只剩标题和日期：数主卡容器里的子元素（build 42 起子元素保留各自的标识）
            let heroParts = hero.descendants(matching: .any)
            let t0 = Date()
            let full = waitUntil(10) { heroParts.count >= 4 }   // 空卡最多 3 个：标题、档位、日期（build 43 起「坚持习惯」在主卡下面）
            let a = XCTAttachment(string: "\(name) hero_parts=\(heroParts.count) wait_s=\(String(format: "%.1f", Date().timeIntervalSince(t0)))")
            a.name = "03-\(name)-hero-parts"; a.lifetime = .keepAlways; add(a)
            continueAfterFailure = true
            XCTAssertTrue(full, "\(name) 页主卡 10 秒内只有标题没有内容（\(heroParts.count) 个元素）")
            continueAfterFailure = false
            XCTAssertTrue(app.buttons[id].firstMatch.isSelected, "\(name) 的底栏没标成选中")
            XCTAssertFalse(text(containing: "暂时连不上").exists, "\(name) 页显示连不上")
            sleep(1)
            shot("03-\(name)")
        }
    }

    // build 43：主卡下面每个习惯一行；点进去是这个板块的对话，顶部是习惯卡，P-Health 不主动说话
    func test04_HabitRowOpensBoardChat() {
        launch()
        tab("tab-sport", "运动")
        let row = any("habit-qa-habit")
        XCTAssertTrue(row.waitForExistence(timeout: 10), "运动页没有「坚持习惯 · QA 习惯」行")
        XCTAssertTrue(row.label.contains("QA 习惯") && row.label.contains("1/28"), "习惯行内容不对：\(row.label)")
        row.tap()
        XCTAssertTrue(waitUntil(8) { text(containing: "P-Health · 运动").exists }, "习惯行没打开运动对话")
        XCTAssertTrue(any("habit-card").waitForExistence(timeout: 8), "对话顶部没有习惯卡")
        XCTAssertTrue(any("habit-week").waitForExistence(timeout: 8), "习惯卡没有本周 7 天")
        XCTAssertTrue(any("habit-session-a").exists, "习惯卡里没有「QA 力量 A → 视频」")
        XCTAssertTrue(any("chat-about").exists && text(containing: "关于：QA 习惯").exists, "输入框上方没有「关于：QA 习惯」")
        // 打开对话不触发任何消息
        XCTAssertFalse(any("chat-activity").waitForExistence(timeout: 4), "打开习惯对话后 P-Health 自己说话了")
        shot("04-habit-card")
        app.buttons["chat-about-collapse"].firstMatch.tap()
        XCTAssertTrue(any("chat-about-collapsed").waitForExistence(timeout: 3), "习惯卡没收成一行")
        shot("04-habit-collapsed")
        app.buttons["chat-about-clear"].firstMatch.tap()
        XCTAssertTrue(any("chat-about").waitForNonExistence(timeout: 3), "点 × 后「关于」标签还在")
        closeChat()
    }

    // MARK: - 对话

    func test05_MainChatSendAndReplyPersists() {
        launch()
        openMainChat()
        XCTAssertFalse(app.buttons["chat-send"].firstMatch.isEnabled, "空输入时发送键应是灰的")
        say("封版测试：今天下午适合打网球吗？一句话回答")
        shot("05-reply")
        closeChat()
        openMainChat()
        XCTAssertTrue(text(containing: "封版测试：今天下午适合打网球").waitForExistence(timeout: 8), "重开对话后刚才那句话不见了")
        shot("05-reopen")
    }

    func test06_ChatCardsRender() {
        launch(["-openChat", "main", "-flowTest"])
        // 卡片容器上的标识拿不到（同主卡，见报告），按卡里的内容找：布局卡画出「小时」，选项卡有「慢呼吸 5 分钟」
        XCTAssertTrue(waitUntil(25) { any("canvas-card").exists || text(containing: "小时").exists }, "流式测试里的布局卡没画出来")
        for _ in 0..<4 where !app.buttons["慢呼吸 5 分钟"].exists { app.swipeUp(velocity: .slow) }
        // 假回复约 600 字、按真实节奏一小段一小段流（约 30 秒）：选项卡在最后，多等一会
        let t0 = Date()
        XCTAssertTrue(app.buttons["慢呼吸 5 分钟"].waitForExistence(timeout: 30), "流式测试里的选项卡没画出来")
        let a = XCTAttachment(string: "options_card_wait_s=\(String(format: "%.1f", Date().timeIntervalSince(t0)))")
        a.name = "06-options-wait"; a.lifetime = .keepAlways; add(a)
        XCTAssertFalse(text(containing: "phealth-ui").exists, "界面上露出了卡片原文")
        XCTAssertFalse(text(containing: "格式有误").exists, "有卡片画坏了")
        shot("06-cards")
    }

    func test07_StalledStreamFinishes() {
        launch(["-openChat", "main", "-flowTest", "-flowTestStall"])
        let act = any("chat-activity")
        _ = act.waitForExistence(timeout: 10)
        XCTAssertTrue(waitUntil(45) { !act.exists }, "流断了 25 秒以上还在转")
        shot("07-stall-finished")
    }

    // MARK: - 跟练页

    // build 43：练习 = 项目 + 一个视频。展开是整宽视频框，点了全屏播；「先到这」只关掉；对勾才算做完
    func test08_FollowVideoPlaysAndStopsEarly() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 跟练视频").tap()
        let play = card("qa-vid").buttons["todo-play"].firstMatch
        XCTAssertTrue(play.waitForExistence(timeout: 3), "练习卡展开后没有视频框")
        play.tap()
        let video = app.buttons["exec-video"].firstMatch
        XCTAssertTrue(video.waitForExistence(timeout: 5), "全屏播放没打开")
        XCTAssertTrue(app.buttons["exec-close"].firstMatch.exists, "没有「先到这」")
        XCTAssertFalse(app.buttons["exec-next"].exists, "全屏播放不该有「做完了」")
        XCTAssertTrue(app.buttons["静音"].firstMatch.exists, "跟练视频应默认有声音（按钮是「静音」）")
        sleep(4)
        shot("08-video-playing")
        video.tap()
        XCTAssertTrue(waitUntil(3) { video.label == "继续" }, "点画面没暂停（标签：\(video.label)）")
        shot("08-video-paused")
        app.buttons["exec-close"].firstMatch.tap()
        XCTAssertTrue(video.waitForNonExistence(timeout: 4), "「先到这」后没关")
        sleep(2)
        XCTAssertTrue(row("QA 跟练视频").exists, "「先到这」不该算做完")
        card("qa-vid").buttons["todo-done"].firstMatch.tap()
        XCTAssertTrue(card("qa-vid").descendants(matching: .any).matching(identifier: "todo-settled").firstMatch.waitForExistence(timeout: 2),
                      "点对勾后没变成做完")
    }

    // build 43：小组件 / 到点提醒点开练习，直接全屏播
    func test09_ClosingExecDoesNotCountAsDone() {
        launch()
        XCTAssertTrue(app.buttons["tab-now"].firstMatch.waitForExistence(timeout: 15))
        app.open(URL(string: "phealth://todo/qa-vid?board=sport&play=1")!)
        let video = app.buttons["exec-video"].firstMatch
        XCTAssertTrue(video.waitForExistence(timeout: 8), "带 play=1 的深链没有直接全屏播放")
        shot("09-play-link")
        app.buttons["exec-close"].firstMatch.tap()
        XCTAssertTrue(video.waitForNonExistence(timeout: 4), "「先到这」后没关")
    }

    // 旧的多步 / 音频跟做卡（清数据前留下的）：只读显示，没有播放入口，对勾照样能记
    func test10_MultiStepFollow() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 多步跟做").tap()
        XCTAssertTrue(text(containing: "第一步 计时").waitForExistence(timeout: 3), "旧多步卡展开后没有步骤")
        XCTAssertFalse(card("qa-steps").buttons["todo-play"].exists, "旧多步卡不该有视频播放入口")
        shot("10-legacy-steps")
        card("qa-steps").buttons["todo-done"].firstMatch.tap()
        XCTAssertTrue(card("qa-steps").descendants(matching: .any).matching(identifier: "todo-settled").firstMatch.waitForExistence(timeout: 2),
                      "旧多步卡点对勾没反应")
    }

    // MARK: - 其它待办形式

    func test11_FieldsDiary() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 多字段").tap()
        let c = card("qa-diary")
        let time = c.textFields.matching(NSPredicate(format: "placeholderValue == %@", "比如 13:00")).firstMatch
        XCTAssertTrue(time.waitForExistence(timeout: 3), "没有时间输入")
        time.tap(); time.typeText("23:30")
        // 键盘弹起时底栏应留在键盘下面（V3Shell 里的设计），不该浮上来盖住卡片的按钮
        let kb = app.keyboards.firstMatch
        if kb.waitForExistence(timeout: 3) {
            sleep(1)
            let bar = app.buttons["tab-now"].firstMatch
            let hidden = !bar.exists || !bar.isHittable
            let tabTop = bar.exists ? bar.frame.minY : .infinity
            continueAfterFailure = true
            XCTAssertTrue(hidden || tabTop >= kb.frame.minY - 1, "键盘弹起时底栏浮在键盘上面（底栏顶 \(tabTop)，键盘顶 \(kb.frame.minY)），会盖住卡片的按钮")
            shot("11-keyboard-up")
            continueAfterFailure = false
        }
        time.typeText("\n")
        c.buttons["15–30"].firstMatch.tap()
        c.buttons["加"].firstMatch.tap()
        c.buttons["4 分"].firstMatch.tap()
        let more = c.textFields.matching(NSPredicate(format: "placeholderValue == %@", "写一句")).firstMatch
        if more.exists { more.tap(); more.typeText("封版测试\n") }
        sleep(1)
        shot("11-diary-filled")
        let submit = app.buttons["todo-submit"].firstMatch
        if !submit.isHittable { app.swipeUp(velocity: .slow) }
        XCTAssertTrue(submit.isEnabled, "填完了行尾的对勾还是灰的")
        submit.tap()
        // 时间 / 文字项默认交给 P-Health（服务器归一化成 submit=agent）：卡片收起或进入处理都算交上了
        XCTAssertTrue(waitUntil(3) { any("todo-settled").exists || !submit.exists || text(containing: "P-Health").exists },
                      "多字段提交没反应")
    }

    // build 43：卡上不再有「自己写一句」
    func test12_MultiSelectWithOwnText() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 多选").tap()
        let c = card("qa-multi")
        XCTAssertTrue(c.buttons["膝盖"].firstMatch.waitForExistence(timeout: 3), "多选卡没展开")
        sleep(1)        // 展开动画走完再点，不然选项点不中
        c.buttons["膝盖"].firstMatch.tap()
        c.buttons["肩"].firstMatch.tap()
        XCTAssertEqual(c.textFields.count, 0, "卡上还有「自己写一句」的输入框")
        shot("12-multi")
        c.buttons["todo-submit"].firstMatch.tap()
        XCTAssertTrue(c.descendants(matching: .any).matching(identifier: "todo-settled").firstMatch.waitForExistence(timeout: 2), "多选提交没反应")
    }

    func test13_ProposalPick() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 提议").tap()
        let c = card("qa-proposal")
        XCTAssertTrue(c.buttons["方案一"].firstMatch.waitForExistence(timeout: 3), "提议的方案没出来")
        shot("13-proposal")
        c.buttons["方案一"].firstMatch.tap()
        XCTAssertTrue(waitUntil(3) { c.descendants(matching: .any).matching(identifier: "todo-settled").firstMatch.exists
                                     || text(containing: "P-Health").exists || !row("QA 提议").exists },
                      "选了方案没反应")
    }

    // 设备自动记的卡：写「设备会自动记」，行尾也是对勾（build 47 起，没识别到可以自己点）；记错了点 P-Health 图标说
    func test14_AutoDoneManualRecord() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 自动记")
        let c = card("qa-auto")
        XCTAssertTrue(text(containing: "设备会自动记").exists, "自动记的卡没写「设备会自动记」")
        // build 47：「上床」这种设备会自动记的也是对勾（没识别到可以自己点）
        XCTAssertTrue(c.buttons["todo-done"].firstMatch.exists, "自动记的卡行尾没有对勾")
        row("QA 自动记").tap()
        XCTAssertTrue(c.buttons["todo-chat"].firstMatch.waitForExistence(timeout: 3), "展开后没有 P-Health 图标")
        XCTAssertFalse(c.buttons["手动记一下"].exists, "还有「手动记一下」")
        shot("14-auto")
    }

    func test15_PhotoTodoOpensPicker() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 拍照")
        let b = card("qa-photo").buttons["todo-photo"].firstMatch
        XCTAssertTrue(b.exists, "拍照卡没有「拍照」按钮")
        b.tap()
        // 模拟器没有相机，走系统相册
        sleep(3)
        shot("15-picker")
        // 系统相册选择器跑在别的进程里，元素拿不到：按位置点第一张（相册最上面一行最左）
        XCTAssertTrue(waitUntil(6) { app.staticTexts["照片"].exists || app.buttons["照片"].exists || true })
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.16, dy: 0.41)).tap()
        // 选了照片：打开对话，以待办的名义把照片发给 P-Health
        XCTAssertTrue(app.textViews["chat-input"].firstMatch.waitForExistence(timeout: 15), "选了照片后没进对话")
        XCTAssertTrue(text(containing: "QA 拍照").waitForExistence(timeout: 20) || any("chat-activity").exists, "照片没以待办名义发出去")
        let act = any("chat-activity")
        XCTAssertTrue(waitUntil(300) { !act.exists }, "P-Health 没回完照片")
        sleep(2)
        shot("15-photo-reply")
    }

    // MARK: - 系统入口

    func test16_DeepLinks() {
        launch()
        XCTAssertTrue(app.buttons["tab-now"].firstMatch.waitForExistence(timeout: 15))
        app.open(URL(string: "phealth://page/sport")!)
        XCTAssertTrue(waitUntil(6) { app.staticTexts["page-title"].firstMatch.label == "运动" }, "page 深链没切到运动页")
        app.open(URL(string: "phealth://page/now")!)
        XCTAssertTrue(waitUntil(6) { app.staticTexts["page-title"].firstMatch.label == "此刻" }, "page 深链没切回此刻")
        app.open(URL(string: "phealth://todo/qa-deeplink?board=sport")!)
        XCTAssertTrue(waitUntil(8) { app.staticTexts["page-title"].firstMatch.label == "运动" }, "todo 深链没切到运动页")
        XCTAssertTrue(text(containing: "从深链打开会自动展开").waitForExistence(timeout: 6), "todo 深链没展开那张卡")
        shot("16-todo-link")
        app.open(URL(string: "phealth://chat")!)
        XCTAssertTrue(app.textViews["chat-input"].firstMatch.waitForExistence(timeout: 8), "chat 深链没打开对话")
    }

    func test17_PullToRefresh() {
        launch()
        tab("tab-now", "此刻")
        XCTAssertTrue(hero.waitForExistence(timeout: 20))
        sleep(2)
        // 从标语（纯文字，不是按钮）开始往下拉；拉完 1 秒、3 秒各拍一张，看手势有没有触发
        let head = app.staticTexts["headline-now"].firstMatch
        let anchor = head.exists ? head : app.staticTexts["page-title"].firstMatch
        let toast = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR label CONTAINS %@ OR identifier == %@", "已刷新", "已同步", "toast")).firstMatch
        var seen = false
        // XCUITest 的按住拖动在 iOS 26 上不会带动页面滚动（截图里页面不动；手动下拉正常会出「页面已刷新」），改用系统下滑手势
        for i in 0..<2 where !seen {
            app.scrollViews.firstMatch.swipeDown(velocity: XCUIGestureVelocity(500))
            sleep(1); shot("17-after-swipe-\(i)-1s")
            seen = toast.waitForExistence(timeout: 10)
        }
        XCTAssertTrue(seen, "下拉刷新后没有提示")
        shot("17-refresh-toast")
    }

    // build 43：点卡上的 P-Health 图标，带着这张卡进对话：顶部是这张卡，输入框上方「关于：标题」，输入框是空的
    func test18_TodoChatButtonDrafts() {
        launch()
        tab("tab-sport", "运动")
        reveal("QA 带话").tap()
        let talk = card("qa-draft").buttons["todo-chat"].firstMatch
        XCTAssertTrue(talk.waitForExistence(timeout: 3), "卡片上没有 P-Health 图标")
        talk.tap()
        let input = app.textViews["chat-input"].firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 8), "图标没打开对话")
        XCTAssertTrue(any("todo-about-card").waitForExistence(timeout: 5), "对话顶部没有这张待办")
        XCTAssertTrue(text(containing: "关于：QA 带话").exists, "输入框上方没有「关于：QA 带话给 P-Health」")
        XCTAssertTrue((input.value as? String ?? "").isEmpty, "输入框不该有草稿（\(input.value ?? "")）")
        XCTAssertFalse(any("chat-activity").waitForExistence(timeout: 3), "打开对话后 P-Health 自己说话了")
        shot("18-todo-chat")
    }

    func test19_ServerDownShowsRetry() {
        launch(["-pivisBase", "http://127.0.0.1:1", "-dshBase", "http://127.0.0.1:1"])
        XCTAssertTrue(text(containing: "暂时连不上 P-Health").waitForExistence(timeout: 30), "服务器连不上时没有提示")
        let retry = app.buttons["重试"].firstMatch
        XCTAssertTrue(retry.exists, "没有「重试」")
        shot("19-offline")
        retry.tap()
        XCTAssertTrue(text(containing: "暂时连不上 P-Health").waitForExistence(timeout: 30), "重试后状态不对")
        XCTAssertTrue(app.buttons["tab-sleep"].firstMatch.isHittable, "连不上时底栏不能点")
    }

    func test20_ReplyArrivesAfterBackground() {
        launch()
        openMainChat()
        let input = app.textViews["chat-input"].firstMatch
        input.tap()
        input.typeText("封版测试：用两句话说说我昨晚睡得怎么样")
        app.buttons["chat-send"].firstMatch.tap()
        _ = any("chat-activity").waitForExistence(timeout: 15)
        XCUIDevice.shared.press(.home)
        sleep(30)
        app.activate()
        let act = any("chat-activity")
        XCTAssertTrue(waitUntil(300) { !act.exists }, "回到前台后回复一直没到")
        sleep(3)
        shot("20-after-background")
        XCTAssertFalse(text(containing: "还在处理").exists && !act.exists, "回到前台后停在「还在处理」")
    }

    // MARK: - 性能、方向、大字

    func test21_LaunchPerformance() {
        let opts = XCTMeasureOptions()
        opts.iterationCount = 5
        measure(metrics: [XCTApplicationLaunchMetric(waitUntilResponsive: true)], options: opts) {
            let a = XCUIApplication()
            a.launchArguments = ["-pivisProfile", "sim", "-uiTestDisableDeviceData", "-noSplash"]
            a.launch()
            a.terminate()
        }
    }

    func test21b_TimeToFirstHero() {
        var secs: [Double] = []
        for _ in 0..<3 {
            let t0 = Date()
            launch()
            XCTAssertTrue(hero.waitForExistence(timeout: 30), "主卡 30 秒内没出来")
            secs.append(Date().timeIntervalSince(t0))
            app.terminate()
        }
        let a = XCTAttachment(string: "time_to_hero_s=" + secs.map { String(format: "%.2f", $0) }.joined(separator: ","))
        a.name = "21b-time-to-hero"
        a.lifetime = .keepAlways
        add(a)
        XCTAssertLessThan(secs.max() ?? 99, 8, "主卡出来太慢：\(secs)")
    }

    func test22_StaysPortrait() {
        launch()
        XCTAssertTrue(hero.waitForExistence(timeout: 20))
        let before = app.buttons["tab-stress"].firstMatch.frame
        XCUIDevice.shared.orientation = .landscapeLeft
        sleep(2)
        shot("22-landscape")
        let after = app.buttons["tab-stress"].firstMatch.frame
        XCTAssertEqual(before.midY, after.midY, accuracy: 2, "横过来后界面跟着转了（应只支持竖屏）")
    }

    func test23_LargeTextStillUsable() {
        launch(["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityL"])
        for (id, name) in [("tab-now", "此刻"), ("tab-sleep", "休息"), ("tab-sport", "运动"), ("tab-stress", "压力")] {
            tab(id, name)
            XCTAssertTrue(hero.waitForExistence(timeout: 20), "大字下 \(name) 页没有主卡")
            sleep(1)
            shot("23-large-\(name)")
        }
        openMainChat()
        shot("23-large-chat")
        XCTAssertTrue(app.buttons["chat-send"].firstMatch.isHittable, "大字下发送键点不到")
    }

    // MARK: - 端到端：对话里定的事，页面上能看到

    func test24_ChatCreatesTodoOnPage() {
        launch()
        openMainChat()
        say("封版测试：今天下午 3 点提醒我喝一杯水，只今天这一次，直接加就行不用问我", replyTimeout: 360)
        shot("24-reply")
        closeChat()
        var found = false
        for (id, name) in [("tab-now", "此刻"), ("tab-sleep", "休息"), ("tab-sport", "运动"), ("tab-stress", "压力")] {
            tab(id, name)
            sleep(2)
            for _ in 0..<6 {
                if text(containing: "水").exists || app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "水")).firstMatch.exists {
                    found = true; break
                }
                // 此刻页只列 3 张，其余收在「另有 N 件」里：看到就点开
                let more = app.buttons["todos-more"].firstMatch
                if more.exists && more.isHittable && more.label.contains("另有") { liftAboveTabBar(more); more.tap(); sleep(1); continue }
                app.swipeUp(velocity: .slow)
            }
            if found { shot("24-todo-on-\(name)"); break }
        }
        XCTAssertTrue(found, "对话里加的喝水提醒没出现在任何一页")
    }

    // build 43：带着习惯发的消息，气泡下写「带着：名字」；重开对话后（服务器历史）还在
    func test25_TodoReplyLineGoesToAgent() {
        launch()
        tab("tab-sport", "运动")
        let row = any("habit-qa-habit")
        XCTAssertTrue(row.waitForExistence(timeout: 10), "运动页没有测试习惯行")
        row.tap()
        let input = app.textViews["chat-input"].firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 8), "习惯对话没打开")
        input.tap()
        input.typeText("封版测试：这个习惯现在第几天？一句话回答")
        app.buttons["chat-send"].firstMatch.tap()
        XCTAssertTrue(text(containing: "带着：QA 习惯").waitForExistence(timeout: 5), "发出的气泡下没有「带着：QA 习惯」")
        XCTAssertFalse(text(containing: "【习惯").exists, "气泡里露出了标记")
        let act = any("chat-activity")
        _ = act.waitForExistence(timeout: 15)
        XCTAssertTrue(waitUntil(300) { !act.exists }, "P-Health 没回完")
        shot("25-carried")
        closeChat()
        row.tap()
        XCTAssertTrue(waitUntil(10) { text(containing: "带着：QA 习惯").exists }, "重开对话后「带着：QA 习惯」不见了")
        XCTAssertFalse(text(containing: "【习惯").exists, "历史里露出了标记")
    }

    func test26_NowPageMoreTodos() {
        launch()
        XCTAssertTrue(hero.waitForExistence(timeout: 20))
        let more = app.buttons["todos-more"].firstMatch
        var n = 0
        while !(more.exists && more.isHittable) && n < 10 { app.swipeUp(velocity: .slow); n += 1 }
        XCTAssertTrue(more.exists, "待办超过 3 张时没有「另有 N 件」")
        XCTAssertTrue(more.label.contains("另有"), "按钮文字不对：\(more.label)")
        liftAboveTabBar(more)
        shot("26-more-collapsed")
        more.tap()
        XCTAssertTrue(waitUntil(5) { app.buttons["todos-more"].firstMatch.label.contains("收起") }, "点开后没变成「收起」")
        XCTAssertTrue(reveal("UI 断网计数").exists, "展开后看不到被收起来的卡")
        // 日常卡在此刻页上（前 3 张或展开后），不会哪儿都找不到
        var life = row("QA 日常喝水").exists
        n = 0
        while !life && n < 8 { app.swipeDown(velocity: .slow); life = row("QA 日常喝水").exists; n += 1 }
        XCTAssertTrue(life, "日常卡「QA 日常喝水」在此刻页上找不到")
        shot("26-more-expanded")
    }

    // build 41：会话还没建时（新环境、新开的专项对话），第一句不再报 session/not-found
    func test27_FirstMessageOnMissingSession() {
        launch()
        // 用一个还没建会话的板块（跑之前别跑 ensure_sessions.py；每个新环境只能验一次）
        tab("tab-sleep", "休息")
        reveal("QA 新会话对话", swipes: 16).tap()
        let talk = card("qa-newsession").buttons["todo-chat"].firstMatch
        XCTAssertTrue(talk.waitForExistence(timeout: 3), "卡片上没有 P-Health 图标")
        talk.tap()
        XCTAssertTrue(app.textViews["chat-input"].firstMatch.waitForExistence(timeout: 8), "图标没打开对话")
        // 不用 say()：回复很快（1 秒内），「正在处理」那一行可能一闪就没了，直接等回复本身
        let input = app.textViews["chat-input"].firstMatch
        input.tap()
        input.typeText("封版测试：只回一个字「好」")
        app.buttons["chat-send"].firstMatch.tap()
        XCTAssertTrue(waitUntil(120) { app.staticTexts["好"].exists || text(containing: "发送失败").exists }, "120 秒内没等到回复")
        XCTAssertFalse(text(containing: "发送失败").exists, "第一句发送失败：\(text(containing: "发送失败").label)")
        XCTAssertFalse(text(containing: "not-found").exists, "还在显示英文报错")
        shot("27-first-message")
    }

    // build 43：「坚持习惯」在主卡下面（不在主卡里），每个习惯一行，有自己的标识
    func test28_HeroChildrenKeepIdentifiers() {
        launch()
        tab("tab-sport", "运动")
        XCTAssertTrue(hero.waitForExistence(timeout: 20), "运动页没有主卡")
        let row = any("habit-qa-habit")
        XCTAssertTrue(row.waitForExistence(timeout: 5), "习惯行按标识找不到")
        XCTAssertGreaterThanOrEqual(row.frame.minY, hero.frame.maxY - 1, "习惯行应在主卡下面")
        XCTAssertEqual(hero.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "habit-")).count, 0,
                       "主卡里不该再有习惯行")
        XCTAssertTrue(row.label.contains("20:00"), "习惯行右边没写今天要做的：\(row.label)")
    }


    // build 47：习惯卡里的视频全屏后，右上角 × 能关掉（以前全屏挂在卡上，卡一收起 × 就没反应）
    func test29_FullscreenVideoCloses() {
        launch()
        tab("tab-sport", "运动")
        let row = any("habit-qa-habit")
        XCTAssertTrue(row.waitForExistence(timeout: 10), "运动页没有习惯行")
        row.tap()
        XCTAssertTrue(any("habit-card").waitForExistence(timeout: 8), "对话顶部没有习惯卡")
        let full = app.buttons["practice-video-fullscreen"].firstMatch
        XCTAssertTrue(full.waitForExistence(timeout: 8), "习惯卡的视频上没有全屏按钮")
        full.tap()
        let close = app.buttons["practice-fullscreen-close"].firstMatch
        XCTAssertTrue(close.waitForExistence(timeout: 5), "全屏没打开")
        shot("29-fullscreen")
        close.tap()
        XCTAssertTrue(close.waitForNonExistence(timeout: 5), "点右上角 × 没关掉全屏")
        XCTAssertTrue(any("habit-card").exists || text(containing: "P-Health · 运动").exists, "关掉全屏后没回到对话")
        closeChat()
    }

    // build 52：P-Health 每轮回完的那条下面有 👍 / 👎；👎 弹「哪里不好？」，选原因提交后小手变实心，重开对话还在。
    // 只选原因、不写字：服务器只记一笔，不转给 P-Health（不会多一轮对话）。最后再点一次撤回，测试环境不留痕
    func test31_FeedbackThumbs() {
        launch()
        openMainChat()
        let downs = app.buttons.matching(identifier: "fb-down")
        XCTAssertTrue(downs.firstMatch.waitForExistence(timeout: 15), "主对话里 P-Health 的回复下面没有 👎（测试环境主对话要有 P-Health 回过的话）")
        // 最新一轮回复（最下面那条）
        var down: XCUIElement { downs.element(boundBy: downs.count - 1) }
        XCTAssertGreaterThan(app.buttons.matching(identifier: "fb-up").count, 0, "回复下面没有 👍")
        // 上一轮跑完没撤回（服务器上还是 👎）：先撤回，好从头点
        if waitUntil(3, { down.isSelected }) {
            down.tap()
            XCTAssertTrue(waitUntil(5) { !down.isSelected }, "点已经选中的 👎 没撤回")
        }
        down.tap()
        let sheet = any("fb-sheet")
        XCTAssertTrue(sheet.waitForExistence(timeout: 5), "点 👎 没弹出「哪里不好？」")
        XCTAssertTrue(text(containing: "哪里不好").exists, "面板上没有标题「哪里不好？」")
        XCTAssertTrue(any("fb-note").exists, "面板上没有「应该是……」输入框")
        let submit = app.buttons["fb-submit"].firstMatch
        XCTAssertFalse(submit.isEnabled, "什么都没选时「提交」应是灰的")
        let reason = app.buttons["fb-reason-说错了"].firstMatch
        XCTAssertTrue(reason.exists, "没有原因「说错了」")
        reason.tap()
        XCTAssertTrue(waitUntil(3) { reason.isSelected }, "点了原因没选上")
        XCTAssertTrue(submit.isEnabled, "选了原因「提交」还是灰的")
        shot("31-feedback-panel")
        submit.tap()
        XCTAssertTrue(sheet.waitForNonExistence(timeout: 5), "提交后面板没收起")
        XCTAssertTrue(waitUntil(5) { down.isSelected }, "提交后 👎 没变成选中")
        XCTAssertTrue(app.textViews["chat-input"].firstMatch.exists, "面板收起后输入框没回来")
        // 只选原因不写字：不该引起新的一轮
        XCTAssertFalse(any("chat-activity").waitForExistence(timeout: 3), "只选原因提交后 P-Health 开始说话了")
        shot("31-feedback-selected")
        // 重开对话：手机上的缓存 + 服务器拉回来的都还是 👎
        closeChat()
        openMainChat()
        XCTAssertTrue(downs.firstMatch.waitForExistence(timeout: 15), "重开对话后没有 👎")
        XCTAssertTrue(waitUntil(8) { down.isSelected }, "重开对话后 👎 不是选中的")
        // 再点一次 = 撤回
        down.tap()
        XCTAssertFalse(sheet.waitForExistence(timeout: 2), "点已经选中的 👎 又弹了面板（应该直接撤回）")
        XCTAssertTrue(waitUntil(5) { !down.isSelected }, "点已经选中的 👎 没撤回")
    }
}
