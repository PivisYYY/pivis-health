import XCTest

@MainActor
final class FollowProgressUITests: XCTestCase {
    private var app: XCUIApplication!

    private func state(_ name: String) throws {
        let url = URL(string: "http://127.0.0.1:18959/test/\(name)")!
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        let done = expectation(description: name)
        var code = 0
        URLSession.shared.dataTask(with: req) { _, response, _ in
            code = (response as? HTTPURLResponse)?.statusCode ?? 0
            done.fulfill()
        }.resume()
        wait(for: [done], timeout: 5)
        XCTAssertEqual(code, 200)
    }

    override func setUpWithError() throws {
        continueAfterFailure = false
        try state("online")
        try state("voice")
        app = XCUIApplication()
        app.launchArguments = ["-pivisProfile", "sim", "-uiTestDisableDeviceData", "-progressReview",
                               "-pivisBase", "http://127.0.0.1:18959"]
        app.launch()
    }

    override func tearDownWithError() throws { app?.terminate() }

    func testTextStagesLiveProgressAndReopen() throws {
        XCTAssertTrue(app.staticTexts["查看视频生成进度"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["正在制作报数和教练配音"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["阶段进度 62%"].exists)
        try state("render")
        XCTAssertTrue(app.staticTexts["正在合成跟练视频"].waitForExistence(timeout: 12))
        app.buttons["收起进度"].tap()
        try state("done")
        app.buttons["查看生成进度"].tap()
        XCTAssertTrue(app.staticTexts["视频已生成，验收通过"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["阶段进度 100%"].exists)
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "progress-complete"; shot.lifetime = .keepAlways; add(shot)
    }

    func testRejectionAndBackgroundResume() throws {
        XCTAssertTrue(app.staticTexts["阶段进度 62%"].waitForExistence(timeout: 10))
        XCUIDevice.shared.press(.home)
        try state("rejected")
        app.activate()
        XCTAssertTrue(app.staticTexts["验收未通过"].waitForExistence(timeout: 12))
        XCTAssertFalse(app.staticTexts["阶段进度 100%"].exists)
    }

    func testNetworkRecoveryAndGenerationFailure() throws {
        XCTAssertTrue(app.staticTexts["阶段进度 62%"].waitForExistence(timeout: 10))
        try state("offline")
        XCTAssertTrue(app.staticTexts["暂时取不到最新进度，正在重试"].waitForExistence(timeout: 15))
        try state("failed")
        try state("online")
        XCTAssertTrue(app.staticTexts["视频生成中断"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.staticTexts["阶段进度 100%"].exists)
    }
}
