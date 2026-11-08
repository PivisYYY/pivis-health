import SwiftUI

// MARK: - 根布局：四个板块 + 右下 P（主对话）+ 对话抽屉 + 跟做页
struct V3Board: Identifiable, Hashable {
    let id: String      // now / sleep / sport / stress
    let label: String
    let context: String // 对话上下文（板块 Session）
}

let V3_BOARDS: [V3Board] = [
    V3Board(id: "now", label: "此刻", context: ""),
    V3Board(id: "sleep", label: "休息", context: "休息"),
    V3Board(id: "sport", label: "运动", context: "运动"),
    V3Board(id: "stress", label: "压力", context: "压力"),
]

struct V3Root: View {
    @State private var selected = V3Root.initialBoard()
    @State private var chatTarget: ChatTarget? = V3Root.initialChat()
    @State private var execTodo: V3Todo?
    @State private var splash: Truth? = V3Root.initialSplash()
    /// 键盘弹起时把底栏和底部遮罩藏起来：ignoresSafeArea(.keyboard) 在 iOS 26 上留不住，底栏会浮到键盘上面盖住卡片按钮
    @State private var keyboardUp = false
    @ObservedObject private var sync = PageSync.shared
    @Namespace private var tabNS
    @Environment(\.scenePhase) private var scenePhase

    /// 开屏：冷启动时显示一条健康观。测试启动（-uiTestDisableDeviceData）默认不显示，加 -showSplash 才显示；-noSplash 关掉
    private static func initialSplash() -> Truth? {
        let a = ProcessInfo.processInfo.arguments
        if a.contains("-noSplash") || a.contains("-canvasGallery") || a.contains("-openChat") { return nil }
        if a.contains("-uiTestDisableDeviceData") && !a.contains("-showSplash") { return nil }
        return TruthStore.forLaunch()
    }

    private static func initialBoard() -> String {
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "-initialPage"), i + 1 < args.count {
            let v = args[i + 1]
            if let n = Int(v), (0..<V3_BOARDS.count).contains(n) { return V3_BOARDS[n].id }
            if V3_BOARDS.contains(where: { $0.id == v }) { return v }
        }
        return "now"
    }

    private static func initialChat() -> ChatTarget? {
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-openChat"), i + 1 < args.count else { return nil }
        let ctx = args[i + 1] == "main" ? "" : args[i + 1]
        var pending: String? = nil
        if let j = args.firstIndex(of: "-chatSend"), j + 1 < args.count { pending = args[j + 1] }   // 测试：首条消息走正常发送链路
        // 测试（仅模拟器回放）：-chatPhoto <图片路径> [-chatPhotoTodo <待办id> <标题> <字段id>]，走和拍照完全一样的发送链路
        var photo: PendingPhoto? = nil
        if Profile.isSim, let j = args.firstIndex(of: "-chatPhoto"), j + 1 < args.count, let img = UIImage(contentsOfFile: args[j + 1]) {
            photo = PendingPhoto(image: img)
            if let k = args.firstIndex(of: "-chatPhotoTodo"), k + 3 < args.count {
                photo = PendingPhoto(image: img, todoId: args[k + 1], todoTitle: args[k + 2], fieldId: args[k + 3])
            }
        }
        return ChatTarget(context: ctx, pendingText: pending, photo: photo)
    }

    /// 验收用画廊（仅模拟器回放）
    private static let gallery: (String, Int)? = {
        let a = ProcessInfo.processInfo.arguments
        guard Profile.isSim, let i = a.firstIndex(of: "-canvasGallery"), i + 1 < a.count else { return nil }
        let n = a.firstIndex(of: "-galleryIndex").flatMap { $0 + 1 < a.count ? Int(a[$0 + 1]) : nil } ?? 0
        return (a[i + 1], n)
    }()

    var body: some View {
        if let g = Self.gallery {
            CanvasGallery(path: g.0, index: g.1).preferredColorScheme(.dark)
        } else {
            ZStack {
                root
                if let t = splash {
                    SplashView(truth: t) { splash = nil }      // 开屏自己做完离场动效（往上推走）再移除
                        .zIndex(10)
                }
            }
            .task { await TruthStore.prefetch() }    // 预取下一次开屏的那条
        }
    }

    private var root: some View {
        ZStack(alignment: .bottom) {
            E.bg.ignoresSafeArea()
            ForEach(V3_BOARDS) { b in
                BoardPageView(board: b, visible: selected == b.id)
                    // 四页叠在一起只是透明度切换：看不见的页和 App 不在前台时，循环动效全停（不然四页一起每帧重画）
                    .environment(\.motionPaused, selected != b.id || scenePhase != .active)
                    .opacity(selected == b.id ? 1 : 0)
                    .allowsHitTesting(selected == b.id)
                    .accessibilityHidden(selected != b.id)
            }
            // 状态栏下的黑条 + 底栏后的渐隐，滚动内容不和系统栏、底栏叠在一起
            GeometryReader { geo in
                VStack(spacing: 0) {
                    Color.black.frame(height: geo.safeAreaInsets.top)
                    LinearGradient(colors: [.black, .black.opacity(0)], startPoint: .top, endPoint: .bottom).frame(height: 18)
                    Spacer()
                }
                .ignoresSafeArea(edges: .top)
            }
            .allowsHitTesting(false)
            VStack(spacing: 0) {
                Spacer()
                LinearGradient(colors: [.black.opacity(0), .black], startPoint: .top, endPoint: .bottom).frame(height: 36)
                Color.black.frame(height: 106)      // 盖到底栏那条细线上面一点，页面内容不和细线叠在一起
            }
            .ignoresSafeArea(edges: .bottom)
            .ignoresSafeArea(.keyboard)          // 键盘弹起时留在键盘下面，不跟着升上来
            .allowsHitTesting(false)
            .opacity(keyboardUp ? 0 : 1)
            // 底栏：打字时藏起来（以前会浮到键盘上面，底栏和中间的圆钮盖住卡片上的「晚点 / 记好了」）
            tabBar
                .ignoresSafeArea(.keyboard)
                .opacity(keyboardUp ? 0 : 1)
                .allowsHitTesting(!keyboardUp)
                .accessibilityHidden(keyboardUp)
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in
            withAnimation(.easeOut(duration: 0.15)) { keyboardUp = true }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            withAnimation(.easeOut(duration: 0.2)) { keyboardUp = false }
        }
        .preferredColorScheme(.dark)
        .sheet(item: $chatTarget, onDismiss: {
            NotificationCenter.default.post(name: .pivisPagesDirty, object: nil)
            PageSync.shared.poke()
        }) { target in
            NativeChatView(context: target.context, pendingText: target.pendingText, draft: target.draft,
                           pendingPhoto: target.photo, about: target.about)
                .presentationDetents([.fraction(0.9), .large])
                .presentationDragIndicator(.visible)
                .presentationBackground(Color.black)
                .preferredColorScheme(.dark)
        }
        .fullScreenCover(item: $execTodo, onDismiss: {
            NotificationCenter.default.post(name: .pivisPagesDirty, object: nil)
            PageSync.shared.poke()
        }) { todo in
            ExecView(todo: todo)
        }
        .onReceive(NotificationCenter.default.publisher(for: .pivisOpenChat)) { note in
            let info = note.userInfo ?? [:]
            chatTarget = ChatTarget(context: info["context"] as? String ?? "",
                                    pendingText: info["pending"] as? String,
                                    draft: info["draft"] as? String,
                                    photo: info["photo"] as? PendingPhoto,
                                    about: (info["about"] as? MemoBox<ChatAbout>)?.value)
        }
        .onReceive(NotificationCenter.default.publisher(for: .pivisStartTodo)) { note in
            if let t = note.object as? V3Todo { execTodo = t }
        }
        .onReceive(NotificationCenter.default.publisher(for: .pivisPushTapped)) { note in
            let info = note.userInfo ?? [:]
            if let page = info["page"] as? String {
                selected = ["today": "now", "now": "now", "sleep": "sleep", "sport": "sport", "stress": "stress"][page] ?? "now"
            }
            if let ctx = info["context"] as? String {
                // P-Health 回了新消息：点开直接进那个对话
                splash = nil
                chatTarget = ChatTarget(context: ctx, pendingText: nil)
            } else if let todoId = info["todo"] as? String {
                splash = nil
                Task {
                    // 练习的到点提醒：点开直接全屏播；别的卡：切到那一页并展开它
                    if let t = try? await V3API.todo(todoId), t.practiceVideo != nil {
                        await MainActor.run { execTodo = t }
                    } else {
                        try? await Task.sleep(for: .milliseconds(400))
                        await MainActor.run { NotificationCenter.default.post(name: .pivisExpandTodo, object: todoId) }
                    }
                }
            } else if let pending = info["pending"] as? String {
                // 推送里带的问句只放进输入框当草稿，老大自己决定发不发（不替他发，P-Health 也不抢先说话）
                chatTarget = ChatTarget(context: V3_BOARDS.first { $0.id == selected }?.context ?? "", pendingText: nil,
                                        draft: pending)
            }
        }
        .task {
            Reminders.shared.requestAuthorization()
            PageSync.shared.start()
            WidgetBridge.clearWidgetDoneReminders()
            WidgetBridge.refresh()
            AppUpdater.shared.check()
        }
        .onChange(of: scenePhase) { _, phase in
            // 回到前台：页面可能早就变了（P-Health 后台改过、设备数据进来了），立刻对一次
            // 只有真的进后台才停；系统弹窗、控制中心、多任务界面时是 inactive，页面还在眼前，照常同步
            PageSync.shared.setActive(phase != .background)
            if phase == .active {
                WidgetBridge.clearWidgetDoneReminders()     // 小组件上打过勾的：撤掉还没响的本地提醒
                NotificationCenter.default.post(name: .pivisPagesDirty, object: nil)
                AppUpdater.shared.check()
            }
            if phase == .background { WidgetBridge.refresh(after: 0) }
        }
        // 有新版本：系统提示，点「现在更新」直接无线安装
        .alert("P-Health 有新版本", isPresented: Binding(get: { AppUpdater.shared.available != nil },
                                                      set: { if !$0 && AppUpdater.shared.available != nil { AppUpdater.shared.snooze() } })) {
            Button("现在更新") { AppUpdater.shared.install() }
            Button("稍后", role: .cancel) { AppUpdater.shared.snooze() }
        } message: {
            Text("build \(AppUpdater.shared.available ?? 0) 已经发布（你现在是 \(AppUpdater.shared.current)）。点「现在更新」后在系统弹窗里选「安装」，装好自动替换。")
        }
        // 页面或待办变了：小组件也跟着换
        .onReceive(NotificationCenter.default.publisher(for: .pivisPagesDirty)) { _ in WidgetBridge.refresh() }
        .onReceive(NotificationCenter.default.publisher(for: .pivisTodosChanged)) { _ in WidgetBridge.refresh() }
        // 从小组件点进来：phealth://page/sleep 切到那一页；phealth://todo/<id>?board=sleep 切过去并展开那张卡
        .onOpenURL { url in
            guard url.scheme == "phealth" else { return }
            splash = nil      // 从小组件点进来：要直接看到那一页 / 那张卡，不放开屏
            let parts = url.pathComponents.filter { $0 != "/" }
            let q = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            switch url.host {
            case "page":
                if let p = parts.first, V3_BOARDS.contains(where: { $0.id == p }) { selected = p }
            case "todo":
                if let b = q.first(where: { $0.name == "board" })?.value, V3_BOARDS.contains(where: { $0.id == b }) { selected = b }
                // 练习（小组件上点 ▶ / 那一行）：直接全屏播视频
                if let id = parts.first, q.first(where: { $0.name == "play" })?.value == "1" {
                    Task {
                        if let t = try? await V3API.todo(id), t.practiceVideo != nil {
                            await MainActor.run { execTodo = t }
                        } else {
                            await MainActor.run { NotificationCenter.default.post(name: .pivisExpandTodo, object: id) }
                        }
                    }
                } else if let id = parts.first {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                        NotificationCenter.default.post(name: .pivisExpandTodo, object: id)
                    }
                }
            case "chat":
                chatTarget = ChatTarget(context: "", pendingText: nil)
            default: break
            }
        }
    }

    private var tabBar: some View {
        // 方案 3：底部一条细线贯穿；此刻、休息在左，运动、压力在右；当前页文字变白、下面一个小点（滑过去）；
        // 正中间浮起一个细线圆圈里的莫比乌斯，点它进主对话；P-Health 在处理时环上有白点在走
        ZStack(alignment: .top) {
            Rectangle().fill(E.line).frame(height: 1)
            HStack(spacing: 0) {
                tabItem(V3_BOARDS[0])
                tabItem(V3_BOARDS[1])
                Color.clear.frame(width: 80)
                tabItem(V3_BOARDS[2])
                tabItem(V3_BOARDS[3])
            }
            .padding(.top, 14)
            Button {
                chatTarget = ChatTarget(context: "", pendingText: nil)
            } label: {
                // 59pt、高出细线 23pt：介于最早的 64pt / 半个圆浮在上面 和 54pt / 只高出 14pt 之间
                MobiusMark(lineWidth: 1.05, active: sync.agentBusy)
                    .frame(width: 40)
                    .frame(width: 59, height: 59)
                    .background(Circle().fill(Color.black))
                    .overlay(Circle().strokeBorder(E.text, lineWidth: 1))
                    .overlay(alignment: .topTrailing) {
                        // P-Health 在主对话回了你还没看：右上角一个实心小白点（外面一圈黑，和描边分开）
                        if sync.unread.contains("") {
                            Circle().fill(E.text).frame(width: 9, height: 9)
                                .background(Circle().fill(Color.black).frame(width: 14, height: 14))
                                .offset(x: -4, y: 4)
                                .transition(.opacity)
                                .accessibilityIdentifier("main-chat-unread")
                        }
                    }
                    .contentShape(Circle())
            }
            .buttonStyle(EPress())
            .offset(y: -23)
            .accessibilityLabel(sync.unread.contains("") ? "打开 P-Health 主对话，有新回复" : "打开 P-Health 主对话")
            .accessibilityIdentifier("open-main-chat")
        }
        .frame(height: 64, alignment: .top)
        .padding(.horizontal, 8)
    }

    private func tabItem(_ b: V3Board) -> some View {
        Button {
            withAnimation(.easeOut(duration: 0.25)) { selected = b.id }
        } label: {
            VStack(spacing: 6) {
                Text(b.label)
                    .font(E.body(15))
                    .foregroundStyle(selected == b.id ? E.text : E.text3)
                    .overlay(alignment: .topTrailing) {
                        // 这个板块的对话里 P-Health 回了你还没看（此刻页的对话是中间那个按钮）
                        if b.id != "now", sync.unread.contains(b.context) {
                            Circle().fill(E.text).frame(width: 5, height: 5).offset(x: 7, y: -1)
                                .transition(.opacity)
                                .accessibilityIdentifier("tab-unread-\(b.id)")
                        }
                    }
                ZStack {
                    if selected == b.id {
                        Circle().fill(E.text).frame(width: 4, height: 4)
                            .matchedGeometryEffect(id: "tab-dot", in: tabNS)
                    }
                }
                .frame(width: 4, height: 4)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(EPress())
        .accessibilityLabel(b.id != "now" && sync.unread.contains(b.context) ? "\(b.label)，对话有新回复" : b.label)
        .accessibilityAddTraits(selected == b.id ? .isSelected : [])
        .accessibilityIdentifier("tab-\(b.id)")
    }
}

/// 打开对话（任何地方都能调）
func openChat(context: String, pending: String? = nil, draft: String? = nil, photo: PendingPhoto? = nil,
              about: ChatAbout? = nil) {
    var info: [String: Any] = ["context": context]
    if let pending { info["pending"] = pending }
    if let draft { info["draft"] = draft }
    if let photo { info["photo"] = photo }
    if let about { info["about"] = MemoBox(about) }
    NotificationCenter.default.post(name: .pivisOpenChat, object: nil, userInfo: info)
}
