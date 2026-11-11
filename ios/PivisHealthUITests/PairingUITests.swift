import XCTest

/// build 55：引导页、配对链接、演示模式。不连任何服务器（不依赖封版测试环境）：
/// -forceUnpaired 当作没配对；配对链接指向 127.0.0.1:1，一定连不上；演示页来自包里的 Demo/*.json。
@MainActor
final class PairingUITests: XCTestCase {
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

    private func launch(_ extra: [String]) {
        app = XCUIApplication()
        app.launchArguments = ["-pivisProfile", "sim", "-uiTestDisableDeviceData", "-noSplash", "-forceUnpaired"] + extra
        app.launch()
    }

    private func any(_ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    /// 没配对 → 引导页；从外面打开一条配对链接 → 「连接到 X？」→ 连不上时说清楚、什么都不存，取消后还在引导页
    func testOnboardingAndUnreachablePairLink() {
        launch(["-pairURL", "phealth://pair?v=1&n=UITest%20Mac&h=127.0.0.1&p=1&d=1&k=x"])
        XCTAssertTrue(any("onboarding").waitForExistence(timeout: 10), "没配对时没有引导页")
        XCTAssertTrue(app.buttons["onboard-scan"].exists, "引导页没有「扫码配对」")
        XCTAssertTrue(app.buttons["onboard-paste"].exists, "引导页没有「粘贴链接」")
        XCTAssertFalse(app.buttons["tab-now"].exists, "没配对却出了主界面")

        let title = any("pair-title")
        XCTAssertTrue(title.waitForExistence(timeout: 8), "打开配对链接后没有确认弹层")
        XCTAssertEqual(title.label, "连接到 UITest Mac？")
        app.buttons["pair-connect"].tap()
        XCTAssertTrue(any("pair-error").waitForExistence(timeout: 10), "连不上时没有说明")
        app.buttons["pair-cancel"].tap()
        XCTAssertTrue(any("onboarding").waitForExistence(timeout: 5), "取消后不在引导页")
        XCTAssertFalse(app.buttons["tab-now"].exists, "连不上却存下了配对")
    }

    /// 粘贴一段不是配对链接的字：说「这不是配对链接」，不弹确认
    func testPasteRejectsNonPairText() {
        launch([])
        XCTAssertTrue(app.buttons["onboard-paste"].waitForExistence(timeout: 10))
        app.buttons["onboard-paste"].tap()
        let field = any("pair-paste-field")
        XCTAssertTrue(field.waitForExistence(timeout: 5), "没有粘贴框")
        field.tap()
        field.typeText("https://example.com")
        app.buttons["pair-paste-connect"].tap()
        let err = any("pair-paste-error")
        XCTAssertTrue(err.waitForExistence(timeout: 3))
        XCTAssertTrue(err.label.contains("不是"), "粘贴了别的链接却没有提示（\(err.label)）")
        XCTAssertFalse(any("pair-title").exists, "不是配对链接却弹了确认")
    }

    /// 演示：页面能翻、待办能点（只在手机上）、对话说要先配对；点「演示」回到引导页
    func testDemoMode() throws {
        launch(["-demoMode"])
        let badge = app.buttons["demo-badge"]
        XCTAssertTrue(badge.waitForExistence(timeout: 10), "演示里没有回到引导页的标记")
        let title = app.staticTexts["page-title"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 10), "演示里没有页面")
        let failed = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "暂时连不上")).firstMatch
        if failed.waitForExistence(timeout: 3) { throw XCTSkip("包里还没有演示样例（PivisHealth/Demo/*.json）") }
        let hero = app.descendants(matching: .any).matching(NSPredicate(format: "identifier IN %@", ["hero", "hero-updating"])).firstMatch
        XCTAssertTrue(hero.waitForExistence(timeout: 10), "演示的此刻页没有主卡")

        for (id, name) in [("tab-sleep", "休息"), ("tab-sport", "运动"), ("tab-stress", "压力"), ("tab-now", "此刻")] {
            app.buttons[id].firstMatch.tap()
            let ok = expectation(for: NSPredicate(format: "label == %@", name), evaluatedWith: title)
            wait(for: [ok], timeout: 5)
            XCTAssertFalse(failed.exists, "演示的\(name)页显示连不上")
        }

        app.buttons["open-main-chat"].firstMatch.tap()
        XCTAssertTrue(any("demo-chat-note").waitForExistence(timeout: 8), "演示的对话没有说要先配对")
        XCTAssertFalse(app.buttons["chat-send"].exists, "演示的对话还能发消息")
        app.buttons["收起"].firstMatch.tap()

        XCTAssertTrue(badge.waitForExistence(timeout: 5))
        badge.tap()
        XCTAssertTrue(any("onboarding").waitForExistence(timeout: 8), "点「演示」没回到引导页")
    }
}
