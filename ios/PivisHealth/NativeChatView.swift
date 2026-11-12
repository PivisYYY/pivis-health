import SwiftUI
import Charts
import AVKit
import WebKit

/// 原生 P-Health 聊天（抽屉 + 生成式 UI + DSH 实时逐句回复 + 增量轮询兜底）
struct NativeChatView: View {
    let context: String
    let pendingText: String?      // 打开抽屉后自动发送（如「换一个：…」）
    @State private var messages: [ChatMsg] = []
    @State private var input = ""
    @State private var focusInput = false
    @State private var inputHeight: CGFloat = 38
    @State private var inputClearSignal = 0   // 发出去后要求输入框彻底清空（包括还在组字的拼音）
    @State private var sending = false      // 发送请求进行中
    @State private var awaitingReply = false // 等 Bot 回复（显示输入中）
    @State private var latestTime: String? = nil
    @State private var seenKeys: Set<String> = []
    @State private var idleTimer: Timer?
    @State private var fastPoll: Task<Void, Never>?
    @State private var toolHint: String? = nil
    @State private var streamClient: DshStreamClient?
    @State private var streamAttempt: String?
    @State private var lastStreamAttempt: String?
    @State private var streamBuffer = ""
    @State private var streamVersion = 0
    @State private var pendingStreamFinal: ChatMsg?
    /// 流式气泡被最终消息替换后，行仍用气泡的 id：视图不重建，没流完的字接着流
    @State private var rowAlias: [String: String] = [:]
    @State private var activities: [ActivityRowItem] = []
    @State private var eventClient: DshEventClient?
    @State private var interactions: [InteractionRequest] = []
    @State private var lastEmitFetch: Date = .distantPast
    @State private var scrollReset = 0
    @State private var atBottom = true      // 用户停在底部附近：内容一变就跟到底；往上翻看时不打扰
    @State private var revealed = false     // 打开时先在后台排好、停在最新一条，再一次性淡入（不让人看到一条条蹦、来回跳）
    @State private var pinnedKey: String?   // 刚发出的那条：顶到屏幕上方，回复在它下面往下流，屏幕不再跟着滚
    @State private var pinRequest = 0
    @State private var pinnedY: CGFloat = 0
    @State private var tailY: CGFloat = 0
    @State private var viewportH: CGFloat = 0
    @State private var userScrolling = false   // 老大正在拖动 / 惯性滑动：这时不替他滚
    @State private var settleGen = 0           // 打开时等排版稳定再淡入
    @State private var flushPending = false    // 流式字合并成小批再上屏，不是每个字都重排整个列表
    @State private var showCapture = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var wasInBackground = false
    /// 被全屏页盖住过（练习视频、看大图、拍照用的 fullScreenCover 会让这页 onDisappear）：回来时按回到前台的流程重连
    @State private var wasCovered = false
    @State private var launchConsumed = false    // 待发送 / 草稿 / 照片：每次打开对话只用一次
    @State private var lastStreamEvent = Date()  // 实时流最后一次有动静的时间（看门狗用）
    /// 带进来的习惯 / 待办：对话里的一张卡（放在这次对话开始的位置，打开时顶在屏幕上方，跟着对话滚走；
    /// 划出屏幕后顶上出一行，点了滚回来），输入框上方「关于：X」（点 × 这条起不带）
    let about: ChatAbout?
    @State private var aboutActive: ChatAbout?
    @State private var aboutExpanded = true
    /// 卡在屏幕上；划走了顶上出那一行
    @State private var aboutOnScreen = true
    /// 卡在屏幕上方（那一行的箭头朝上）
    @State private var aboutAbove = true
    @State private var aboutY: CGFloat = 0
    /// 这次对话开始时已经有的行：卡排在它们后面，之后的新消息在卡下面（nil = 还没定，卡先排在最后）
    @State private var aboutBefore: Set<String>?
    @State private var aboutScroll = 0
    /// 打开后、老大还没滑动也没发话：排版怎么变，卡都顶在上方
    @State private var holdAboutTop = false
    private static let aboutRowId = "about-card"
    /// 顶上那一行占的高度：上下各 8 + 胶囊 48
    private static let aboutBand: CGFloat = 64
    @State private var habitDoc: V3HabitDoc?
    /// 顶部习惯卡 / 待办卡里的视频：播放器由对话页拿着，卡收成一行时正在放的不断。
    /// 用 @State 只是拿着、不观察：播放进度每半秒一变，不能让整个对话页跟着重算
    @State private var aboutPlayer = PracticePlayer()
    /// 点洞察推送进来：打开后直接点开这条（不经过浮条）
    let openInsight: String?
    /// 洞察 open / 点踩带的那句话 还在路上（服务器发进对话后才回）：轮询别把「正在思考」清掉
    @State private var promptInFlight = false
    /// 点了 👎 的那条：底部换成「哪里不好？」面板
    @State private var feedbackFor: ChatMsg?
    /// 这个对话页的标记（ChatPresence.insightHost 记的是它：新开的对话页先出现、旧的后消失也不会互相清掉）
    @State private var presenceToken = UUID()
    /// 洞察点开时最后一条消息：等回复时它的头像不跟着动（那是上一轮的话，新回复还没来）
    @State private var turnFloorKey: String?

    /// 洞察浮条只在主对话里出现：板块对话、带着习惯 / 待办进来的对话都没有
    private var hostsInsight: Bool { context.isEmpty && about == nil }

    // MARK: - 消息本地缓存（退出抽屉再进，消息不消失：先上屏缓存，再与服务器合并去重）
    private struct CachedMsg: Codable { let role: String; let text: String; let time: String; let stableId: String?; var about: String? = nil }

    private var cacheFile: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("chat_cache/\(Profile.isSim ? "sim-" : "")\(context.isEmpty ? "main" : context).json")
    }

    /// 缓存属于哪个服务器会话。服务器换了会话（比如从头聊），旧缓存不再上屏。
    private var sessionKey: String { "chat_session_\(Profile.isSim ? "sim-" : "")\(context.isEmpty ? "main" : context)" }

    private func loadCache() {
        guard !ServerConfig.isDemo else { return }        // 演示：不碰真对话的缓存
        guard UserDefaults.standard.string(forKey: sessionKey) != nil else { DshAPI.dbg("loadCache: no known session"); return }
        guard let data = try? Data(contentsOf: cacheFile) else { DshAPI.dbg("loadCache: no file"); return }
        guard let arr = try? JSONDecoder().decode([CachedMsg].self, from: data) else { DshAPI.dbg("loadCache: decode failed"); return }
        // 上次没合并掉的流式气泡不再上屏：服务器那边会补上完整的那条；DSH 重启后流的编号从头数，旧气泡会和新回复撞号
        for m in arr where !(m.stableId ?? "").hasPrefix("stream-") {
            appendMessage(ChatMsg(role: m.role, text: m.text, time: m.time, stableId: m.stableId, about: m.about))
        }
        DshAPI.dbg("loadCache: loaded=\(arr.count) messages=\(self.messages.count)")
    }

    private func saveCache() {
        guard !ServerConfig.isDemo else { return }        // 演示：空的对话不能把真缓存盖掉
        let arr = messages.filter { !($0.stableId ?? "").hasPrefix("pending-photo-") }   // 还没传完的照片不进缓存
            .map { CachedMsg(role: $0.role, text: $0.text, time: $0.time, stableId: $0.stableId, about: $0.about) }
        guard let data = try? JSONEncoder().encode(arr) else { return }
        try? FileManager.default.createDirectory(at: cacheFile.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        try? data.write(to: cacheFile, options: .atomic)
    }

    let draft: String?
    let pendingPhoto: PendingPhoto?

    init(context: String = "", pendingText: String? = nil, draft: String? = nil, pendingPhoto: PendingPhoto? = nil,
         about: ChatAbout? = nil, openInsight: String? = nil) {
        self.context = context
        self.pendingText = pendingText
        self.draft = draft
        self.pendingPhoto = pendingPhoto
        self.about = about
        self.openInsight = openInsight
        _aboutActive = State(initialValue: about)
        // 带着卡进来：卡顶在屏幕上方（和刚发出的消息一样「钉住」，下面留白），以前的聊天在它上面
        if about != nil {
            _pinnedKey = State(initialValue: Self.aboutRowId)
            _holdAboutTop = State(initialValue: true)
        }
    }

    /// 卡的图标在习惯取回来之前按对话所在的板块画
    private var aboutBoard: String { ["休息": "sleep", "运动": "sport", "压力": "stress"][context] ?? "" }

    /// 卡排在第几行后面：这次对话开始时已有的行在上面，之后来的在下面
    private func aboutSplit(_ all: [ChatRowItem]) -> Int {
        guard about != nil, let before = aboutBefore else { return all.count }
        return all.firstIndex { !before.contains($0.id) } ?? all.count
    }

    /// 定下卡的位置（打开后第一次拉完消息、或者在那之前就发了话）
    private func freezeAboutPosition() {
        guard about != nil, aboutBefore == nil else { return }
        aboutBefore = Set(rows.map(\.id))
    }

    var body: some View {
        GeometryReader { geo in
            // P-Health 那一栏（字、卡）从头像右边到右边线；我的气泡也不超过这么宽
            let column = max(120, geo.size.width - 2 * E.chatGutter - E.chatTextInset)
            let answers = answerMap()
            let liveKey = streamAttempt.map { "stream-\($0)" }
            let all = rows
            let split = aboutSplit(all)
            NavigationStack {
                ScrollViewReader { proxy in
                    ScrollView {
                        // 消息最多保留 120 条，用普通 VStack：高度都是真实测量的，拖动抽屉改变尺寸时不会因估算高度跳屏
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(all[..<split]) { row in chatRow(row, column: column, answers: answers, liveKey: liveKey) }
                            if let about { aboutCard(about) }
                            ForEach(all[split...]) { row in chatRow(row, column: column, answers: answers, liveKey: liveKey) }
                            ForEach(interactions) { req in
                                InteractionCardView(request: req) { value in
                                    answerInteraction(req, value: value)
                                }
                                .id("interaction-\(req.eventId)")
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.leading, E.chatTextInset)
                            }
                            // 当前阶段用一句短文字说明，配细线图标。
                            if awaitingReply {
                                TypingRow(tool: toolHint, responding: streamAttempt != nil)
                                    .id("typing")
                            }
                            // 底下留白：刚发的那条能顶到屏幕上方；回复长到填满屏幕后留白自动变成 0
                            Color.clear
                                .frame(height: tailSpace)
                                .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named("chatContent")).minY } action: { y in
                                    if abs(y - tailY) > 0.5 { tailY = y }
                                }
                                .id("bottom")
                        }
                        .coordinateSpace(.named("chatContent"))
                        .padding(.horizontal, E.chatGutter)
                        .padding(.top, 12)
                        .padding(.bottom, 24)
                    }
                    // 只管「打开时落在最底下」。不带 role 的 defaultScrollAnchor(.bottom) 还会在内容变高时贴住底部，
                    // 回复一长过屏幕就把屏幕往下拽（抢屏幕）
                    .defaultScrollAnchor(.bottom, for: .initialOffset)
                    .scrollDismissesKeyboard(.interactively)
                    // 带着卡的对话：顶上留出那一行的位置（一直留，不随那一行出现 / 消失变）。
                    // 刚发的消息、滚回的卡都停在它下面，不会被那一行盖住
                    .contentMargins(.top, about != nil ? Self.aboutBand : 0, for: .scrollContent)
                    .opacity(revealed ? 1 : 0)
                    .overlay { if !revealed && messages.isEmpty { WorkingLine().frame(width: 90) } }
                    // 卡划出屏幕：顶上一行（和收起的卡一个样子），点了滚回卡。浮在留出的那一条上、不挤动排版；
                    // 底下一层黑 + 一小段渐隐，滚过去的字不会从它两边露出来。卡在屏幕上时那一条只是渐隐，上面的旧消息淡出去
                    .overlay(alignment: .top) {
                        if about != nil, revealed, aboutOnScreen {
                            LinearGradient(colors: [.black, .black.opacity(0)], startPoint: .top, endPoint: .bottom)
                                .frame(height: Self.aboutBand)
                                .allowsHitTesting(false)
                                .transition(.opacity)
                        }
                    }
                    .overlay(alignment: .top) {
                        if let about, revealed, !aboutOnScreen {
                            VStack(spacing: 0) {
                                ChatAboutCapsule(about: about, habit: habitDoc, board: aboutBoard, working: awaitingReply,
                                                 cardAbove: aboutAbove, player: aboutPlayer) {
                                    withAnimation(.easeOut(duration: 0.25)) { aboutExpanded = true }
                                    aboutScroll += 1
                                }
                                .padding(.horizontal, E.chatGutter)
                                .padding(.vertical, 8)
                                .background(Color.black)
                                LinearGradient(colors: [.black, .black.opacity(0)], startPoint: .top, endPoint: .bottom)
                                    .frame(height: 16)
                                    .allowsHitTesting(false)
                            }
                            .transition(.opacity)
                        }
                    }
                    // 「哪里不好？」开着：对话变暗（还看得见被评的那条），点暗处 = 不评了
                    .overlay {
                        if feedbackFor != nil {
                            Color.black.opacity(0.45)
                                .contentShape(Rectangle())
                                .onTapGesture { closeFeedback() }
                                .transition(.opacity)
                                .accessibilityHidden(true)
                        }
                    }
                    .background(Color.black)
                    // 高度一变（卡片后加载完、新消息、键盘、抽屉）就在这一帧里处理，不再延迟 0.05 秒再滚（那样会一顿一顿）：
                    // 停在底部且不是刚发完消息的这一轮 → 立刻贴住底部；正在往上翻、正在拖动、刚发完消息 → 不动
                    .onScrollGeometryChange(for: ChatGeo.self) { g in
                        ChatGeo(contentH: g.contentSize.height, visibleMinY: g.visibleRect.minY, visibleMaxY: g.visibleRect.maxY,
                                containerH: g.containerSize.height)
                    } action: { old, new in
                        let near = new.visibleMaxY >= new.contentH - 120
                        if near != atBottom { atBottom = near }
                        if abs(new.containerH - viewportH) > 0.5 { viewportH = new.containerH }
                        if about != nil {
                            // 卡不在屏幕上时要么整个在上面、要么整个在下面：拿它的顶和屏幕中线比就知道是哪边
                            let above = aboutY < (new.visibleMinY + new.visibleMaxY) / 2
                            if above != aboutAbove { aboutAbove = above }
                        }
                        let resized = abs(new.contentH - old.contentH) > 0.5 || abs(new.containerH - old.containerH) > 0.5
                        // 带着卡刚打开、老大还没动过：上面的旧消息（卡片、图）后排好、网络补来的记录插在卡上面，
                        // 每次高度一变都重新落到卡上，卡一直顶在上方（以前只落一次，旧消息长高后卡被挤到了输入框后面）。
                        // 还没淡入的话排版停了再淡入
                        if resized, holdAboutTop, pinnedKey == Self.aboutRowId, !userScrolling {
                            proxy.scrollTo(Self.aboutRowId, anchor: .top)
                            if !revealed { noteLayoutChange() }
                            return
                        }
                        guard resized, pinnedKey == nil, !userScrolling else { return }
                        if !revealed || old.visibleMaxY >= old.contentH - 80 {
                            proxy.scrollTo("bottom", anchor: .bottom)
                        }
                        if !revealed { noteLayoutChange() }
                    }
                    .onScrollPhaseChange { _, phase in
                        userScrolling = phase == .tracking || phase == .interacting || phase == .decelerating
                        // 老大自己滑了：卡不再替他顶在上方
                        if holdAboutTop, phase == .tracking || phase == .interacting { holdAboutTop = false }
                        // 回复已经长过一屏、老大自己动手滑了：不再钉住刚发的那条，之后停到底部就跟着新内容走
                        if userScrolling, pinnedKey != nil, tailSpace <= 1 { pinnedKey = nil }
                    }
                    .onChange(of: scrollReset) { _, _ in
                        atBottom = true
                        // 带着卡刚打开：落在卡上（卡比屏幕高时也是卡头在上面），不是落在最底下
                        if pinnedKey == Self.aboutRowId {
                            proxy.scrollTo(Self.aboutRowId, anchor: .top)
                        } else {
                            proxy.scrollTo("bottom", anchor: .bottom)
                        }
                    }
                    .onChange(of: pinRequest) { _, _ in
                        guard let k = pinnedKey else { return }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
                            withAnimation(.easeOut(duration: 0.35)) { proxy.scrollTo(k, anchor: .top) }
                        }
                    }
                    // 点顶上那一行：滚回卡（先展开，排好再滚）
                    .onChange(of: aboutScroll) { _, _ in
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                            withAnimation(.easeOut(duration: 0.35)) { proxy.scrollTo(Self.aboutRowId, anchor: .top) }
                        }
                    }
                }
                .navigationTitle(context.isEmpty ? "P-Health" : "P-Health · \(context)")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { dismiss() } label: {
                            Image(systemName: "xmark").font(.system(size: 13, weight: .light)).foregroundStyle(.white)
                                .frame(width: 32, height: 32).overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                        }
                        .accessibilityLabel("收起")
                    }
                }
                .safeAreaInset(edge: .bottom) {
                    VStack(spacing: 0) {
                        if let m = feedbackFor {
                            // 点了 👎：输入栏换成「哪里不好？」（每条重新开始选）
                            FeedbackPanel(onSubmit: { reasons, note in
                                closeFeedback()
                                submitFeedback(m, reasons: reasons, note: note)
                            }, onClose: closeFeedback)
                            .id(m.key)
                            .transition(.move(edge: .bottom))
                        } else {
                            // 洞察浮条：输入框正上方，左右各留 12、离输入框 12
                            if ServerConfig.isDemo {
                                // 演示：对话要连上自己的电脑；点了收起抽屉、回到引导页
                                DemoChatNote {
                                    dismiss()
                                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { ServerLink.shared.exitDemo() }
                                }
                            } else {
                                if hostsInsight { InsightBar(onOpen: startInsight) }
                                inputBar
                            }
                        }
                    }
                }
            }
        }
        .task { await bootstrap() }
        .onAppear {
            ChatPresence.openContext = context
            if hostsInsight { ChatPresence.insightHost = presenceToken }
            PageSync.shared.markSeen(context)
            if wasCovered {
                wasCovered = false
                resumeFromBackground()      // 盖住期间实时通道停了：重连，并把这段时间的回复拉回来
            }
        }
        .onDisappear {
            if ChatPresence.openContext == context { ChatPresence.openContext = nil }
            if ChatPresence.insightHost == presenceToken { ChatPresence.insightHost = nil }
            PageSync.shared.markSeen(context)
            stopAll(); saveCache()
            if !aboutPlayer.fullscreen { aboutPlayer.stop() }      // 习惯卡的视频正在全屏：不是离开对话
            wasCovered = true                                       // 真关掉了这页就不会再 onAppear，记了也无妨
        }
        // 退到后台：断开实时通道（系统也会把它掐掉，掐掉时不一定通知我们）；回到前台：重连并立刻拉最新消息
        .onChange(of: scenePhase) { old, phase in
            if phase == .background {
                streamClient?.stop(); eventClient?.stop()
                wasInBackground = true
            } else if phase == .active, wasInBackground {
                wasInBackground = false
                resumeFromBackground()
            }
        }
        .captureSheet(isPresented: $showCapture) { img in sendPhoto(PendingPhoto(image: img)) }
    }


    /// 一条消息
    private func chatRow(_ row: ChatRowItem, column: CGFloat, answers: [String: [String: String]], liveKey: String?) -> some View {
        let msg = row.msg
        return ChatRow(msg: msg, maxWidth: column,
                       avatarActive: awaitingReply && msg.key == messages.last?.key && !msg.isMe
                           && msg.key != turnFloorKey,
                       answers: msg.isMe ? nil : answers[msg.key],
                       streaming: msg.key == liveKey,
                       quiet: row.quiet,
                       rateContext: context,
                       rateable: row.rateable,
                       onAction: sendAction,
                       onDislike: openFeedback)
            // 行的输入没变就不重算（流式每批字、打字每个键都会刷新整个页面）
            .equatable()
            .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named("chatContent")).minY } action: { y in
                if row.id == pinnedKey, abs(y - pinnedY) > 0.5 { pinnedY = y }
            }
            .id(row.id)
    }

    /// 带进来的卡：对话内容里的一项，和消息贴同一组左右边
    private func aboutCard(_ about: ChatAbout) -> some View {
        ChatAboutCard(about: about, habit: habitDoc, board: aboutBoard, expanded: $aboutExpanded,
                      working: awaitingReply, player: aboutPlayer)
            .padding(.bottom, 8)
            .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named("chatContent")).minY } action: { y in
                if abs(y - aboutY) > 0.5 { aboutY = y }
                if pinnedKey == Self.aboutRowId, abs(y - pinnedY) > 0.5 { pinnedY = y }
            }
            // 卡几乎看不见了（划到上面或者往上翻到了以前的记录）：顶上出那一行
            .onScrollVisibilityChange(threshold: 0.12) { visible in
                guard visible != aboutOnScreen else { return }
                withAnimation(.easeOut(duration: 0.2)) { aboutOnScreen = visible }
            }
            .id(Self.aboutRowId)
    }

    /// 底部留白：只在刚发过消息的这一轮需要，让那条能顶到屏幕上方
    private var tailSpace: CGFloat {
        guard pinnedKey != nil else { return 1 }
        return max(1, viewportH - (tailY - pinnedY) - 36)
    }

    /// 自己发出的消息：顶到屏幕上方，回复在下面往下流
    private func pin(_ key: String) {
        pinnedKey = key
        pinRequest += 1
    }

    /// 内容排好、停在最新一条之后再淡入；之前的定位过程看不到
    private func settleAndReveal() {
        scrollReset += 1
        noteLayoutChange()
    }

    /// 还没淡入时，每次高度变化都重新计时：连续 0.2 秒不再变（卡片都画好了）才淡入
    private func noteLayoutChange() {
        guard !revealed else { return }
        settleGen += 1
        let g = settleGen
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            guard g == settleGen, !revealed else { return }
            scrollReset += 1
            withAnimation(.easeOut(duration: 0.25)) { revealed = true }
        }
    }

    // MARK: - 输入栏（UITextView 封装：中文输入法组字稳定、自动增高、return 发送）
    private var inputBar: some View {
        VStack(alignment: .leading, spacing: 10) {
        if let a = aboutActive {
            // 这条消息带着哪个习惯 / 哪张待办一起发；点 × 就不带
            HStack(spacing: 6) {
                Text("关于：\(a.name)").font(E.body(12)).foregroundStyle(E.text2).lineLimit(1)
                Button {
                    withAnimation(.easeOut(duration: 0.2)) { aboutActive = nil }
                } label: {
                    Image(systemName: "xmark").font(.system(size: 8, weight: .light)).foregroundStyle(E.text3)
                        .frame(width: 22, height: 22)
                        .hitArea(11, 11)          // 画出来 22，点的范围 44
                }
                .buttonStyle(EPress())
                .accessibilityLabel(a.kind == .habit ? "这条不带习惯" : "这条不带待办")
                .accessibilityIdentifier("chat-about-clear")
            }
            .padding(.leading, 12).padding(.trailing, 6)
            .frame(height: 28)
            .overlay(Capsule().strokeBorder(E.stroke, lineWidth: 1))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("chat-about")
        }
        HStack(alignment: .bottom, spacing: 10) {
            // 拍照：拍完直接发给 P-Health（压缩、上传都在后台，不卡界面）
            Button { showCapture = true } label: {
                Image(systemName: "camera").font(.system(size: 15, weight: .light)).foregroundStyle(E.text)
                    .frame(width: 40, height: 40)
                    .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
            }
            .buttonStyle(EPress())
            .accessibilityLabel("拍照发给 P-Health")
            .accessibilityIdentifier("chat-camera")
            ChatInputField(text: $input, height: $inputHeight, focus: $focusInput, clearSignal: inputClearSignal, onSend: submitText)
                .frame(height: inputHeight)
                .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Color.black))
                .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
                .overlay(
                    Text("和 P-Health 说…")
                        .font(E.body(15))
                        .foregroundStyle(E.hint)
                        .padding(.leading, 16)
                        .opacity(input.isEmpty ? 1 : 0)
                        .allowsHitTesting(false),
                    alignment: .leading
                )
            Button(action: send) {
                Group {
                    if sending {
                        ProgressView().tint(.black)
                    } else {
                        Image(systemName: "arrow.up").font(.system(size: 15, weight: .medium)).foregroundStyle(.black)
                    }
                }
                .frame(width: 40, height: 40)
                .background(Circle().fill(Color.white))
            }
            .buttonStyle(EPress())
            .accessibilityLabel("发送")
            .accessibilityIdentifier("chat-send")
            .disabled(input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sending)
            .opacity(input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.35 : 1)
        }
        }
        .padding(.horizontal, E.chatGutter)
        .padding(.top, 10)
        .padding(.bottom, 8)
        // 黑底一直铺到屏幕底边：列表停在中间时，内容不会从 Home 条那一窄条里露出来
        .background(Color.black.ignoresSafeArea(edges: .bottom).overlay(alignment: .top) { Hairline(color: E.line2) })
    }

    // MARK: - 初始化与轮询
    private func bootstrap() async {
        DshAPI.dbg("chat bootstrap context=[\(context)]")
        if let a = about, a.kind == .habit, habitDoc == nil {
            Task { if let h = try? await V3API.habit(a.id) { await MainActor.run { habitDoc = h } } }
        }
        // 演示：没有服务器，不拉消息、不开实时通道（带进来的习惯卡照样从样例里拿）
        if ServerConfig.isDemo {
            await MainActor.run { withAnimation(.easeOut(duration: 0.25)) { revealed = true } }
            return
        }
        // 1) 缓存先上屏：退出再进时旧消息立刻在（服务器读取可能滞后，特别是刚发完就退出）；排好、停到底再淡入
        await MainActor.run {
            loadCache()
            if !messages.isEmpty { settleAndReveal() }
            // 网络很慢也别一直空着：最多等 2 秒
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                if !revealed { scrollReset += 1; withAnimation(.easeOut(duration: 0.25)) { revealed = true } }
            }
        }
        // 2) 网络合并：服务器消息按 key 去重，时间齐全的「真身」会替换掉本地回声
        let result = await DshAPI.fetchMessages(limit: 20, session: context)
        await MainActor.run {
            if let sid = result.sessionId {
                if UserDefaults.standard.string(forKey: sessionKey) != sid {
                    messages.removeAll(); seenKeys.removeAll(); latestTime = nil   // 服务器换了会话：旧缓存作废
                    UserDefaults.standard.set(sid, forKey: sessionKey)
                }
            }
            for m in result.msgs { appendMessage(m) }
            if let latest = result.latest { latestTime = latest }
            awaitingReply = result.busy
            toolHint = result.busy ? result.lastTool : nil
            DshAPI.dbg("chat restored busy=\(result.busy) tool=\(result.lastTool ?? "nil") msgs=\(self.messages.count) last=\(self.messages.last?.text.prefix(30) ?? "nil")")
            trimMessages()
            freezeAboutPosition()    // 以前的聊天都到齐了：带进来的卡排在它们后面
            saveCache()
            if result.busy { startReplyMonitor(showPendingHint: false) }
            // 布局稳定后确保落在最新消息（缓存+网络合并后内容高度才确定）；还没显示的话这时才淡入
            settleAndReveal()
        }
        startIdlePolling()
        startLiveStream()
        // 这个对话里点过的 👍 / 👎：以服务器为准填上（手机上的缓存先已经画出来了）
        Task { await FeedbackStore.shared.refresh(context) }
        // 自动发送待发送消息（如「换一个：…」），让 Agent 接续处理。
        // 只在这次打开对话时用一次：对话被盖住再露出来时 .task 会再跑一遍，不能再把草稿填回输入框、再发一次
        let firstRun = await MainActor.run { () -> Bool in
            guard !launchConsumed else { return false }
            launchConsumed = true
            return true
        }
        guard firstRun else { return }
        if let id = openInsight {
            await MainActor.run { startInsight(id) }
        } else if let p = pendingPhoto {
            await MainActor.run { sendPhoto(p) }
        } else if let t = pendingText, !t.isEmpty {
            await MainActor.run { sendText(t) }
        } else if let d = draft, !d.isEmpty {
            await MainActor.run { input = d; focusInput = true }
        }
    }

    private func startIdlePolling() {
        stopIdlePolling()
        idleTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in
            Task { @MainActor in
                // 看门狗：流开了头却 25 秒没有任何动静（通道被系统掐断了），按结束处理，别把最终回复一直压着不显示
                if self.streamAttempt != nil, Date().timeIntervalSince(self.lastStreamEvent) > 25 {
                    DshAPI.dbg("live stream stalled: finalize")
                    self.finalizeStaleStream()
                }
            }
            Task {
                let result = await self.fetchIncremental()
                await MainActor.run {
                    if result.busy {
                        self.awaitingReply = true
                        self.toolHint = result.lastTool
                        self.startReplyMonitor(showPendingHint: false)
                    } else if self.fastPoll == nil, self.streamAttempt == nil, !self.sending, !self.promptInFlight,
                              self.interactions.isEmpty {
                        // 服务器说这一轮已经结束：清掉还挂着的「正在…」（以前只会打开、不会关，退到后台再回来会一直挂着）
                        self.awaitingReply = false
                        self.toolHint = nil
                    }
                }
            }
        }
    }

    private func stopIdlePolling() {
        idleTimer?.invalidate(); idleTimer = nil
    }

    private func stopAll() {
        stopIdlePolling()
        fastPoll?.cancel(); fastPoll = nil
        streamClient?.stop(); streamClient = nil
        eventClient?.stop(); eventClient = nil
    }

    /// 聊天只保留最近 N 条在渲染树里：控制无障碍树体积与布局开销（更老的仍在服务端，可后续做分页）
    private static let maxRenderedMessages = 120

    private func trimMessages() {
        if messages.count > Self.maxRenderedMessages {
            messages.removeFirst(messages.count - Self.maxRenderedMessages)
        }
    }

    /// 增量拉取新消息（空闲轮询与快轮询共用）
    @discardableResult
    private func fetchIncremental() async -> (busy: Bool, lastTool: String?) {
        let after = await MainActor.run { latestTime }
        let result = await DshAPI.fetchMessages(limit: 10, after: after, session: context)
        await MainActor.run {
            for m in result.msgs { appendMessage(m) }
            if let latest = result.latest { latestTime = latest }
            if !result.busy { dropStaleStreamBubbles() }
            trimMessages()
            saveCache()
        }
        return (result.busy, result.lastTool)
    }

    private func appendMessage(_ m: ChatMsg) {
        // 同一条服务器消息又拉到一次（好几个拉取会叠在一起）：直接忽略。以前它会再走一遍合并、把「暂存的最终消息」顶掉，
        // 中途说的那句就此不见（头像跟着整行没了）
        if !m.time.isEmpty, seenKeys.contains(m.key) { return }
        // 本地回声与随后拉取到的同一条消息去重：用带时间的远端消息替换回声
        if !m.time.isEmpty {
            if let idx = messages.firstIndex(where: { $0.isMe && $0.time.isEmpty && $0.text == m.text }) {
                // 原地替换，行的身份不变（pinnedKey 记的是行 id）：不重建、不挪到回复下面
                guard seenKeys.insert(m.key).inserted else { return }
                rowAlias[m.key] = rowAlias[messages[idx].key] ?? messages[idx].key
                messages[idx] = m
                latestTime = m.time
                return
            }
            // 待办拍照的占位：服务器发给 P-Health 的那条「【待办提交】id=…」到了就撤掉
            if m.isMe, m.text.hasPrefix("【待办提交】id="), let id = m.text.dropFirst(9).split(separator: "｜").first {
                messages.removeAll { $0.time.isEmpty && ($0.stableId ?? "").hasPrefix("pending-photo-")
                    && $0.text.hasPrefix("【待办提交】id=\(id)｜") }
            }
        }
        // Bot 回复到达后，撤掉末尾的「还在处理」提示
        if m.role == "phealth" {
            while let last = messages.last, last.role == "error" {
                messages.removeLast()
            }
        }
        if m.role == "phealth", !m.time.isEmpty, mergeStreamedFinal(m) {
            return
        }
        guard seenKeys.insert(m.key).inserted else { return }
        messages.append(m)
        if !m.time.isEmpty { latestTime = m.time }
    }

    /// 流式气泡合并：一轮回复可能流出好几个气泡（调用工具前说的一句 + 最后的回复），服务器每段各回一条。
    /// 拿到的最终消息和哪个气泡的字一样，就替换哪个（以前只比最新的气泡，前面那句会和服务器的那条各显示一次）
    private func mergeStreamedFinal(_ m: ChatMsg) -> Bool {
        let norm = normalizedText(m.text)
        if let idx = messages.firstIndex(where: { ($0.stableId ?? "").hasPrefix("stream-") && normalizedText($0.text) == norm }) {
            DshAPI.dbg("stream merge matched")
            rowAlias[m.key] = rowAlias[messages[idx].key] ?? messages[idx].key
            messages[idx] = m
            seenKeys.insert(m.key)
            latestTime = m.time
            if pendingStreamFinal?.key == m.key { pendingStreamFinal = nil }
            saveCache()
            return true
        }
        // 半截气泡：除了正在流的那个，都可以换成完整的（以前只要还有一段在流就不换，前面那句会挪到最底下、原位被撤掉）
        let liveId = streamAttempt.map { "stream-\($0)" }
        if let idx = messages.firstIndex(where: { msg in
               guard let sid = msg.stableId, sid.hasPrefix("stream-"), sid != liveId else { return false }
               let t = normalizedText(msg.text)
               return t.count >= 4 && norm.hasPrefix(t)
           }) {
            // 流断在半路留下的半截气泡：最终消息到了就用它替换（不再一半一整各显示一次）
            DshAPI.dbg("stream merge partial")
            rowAlias[m.key] = rowAlias[messages[idx].key] ?? messages[idx].key
            messages[idx] = m
            seenKeys.insert(m.key)
            latestTime = m.time
            saveCache()
            return true
        }
        if let attempt = streamAttempt {
            // 流还在进行，最终消息先到了（气泡的字是它的开头，或者气泡还没出现）：等流结束再合并
            let bubble = messages.first(where: { $0.stableId == "stream-\(attempt)" })
            // 只有正在流的气泡确实是它的开头才先放着；气泡还没出现就直接上屏（以前一律放进唯一的暂存位，后来的一条会把它顶掉）
            if let bubble, norm.hasPrefix(normalizedText(bubble.text)) {
                pendingStreamFinal = m
                return true
            }
        }
        if messages.contains(where: { ($0.stableId ?? "").hasPrefix("stream-") }) {
            DshAPI.dbg("stream merge mismatch finalChars=\(m.text.count)")
        }
        return false
    }

    /// 兜底：一轮结束后还没被合并掉的流式气泡，如果服务器已经有内容相同（互相包含）的消息，就撤掉气泡，免得一段话出现两次
    private func dropStaleStreamBubbles() {
        guard streamAttempt == nil else { return }
        let finals = messages.filter { $0.role == "phealth" && !$0.time.isEmpty }.map { normalizedText($0.text) }
        messages.removeAll { msg in
            guard (msg.stableId ?? "").hasPrefix("stream-") else { return false }
            let t = normalizedText(msg.text)
            guard t.count >= 4 else { return false }
            return finals.contains { $0.contains(t) || (t.contains($0) && $0.count >= t.count / 2) }
        }
    }

    /// 【每日推荐】（系统发的，显示成一条分隔线）后面 P-Health 回的那一句：quiet，画成分隔线下的小灰字，
    /// 不当成 P-Health 先开口说话。早上那次例外：回的是「今日判断」，老大要看的，照常显示。
    /// rateable：每一轮 P-Health 回完的最后一条（后面一条不是它说的，或者没有了）下面放 👍 / 👎；最后一轮还在回（等回复中）时先不放。
    /// 服务器的历史会滤掉【洞察】【反馈】那段，前后两轮 P-Health 的话看着是连着的：这次打开对话里点开洞察 / 点踩转述时
    /// 记下的上一轮最后一条（turnFloorKey）照样算一轮的结尾；评过的那条不管在哪都留着小手（ReplyThumbs 自己看）
    private var rows: [ChatRowItem] {
        var out: [ChatRowItem] = []
        var afterDigest = false
        let msgs = messages
        for (i, m) in msgs.enumerated() {
            // 洞察 / 点踩转述：服务器塞给 P-Health 的那段（【洞察…】【反馈…】）不显示、也不画分隔线，P-Health 的回复照常显示
            if m.isMe && (isInsightPrompt(m.text) || isFeedbackPrompt(m.text)) { afterDigest = false; continue }
            let quiet = afterDigest && m.role == "phealth" && !m.text.contains("```phealth-ui")
            let rateable = m.role == "phealth"
                && (m.key == turnFloorKey || (i + 1 < msgs.count ? msgs[i + 1].role != "phealth" : !awaitingReply))
            out.append(ChatRowItem(id: rowAlias[m.key] ?? m.key, msg: m, quiet: quiet, rateable: rateable))
            if m.isMe && isHarnessNoise(m.text) { continue }    // 后台通知不打断
            afterDigest = m.isMe && m.text.hasPrefix("【每日推荐】") && recommendSlot(m.text) != "早上"
        }
        return out
    }

    private func normalizedText(_ text: String) -> String {
        text.filter { !$0.isWhitespace }
    }

    // MARK: - DSH 实时逐句回复
    private func startLiveStream() {
        if ProcessInfo.processInfo.arguments.contains("-disableLiveStream") { return }
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-flowTest") { runFlowTest(); return }
        #endif
        streamClient?.stop()
        eventClient?.stop()
        let sessionId = DshAPI.sessionId(for: context)
        let client = DshStreamClient(sessionId: sessionId) { event in
            Task { @MainActor in self.handleStreamEvent(event) }
        }
        streamClient = client
        Task { await client.start() }
        // $events 并行订阅：授权请求 / 主动提问 → 客户端交互卡
        let events = DshEventClient(sessionId: sessionId) { event in
            Task { @MainActor in self.handleInteractionEvent(event) }
        }
        eventClient = events
        Task { await events.start() }
    }

    // MARK: - DSH $events 交互（授权 / 提问）
    private func handleInteractionEvent(_ event: DshEventClient.Event) {
        switch event {
        case .request(let req):
            interactions.removeAll { $0.eventId == req.eventId }
            interactions.append(req)
            awaitingReply = true
            toolHint = "等待你确认"
            DshAPI.dbg("interaction card shown eventId=\(req.eventId.prefix(8))")
        case .cancelled(let eventId):
            interactions.removeAll { $0.eventId == eventId }
            if interactions.isEmpty, toolHint == "等待你确认" { toolHint = nil }
        case .emit(let event):
            DshAPI.dbg("dsh emit \(event)")
            throttledEmitFetch()
        case .failure(let message):
            DshAPI.dbg("events failure: \(message)")
        }
    }

    /// emit 高频触发（如 api-session/activity 每步都发），节流 2 秒，避免主线程 churn
    private func throttledEmitFetch() {
        let now = Date()
        guard now.timeIntervalSince(lastEmitFetch) >= 2 else { return }
        lastEmitFetch = now
        Task { await self.fetchIncremental() }
    }

    /// 用户作答后回传 DSH 并移除卡片；value 为 nil 表示取消类应答
    private func answerInteraction(_ req: InteractionRequest, value: Any?) {
        eventClient?.respond(eventId: req.eventId, value: value)
        interactions.removeAll { $0.eventId == req.eventId }
        if interactions.isEmpty { toolHint = nil }
        awaitingReply = true
        startReplyMonitor(showPendingHint: false)
    }

    /// 流断在半路（退到后台被掐、网络断）：把已经流出来的字留着，按结束处理，压着的最终回复放出来
    private func finalizeStaleStream() {
        guard streamAttempt != nil else { return }
        upsertStreamBubble()
        lastStreamAttempt = streamAttempt
        streamAttempt = nil
        streamBuffer = ""
        if let p = pendingStreamFinal {
            pendingStreamFinal = nil
            appendMessage(p)
        }
        saveCache()
    }

    /// 从后台回来：流状态清掉、重连实时通道、立刻拉一次最新消息（P-Health 在后台时可能已经回完了）
    private func resumeFromBackground() {
        guard !ServerConfig.isDemo else { return }
        DshAPI.dbg("chat resume from background")
        finalizeStaleStream()
        startLiveStream()
        Task { await FeedbackStore.shared.refresh(context) }
        Task {
            let r = await fetchIncremental()
            await MainActor.run {
                awaitingReply = r.busy
                toolHint = r.busy ? r.lastTool : nil
                if r.busy { startReplyMonitor(showPendingHint: false) }
            }
        }
    }

    #if DEBUG
    /// 模拟器里实时通道连不上：-flowTest 在本地按真实节奏放一段流（开始 → 一小段一小段 → 结束 → 最终消息合并），
    /// 走的是和真流一样的 handleStreamEvent / appendMessage 路径，用来验收流式文字和不抢屏幕
    private static var flowTestRan = false
    private func runFlowTest() {
        guard !Self.flowTestRan else { return }
        Self.flowTestRan = true
        if ProcessInfo.processInfo.arguments.contains("-flowTestStall") {
            // 流开了头、流到一半通道被掐（没有结束事件），最终回复由轮询拿到：看门狗要在 25 秒后把它放出来
            let full = "流断测试：这是一条完整的回复，前半截先流出来，后半截因为通道被掐没流完。最终消息到了以后应该替换掉半截气泡。"
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                handleStreamEvent(.start(attemptId: "stalltest"))
                handleStreamEvent(.delta("流断测试：这是一条完整的回复，前半截先流出来，"))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                appendMessage(ChatMsg(role: "phealth", text: full, time: PTime.isoFractional(Date())))
                DshAPI.dbg("stalltest final delivered while stream open")
            }
            return
        }
        let reply = "老大，今晚就这几件事：\n1. 22:40 把明天要做的事写下来，写完合上纸。\n2. 23:00 手机放到卧室外，开勿扰。\n3. 00:30 在床外做 5 分钟拉伸，困了再上床。\n4. 明早 08:30 照常起，周末也一样。\n\n```phealth-ui\n{\"type\":\"layout\",\"layout\":{\"t\":\"v\",\"children\":[{\"t\":\"value\",\"bind\":\"sleep\",\"size\":\"xl\"},{\"t\":\"chart\",\"metric\":\"hrv\",\"height\":\"l\"}]}}\n```\n\n```phealth-ui\n{\"type\":\"options\",\"title\":\"今晚先做哪个\",\"options\":[\"拉伸\",\"慢呼吸 5 分钟\",\"都不做\"]}\n```\n\n**今晚最要紧的是第 3 条**：床只用来睡。"   // 演示用的假回复（DEBUG -flowTest），不是真实对话
        var chunks: [String] = []
        var cur = ""
        for ch in reply {
            cur.append(ch)
            if "，。；：\n".contains(ch) || cur.count >= Int.random(in: 4...10) { chunks.append(cur); cur = "" }
        }
        if !cur.isEmpty { chunks.append(cur) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            let mine = ChatMsg(role: "me", text: "今晚睡前我该注意哪几件事？", time: "")
            appendMessage(mine)
            pin(mine.key)
            awaitingReply = true
            // 第一段：调用工具前先说一句（单独一次模型调用 = 单独一个流式气泡）
            let pre = "我先看一下你今晚的待办和昨晚的睡眠。"
            var t = 1.2
            DispatchQueue.main.asyncAfter(deadline: .now() + t) { handleStreamEvent(.start(attemptId: "flowtest-1")) }
            for c in ["我先看一下", "你今晚的待办", "和昨晚的睡眠。"] {
                t += 0.12
                DispatchQueue.main.asyncAfter(deadline: .now() + t) { handleStreamEvent(.delta(c)) }
            }
            t += 0.2
            DispatchQueue.main.asyncAfter(deadline: .now() + t) {
                handleStreamEvent(.end(attemptId: "flowtest-1"))
                handleStreamEvent(.toolStart(key: "flowtest-tool", label: "看今晚的待办"))
            }
            t += 1.0
            DispatchQueue.main.asyncAfter(deadline: .now() + t) {
                handleStreamEvent(.toolEnd(key: "flowtest-tool", label: "看今晚的待办"))
                handleStreamEvent(.start(attemptId: "flowtest-2"))
            }
            let mid = chunks.count / 2
            for (i, c) in chunks.enumerated() {
                t += Double.random(in: 0.05...0.2)
                DispatchQueue.main.asyncAfter(deadline: .now() + t) {
                    handleStreamEvent(.delta(c))
                    // 第二段流到一半时，轮询拿到了第一段的服务器版本（以前这里会多出一条一样的话）
                    if i == mid { appendMessage(ChatMsg(role: "phealth", text: pre, time: PTime.isoFractional(Date().addingTimeInterval(-3)))) }
                }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + t + 0.1) {
                handleStreamEvent(.end(attemptId: "flowtest-2"))
                appendMessage(ChatMsg(role: "phealth", text: reply, time: PTime.isoFractional(Date())))
            }
        }
    }
    #endif

    private func handleStreamEvent(_ event: DshStreamClient.Event) {
        lastStreamEvent = Date()
        switch event {
        case .start(let attemptId):
            upsertStreamBubble()   // 上一段（调用工具前说的话）还没上屏的字
            streamAttempt = attemptId
            lastStreamAttempt = nil
            streamBuffer = ""
            awaitingReply = true
        case .baseline(let attemptId, let text):
            if streamAttempt != attemptId {
                streamAttempt = attemptId
                lastStreamAttempt = nil
                streamBuffer = ""
            }
            awaitingReply = true
            streamBuffer = text
            upsertStreamBubble()
        case .delta(let text):
            streamBuffer += text
            // 合并成小批上屏（约 12 次/秒）：字怎么出现由 FlowingText 逐帧流，列表不用每来一个字就重排
            if !flushPending {
                flushPending = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
                    flushPending = false
                    upsertStreamBubble()
                }
            }
        case .toolStart(let key, let label):
            awaitingReply = true
            // 该调用的完成帧可能已到（适配器先放 block-end）：不再回退成"正在调用"
            if !activities.contains(where: { $0.key == key }) {
                toolHint = label
                activities.append(ActivityRowItem(key: key, label: label, done: false))
            }
        case .toolEnd(let key, let label):
            // 参数写完 = 知道它要做什么了：行里换成具体动作；命令接着执行，提示也换成这个动作
            if let idx = activities.firstIndex(where: { $0.key == key }) {
                activities[idx].label = label
                activities[idx].done = true
            } else {
                activities.append(ActivityRowItem(key: key, label: label, done: true))
            }
            toolHint = label
        case .end(let attemptId):
            upsertStreamBubble()   // 还没上屏的最后一批字
            lastStreamAttempt = attemptId
            streamAttempt = nil
            streamBuffer = ""
            saveCache()
            if let pendingStreamFinal {
                self.pendingStreamFinal = nil
                appendMessage(pendingStreamFinal)
            }
            Task {
                let result = await fetchIncremental()
                await MainActor.run {
                    awaitingReply = result.busy
                    toolHint = result.lastTool
                }
            }
        case .failure(let message):
            DshAPI.dbg("live stream fallback: \(message)")
            lastStreamAttempt = streamAttempt
            streamAttempt = nil
            streamBuffer = ""
            if let pendingStreamFinal {
                self.pendingStreamFinal = nil
                appendMessage(pendingStreamFinal)
            }
        }
    }

    /// 单气泡流式：同一 attempt 只维护一个不断增长的气泡，客户端不做任何切句
    private func upsertStreamBubble() {
        guard let attempt = streamAttempt, !streamBuffer.isEmpty else { return }
        let id = "stream-\(attempt)"
        if let idx = messages.lastIndex(where: { $0.stableId == id }) {
            messages[idx].text = streamBuffer
        } else {
            appendMessage(ChatMsg(role: "phealth", text: streamBuffer, time: "", stableId: id))
        }
        streamVersion += 1
    }

    // MARK: - 发送
    /// 统一发送入口：直接吃传入文本，不依赖 input 绑定（IME 组字提交后绑定可能尚未回写）
    private func submitText(_ raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !sending else { return }
        sendText(text)
    }

    private func send() {
        submitText(input)
    }

    private func sendText(_ text: String) {
        sending = true
        turnFloorKey = nil
        input = ""
        inputClearSignal += 1
        activities = []   // 新的用户回合开始，清空上一轮工具行
        freezeAboutPosition()
        let carry = aboutActive
        let mine = ChatMsg(role: "me", text: text, time: "", about: carry?.name)
        appendMessage(mine)
        pin(mine.key)     // 自己发的消息：顶到屏幕上方，回复在下面流；带进来的卡跟着往上滚走（视频不停）
        // 带着习惯 / 待办：正文前加一行标记，P-Health 先看那个项目 / 那张卡再答
        let wire = carry.map { $0.marker + "\n" + text } ?? text
        Task {
            let failure = await DshAPI.sendMessage(wire, context: context)
            await MainActor.run {
                sending = false
                if let failure {
                    appendMessage(ChatMsg(role: "error", text: "发送失败：\(failure)", time: ""))
                    return
                }
                if DshAPI.consumeSessionCreated() { startLiveStream() }   // 会话刚建好：重新订阅实时回复
                awaitingReply = true
                startReplyMonitor(showPendingHint: true)
            }
        }
    }

    /// 发一张照片：先把小图上屏（不等网络），后台压缩、上传，再发给 P-Health。
    /// 待办卡上拍的：走待办提交，P-Health 收到「【待办提交】…照片」后直接记到那条待办上。
    private func sendPhoto(_ p: PendingPhoto) {
        let caption = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if p.todoId == nil { input = ""; inputClearSignal += 1 }
        let local = "local-\(UUID().uuidString)"
        let placeholderId = "pending-photo-\(local)"
        let shownText: (String) -> String = { name in
            if let id = p.todoId {
                return "【待办提交】id=\(id)｜\(p.todoTitle ?? "待办")\n用户在待办卡里提交：\(PhotoMarker.tag(name))"
            }
            return PhotoMarker.tag(name) + (caption.isEmpty ? "" : "\n" + caption)
        }
        activities = []
        freezeAboutPosition()
        atBottom = true
        sending = true
        Task {
            var finalText: String?
            let thumb = await PhotoPrep.thumbnail(p.image)
            await MainActor.run {
                ChatPhotoCache.shared.put(local, thumb)
                let mine = ChatMsg(role: "me", text: shownText(local), time: "", stableId: placeholderId)
                appendMessage(mine)
                pin(mine.key)
            }
            do {
                guard let data = await PhotoPrep.jpeg(p.image) else { throw URLError(.cannotDecodeContentData) }
                if let todoId = p.todoId {
                    let path = try await V3API.uploadPhoto(todoId, data: data)
                    let name = (path as NSString).lastPathComponent
                    await MainActor.run { ChatPhotoCache.shared.put(name, thumb) }
                    _ = try await V3API.submit(todoId, action: "agent", values: [p.fieldId ?? "photo": path])
                    NotificationCenter.default.post(name: .pivisPagesDirty, object: nil)
                } else {
                    let up = try await V3API.uploadChatPhoto(data: data)
                    finalText = shownText(up.name)
                    await MainActor.run {
                        ChatPhotoCache.shared.put(up.name, thumb)
                        // 先换成和服务器历史一样的文字（发出去后拉到的那条会替换掉这条回声，不重复）
                        if let i = messages.firstIndex(where: { $0.stableId == placeholderId }) {
                            messages[i] = ChatMsg(role: "me", text: shownText(up.name), time: "")
                        }
                    }
                    let wire = "照片 \(up.path)（用 read_image 看这张图）" + (caption.isEmpty ? "" : "\n" + caption)
                    if let failure = await DshAPI.sendMessage(wire, context: context) { throw NSError(domain: "send", code: 0, userInfo: [NSLocalizedDescriptionKey: failure]) }
                }
                await MainActor.run {
                    sending = false
                    awaitingReply = true
                    startReplyMonitor(showPendingHint: true)
                }
            } catch {
                let ft = finalText
                await MainActor.run {
                    sending = false
                    // 没发出去：照片气泡撤掉，只留一句失败提示，免得看着像发了
                    messages.removeAll { $0.stableId == placeholderId || ($0.time.isEmpty && ft != nil && $0.text == ft) }
                    appendMessage(ChatMsg(role: "error", text: "照片没发出去，再拍一次试试（\(error.localizedDescription)）", time: ""))
                }
            }
        }
    }

    /// 点开洞察（浮条上的「聊聊」，或者点洞察推送进来）：浮条马上收起，叫服务器把那段话塞进主对话，
    /// 对话进入和发完消息一样的「等 P-Health 回复」状态，回复照常流进来
    private func startInsight(_ id: String) {
        PageSync.shared.insightHandled(id)
        activities = []
        pinnedKey = nil                 // 上一轮钉住的那条不再钉着：回复直接接在最底下，屏幕跟着走
        scrollReset += 1
        turnFloorKey = messages.last?.key
        awaitingReply = true
        toolHint = nil
        promptInFlight = true
        Task {
            let result = await InsightAPI.open(id)
            await MainActor.run {
                promptInFlight = false
                switch result {
                case .opened:
                    awaitingReply = true
                    startReplyMonitor(showPendingHint: true)
                case .notPending:
                    // 已经点开过 / 划掉了：没有新的一轮，不等了
                    if fastPoll == nil, streamAttempt == nil { awaitingReply = false }
                case .notDelivered:
                    if fastPoll == nil, streamAttempt == nil { awaitingReply = false }
                    appendMessage(ChatMsg(role: "error", text: "P-Health 这次没接上，过会儿直接问它就行", time: ""))
                case .failed:
                    if fastPoll == nil, streamAttempt == nil { awaitingReply = false }
                    PageSync.shared.insightUnhandled(id)     // 浮条放回去，等会儿再点
                    appendMessage(ChatMsg(role: "error", text: "没打开：连不上服务器，等会儿再点一次", time: ""))
                }
            }
        }
    }

    private func openFeedback(_ m: ChatMsg) {
        withAnimation(.easeOut(duration: 0.22)) { feedbackFor = m }
    }

    private func closeFeedback() {
        withAnimation(.easeOut(duration: 0.2)) { feedbackFor = nil }
    }

    /// 「哪里不好？」提交：没写字 → 记一下就完（排队发）；写了一句 → 服务器把它转给这个对话里的 P-Health 当场改，
    /// 对话和点开洞察一样进入「等 P-Health 回复」，回复照常流进来（转过去的那句以【反馈开头，不显示）
    private func submitFeedback(_ msg: ChatMsg, reasons: [String], note: String) {
        guard !note.isEmpty else {
            FeedbackStore.shared.set(.down, context: context, msg: msg, reasons: reasons)
            return
        }
        FeedbackStore.shared.mark(.down, context: context, time: msg.time)
        activities = []
        freezeAboutPosition()
        pinnedKey = nil                 // 回复接在最底下，屏幕跟着走
        scrollReset += 1
        turnFloorKey = messages.last?.key
        awaitingReply = true
        toolHint = nil
        promptInFlight = true
        Task {
            let result = await FeedbackStore.shared.sendNow(context: context, msg: msg, reasons: reasons, note: note)
            await MainActor.run {
                promptInFlight = false
                let idle = fastPoll == nil && streamAttempt == nil
                switch result {
                case .forwarded:
                    awaitingReply = true
                    startReplyMonitor(showPendingHint: true)
                case .unknown:
                    // 服务器还没回：多半在转，安静地等一会儿
                    startReplyMonitor(showPendingHint: false)
                case .notForwarded:
                    if idle { awaitingReply = false }
                    appendMessage(ChatMsg(role: "error", text: "记下了，但 P-Health 这次没接上，过会儿直接跟它说就行", time: ""))
                case .queued:
                    if idle { awaitingReply = false }
                    appendMessage(ChatMsg(role: "error", text: "连不上服务器：记在手机上了，连上后再转给 P-Health", time: ""))
                case .rejected:
                    if idle { awaitingReply = false }
                    FeedbackStore.shared.mark(.none, context: context, time: msg.time)
                    appendMessage(ChatMsg(role: "error", text: "没记上，等会儿再点一次", time: ""))
                }
            }
        }
    }

    private func startReplyMonitor(showPendingHint: Bool) {
        guard fastPoll == nil else { return }
        fastPoll = Task {
            await waitForReply(showPendingHint: showPendingHint)
            await MainActor.run { fastPoll = nil }
        }
    }

    /// 阶段性等回复（hermesbot 式）：回合进行中持续快轮询，每完成一步
    /// （一条 assistant/message 落盘）就立刻上屏一段；turn/end 事件到达才收尾。
    private func waitForReply(showPendingHint: Bool) async {
        let started = Date()
        let timeout = started.addingTimeInterval(120)
        let baselineReplies = messages.count { $0.role == "phealth" }
        var sawReply = false
        var turnOpened = false
        var lastStatus = ""
        while Date() < timeout {
            try? await Task.sleep(for: .milliseconds(900))
            if Task.isCancelled { return }
            let r = await fetchIncremental()
            let status = "busy=\(r.busy) tool=\(r.lastTool ?? "nil")"
            if status != lastStatus {
                DshAPI.dbg("chat poll \(status)")
                lastStatus = status
            }
            if r.busy { turnOpened = true }
            let gotReply = await MainActor.run { messages.count { $0.role == "phealth" } > baselineReplies }
            if gotReply { sawReply = true }
            await MainActor.run {
                awaitingReply = r.busy
                toolHint = r.busy ? r.lastTool : nil
            }
            if !r.busy && (turnOpened || sawReply) && Date() > started.addingTimeInterval(1.5) {
                break
            }
        }
        await MainActor.run {
            awaitingReply = false
            toolHint = nil
            saveCache()
            if showPendingHint && !sawReply {
                appendMessage(ChatMsg(role: "error", text: "P-Health 还在处理；新回复到达后会自动显示", time: ""))
            }
        }
    }

    /// 卡片的「已回答」（重开对话后卡片仍锁着）：按卡片标题找后面老大的回答。
    /// 只认以「回答「<卡片标题>」」开头的那条（问题 / 选项 / 打分卡点提交时发的就是它）；
    /// 方案 / 确认卡认「<按钮上的字>（<卡片标题>）」。以前后面随便哪句话都算回答，聊别的也会把卡锁上。
    /// 同名的卡后来又发了一次：再往后的回答算新的那张。
    private func answerMap() -> [String: [String: String]] {
        var map: [String: [String: String]] = [:]
        let msgs = messages
        for (i, m) in msgs.enumerated() where !m.isMe && m.text.contains("```phealth-ui") {
            var found: [String: String] = [:]
            for card in Self.cards(in: m.text) {
                guard let title = card.title, !title.isEmpty, found[title] == nil else { continue }
                let head = "回答「\(title)」"
                let tail = "（\(title)）"
                let buttons = Set(card.buttonLabels)
                scan: for later in msgs.dropFirst(i + 1) {
                    if !later.isMe {
                        if later.text.contains("```phealth-ui"), Self.cards(in: later.text).contains(where: { $0.title == title }) { break scan }
                        continue
                    }
                    let t = later.text
                    if t.hasPrefix(head) {
                        var rest = Substring(t.dropFirst(head.count))
                        if rest.first == "：" || rest.first == ":" { rest = rest.dropFirst() }
                        found[title] = rest.isEmpty ? "已回答" : String(rest)
                        break scan
                    }
                    if t.hasSuffix(tail), buttons.contains(String(t.dropLast(tail.count))) {
                        found[title] = String(t.dropLast(tail.count))
                        break scan
                    }
                }
            }
            if !found.isEmpty { map[m.key] = found }
        }
        return map
    }

    private static func cards(in text: String) -> [GenCard] {
        GenParser.parse(text).compactMap { if case .card(let c) = $0 { return c } else { return nil } }
    }

    private func sendAction(_ raw: String) {
        var text = raw
        if text.hasPrefix("raw:") {
            text = String(text.dropFirst(4))
        } else if text.hasPrefix("opt:") {
            // 生成式 UI 选项：以「选 A · 完整舒缓」的形式发回，Bot 与用户都可读
            let body = text.dropFirst(4)
            let parts = body.split(separator: "|", maxSplits: 1).map(String.init)
            let label = parts.count > 1 ? parts[1] : (parts.first ?? "")
            let id = parts.first ?? ""
            text = label.isEmpty ? raw : "选 \(label)"
            if !id.isEmpty && id.lowercased() != label.lowercased() { text += "（\(id)）" }
        }
        else if text.hasPrefix("rate:") { text = "评分：\(text.dropFirst(5))" }
        else if text == "confirm" { text = "确认这套方案" }
        else if text == "adjust" { text = "帮我调整这套方案" }
        else if text == "yes" { text = "对" }
        else if text == "no" { text = "不对" }
        guard !sending else { return }
        sendText(text)
    }
}

// MARK: - 消息行：头像在每段开头，生成式 UI 与气泡左对齐
struct ChatRow: View, Equatable {
    static func == (a: ChatRow, b: ChatRow) -> Bool {
        a.msg == b.msg && a.maxWidth == b.maxWidth && a.avatarActive == b.avatarActive
            && a.answers == b.answers && a.streaming == b.streaming && a.quiet == b.quiet
            && a.rateContext == b.rateContext && a.rateable == b.rateable
    }
    let msg: ChatMsg
    let maxWidth: CGFloat
    /// 回复进行中：本条最新消息的头像带脉冲动效
    var avatarActive = false
    /// 这条里各张卡片（按标题）的回答
    var answers: [String: String]? = nil
    /// 这条是正在流式到达的回复
    var streaming = false
    /// 【每日推荐】后面 P-Health 回的那一句：分隔线下的小灰字
    var quiet = false
    /// 评价记在哪个对话下；nil = 这里不评（没有小手）
    var rateContext: String? = nil
    /// 一轮回完的最后一条：一直放 👍 / 👎；别的回复只有评过才放（评过的不能因为后面又来了一条就看不见）
    var rateable = false
    let onAction: (String) -> Void
    var onDislike: (ChatMsg) -> Void = { _ in }

    /// 回完了（服务器给了 time）才能评：还在流的、本地的都不放
    private var thumbsContext: String? {
        guard let rateContext, !streaming, !msg.time.isEmpty, msg.role == "phealth" else { return nil }
        return rateContext
    }

    var body: some View {
        if msg.isMe, isHarnessNoise(msg.text) || isInsightPrompt(msg.text) || isFeedbackPrompt(msg.text) {
            // DSH 的后台任务通知、服务器塞的洞察提示、点踩转述等，不是老大说的话
            EmptyView()
        } else if msg.isMe, msg.text.hasPrefix("【每日推荐】") {
            // 系统的定时推荐（早上 / 午后 / 傍晚）：不展示指令，只留一条分隔线；早上那次回的是「今日判断」
            let day = String(msg.text.dropFirst(6).prefix(10)).split(separator: "-").suffix(2).joined(separator: "/")
            let slot = recommendSlot(msg.text) ?? ""
            HStack(spacing: 10) {
                Hairline(color: E.line2)
                Text(slot == "早上" ? "\(day) 今日判断" : "\(day) \(slot)推荐").font(E.body(11)).foregroundStyle(E.text3).fixedSize()
                Hairline(color: E.line2)
            }
            .padding(.vertical, 8)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("chat-recommend-divider")
        } else if msg.isMe, msg.text.hasPrefix("【每日整理】") {
            // 系统的每日整理：不展示指令，只留一条日期分隔线
            let day = String(msg.text.dropFirst(6).prefix(10)).split(separator: "-").suffix(2).joined(separator: "/")
            HStack(spacing: 10) {
                Hairline(color: E.line2)
                Text("\(day) 早上整理").font(E.body(11)).foregroundStyle(E.text3).fixedSize()
                Hairline(color: E.line2)
            }
            .padding(.vertical, 8)
        } else if msg.isMe, let note = TodoSubmitNote(msg.text) {
            // 待办卡里的提交：App 发给 P-Health 的指令不展示，只留一行「在哪张卡里说了什么」
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Spacer(minLength: 40)
                VStack(alignment: .trailing, spacing: 3) {
                    Text("在待办「\(note.title)」里")
                        .font(E.body(11)).foregroundStyle(E.text3)
                    let parts = PhotoMarker.split(note.content)
                    ForEach(parts.photos, id: \.self) { ChatPhotoView(name: $0) }
                    if !parts.rest.isEmpty {
                        Text(parts.rest)
                            .font(E.body(15)).foregroundStyle(E.text)
                            .multilineTextAlignment(.trailing)
                    }
                }
            }
            .padding(.vertical, 6)
            .accessibilityElement(children: .combine)
        } else if msg.isMe, msg.text.hasPrefix("回答「"), let r = msg.text.range(of: "」：") {
            // 卡片里的回答：卡片本身已显示「已回答」，气泡只留答案
            ChatBubble(msg: ChatMsg(role: msg.role, text: String(msg.text[r.upperBound...]), time: msg.time), maxWidth: maxWidth)
        } else if msg.isMe, case let parts = PhotoMarker.split(msg.text), !parts.photos.isEmpty {
            // 发给 P-Health 的照片：图 + 附言
            VStack(alignment: .trailing, spacing: 6) {
                ForEach(parts.photos, id: \.self) { name in
                    HStack { Spacer(minLength: 40); ChatPhotoView(name: name) }
                }
                if !parts.rest.isEmpty {
                    ChatBubble(msg: ChatMsg(role: msg.role, text: parts.rest, time: msg.time), maxWidth: maxWidth)
                }
            }
            .padding(.vertical, 2)
        } else if msg.isMe, let carried = msg.about ?? ChatAbout.split(msg.text).1?.name {
            // 带着习惯 / 待办发的：气泡里不显示标记，下面一行小字「带着：X」
            VStack(alignment: .trailing, spacing: 6) {
                ChatBubble(msg: ChatMsg(role: msg.role, text: ChatAbout.split(msg.text).0, time: msg.time), maxWidth: maxWidth)
                Text("带着：\(carried)").font(E.body(11)).foregroundStyle(E.text3)
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("chat-carried")
        } else if msg.isMe || msg.role == "error" {
            ChatBubble(msg: msg, maxWidth: maxWidth)
        } else if quiet {
            // 每日推荐是系统按点发的（上面一条分隔线），P-Health 回的那一句跟在线下面、小灰字，不像它先开口说话
            let t = msg.text.trimmingCharacters(in: .whitespacesAndNewlines)
            VStack(spacing: 0) {
                Text(cjkMarkdown(t))
                    .font(E.body(12)).foregroundStyle(E.text3).lineSpacing(3)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, 28)
                    .accessibilityIdentifier("chat-digest-note")
                // 一句话的小结不放小手（太碎）；P-Health 写长了（几行）才放，和字一样居中
                if let ctx = thumbsContext {
                    ReplyThumbs(context: ctx, msg: msg, always: rateable && (t.contains("\n") || t.count > 80),
                                centered: true, onDown: onDislike)
                }
            }
            .padding(.top, -10)
            .padding(.bottom, 6)
        } else {
            // P-Health：解析 ```phealth-ui 块，失败回退纯文本
            let segs = GenParser.parse(msg.text)
            // 头像贴左边线，字、卡从 chatTextInset 开始，一直到右边线（卡的右边和我的气泡、带进来的卡、输入栏对齐）
            HStack(alignment: .top, spacing: E.chatTextInset - E.avatarSize) {
                EAvatar(active: avatarActive, size: E.avatarSize)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(segs.enumerated()), id: \.offset) { _, seg in
                        switch seg {
                        case .text(let t) where streaming && t.hasPrefix("```phealth-ui"):
                            // 卡片还没写完：不露出原始 JSON，留一条细线等它画好
                            WorkingLine().frame(width: 90, height: 18)
                        case .text(let t):
                            ChatBubble(msg: ChatMsg(role: "phealth", text: t, time: msg.time), maxWidth: maxWidth, live: streaming)
                        case .card(let c) where (c.type ?? "").lowercased() == "sticker":
                            // 表情包：不套卡片边框，放在这条回复最后（card-check 管顺序）
                            StickerView(name: c.name ?? c.title ?? "")
                                .padding(.top, 4)
                        case .card(let c):
                            GenCardView(card: c, onAction: onAction, answered: c.title.flatMap { answers?[$0] })
                                .frame(maxWidth: maxWidth, alignment: .leading)
                        }
                    }
                    // 一轮回完：下面两只小手，和字的左边对齐
                    if let ctx = thumbsContext {
                        ReplyThumbs(context: ctx, msg: msg, always: rateable, onDown: onDislike)
                    }
                }
                // 不用 Spacer 撑：HStack 的间距也会加在 Spacer 前面，卡的右边就差 8 够不到右边线
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 2)
        }
    }
}

struct ChatGeo: Equatable {
    var contentH: CGFloat
    var visibleMinY: CGFloat
    var visibleMaxY: CGFloat
    var containerH: CGFloat
}

struct ChatRowItem: Identifiable {
    let id: String
    let msg: ChatMsg
    var quiet = false
    /// 一轮回复的最后一条：下面放 👍 / 👎
    var rateable = false
}

/// DSH 运行时自己塞进会话的消息（后台任务完成通知等）
func isHarnessNoise(_ text: String) -> Bool {
    (text.hasPrefix("background job ") && text.contains("finished [status:"))
        || text.hasPrefix("<system-reminder>")
}

/// 洞察点开时服务器塞进主对话的那段（以【洞察 开头）：服务器的历史会滤掉，这里再兜一次底
func isInsightPrompt(_ text: String) -> Bool {
    text.drop(while: { $0.isWhitespace }).hasPrefix("【洞察")
}

/// 点踩时写的那句，服务器转给 P-Health 的那段（以【反馈 开头）：不是老大在对话里打的字，不显示
func isFeedbackPrompt(_ text: String) -> Bool {
    text.drop(while: { $0.isWhitespace }).hasPrefix("【反馈")
}

/// 【每日推荐】那条是哪一档：第一行「｜」后面的字（早上 / 午后 / 傍晚）
func recommendSlot(_ text: String) -> String? {
    guard text.hasPrefix("【每日推荐】") else { return nil }
    let head = text.dropFirst(6).prefix(while: { $0 != "\n" })
    guard let bar = head.lastIndex(of: "｜") else { return nil }
    let slot = head[head.index(after: bar)...].trimmingCharacters(in: .whitespaces)
    return slot.isEmpty ? nil : slot
}

/// 解析服务器发给 P-Health 的「【待办提交】」消息
struct TodoSubmitNote {
    let title: String
    let content: String
    init?(_ text: String) {
        guard text.hasPrefix("【待办提交】") else { return nil }
        let first = text.split(separator: "\n", maxSplits: 1).first.map(String.init) ?? ""
        var t = first.components(separatedBy: "｜").dropFirst().first ?? "待办"
        if let r = t.range(of: "（", options: .backwards) { t = String(t[..<r.lowerBound]) }
        title = t
        var c = ""
        if let r = text.range(of: "用户在待办卡里提交：") {
            c = String(text[r.upperBound...].prefix { $0 != "\n" })
        }
        c = c.replacingOccurrences(of: "文字：", with: "")
        content = c.isEmpty ? "（提交了一次）" : c.replacingOccurrences(of: "；", with: " · ")
    }
}

// MARK: - 工具调用行（阶段性反馈：看到 Agent 在调用什么）
struct ActivityRowItem: Identifiable {
    var id: String { key }
    let key: String
    var label: String
    var done: Bool
}

/// 正在做的事 → 一个细线小图标（不写字；字只留给读屏）。
/// 认的是 actionLabel / commandLabel 给出的话，P-Health 自己写的中文说明按关键字归类，都不认识就是「…」
func toolGlyph(_ label: String) -> String {
    let t = label
    func has(_ words: String...) -> Bool { words.contains { t.contains($0) } }
    if has("等待") { return "hand.raised" }
    if has("照片", "图片") { return "photo" }
    if has("提醒") { return "bell" }
    if has("视频", "跟练", "素材", "出片", "剪") { return "film" }
    if has("查资料", "搜", "网上", "文献") { return "magnifyingglass" }
    if has("翻") { return "doc.text" }      // 翻记录、翻记忆、翻做法说明：是在读
    if has("记", "写", "加", "改", "删", "排", "定", "同步", "卡") { return "square.and.pencil" }
    if has("数据", "睡眠", "图表", "基线", "常态", "对比", "异常", "晨报", "周报", "情况", "心率", "恢复", "步数", "全不全") {
        return "chart.xyaxis.line"
    }
    if has("看") { return "doc.text" }
    return "ellipsis"
}

/// 工具调用换成给老大看的话。P-Health 给 bash 写了中文说明（description）就直接用；
/// 没写或写成英文，就按 ./pivis-health 的子命令翻译；都不认识才说「处理中」。
func actionLabel(_ name: String, _ arguments: String? = nil) -> String {
    let n = name.lowercased()
    var args: [String: Any] = [:]
    if let a = arguments, let d = a.data(using: .utf8),
       let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] { args = o }
    if n.contains("bash") || n.contains("shell") || n.contains("exec") || n.contains("command") {
        if let desc = args["description"] as? String, isUserFacing(desc) { return desc }
        if let cmd = args["command"] as? String { return commandLabel(cmd) }
        return "处理中"
    }
    if n.contains("image") { return "看照片" }
    if n.contains("schedule") { return "设提醒" }
    if n.contains("skill") { return "翻做法说明" }
    if n.contains("web") || n.contains("search") || n.contains("fetch") { return "查资料" }
    if n.contains("write") || n.contains("edit") { return "写下记录" }
    if n.contains("read") || n.contains("grep") || n.contains("glob") || n.contains("list") { return "翻看记录" }
    return "处理中"
}

/// 中文、够短，才当成说给老大听的话
private func isUserFacing(_ s: String) -> Bool {
    let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !t.isEmpty, t.count <= 14 else { return false }
    return t.unicodeScalars.contains { (0x4E00...0x9FFF).contains($0.value) }
}

private let pivisCommandLabels: [String: String] = [
    "facts": "看今天的数据", "series": "看历史数据", "baseline": "看你的常态范围", "compare": "跟基线对比",
    "viz": "算图表的数", "today": "看今天的情况", "sleep": "看睡眠数据", "v2-page": "看页面数据",
    "morning-report": "看晨报", "weekly-report": "看周报", "monitor": "检查有没有异常", "coverage": "看数据全不全",
    "answer": "记下你的回答", "log": "记一笔", "todo-list": "看今天的待办", "todo-add": "加一条待办",
    "todo-update": "改待办", "todo-remove": "删掉一条待办", "project-set": "改计划", "project-list": "看计划",
    "media-library": "找跟练素材", "relax-library": "找放松素材", "relax-plan": "排放松安排", "relax-rate": "记下评价",
    "params-list": "看设置", "params-set": "改设置", "context-list": "翻记忆", "dialogue-list": "看对话偏好",
    "dialogue-add": "记下对话规则", "page-v3": "看页面", "publish-v3": "重排页面", "daily-review": "过一遍今天",
    "now": "看时间", "prefs-sync": "同步偏好", "doctor": "检查数据源", "rules-list": "看提醒规则",
    "rules-add": "加提醒规则", "rules-remove": "删提醒规则", "push": "发提醒", "need-feedback": "记下反馈",
]

func commandLabel(_ cmd: String) -> String {
    let parts = cmd.split(whereSeparator: { $0 == " " || $0 == "\n" || $0 == ";" || $0 == "&" })
    if let i = parts.firstIndex(where: { $0.hasSuffix("pivis-health") }), i + 1 < parts.count {
        let sub = String(parts[i + 1])
        if sub == "context-record" { return cmd.contains("pref.") ? "记下你的偏好" : "记到记忆里" }
        if sub == "follow", i + 2 < parts.count {
            return ["fetch": "下载原片", "analyze": "识别动作和讲解", "make": "开始制作跟练视频",
                    "build": "重新制作跟练视频", "job": "查看视频生成进度", "verify": "验收跟练视频",
                    "cut": "剪辑动作示范", "lib": "查找动作素材", "session": "查看跟练课程"][String(parts[i + 2])] ?? "处理跟练视频"
        }
        return pivisCommandLabels[sub] ?? "查数据"
    }
    return "处理中"
}

// MARK: - 输入中指示：简短文字说明当前阶段，和图标一起显示。
struct TypingRow: View {
    var tool: String? = nil
    var responding = false
    var body: some View {
        HStack(alignment: .center, spacing: E.chatTextInset - E.avatarSize) {
            EAvatar(active: true, size: E.avatarSize)
            HStack(spacing: 7) {
                if let tool, !tool.isEmpty {
                    phaseGlyph(toolGlyph(tool))
                        .accessibilityHidden(true)
                    Text(tool)
                        .accessibilityIdentifier("chat-tool")
                } else {
                    phaseGlyph(responding ? "ellipsis.bubble" : "ellipsis")
                        .accessibilityHidden(true)
                    Text(responding ? "正在整理回复" : "正在想怎么帮你")
                        .accessibilityIdentifier("chat-phase")
                }
            }
            .font(E.body(13))
            .foregroundStyle(E.text2)
            .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
        .accessibilityIdentifier("chat-activity")
    }

    private func phaseGlyph(_ symbol: String) -> some View {
        Image(systemName: symbol)
            .font(.system(size: 13, weight: .light))
            .foregroundStyle(E.text2)
            .contentTransition(.symbolEffect(.replace))     // 换一件事：图标原地换，不跳
            .frame(width: 20, height: 20)
            .animation(.easeOut(duration: 0.25), value: symbol)
    }
}

/// P-Health 头像：细线圆圈里的 Pivis 莫比乌斯（收束线）；回复中一个白点沿环走
struct EAvatar: View {
    var active = false
    var size: CGFloat = 28
    var body: some View {
        ZStack {
            Circle().strokeBorder(E.text.opacity(active ? 0.6 : 0.3), lineWidth: 1)
            MobiusMark(lineWidth: 0.9, active: active, strands: size < 34 ? 2 : 4)
                .frame(width: size * 0.74)
        }
        .frame(width: size, height: size)
        .animation(.easeOut(duration: 0.3), value: active)
        .accessibilityHidden(true)
    }
}

/// 卡片答过了：一个细线对勾 + 答的内容（不再写「已回答：」「你选了：」「已提交」）
struct AnsweredMark: View {
    var answer: String? = nil
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: "checkmark").font(.system(size: 11, weight: .light))
            if let a = answer, !a.isEmpty, a != "已回答" {
                Text(a).font(E.body(12)).fixedSize(horizontal: false, vertical: true)
            }
        }
        .foregroundStyle(E.text3)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(answer.map { $0 == "已回答" ? "已回答" : "已回答：\($0)" } ?? "已提交")
    }
}

// MARK: - DSH 交互卡（授权请求 / 主动提问）
struct InteractionCardView: View {
    let request: InteractionRequest
    /// value：approval 传 "allowed-once"/"rejected"/"cancelled"；questions 传 answers 字典
    let onAnswer: (Any?) -> Void

    var body: some View {
        switch request.kind {
        case .approval(let tool, let reason):
            ApprovalCard(tool: tool, reason: reason, onAnswer: onAnswer)
        case .questions(let header, let items):
            QuestionsCard(header: header, items: items, onAnswer: onAnswer)
        }
    }
}

private struct ApprovalCard: View {
    let tool: String
    let reason: String
    let onAnswer: (Any?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("P-Health 需要你允许一次操作").font(E.body(16)).foregroundStyle(E.text)
            Text(tool).font(E.body(13)).foregroundStyle(E.text2)
            if !reason.isEmpty { Text(reason).font(E.body(13)).foregroundStyle(E.text3) }
            HStack(spacing: 4) {
                OutlinePill(title: "允许一次", width: nil) { onAnswer("allowed-once") }
                QuietButton(title: "拒绝") { onAnswer("rejected") }
                QuietButton(title: "取消") { onAnswer("cancelled") }
            }
        }
        .padding(E.cardPad)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: E.cardRadius).strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
    }
}

private struct QuestionsCard: View {
    let header: String?
    let items: [InteractionRequest.QuestionItem]
    let onAnswer: (Any?) -> Void
    @State private var values: [String: GenValue] = [:]
    @State private var sent = false

    private var fields: [GenField] {
        items.map { item in
            GenField(id: item.id, type: item.options.isEmpty ? "text" : (item.multiSelect ? "multi" : "options"),
                     label: item.question, options: item.options.map { ($0.label, $0.label) },
                     placeholder: item.detail, allowText: false)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(header ?? "P-Health 想问你").font(E.body(16)).foregroundStyle(E.text)
            ForEach(fields) { f in
                GenFieldView(field: f, value: Binding(get: { values[f.id] }, set: { values[f.id] = $0 }))
            }
            if !sent {
                OutlinePill(title: "提交", width: 112) { submit() }
                    .disabled(!canSubmit).opacity(canSubmit ? 1 : 0.4)
            } else {
                AnsweredMark()
            }
        }
        .padding(E.cardPad)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: E.cardRadius).strokeBorder(E.stroke, lineWidth: 1).allowsHitTesting(false))
        .disabled(sent)
    }

    private var canSubmit: Bool { fields.allSatisfy { values[$0.id].map { !$0.isEmpty } ?? false } }

    private func submit() {
        sent = true
        let answers: [[String: Any]] = fields.map { f in
            var entry: [String: Any] = ["id": f.id]
            switch values[f.id] {
            case .choice(let s): entry["selected"] = [s]
            case .multi(let set): entry["selected"] = Array(set).sorted()
            case .text(let t): entry["selected"] = [String](); entry["custom"] = t
            case .scale(let n): entry["selected"] = ["\(n)"]
            case .photo, .none: entry["selected"] = [String]()
            }
            return entry
        }
        onAnswer(["answers": answers])
    }
}

// MARK: - 生成式 UI 协议解析
enum GenSeg {
    case text(String)
    case card(GenCard)
}

struct GenCard: Decodable {
    let type: String?
    let title: String?
    let description: String?
    let summary: String?
    let options: [GenLooseOption]?
    let steps: [GenStep]?
    let scale: Int?
    let yes: String?
    let no: String?
    let confirmLabel: String?
    let label: String?
    let value: String?
    let unit: String?
    let note: String?
    let tone: String?
    let columns: [String]?
    let rows: [[String]]?
    let points: [GenPoint]?
    let low: Double?
    let high: Double?
    let target: Double?
    let url: String?
    let mediaType: String?  // embed / video / audio
    let kind: String?
    let poster: String?
    /// 表情卡 {"type":"sticker","name":"抱抱"}
    let name: String?
    // v3：question / plan / receipt / list
    let fields: [GenFieldSpec]?
    let submitLabel: String?
    let items: [GenItem]?
    let rules: [String]?
    let actions: [String]?
    let change: String?
    let effective: String?
    let remembered: Bool?
    // viz：主卡同款图表预览（数字由服务器内核算）
    let metric: String?
    let days: Int?
    let show: [String]?
    /// type=layout 时：零件树原文（解析时填）
    var layoutRaw: Data? = nil

    private enum CodingKeys: String, CodingKey {
        case type, title, description, summary, options, steps, scale, yes, no, confirmLabel, label, value, unit, note, tone
        case columns, rows, points, low, high, target, url, mediaType, kind, poster
        case fields, submitLabel, items, rules, actions, change, effective, remembered
        case metric, days, show, name
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func str(_ k: CodingKeys) -> String? {
            if let s = try? c.decodeIfPresent(String.self, forKey: k) { return s }
            if let d = try? c.decodeIfPresent(Double.self, forKey: k) {
                return d == d.rounded() ? String(Int(d)) : String(d)
            }
            return nil
        }
        type = str(.type); title = str(.title); description = str(.description); summary = str(.summary)
        options = try? c.decodeIfPresent([GenLooseOption].self, forKey: .options)
        steps = try? c.decodeIfPresent([GenStep].self, forKey: .steps)
        scale = try? c.decodeIfPresent(Int.self, forKey: .scale)
        yes = str(.yes); no = str(.no); confirmLabel = str(.confirmLabel)
        label = str(.label); value = str(.value); unit = str(.unit); note = str(.note); tone = str(.tone)
        columns = try? c.decodeIfPresent([String].self, forKey: .columns)
        rows = try? c.decodeIfPresent([[String]].self, forKey: .rows)
        points = try? c.decodeIfPresent([GenPoint].self, forKey: .points)
        low = try? c.decodeIfPresent(Double.self, forKey: .low)
        high = try? c.decodeIfPresent(Double.self, forKey: .high)
        target = try? c.decodeIfPresent(Double.self, forKey: .target)
        url = str(.url); mediaType = str(.mediaType); kind = str(.kind); poster = str(.poster)
        fields = try? c.decodeIfPresent([GenFieldSpec].self, forKey: .fields)
        submitLabel = str(.submitLabel)
        items = try? c.decodeIfPresent([GenItem].self, forKey: .items)
        rules = try? c.decodeIfPresent([String].self, forKey: .rules)
        actions = try? c.decodeIfPresent([String].self, forKey: .actions)
        change = str(.change); effective = str(.effective)
        remembered = try? c.decodeIfPresent(Bool.self, forKey: .remembered)
        metric = str(.metric)
        days = (try? c.decodeIfPresent(Int.self, forKey: .days)) ?? str(.days).flatMap { Int($0) }
        show = try? c.decodeIfPresent([String].self, forKey: .show)
        name = str(.name)
    }

    /// 方案 / 确认卡上的按钮字（点了发「字（标题）」）
    var buttonLabels: [String] {
        switch (type ?? "").lowercased() {
        case "confirm": return [yes ?? "对", no ?? "不对"]
        case "plan": return actions ?? [confirmLabel ?? "就这样", "改一下"]
        default: return []
        }
    }
}

/// 选项：字符串或 {id,label,hint}
struct GenLooseOption: Decodable, Hashable {
    let id: String
    let label: String
    let hint: String?
    init(from decoder: Decoder) throws {
        if let s = try? decoder.singleValueContainer().decode(String.self) { id = s; label = s; hint = nil; return }
        let c = try decoder.container(keyedBy: K.self)
        let l = (try? c.decode(String.self, forKey: .label)) ?? (try? c.decode(String.self, forKey: .id)) ?? ""
        label = l
        id = (try? c.decode(String.self, forKey: .id)) ?? l
        hint = try? c.decode(String.self, forKey: .hint)
    }
    enum K: String, CodingKey { case id, label, hint }
}

/// 清单项 / 方案项：字符串或 {when,title,note}
struct GenItem: Decodable, Hashable {
    let when: String?
    let title: String
    let note: String?
    init(from decoder: Decoder) throws {
        if let s = try? decoder.singleValueContainer().decode(String.self) { when = nil; title = s; note = nil; return }
        let c = try decoder.container(keyedBy: K.self)
        when = try? c.decode(String.self, forKey: .when)
        title = (try? c.decode(String.self, forKey: .title)) ?? (try? c.decode(String.self, forKey: .label)) ?? ""
        note = try? c.decode(String.self, forKey: .note)
    }
    enum K: String, CodingKey { case when, title, label, note }
}

struct GenFieldSpec: Decodable, Hashable {
    let id: String?
    let label: String?
    let type: String?
    let options: [GenLooseOption]?
    let min: Int?
    let max: Int?
    let minLabel: String?
    let maxLabel: String?
    let unit: String?
    let placeholder: String?
    let allowText: Bool?

    func field(_ idx: Int) -> GenField {
        GenField(id: id ?? "f\(idx)", type: type ?? ((options ?? []).isEmpty ? "text" : "options"), label: label ?? "",
                 options: (options ?? []).map { ($0.id, $0.label) }, min: min ?? 1, max: max ?? 5,
                 minLabel: minLabel, maxLabel: maxLabel, unit: unit, placeholder: placeholder, allowText: allowText ?? false)
    }
}

struct GenStep: Decodable {
    let title: String?
    let durationMin: Int?
    let url: String?
}

struct GenPoint: Decodable {
    let label: String
    let value: Double
    let group: String?
}

/// 解析结果按原文缓存：同一条消息每次刷新都要解析（卡片还要解 JSON），缓存后只算一次
final class MemoBox<T>: NSObject { let value: T; init(_ v: T) { value = v } }

enum GenParser {
    private static let cache: NSCache<NSString, MemoBox<[GenSeg]>> = { let c = NSCache<NSString, MemoBox<[GenSeg]>>(); c.countLimit = 300; return c }()

    static func parse(_ text: String) -> [GenSeg] {
        if let hit = cache.object(forKey: text as NSString) { return hit.value }
        let out = parseUncached(text)
        cache.setObject(MemoBox(out), forKey: text as NSString)
        return out
    }

    private static func parseUncached(_ text: String) -> [GenSeg] {
        var out: [GenSeg] = []
        var rest = text
        while let range = rest.range(of: "```phealth-ui") {
            let head = String(rest[rest.startIndex..<range.lowerBound])
            if !head.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                out.append(.text(head))
            }
            let after = rest[range.upperBound...]
            guard let end = after.range(of: "```") else {
                out.append(.text(String(rest[range.lowerBound...])))
                rest = ""
                break
            }
            let json = after[after.startIndex..<end.lowerBound]
            if let data = json.data(using: .utf8),
               var card = try? PivisAPI.decoder.decode(GenCard.self, from: data) {
                // 画布卡：把零件树原样留着，交给服务器校验、现算
                if (card.type ?? "").lowercased() == "layout",
                   let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    let root: Any? = obj["layout"] ?? obj["children"].map { ["t": "v", "children": $0] as [String: Any] }
                    if let root, let d = try? JSONSerialization.data(withJSONObject: root) { card.layoutRaw = d }
                }
                out.append(.card(card))
            } else {
                // 卡片 JSON 写坏了：不把原始代码露给老大，留一句话。
                // （以前这里用闭区间 ...end.upperBound 截原文，卡片正好在消息最后时越界，打开对话就闪退）
                out.append(.text("〔这张卡格式有误，没画出来〕"))
            }
            rest = String(after[end.upperBound...])
        }
        if !rest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            out.append(.text(rest))
        }
        return out
    }
}

// MARK: - 生成式卡片：和页面同一套 E 留白风格；Agent 只决定内容，不决定样式
struct GenCardView: View {
    let card: GenCard
    let onAction: (String) -> Void
    @State private var values: [String: GenValue] = [:]
    @State private var submitted: String?
    /// 历史里已经回答过（下一条用户消息），重开对话后卡片仍保持锁定
    var answered: String? = nil
    private var done: String? { submitted ?? answered }

    private var type: String { (card.type ?? "").lowercased() }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title = card.title, !title.isEmpty, type != "receipt" {
                Text(title).font(E.body(16)).foregroundStyle(E.text).fixedSize(horizontal: false, vertical: true)
            }
            if let desc = card.description ?? card.summary, !desc.isEmpty, type != "receipt" {
                Text(desc).font(E.body(13)).foregroundStyle(E.text2).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
            }
            content
        }
        .padding(.vertical, 14)
        .padding(.horizontal, E.cardPad)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: E.cardRadius).strokeBorder(type == "receipt" ? E.stroke : E.line, lineWidth: 1).allowsHitTesting(false))
        .accessibilityIdentifier("gen-\(type)")
    }

    @ViewBuilder
    private var content: some View {
        switch type {
        case "question":
            questionBody(card.fields?.enumerated().map { $0.element.field($0.offset) } ?? [])
        case "options", "decision", "decisioncard":
            let opts = card.options ?? []
            questionBody([GenField(id: "choice", type: "options", label: "", options: opts.map { ($0.id, $0.label) })], autoSubmit: true)
        case "rating":
            questionBody([GenField(id: "rating", type: "scale", label: "", min: 1, max: max(2, min(card.scale ?? 5, 10)))], autoSubmit: true)
        case "plan":
            planBody
        case "confirm":
            actionRow(card.buttonLabels)
        case "receipt":
            receiptBody
        case "metric", "stat", "stat_tile", "stattile", "list":
            // 和主卡、画布卡同一套零件画（不再各写一份）
            if let n = GenCanvas.node(card, type: type) { CanvasView(node: n) }
        case "table", "datatable":
            if (card.rows ?? []).isEmpty { Text("暂无数据").font(E.body(12)).foregroundStyle(E.text3) }
            else if let n = GenCanvas.node(card, type: type) { CanvasView(node: n) }
        case "chart", "bar_chart", "groupcompare", "attributionbar", "line_chart", "bandline":
            if (card.points ?? []).isEmpty {
                Text("样本不足").font(E.body(12)).foregroundStyle(E.text3)
            } else if let n = GenCanvas.node(card, type: type) {
                CanvasView(node: n)          // 柱状、没有上下限带：画布的 columns 零件
            } else {
                // 折线、带上下限的图画布零件画不了：留着 Swift Charts 画
                GenChart(points: card.points ?? [], kind: GenCanvas.isLine(card, type: type) ? .line : .bar,
                         low: card.low, high: card.high, target: card.target)
            }
        case "media", "mediacard":
            GenMediaView(card: card)
        case "viz":
            VizPreview(metric: card.metric ?? "", kind: card.kind, days: card.days, show: card.show)
        case "layout":
            if let raw = card.layoutRaw { CanvasCard(raw: raw) }
            else { Text("这张卡没有内容").font(E.body(12)).foregroundStyle(E.text3) }
        default:
            Text("这张卡片暂时显示不了（\(card.type ?? "unknown")）").font(E.body(12)).foregroundStyle(E.text3)
        }
    }

    // 问题卡：选项 / 打分 / 数字 / 文字；提交后锁定
    @ViewBuilder
    private func questionBody(_ fields: [GenField], autoSubmit: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(fields) { f in
                GenFieldView(field: f, value: Binding(get: { values[f.id] }, set: { values[f.id] = $0 }),
                             onPick: autoSubmit && fields.count == 1 ? { submitQuestion(fields) } : nil)
            }
            if done == nil && !(autoSubmit && fields.count == 1) {
                OutlinePill(title: card.submitLabel ?? "确定", width: 112) { submitQuestion(fields) }
                    .disabled(!fields.allSatisfy { f in f.type == "text" || (values[f.id].map { !$0.isEmpty } ?? false) })
                    .opacity(fields.allSatisfy { f in f.type == "text" || (values[f.id].map { !$0.isEmpty } ?? false) } ? 1 : 0.4)
                    .accessibilityIdentifier("gen-question-submit")
            }
            if let submitted = done {
                AnsweredMark(answer: submitted)
            }
        }
        .disabled(done != nil)
        .opacity(done != nil ? 0.6 : 1)
    }

    private func submitQuestion(_ fields: [GenField]) {
        guard done == nil else { return }
        let parts = fields.compactMap { f -> String? in
            guard let v = values[f.id], !v.isEmpty else { return nil }
            let label = f.label.trimmingCharacters(in: CharacterSet(charactersIn: "？?：: "))
            return label.isEmpty ? v.display(f) : "\(label) \(v.display(f))"
        }
        guard !parts.isEmpty else { return }
        let answer = parts.joined(separator: " · ")
        submitted = answer
        let head = (card.title ?? "").isEmpty ? "回答" : "回答「\(card.title!)」"
        onAction("raw:\(head)：\(answer)")
    }

    private var planBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            let items = card.items ?? []
            ForEach(Array(items.enumerated()), id: \.offset) { _, it in
                // 和待办行同一套「时间 · 标题」尺寸
                TimeTitleRow(when: it.when ?? "·", title: it.title, note: it.note, noteLines: nil)
                    .padding(.vertical, 10)
                    .overlay(alignment: .top) { Hairline(color: E.line2) }
            }
            ForEach(Array((card.steps ?? []).enumerated()), id: \.offset) { i, st in
                HStack(spacing: 12) {
                    Text("\(i + 1)").font(E.light(15)).foregroundStyle(E.text3).frame(width: 20)
                    Text(st.title ?? "").font(E.body(15)).foregroundStyle(E.text)
                    Spacer()
                    if let d = st.durationMin { Text("\(d) 分钟").font(E.body(12)).foregroundStyle(E.text3) }
                }
                .padding(.vertical, 10)
                .overlay(alignment: .top) { Hairline(color: E.line2) }
            }
            if let rules = card.rules, !rules.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(rules.enumerated()), id: \.offset) { i, r in
                        HStack(alignment: .top, spacing: 12) {
                            Text("\(i + 1)").font(E.light(14)).foregroundStyle(E.text3).frame(width: 14)
                            Text(r).font(E.body(14)).foregroundStyle(E.text2).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(.vertical, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .top) { Hairline(color: E.line2) }
            }
            actionRow(card.actions ?? [card.confirmLabel ?? "就这样", "改一下"])
                .padding(.top, 12)
        }
    }

    @ViewBuilder
    private func actionRow(_ actions: [String]) -> some View {
        if let submitted = done {
            AnsweredMark(answer: submitted)
        } else {
            HStack(spacing: 4) {
                ForEach(Array(actions.enumerated()), id: \.offset) { i, a in
                    if i == 0 {
                        OutlinePill(title: a, width: nil) { pick(a) }.accessibilityIdentifier("gen-plan-primary")
                    } else {
                        QuietButton(title: a) { pick(a) }
                    }
                }
            }
        }
    }

    private func pick(_ action: String) {
        guard done == nil else { return }
        submitted = action
        let title = card.title ?? ""
        onAction("raw:" + (title.isEmpty ? action : "\(action)（\(title)）"))
    }

    private var receiptBody: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "checkmark").font(.system(size: 12, weight: .regular))
                Text(card.title ?? "已改动").font(E.medium(14))
            }
            .foregroundStyle(E.text)
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                if let c = card.change { GridRow { Text("改了").foregroundStyle(E.text3); Text(c).foregroundStyle(E.text) } }
                if let e = card.effective { GridRow { Text("生效").foregroundStyle(E.text3); Text(e).foregroundStyle(E.text) } }
                if let r = card.remembered { GridRow { Text("记住").foregroundStyle(E.text3); Text(r ? "已记住，以后不用再说" : "只这一次").foregroundStyle(E.text) } }
            }
            .font(E.body(13))
        }
    }

}

/// 对话里的老卡片 → 画布零件（metric → value、table → table、list → list、柱状 chart → columns）。
/// 画布画不了的（折线、带上下限的图）返回 nil，留给 GenChart
enum GenCanvas {
    static func isLine(_ card: GenCard, type: String) -> Bool {
        (card.kind ?? "") == "line" || type == "line_chart" || type == "bandline"
    }

    static func node(_ card: GenCard, type: String) -> CNode? {
        switch type {
        case "metric", "stat", "stat_tile", "stattile":
            var root = CNode("v", id: "card")
            root.gap = 4
            var value = CNode("value", id: "card.0")
            value.label = card.label
            value.text = card.value ?? "—"
            value.unit = card.unit
            var kids = [value]
            if let note = card.note, !note.isEmpty {
                var t = CNode("text", id: "card.1")
                t.text = note
                t.role = "caption"
                t.tone = 3
                kids.append(t)
            }
            root.children = kids
            return root
        case "table", "datatable":
            return .table(card.columns ?? [], card.rows ?? [], id: "card")
        case "list":
            var n = CNode("list", id: "card")
            n.style = card.kind == "bullet" ? "bullet" : "number"
            n.items = (card.items ?? []).enumerated().map { CItem(id: "card.\($0.offset)", text: $0.element.title, note: $0.element.note) }
            return n
        default:
            // 柱状图（没有上下限带）：columns 零件，最后一根实心、顶上写数，目标是虚线
            guard !isLine(card, type: type), card.low == nil, card.high == nil else { return nil }
            let pts = card.points ?? []
            var n = CNode("columns", id: "card")
            n.height = "m"
            n.ref = card.target
            n.items = pts.enumerated().map { i, p in
                CItem(id: "card.\(i)", text: i == pts.count - 1 ? pnum(p.value) : nil, value: p.value, label: p.label,
                      on: i == pts.count - 1)
            }
            return n
        }
    }
}

struct GenMediaView: View {
    let card: GenCard
    @State private var embedFailed = false
    @State private var embedLoaded = false

    private var kind: String { (card.mediaType ?? "").lowercased() }

    /// B 站 / YouTube 的页面链接不是视频文件，不管写的是 video 还是 embed 都用网页播放器
    private func isPage(_ url: URL) -> Bool {
        let host = url.host?.lowercased() ?? ""
        return host.contains("bilibili") || host.contains("b23.tv") || host.contains("youtube") || host.contains("youtu.be")
    }

    var body: some View {
        if let url = PivisAPI.resolve(card.url), let scheme = url.scheme?.lowercased(),
           scheme == "http" || scheme == "https" {
            let media = V3Media(kind: kind.isEmpty ? "video" : kind, url: card.url ?? "", title: card.title,
                                durationMin: nil, poster: card.poster)
            if media.isFollowVideo {
                // P-Health 自己做的跟练视频：和习惯卡、待办卡同一个播放器（先封面，点了就地播）
                OwnedPracticeVideo(media: media)
            } else {
                let embed = kind == "embed" || isPage(url) || (!isDirectFile(url) && kind != "video" && kind != "audio")
                let target = embed ? Self.embedURL(url) : url
                VStack(spacing: 8) {
                    Group {
                        if embed {
                            ZStack {
                                EmbeddedWebView(url: target, hasError: $embedFailed, isLoaded: $embedLoaded)
                                if embedFailed {
                                    VStack(spacing: 8) {
                                        Image(systemName: "wifi.exclamationmark").font(.system(size: 20, weight: .light))
                                        Text("当前网络无法加载在线视频").font(E.body(12))
                                        Text("可点击下方链接在浏览器中打开").font(E.body(11))
                                    }
                                    .foregroundStyle(E.text3)
                                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                                    .background(Color.black)
                                }
                            }
                            .onAppear {
                                DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
                                    if !embedLoaded { embedFailed = true }
                                }
                            }
                        } else {
                            NativePlayerView(url: target)
                        }
                    }
                    .frame(height: kind == "audio" ? 130 : 215)
                    .clipShape(RoundedRectangle(cornerRadius: E.mediaRadius, style: .continuous))
                    .background(Color.black, in: RoundedRectangle(cornerRadius: E.mediaRadius, style: .continuous))
                    Link("在浏览器中打开 ↗", destination: url)
                        .font(E.body(12)).foregroundStyle(E.text2)
                }
            }
        } else {
            Text("媒体链接无效").font(E.body(12)).foregroundStyle(E.text3)
        }
    }

    private func isDirectFile(_ url: URL) -> Bool {
        let directExtensions = ["mp4", "mov", "m4v", "m3u8", "mp3", "m4a", "aac", "wav", "flac"]
        if directExtensions.contains(url.pathExtension.lowercased()) { return true }
        if kind == "video" || kind == "audio" {
            let host = url.host?.lowercased() ?? ""
            return !host.contains("bilibili") && !host.contains("b23.tv")
        }
        return false
    }

    static func embedURL(_ url: URL) -> URL {
        let host = url.host?.lowercased() ?? ""
        if host.contains("bilibili.com") {
            let id = url.pathComponents.first(where: { $0.hasPrefix("BV") })
            if let id {
                return URL(string: "https://player.bilibili.com/player.html?bvid=\(id)&autoplay=0") ?? url
            }
        }
        return url
    }
}

struct NativePlayerView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> AVPlayerViewController {
        let controller = AVPlayerViewController()
        controller.view.accessibilityIdentifier = "native-media-player-\(url.pathExtension.lowercased())"
        let player = AVPlayer(url: VideoCache.cacheable(url) ? VideoCache.shared.playableURL(for: url) : url)
        // 锁屏 / 切到后台：声音接着放（睡前躺下可以锁屏只听），回来接着放画面
        player.audiovisualBackgroundPlaybackPolicy = .continuesIfPossible
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
        controller.player = player
        controller.showsPlaybackControls = true
        controller.allowsPictureInPicturePlayback = true
        controller.videoGravity = .resizeAspect
        return controller
    }

    func updateUIViewController(_ controller: AVPlayerViewController, context: Context) {}
}

struct EmbeddedWebView: UIViewRepresentable {
    let url: URL
    @Binding var hasError: Bool
    @Binding var isLoaded: Bool

    func makeCoordinator() -> Coordinator { Coordinator(hasError: $hasError, isLoaded: $isLoaded) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.scrollView.backgroundColor = .black
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard !hasError else { return }
        if webView.url != url {
            hasError = false
            isLoaded = false
            webView.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        @Binding var hasError: Bool
        @Binding var isLoaded: Bool
        init(hasError: Binding<Bool>, isLoaded: Binding<Bool>) {
            _hasError = hasError
            _isLoaded = isLoaded
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            guard let current = webView.url, current.absoluteString != "about:blank" else { return }
            isLoaded = true
            hasError = false
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            fail(error)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            fail(error)
        }

        private func fail(_ error: Error) {
            if (error as NSError).code == NSURLErrorCancelled { return }
            hasError = true
        }
    }
}

/// 对话里的折线 / 带上下限的图（画布零件画不了的这两种才用它）
struct GenChart: View {
    enum Kind { case bar, line }
    let points: [GenPoint]
    let kind: Kind
    var low: Double? = nil
    var high: Double? = nil
    var target: Double? = nil

    var body: some View {
        if points.isEmpty {
            Text("样本不足").font(E.body(12)).foregroundStyle(E.text3)
        } else {
            Chart {
                ForEach(Array(points.enumerated()), id: \.offset) { i, point in
                    if kind == .bar {
                        BarMark(x: .value("项", point.label), y: .value("值", point.value), width: .fixed(10))
                            .foregroundStyle(i == points.count - 1 ? E.text : E.grey4A)
                    } else {
                        LineMark(x: .value("项", point.label), y: .value("值", point.value))
                            .foregroundStyle(E.text).lineStyle(StrokeStyle(lineWidth: 1.2))
                        PointMark(x: .value("项", point.label), y: .value("值", point.value))
                            .foregroundStyle(E.text).symbolSize(14)
                    }
                }
                if let target {
                    RuleMark(y: .value("目标", target)).foregroundStyle(E.text3)
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
                }
                if let low, let high {
                    RectangleMark(yStart: .value("低", low), yEnd: .value("高", high))
                        .foregroundStyle(E.line)
                }
            }
            .chartYAxis { AxisMarks(position: .trailing) { _ in AxisValueLabel().foregroundStyle(E.text3).font(E.body(10)) } }
            .chartXAxis { AxisMarks { _ in AxisValueLabel().foregroundStyle(E.text3).font(E.body(10)) } }
            .frame(height: 140)
        }
    }
}

// MARK: - 聊天气泡：P-Health 直接写在黑底上；我的消息是深灰气泡
struct ChatBubble: View {
    let msg: ChatMsg
    let maxWidth: CGFloat
    /// 正在流式到达：新到的字从模糊流到清楚（S2）
    var live = false

    var body: some View {
        HStack(alignment: .bottom) {
            if msg.isMe { Spacer(minLength: 40) }
            Group {
                // 可选中的 Text 不走自定义 TextRenderer：P-Health 的字流完后才在 FlowingText 里打开选中
                if msg.isMe { Text(attributedText).textSelection(.enabled) } else { FlowingText(text: attributedText, live: live) }
            }
                .font(E.body(15))
                .lineSpacing(5)
                .foregroundStyle(msg.role == "error" ? E.text2 : E.text)
                .padding(.horizontal, msg.isMe ? 14 : (msg.role == "error" ? 12 : 0))
                .padding(.vertical, msg.isMe ? 10 : (msg.role == "error" ? 8 : 2))
                .background {
                    if msg.isMe {
                        RoundedRectangle(cornerRadius: 18, style: .continuous).fill(E.grey1E)
                    } else if msg.role == "error" {
                        // 虚线框贴左边线（以前往外扩 8，伸出了对话的边）
                        RoundedRectangle(cornerRadius: 12).strokeBorder(E.stroke, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    }
                }
                .frame(maxWidth: maxWidth, alignment: msg.isMe ? .trailing : .leading)
            if !msg.isMe { Spacer(minLength: 8) }
        }
        .padding(.vertical, 2)
    }

    private var attributedText: AttributedString {
        cjkMarkdown(msg.text.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}

/// 中文友好的行内 Markdown：**加粗** 自己解析。标准 Markdown 规定「。**睡」这种
/// 标点后紧跟中文的收尾 ** 不算闭合，会把星号原样露出来；其余行内语法（链接、代码、斜体）仍交给系统解析。
private let cjkMarkdownCache: NSCache<NSString, MemoBox<AttributedString>> = { let c = NSCache<NSString, MemoBox<AttributedString>>(); c.countLimit = 400; return c }()

func cjkMarkdown(_ text: String) -> AttributedString {
    if let hit = cjkMarkdownCache.object(forKey: text as NSString) { return hit.value }
    let out = cjkMarkdownUncached(text)
    cjkMarkdownCache.setObject(MemoBox(out), forKey: text as NSString)
    return out
}

private func cjkMarkdownUncached(_ text: String) -> AttributedString {
    var opts = AttributedString.MarkdownParsingOptions()
    opts.interpretedSyntax = .inlineOnlyPreservingWhitespace
    func md(_ s: String) -> AttributedString { (try? AttributedString(markdown: s, options: opts)) ?? AttributedString(s) }
    guard text.contains("**"), let re = try? NSRegularExpression(pattern: #"\*\*(.+?)\*\*"#, options: [.dotMatchesLineSeparators]) else {
        return md(text)
    }
    let ns = text as NSString
    var out = AttributedString()
    var last = 0
    for m in re.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
        if m.range.location > last { out += md(ns.substring(with: NSRange(location: last, length: m.range.location - last))) }
        var bold = md(ns.substring(with: m.range(at: 1)))
        bold.inlinePresentationIntent = .stronglyEmphasized
        out += bold
        last = m.range.location + m.range.length
    }
    if last < ns.length { out += md(ns.substring(from: last)) }
    return out
}

/// 宽度变化时通知重新算高度
final class GrowingTextView: UITextView {
    var onWidthChange: (() -> Void)?
    private var lastWidth: CGFloat = 0
    override func layoutSubviews() {
        super.layoutSubviews()
        if abs(bounds.width - lastWidth) > 0.5 {
            lastWidth = bounds.width
            onWidthChange?()
        }
    }
}

// MARK: - 对话输入框（UIKit UITextView 封装）
/// SwiftUI 的 TextField(axis:) 对中文输入法 marked text（拼音组字）支持有缺陷：
/// 组字过程中视图一旦刷新，未确认的拼音会被吞掉。UITextView 是中文输入最稳的路径。
struct ChatInputField: UIViewRepresentable {
    @Binding var text: String
    @Binding var height: CGFloat
    var focus: Binding<Bool> = .constant(false)
    /// 变了就把输入框清空（发出去之后）。组字中也清：以前组字时一律不碰文字，发出去后整句还留在框里、框也一直是高的
    var clearSignal: Int = 0
    /// 点踩小单子里的「应该是……」也用它（中文组字稳）：标识、return 键各自给
    var identifier = "chat-input"
    var returnKey: UIReturnKeyType = .send
    var onSend: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> UITextView {
        let tv = GrowingTextView()
        // 宽度变了（第一次排好版、抽屉拉高、键盘弹起改了布局）就重新算一次高度：以前只在打字时算，宽度没就绪时算出的高度会一直留着
        tv.onWidthChange = { [weak coordinator = context.coordinator, weak tv] in
            guard let coordinator, let tv else { return }
            coordinator.syncHeight(tv)
        }
        tv.accessibilityIdentifier = identifier
        tv.font = UIFont.systemFont(ofSize: 16)
        tv.textColor = UIColor(E.text)
        tv.tintColor = .white
        tv.backgroundColor = .clear
        tv.delegate = context.coordinator
        tv.isScrollEnabled = false
        tv.isEditable = true
        tv.returnKeyType = returnKey
        tv.enablesReturnKeyAutomatically = true
        tv.autocapitalizationType = .none
        tv.autocorrectionType = .no
        tv.spellCheckingType = .no
        tv.smartQuotesType = .no
        tv.smartDashesType = .no
        tv.textContainerInset = UIEdgeInsets(top: 8, left: 14, bottom: 8, right: 14)
        tv.textContainer.lineFragmentPadding = 0
        tv.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        tv.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return tv
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        context.coordinator.parent = self
        if clearSignal != context.coordinator.lastClearSignal {
            // 刚发出去：彻底清空，连还没选字的拼音一起
            context.coordinator.lastClearSignal = clearSignal
            // 还在组字（拼音没选完）时 unmarkText 会把那段字确认进来、触发 textViewDidChange，把整句又写回绑定，
            // 下一次刷新再从绑定抄回框里：发出去的话就留在输入框里了（11-08 老大在习惯对话里碰到）。清的时候不认这次改动
            context.coordinator.clearing = true
            if uiView.markedTextRange != nil { uiView.unmarkText() }
            uiView.text = ""
            context.coordinator.clearing = false
            let binding = $text
            DispatchQueue.main.async { if uiView.text.isEmpty, !binding.wrappedValue.isEmpty { binding.wrappedValue = "" } }
        } else if uiView.markedTextRange == nil, uiView.text != text {
            // 其余时候组字（marked text）期间绝不对 text 赋值，否则输入法候选会被吞（但高度照样要算）
            uiView.text = text
        }
        if focus.wrappedValue {
            DispatchQueue.main.async {
                uiView.becomeFirstResponder()
                uiView.selectedRange = NSRange(location: (uiView.text as NSString).length, length: 0)
                focus.wrappedValue = false
            }
        }
        context.coordinator.syncHeight(uiView)
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: ChatInputField
        /// 上一次让 SwiftUI 设成的高度（不是 SwiftUI 现在的高度：那个是异步更新的，拿它比会漏掉「变回一行」）
        private var lastHeight: CGFloat = 38
        var lastClearSignal: Int
        var clearing = false
        init(_ parent: ChatInputField) { self.parent = parent; self.lastClearSignal = parent.clearSignal }

        /// 组字（marked text）未确认时return只收起候选；确认后return=发送
        func textView(_ textView: UITextView, shouldChangeTextIn range: NSRange,
                      replacementText newText: String) -> Bool {
            if newText == "\n" {
                if textView.markedTextRange == nil {
                    let t = textView.text.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !t.isEmpty {
                        // 先发送再清空：用捕获的文本发送，不依赖绑定回写时序
                        parent.onSend(t)
                        textView.text = ""
                        parent.text = ""
                        syncHeight(textView)
                    }
                }
                return false
            }
            return true
        }

        func textViewDidChange(_ textView: UITextView) {
            guard !clearing else { return }
            parent.text = textView.text
            syncHeight(textView)
        }

        /// 高度随内容增长，超过 maxH 后改为滚动。宽度未就绪时保持现状。
        /// 高度写入 SwiftUI 绑定驱动布局，不依赖 intrinsicContentSize（该值在 UITextView 上不可靠）。
        func syncHeight(_ textView: UITextView) {
            let maxH: CGFloat = 100
            let w = textView.bounds.width
            guard w > 10 else { return }
            let size = textView.sizeThatFits(CGSize(width: w, height: .greatestFiniteMagnitude))
            let newH = min(max(size.height, 38), maxH)
            textView.isScrollEnabled = size.height > maxH
            // 以前：拿 SwiftUI 当前的高度比，并且用 Task 异步设。刚变高（还没生效）时马上发送清空，
            // 「变回 38」会因为「当前还是 38」被跳过，随后迟到的「变高」生效，空输入框就一直是三行高。
            // 现在：和自己上一次要的高度比，并按顺序在主队列上设，最后一次一定是对的
            guard abs(lastHeight - newH) > 0.5 else { return }
            lastHeight = newH
            let binding = parent.$height
            DispatchQueue.main.async { binding.wrappedValue = newH }
        }
    }
}
