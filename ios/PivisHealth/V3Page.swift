import SwiftUI

// MARK: - 一个板块页：结论 → 主卡（一个问题 + 字段/小表）→ 项目（有才显示）→ 接下来（有才显示）→ 注脚
struct BoardPageView: View {
    let board: V3Board
    /// 是不是当前这一页：看不见的页收到刷新信号只记下，切过来再拉
    let visible: Bool
    @StateObject private var loader: PageLoader
    @State private var expandedTodo: String?
    @State private var showMore = false          // 此刻页「另有 N 件」展开
    @State private var scrollRequest: String?   // 从小组件点进来时滚到那张卡
    @State private var pendingExpand: String?   // 冷启动时页面还没拉到：拉到后再展开
    @State private var poller: Task<Void, Never>?
    @State private var toast: String?
    /// 下拉刷新后顶上的两个小圆点（WHOOP / Apple 健康）；token 防止上一次的淡出把这次的提前收掉
    @State private var syncDots: HealthDots?
    @State private var syncDotsToken = UUID()
    @State private var showWhoopLogin = false
    @ObservedObject private var sync = PageSync.shared
    @ObservedObject private var link = ServerLink.shared
    @State private var heroHold = false

    init(board: V3Board, visible: Bool) {
        self.board = board
        self.visible = visible
        _loader = StateObject(wrappedValue: PageLoader(page: board.id))
    }

    private var doc: V3Page? { loader.doc }
    private var fetchedAt: Date { loader.fetchedAt }
    /// 此刻页的待办（todos + more）就是所有板块今天的待办：所有板块的提醒都按它排，所以它看不见也照常拉
    private var isReminderSource: Bool { board.id == "now" }

    /// 这页的主卡正在被重排（P-Health 按偏好改、或者今天还没排）：主卡进入加载态，排好自动换上
    private var heroUpdating: Bool { doc?.stale == true || sync.isUpdating(board.id) || Self.glowTest }
    /// 测试（仅模拟器回放）：-glowTest 让四页主卡一直处在「正在改」，用来量动效的开销
    private static let glowTest = Profile.isSim && ProcessInfo.processInfo.arguments.contains("-glowTest")
    /// 服务器说排好了到新主卡真正拉下来之间有一小段：这段也保持框住，免得旧卡先清楚一下再换
    private var heroGlow: Bool { heroUpdating || heroHold }
    /// 新主卡到了就换一个 id，淡入并重画图
    private var heroKey: String { (doc?.publication?.publishedAt ?? "") + (doc?.hero.viz?.kind ?? "") + (doc?.hero.value ?? "") }

    var body: some View {
        ScrollViewReader { scroller in
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                header
                // P-Health 在处理：底栏圆钮里的莫比乌斯在走 + 主卡的流光框，页面上不再写一行字（build 53）
                if let doc {
                    if !doc.headline.text.isEmpty && doc.stale != true {
                        Text(doc.headline.text)
                            .font(E.body(15)).foregroundStyle(E.text2)
                            .lineSpacing(5)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 12)
                            .id("headline-" + heroKey)
                            .transition(.opacity)
                            .accessibilityIdentifier("headline-\(board.id)")
                    }
                    // 主卡：正在改时只框住这张卡（白色流光 + 朦胧），换上时新卡从朦胧变清楚；页面别处不动
                    ZStack(alignment: .topLeading) {
                        HeroView(hero: doc.hero, showBoard: board.id == "now", today: doc.date)
                        .id("hero-" + heroKey)
                        .transition(.haze)
                    }
                    .updateGlow(heroGlow)
                    .padding(.top, 24)
                    // 容器：标识只给主卡本身，里面的数值、图表保留各自的标识
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier(heroGlow ? "hero-updating" : "hero")
                    // 主卡下面：每个习惯一行，各进各的对话（顶部是习惯卡）
                    if let habits = doc.habits, !habits.isEmpty { HabitRows(habits: habits).padding(.top, 14) }
                    if !doc.todos.isEmpty { todoSection(doc) }
                    ForEach(doc.notices, id: \.self) { n in
                        if n.text.contains("重新登录 WHOOP") {
                            // 服务器说 WHOOP 登录真失效了：这条提示可以点，直接在手机上重新登录
                            Button { showWhoopLogin = true } label: {
                                HStack(spacing: 6) {
                                    Text(n.text).font(E.body(12)).foregroundStyle(E.text2)
                                        .multilineTextAlignment(.leading)
                                    Image(systemName: "chevron.right").font(.system(size: 10, weight: .light))
                                        .foregroundStyle(E.text3)
                                }
                                .frame(minHeight: 44, alignment: .leading)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(EPress())
                            .padding(.top, 2)
                            .accessibilityIdentifier("notice-whoop-login")
                        } else {
                            Text(n.text).font(E.body(12)).foregroundStyle(E.text3).padding(.top, 12)
                        }
                    }
                } else if loader.failed {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("暂时连不上 P-Health").font(E.body(15)).foregroundStyle(E.text2)
                        if link.keyRejected {
                            Text("这台电脑不认这个配对了，重新扫码").font(E.body(13)).foregroundStyle(E.text3)
                        }
                        HStack(spacing: 4) {
                            OutlinePill(title: "重试") {
                                ServerLink.shared.reprobe(force: true)
                                Task { await loader.load() }
                            }
                            // 换了电脑、电脑换了地址：从这里重新扫码 / 断开
                            if link.mode == .ready {
                                QuietButton(title: "连接设置") { ServerLink.shared.showConnection() }
                                    .accessibilityIdentifier("page-connection")
                            }
                        }
                    }
                    .padding(.top, 40)
                } else {
                    WorkingLine().padding(.top, 40)
                }
            }
            .padding(.horizontal, E.gutter)
            .padding(.bottom, 120)
        }
        .scrollIndicators(.hidden)
        .animation(.easeOut(duration: 0.55), value: heroKey)
        .onChange(of: heroUpdating) { was, now in
            if was && !now {
                heroHold = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { heroHold = false }
            }
        }
        .onChange(of: heroKey) { _, _ in heroHold = false }
        .refreshable {
            // 演示：只重新读一遍样例（不同步健康数据、不出小圆点）
            if ServerConfig.isDemo { await loader.load(); return }
            // 下拉：Apple 健康由手机直接传、服务器马上回 WHOOP / Apple 的数据有多新（需要时它在后台补拉 WHOOP），
            // 两边同时进行；再拉最新页面。不写字：轻震一下 + 顶上两个小圆点（实心 = 新的），2 秒后淡出。
            // 只有服务器说要 Psir 动手（action）时才写那一句；P-Health 还在改主卡由流光框表示
            async let apple = DeviceDataReporter.shared.syncNow()
            async let whoop = V3API.syncHealth()
            let (appleOK, w) = await (apple, whoop)
            DshAPI.dbg("下拉刷新 whoop=\(w.whoop ?? "-") apple=\(w.apple ?? "-") 手机上传=\(appleOK) pulling=\(w.pulling == true) action=\(w.action != nil)")
            await sync.poll()
            await loader.load()
            // 菊花收起的同时出来（不和它叠在一起）
            Haptic.tap()
            showSyncDots(HealthDots(sync: w, appleUploaded: appleOK))
        }
        .overlay(alignment: .top) {
            ZStack(alignment: .top) {
                if let d = syncDots {
                    // 和页面标题同一高度、居中（标题在左、钟在右，中间是空的）
                    HealthDotsView(dots: d) { showWhoopLogin = true }
                        .padding(.top, 21)
                        .padding(.horizontal, E.gutter)
                        .transition(.opacity)
                }
                toastView
            }
        }
        .sheet(isPresented: $showWhoopLogin, onDismiss: {
            // 登录好了（或者关掉）：页面、状态都重新对一次，提示没了就不再显示
            refresh()
            PageSync.shared.poke()
        }) {
            WhoopLoginSheet()
                .presentationDetents([.large])
                .presentationBackground(Color.black)
        }
        .task { if visible || isReminderSource { await loader.load() } }
        // 切到这一页：之前收到过刷新信号（或者还没拉过）就现在拉
        .onChange(of: visible) { _, now in
            if now, loader.dirty || loader.doc == nil { Task { await loader.load() } }
        }
        .onChange(of: loader.version) { _, _ in applyLoaded() }
        .onReceive(NotificationCenter.default.publisher(for: .pivisPagesDirty)) { _ in refresh() }
        // 待办动作送到服务器（或被拒）：重新拉一次，换成服务器的样子
        .onReceive(NotificationCenter.default.publisher(for: .pivisTodosChanged)) { _ in
            let delay = TodoOutbox.shared.reloadDelay
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { refresh() }
        }
        // 从小组件点进来的那张卡：在这页就展开
        .onReceive(NotificationCenter.default.publisher(for: .pivisExpandTodo)) { note in
            guard let id = note.object as? String else { return }
            guard let d = doc, Self.allTodos(d).contains(where: { $0.id == id }) else { pendingExpand = id; return }
            if d.more?.contains(where: { $0.id == id }) == true { showMore = true }
            openTodo(id)
        }
        .onChange(of: TodoOutbox.shared.rejected) { _, msg in
            guard let msg else { return }
            flash(msg)
            TodoOutbox.shared.rejected = nil
        }
        .onDisappear { poller?.cancel() }
        .onChange(of: scrollRequest) { _, id in
            guard let id else { return }
            withAnimation(.easeOut(duration: 0.35)) { scroller.scrollTo("todo-\(id)", anchor: .center) }
            scrollRequest = nil
        }
        }
    }

    // MARK: 顶栏
    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(board.label)
                .font(E.light(32))
                .foregroundStyle(E.text)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("page-title")
            Spacer()
            if let doc { HeaderClock(anchor: doc.now) }
        }
        .padding(.top, 16)
    }

    // MARK: 接下来（没有待办时整块不显示；做完的不列出来）
    private func todoSection(_ doc: V3Page) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("接下来").font(E.body(12)).kerning(1).foregroundStyle(E.text2)
                .padding(.bottom, 10)
            Hairline()
            // 服务器的待办 + 还没送到的动作（点了立刻生效，不等网络）
            ForEach(TodoOutbox.shared.apply(doc.todos, fetchedAt: fetchedAt)) { todo in
                todoRow(todo, doc)
            }
            // 此刻页只列前 3 张：其余的收在「另有 N 件」里，点开看
            if let more = doc.more, !more.isEmpty {
                Button {
                    withAnimation(.easeOut(duration: 0.2)) { showMore.toggle() }
                } label: {
                    HStack {
                        Text(showMore ? "收起" : "另有 \(more.count) 件").font(E.body(13)).foregroundStyle(E.text2)
                        Spacer()
                        Image(systemName: showMore ? "chevron.up" : "chevron.down")
                            .font(.system(size: 11, weight: .light)).foregroundStyle(E.text3)
                    }
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("todos-more")
                if showMore {
                    Hairline(color: E.line2)
                    ForEach(TodoOutbox.shared.apply(more, fetchedAt: fetchedAt)) { todo in
                        todoRow(todo, doc)
                    }
                }
            }
        }
        .padding(.top, 28)
    }

    /// 页面上所有还没做的待办（此刻页含收起来的那些）
    static func allTodos(_ d: V3Page) -> [V3Todo] { d.todos + (d.more ?? []) }

    #if DEBUG
    /// 测试（仅模拟器回放、Debug 包）：-timeDraftPreview 把有时间的卡都画成「P-Health 拟的时间」（只改显示，不发服务器），
    /// 测试数据里没有拟的时间时用来看虚线时间和时间轮
    private static let draftPreview = Profile.isSim && ProcessInfo.processInfo.arguments.contains("-timeDraftPreview")
    #endif

    private func todoRow(_ todo: V3Todo, _ doc: V3Page) -> some View {
        var todo = todo
        #if DEBUG
        if Self.draftPreview, !todo.when.isEmpty, todo.auto == nil, todo.timeDraft == nil {
            todo.timeDraft = true
            todo.draftWhy = "按 23:30 上床倒推（预览）"
        }
        #endif
        return VStack(spacing: 0) {
                TodoCardView(todo: todo,
                             expanded: expandedTodo == todo.id,
                             showBoard: board.id == "now",
                             nowText: doc.now,
                             onExpand: {
                                 withAnimation(.easeOut(duration: 0.2)) {
                                     expandedTodo = expandedTodo == todo.id ? nil : todo.id
                                 }
                             })
                    .transition(.opacity)
                    .id("todo-\(todo.id)")
                Hairline(color: E.line2)
        }
    }

    private var toastView: some View {
        Group {
            if let toast {
                Text(toast)
                    .font(E.body(13)).foregroundStyle(Color.black)
                    .padding(.horizontal, 16).frame(minHeight: 40)
                    .background(Capsule().fill(E.text))
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .accessibilityIdentifier("toast")
            }
        }
    }

    /// 展开一张待办并滚到屏幕中间（从小组件点进来）
    private func openTodo(_ id: String) {
        withAnimation(.easeOut(duration: 0.2)) { expandedTodo = id }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { scrollRequest = id }
    }

    /// 测试（仅模拟器回放）：-syncDotsHold 让小圆点多留 8 秒（XCUITest 手势结束后要等 App 空闲约 2 秒，2 秒的窗口抓不到）
    private static let syncDotsHold = Profile.isSim && ProcessInfo.processInfo.arguments.contains("-syncDotsHold")

    /// 两个小圆点：出来后 2 秒淡出；要 Psir 动手（有那句话）时多留一会儿，够读完、够点
    private func showSyncDots(_ d: HealthDots) {
        let token = UUID()
        syncDotsToken = token
        withAnimation(.easeOut(duration: 0.2)) { syncDots = d }
        let stay = (d.action == nil ? 2.0 : 8.0) + (Self.syncDotsHold ? 8 : 0)
        DispatchQueue.main.asyncAfter(deadline: .now() + stay) {
            guard syncDotsToken == token else { return }
            withAnimation(.easeIn(duration: 0.5)) { syncDots = nil }
        }
    }

    private func flash(_ text: String) {
        withAnimation(.easeOut(duration: 0.2)) { toast = text }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.6) {
            withAnimation(.easeIn(duration: 0.2)) { toast = nil }
        }
    }

    /// 刷新信号：看得见（或者是此刻页）就拉，不然记下「脏了」，切过来再拉
    private func refresh() {
        if visible || isReminderSource { Task { await loader.load() } } else { loader.markDirty() }
    }

    /// 新数据到了：展开从小组件点进来的卡、排提醒、有待办在处理就接着刷
    private func applyLoaded() {
        guard let d = loader.doc else { return }
        let all = Self.allTodos(d)
        if let e = expandedTodo, !all.contains(where: { $0.id == e }) { expandedTodo = nil }
        if let p = pendingExpand, all.contains(where: { $0.id == p }) {
            pendingExpand = nil
            if d.more?.contains(where: { $0.id == p }) == true { showMore = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { openTodo(p) }
        }
        if d.more?.isEmpty ?? true { showMore = false }
        // 提醒按「本地已生效」的样子排：已经点了开始 / 做了的，不再提醒（收起来的也要排）
        let shown = TodoOutbox.shared.apply(all, fetchedAt: loader.fetchedAt)
        if isReminderSource {
            // 此刻页 = 所有板块的待办（「日常」没有自己的页，只能在这里排）：看不见的板块页不用为了排提醒去拉
            for b in ["life", "sleep", "sport", "stress"] { Reminders.shared.sync(todos: shown, nowText: d.now, board: b) }
        } else {
            Reminders.shared.sync(todos: shown, nowText: d.now, board: board.id)
        }
        // 今天要练的视频：Wi-Fi 下先下到手机上（出门在外连不上家里的服务器也能放）
        if !ServerConfig.isDemo {
            for t in shown { if let u = PivisAPI.resolve(t.practiceVideo?.url) { VideoCache.shared.prefetch(u) } }
        }
        // 有待办在处理时，持续刷新，直到 P-Health 改完
        if d.todos.contains(where: { $0.status == "processing" }) { schedulePoll() }
    }

    private func schedulePoll(seconds: Double = 2) {
        poller?.cancel()
        poller = Task {
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            if !Task.isCancelled { refresh() }
        }
    }
}

/// 页面顶上的钟：每分钟走一格，按最近一次拿到的服务器时间走（模拟回放时服务器的时钟可以是假的）；看不见的页不走
struct HeaderClock: View {
    /// 页面数据里的「现在」：变了就重新对一次表
    let anchor: String
    @Environment(\.motionPaused) private var paused

    var body: some View {
        let offset = PTime.serverOffset
        Group {
            if paused {
                Text(PTime.dayAndClock(Date().addingTimeInterval(offset)))
            } else {
                // 对齐到服务器时钟的整分钟：每到那一刻换一次
                let into = Date().addingTimeInterval(offset).timeIntervalSince1970.truncatingRemainder(dividingBy: 60)
                TimelineView(.periodic(from: Date().addingTimeInterval(-into), by: 60)) { ctx in
                    Text(PTime.dayAndClock(ctx.date.addingTimeInterval(offset)))
                }
            }
        }
        .font(E.body(15)).foregroundStyle(E.text2).monospacedDigit()
        .id(anchor)
    }
}

/// 单位统一说中文（模型有时写 h / min）
func displayUnit(_ u: String) -> String {
    ["h": "小时", "hr": "小时", "hrs": "小时", "hours": "小时", "min": "分钟", "mins": "分钟", "minutes": "分钟", "kcal": "千卡"][u.lowercased()] ?? u
}

/// 数字后面接单位：% 紧贴，其余空一格
func unitSuffix(_ u: String?) -> String {
    guard let u, !u.isEmpty else { return "" }
    let d = displayUnit(u)
    return d == "%" ? d : " " + d
}

func contextFor(_ board: String) -> String {
    ["sleep": "休息", "sport": "运动", "stress": "压力"][board] ?? ""
}

// MARK: - 主卡：一个问题的值 + 档位，下面是 P-Health 给的支撑字段或小表；有项目才显示项目行
struct HeroView: View {
    let hero: V3Page.Hero
    let showBoard: Bool
    var today: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Hairline()
            HStack(alignment: .firstTextBaseline) {
                Text(showBoard && !(hero.boardLabel ?? "").isEmpty ? "\(hero.label) · \(hero.boardLabel ?? "")" : hero.label)
                    .font(E.body(15)).foregroundStyle(E.text2)
                Spacer()
                LevelTag(level: hero.level, label: hero.levelLabel ?? "")
            }
            .padding(.top, 18)
            if let lay = hero.layout {
                CanvasView(node: lay, today: today).padding(.top, 14)
                if let note = hero.note, !note.isEmpty {
                    Text(note).font(E.body(13)).foregroundStyle(E.text2).lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true).padding(.top, 10)
                }
            } else {
                legacyBody
            }
        }
    }

    @ViewBuilder
    private var legacyBody: some View {
            let viz = hero.viz
            if viz?.kind == "gauge", let v = viz {
                // 分数类：数字放进仪表中间
                RiskViz(viz: v, level: hero.level, today: today).padding(.top, 14)
            } else if !hero.value.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(heroValueText)
                        .font(E.thin(viz == nil ? 88 : 80)).kerning(-3)
                        .foregroundStyle(E.text)
                        .minimumScaleFactor(0.5).lineLimit(1)
                    if let u = hero.unit, !u.isEmpty {
                        Text(displayUnit(u)).font(E.light(viz == nil ? 26 : 24)).foregroundStyle(E.text)
                    }
                    if let a = viz?.aside {
                        Spacer(minLength: 8)
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(a.text).font(E.body(15)).foregroundStyle(E.text)
                            if let sub = a.sub { Text(sub).font(E.body(11)).foregroundStyle(E.text3) }
                        }
                    }
                }
                .padding(.top, 6)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("hero-value")
                if let v = viz {
                    RiskViz(viz: v, level: hero.level, today: today).padding(.top, 14)
                }
            }
            if let note = hero.note, !note.isEmpty {
                Text(note).font(E.body(13)).foregroundStyle(E.text2).lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, viz == nil ? 0 : 10)
            }
            if viz != nil {
                EmptyView()
            } else if let fields = hero.fields, !fields.isEmpty {
                HeroFields(fields: fields).padding(.top, 18)
            } else if let table = hero.table, !table.rows.isEmpty {
                // 和画布、对话里的表格是同一个零件
                TablePart(n: .table(table.columns, table.rows, id: "hero.table"))
                    .accessibilityIdentifier("hero-table")
                    .padding(.top, 18)
            }
    }
}

extension HeroView {
    /// 步数这类大数加千分位
    var heroValueText: String {
        if displayUnit(hero.unit ?? "") == "步", let v = Double(hero.value), v >= 1000 { return grouped(v) }
        return hero.value
    }
}

/// 主卡下面的「坚持习惯」：一个习惯一行（图标、名字 · N/M、右边今天要做的）
struct HabitRows: View {
    let habits: [V3Page.Habit]
    @ObservedObject private var sync = PageSync.shared
    var body: some View {
        VStack(spacing: 0) {
            ForEach(habits) { h in
                Button {
                    openChat(context: contextFor(h.board), about: ChatAbout(kind: .habit, id: h.id, name: h.name))
                } label: {
                    // 一行：图标、名字 · 第几天/共几天、右边今天要做的（Psir 11-10：字要少，不再每行写「坚持习惯」）
                    HStack(spacing: 12) {
                        // 每个项目自己的线条图标（「腰背放松」不再是网球拍）；没给就用板块图标
                        ProjectGlyph(icon: h.icon, board: h.board)
                        Text(h.label).font(E.body(15)).foregroundStyle(E.text).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(h.today).font(E.body(12)).foregroundStyle(E.text2).lineLimit(1)
                        // 点进去的那个对话里 P-Health 回了你还没看：箭头前一个小白点
                        if sync.unread.contains(contextFor(h.board)) {
                            Circle().fill(E.text).frame(width: 6, height: 6)
                                .accessibilityLabel("有新回复")
                                .accessibilityIdentifier("habit-unread-\(h.id)")
                        }
                        Image(systemName: "chevron.right").font(.system(size: 12, weight: .light)).foregroundStyle(E.text3)
                    }
                    .frame(minHeight: 52)
                    .overlay(alignment: .top) { Hairline(color: E.line2).allowsHitTesting(false) }
                    .contentShape(Rectangle())
                }
                .buttonStyle(EPress())
                .accessibilityElement(children: .combine)
                .accessibilityLabel("坚持习惯，\(h.label)，\(h.today)")
                .accessibilityIdentifier("habit-\(h.id)")
            }
        }
        .overlay(alignment: .bottom) { Hairline(color: E.line2).allowsHitTesting(false) }
    }
}

/// 2–3 个字段并排：小字标签在上，细体数字在下，中间一根竖线分开
struct HeroFields: View {
    let fields: [V3Page.Field]
    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(fields.enumerated()), id: \.offset) { i, f in
                VStack(alignment: .leading, spacing: 4) {
                    Text(f.label).font(E.body(12)).foregroundStyle(E.text3).lineLimit(1)
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(f.value).font(E.light(24)).foregroundStyle(E.text).monospacedDigit()
                            .minimumScaleFactor(0.6).lineLimit(1)
                        if let u = f.unit, !u.isEmpty {
                            Text(displayUnit(u)).font(E.body(12)).foregroundStyle(E.text2)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, i == 0 ? 0 : 14)
                .overlay(alignment: .leading) {
                    if i > 0 { Rectangle().fill(E.line2).frame(width: 1).padding(.vertical, 2) }
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("hero-fields")
    }
}
