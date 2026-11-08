import SwiftUI

// MARK: - 待办卡（build 43 起 13 种统一一套）
// 行尾 = P-Health 图标 + 这张卡的主动作。build 45 起每张卡行尾都有一个细线圆圈图标：
// 一点就完成的（打勾，包括设备会自动记的「上床」/ 练习 / 计数 / 计时 / 拍照 / 确认）点了就做；要选的（？）、要填的（笔 / 链接）、
// 清单（进度）点了展开，选项和输入在展开后的内容里。展开后 P-Health 图标和主动作并排，下面只放内容。
// 没有回复框、没有「晚点」「算了」：想改时间、今天不做、补充说明，点图标带着这张卡进对话说。
// P-Health 想追问（escalate=chat）时不自己弹出对话：图标上一个小白点，收起时图标也露出来，点了再进对话。
struct TodoCardView: View {
    let todo: V3Todo
    let expanded: Bool
    let showBoard: Bool
    let nowText: String
    let onExpand: () -> Void

    @State private var values: [String: GenValue] = [:]
    @State private var busy = false
    @State private var errorText: String?
    @State private var settled = false       // 刚做完：对勾变实心，原位停两秒，然后收进「已完成」
    @State private var showCapture = false
    @State private var localCount: Int?      // 计数：点了先显示，不等服务器
    @State private var localChecked: Set<Int>?
    @State private var pickedTime: Date?     // 确认卡：老大在展开里改过的实际时间；没改就记点下去的那一刻

    /// 卡上不再有「自己写一句」：老卡里的 allow_text 也不画
    private var fields: [GenField] {
        todo.inputs.map { i in
            let f = GenField(i)
            return GenField(id: f.id, type: f.type, label: f.label, options: f.options, min: f.min, max: f.max,
                            minLabel: f.minLabel, maxLabel: f.maxLabel, unit: f.unit, placeholder: f.placeholder,
                            allowText: false, step: f.step)
        }
    }
    /// 只要一张照片的待办（「晚饭拍一张」）：主动作是相机，拍完发进 P-Health 对话
    private var photoOnlyField: GenField? {
        let fs = fields
        return fs.count == 1 && fs[0].type == "photo" ? fs[0] : nil
    }
    private var processing: Bool { todo.status == "processing" }
    /// P-Health 有话要问这张卡（不自己开对话，图标上点个白点等老大点）
    private var asks: Bool { todo.escalate == "chat" }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if expanded && !settled { content }
        }
        // P-Health 在改这条：只框住这条（白色流光 + 朦胧），不写字
        .updateGlow(processing, cornerRadius: 14, outset: 6)
        .animation(.easeOut(duration: 0.3), value: todo.title + todo.when + todo.note)
        .allowsHitTesting(!processing && !settled)
        .onAppear { prefillDefaults() }
        // 整张卡是一个容器（里面的按钮各自可点）：VoiceOver 按卡分组，UI 测试也能在卡里找按钮
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("todo-\(todo.id)")
        .captureSheet(isPresented: $showCapture) { img in
            openChat(context: contextFor(todo.board),
                     photo: PendingPhoto(image: img, todoId: todo.id, todoTitle: todo.title, fieldId: photoOnlyField?.id))
        }
    }

    // MARK: 一行：时间 · 标题 / 副标题 · 行尾
    // 时间 + 标题这一块是一个按钮（点了展开 / 收起，读屏读出展开状态）；行尾的图标和主动作各是各的按钮
    private var header: some View {
        HStack(alignment: .center, spacing: 0) {
            Button { if !settled { onExpand() } } label: {
                HStack(alignment: .center, spacing: E.timeGap) {
                    // 每条都有时间（老大 11-08）：没定时间的占位「—」，不空着
                    Text(todo.when.isEmpty ? "—" : todo.when)
                        .font(E.timeFont).monospacedDigit().frame(width: E.timeColumn, alignment: .leading)
                        .foregroundStyle(settled || todo.when.isEmpty ? E.text3 : E.text)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(todo.title).font(E.body(15)).foregroundStyle(settled ? E.text2 : E.text)
                            .lineLimit(expanded ? 3 : 2)
                            .fixedSize(horizontal: false, vertical: true)
                            .multilineTextAlignment(.leading)
                        subLine
                    }
                    Spacer(minLength: 4)
                }
                .frame(minHeight: 64)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowPress())
            .accessibilityLabel(todo.title)
            .accessibilityValue(rowValue)
            .accessibilityHint(settled ? "" : (expanded ? "点一下收起" : "点一下展开"))
            trailing
        }
    }

    /// 读屏读的：时间、副标题、P-Health 有话问、展开 / 收起
    private var rowValue: String {
        var parts: [String] = []
        if !todo.when.isEmpty { parts.append(todo.when) }
        if todo.kind == "timer", todo.status == "in_progress" {
            parts.append("还剩 " + TimerText.remaining(startedAt: todo.record?.startedAt, minutes: todo.durationMin ?? 0, at: Date()))
        } else if !subText.isEmpty {
            parts.append(subText)
        }
        if asks { parts.append("P-Health 有话问你") }
        parts.append(expanded ? "已展开" : "已收起")
        return parts.joined(separator: "，")
    }

    private var subText: String {
        [showBoard ? todo.boardLabel : nil, hint.isEmpty ? nil : hint].compactMap { $0 }.joined(separator: " · ")
    }

    @ViewBuilder
    private var subLine: some View {
        if todo.kind == "timer", todo.status == "in_progress" {
            HStack(spacing: 0) {
                Text("还剩 ").font(E.body(12)).foregroundStyle(E.text3)
                TimerText(startedAt: todo.record?.startedAt, minutes: todo.durationMin ?? 0, size: 12)
                    .foregroundStyle(E.text3)
            }
        } else if !subText.isEmpty {
            Text(subText).font(E.body(12)).foregroundStyle(E.text3).lineLimit(expanded ? 3 : 1)
                .multilineTextAlignment(.leading)
        }
    }

    @ViewBuilder
    private var trailing: some View {
        if settled {
            Image(systemName: "checkmark").font(.system(size: 14, weight: .regular)).foregroundStyle(Color.black)
                .frame(width: 44, height: 44).background(Circle().fill(E.text))
                .accessibilityIdentifier("todo-settled")
        } else {
            HStack(spacing: 10) {
                if expanded || asks { chatButton }
                mainAction
            }
        }
    }

    /// P-Health 图标：带着这张卡进它所在板块的对话（顶部是这张卡，输入框上方「关于：标题」）
    private var chatButton: some View {
        Button {
            openChat(context: contextFor(todo.board),
                     about: ChatAbout(kind: .todo, id: todo.id, name: todo.title, todo: todo))
        } label: {
            MobiusMark(lineWidth: 1.2, strands: 2).frame(width: 22)
                .frame(width: 44, height: 44)
                .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                .overlay {
                    // P-Health 有话问：圆圈右上角一个实心小白点（外面一圈黑，和描边分开）
                    if asks {
                        Circle().fill(E.text).frame(width: 7, height: 7)
                            .background(Circle().fill(Color.black).frame(width: 11, height: 11))
                            .offset(x: 15.5, y: -15.5)
                            .accessibilityIdentifier("todo-asks")
                    }
                }
                .contentShape(Circle())
        }
        .buttonStyle(EPress())
        .accessibilityLabel(asks ? "P-Health 有话问你，点开和它说这个待办" : "和 P-Health 说这个待办")
        .accessibilityIdentifier("todo-chat")
    }

    /// 主动作：一点就完成的（练习 / 打勾 / 计数 / 计时 / 拍照 / 确认时间）收起也在；要填的（数值、日记）展开才有对勾
    @ViewBuilder
    private var mainAction: some View {
        switch todo.kind {
        case "follow":
            circle(system: "checkmark", label: "做完了", id: "todo-done") {
                submit(action: "done", summary: practiceSummary)
            }
        case "done":
            // 「上床」这种设备会自动记的也是对勾（老大 11-08）：设备识别到入睡会自己打上，没识别到就自己点
            circle(system: "checkmark", label: "做完了", id: "todo-done") { submit(action: "done", summary: "做到了") }
        case "counter":
            circle(text: "+1", label: "加一次", id: "todo-inc") { increment() }
        case "timer" where todo.status == "in_progress":
            // 主动作的字由 P-Health 定（submit_label），没给就是中性的「好了」
            circle(system: "checkmark", label: todo.submitLabel ?? "好了", id: "todo-timer-end") { submit(action: "done", summary: timerSummary) }
        case "timer":
            circle(system: "play", label: "开始", id: "todo-timer-start") { submit(action: "start") }
        case "confirm":
            circle(system: "checkmark", label: "记下", id: "todo-confirm") {
                // 记点下去的这一刻（服务器时钟，北京时间）；展开里改过时间才用改的
                let hm = PTime.hhmm(pickedTime ?? PTime.serverNow)
                submit(action: "done", values: ["time": hm], summary: "\(hm) 完成")
            }
        case "checklist":
            openCircle(text: "\(checked.count)/\(todo.items?.count ?? 0)",
                       label: "清单 \(checked.count) / \(todo.items?.count ?? 0)，点一下展开", id: "todo-open")
        default:
            if photoOnlyField != nil {
                circle(system: "camera", label: "拍照", id: "todo-photo") { showCapture = true }
            } else if !fields.isEmpty && !autoSubmits && expanded {
                if busy {
                    ProgressView().tint(.white).frame(width: 44, height: 44)
                } else {
                    circle(system: "checkmark", label: "记下", id: "todo-submit") { submitFields() }
                        .disabled(!ready).opacity(ready ? 1 : 0.4)
                }
            } else {
                // 要选 / 要填的：收起时也有图标，点了展开（选项、输入框在展开后的内容里）
                openCircle(system: openGlyph, label: autoSubmits || fields.isEmpty ? "点一下展开选" : "点一下展开填",
                           id: "todo-open")
            }
        }
    }

    /// 要选的是问号，要填链接的是链接，其他要填的是笔
    private var openGlyph: String {
        if autoSubmits || fields.isEmpty || ["options", "proposal", "scale"].contains(todo.kind)
            || fields.allSatisfy({ ["options", "multi", "scale"].contains($0.type) }) { return "questionmark" }
        let wantsLink = fields.contains { f in
            f.type == "text" && ([f.label, f.placeholder ?? ""].joined().contains("链接")
                                 || [f.label, f.placeholder ?? ""].joined().lowercased().contains("link"))
        }
        return wantsLink ? "link" : "pencil"
    }

    /// 不直接完成、只展开 / 收起这张卡的圆圈（和主动作同一个样子）
    private func openCircle(system: String? = nil, text: String? = nil, label: String, id: String) -> some View {
        circle(system: system, text: text, label: label, id: id) { if !settled { onExpand() } }
    }

    private func circle(system: String? = nil, text: String? = nil, label: String, id: String,
                        action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Group {
                if let system { Image(systemName: system).font(.system(size: 14, weight: .light)) }
                else { Text(text ?? "").font(E.body(13)) }
            }
            .foregroundStyle(E.text)
            .frame(width: 44, height: 44)
            .overlay(Circle().strokeBorder(E.text, lineWidth: 1))
            .contentShape(Circle())
        }
        .buttonStyle(EPress())
        .accessibilityLabel(label)
        .accessibilityIdentifier(id)
    }

    // MARK: 展开后的内容（和标题对齐）
    private var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch todo.kind {
            case "follow":
                if let v = todo.practiceVideo, todo.isPracticeVideo {
                    PracticePoster(video: v) { start() }
                        .padding(.top, 2)
                } else {
                    legacySteps.padding(.top, 4)       // 老的多步 / 音频跟做卡：只读
                }
            case "counter":
                counterBoxes.padding(.top, 4)
            case "confirm":
                HStack(spacing: 10) {
                    Text("实际时间").font(E.body(13)).foregroundStyle(E.text2)
                    DatePicker("", selection: Binding(get: { pickedTime ?? PTime.serverNow }, set: { pickedTime = $0 }),
                               displayedComponents: .hourAndMinute)
                        .labelsHidden().colorScheme(.dark)
                        .environment(\.timeZone, PTime.zone)
                }
                .padding(.top, 4)
            case "checklist":
                legacyChecklist
            default:
                if !fields.isEmpty && photoOnlyField == nil {
                    VStack(alignment: .leading, spacing: 14) {
                        if todo.kind == "proposal", !todo.note.isEmpty {
                            Text(todo.note).font(E.body(14)).foregroundStyle(E.text2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        ForEach(fields) { f in
                            GenFieldView(field: f, value: binding(f.id),
                                         onPick: autoSubmits ? { submitFields() } : nil)
                        }
                    }
                    .padding(.top, 4)
                }
            }
            if let errorText {
                Text(errorText).font(E.body(12)).foregroundStyle(E.text2).padding(.top, 8)
            } else if TodoOutbox.shared.waiting(todo.id) {
                Text("还没连上服务器，已经记在手机上，连上后自动发").font(E.body(12)).foregroundStyle(E.text3).padding(.top, 8)
                    .accessibilityIdentifier("todo-waiting")
            }
        }
        .padding(.leading, E.timeColumn + E.timeGap)
        .padding(.bottom, 18)
    }

    private var counterBoxes: some View {
        let target = max(1, todo.target ?? 1)
        return HStack(spacing: 8) {
            ForEach(0..<target, id: \.self) { i in
                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .fill(i < count ? E.text : Color.clear)
                    .overlay(RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .strokeBorder(i < count ? E.text : E.stroke, lineWidth: 1))
                    .frame(width: 20, height: 16)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(todo.title) \(count) / \(target)")
    }

    private var legacySteps: some View {
        VStack(spacing: 0) {
            ForEach(Array(todo.allSteps.enumerated()), id: \.offset) { _, step in
                HStack(spacing: 12) {
                    Text(step.title).font(E.body(14)).foregroundStyle(E.text2)
                    Spacer()
                    if let d = step.durationMin ?? step.media?.durationMin {
                        Text(minutesText(d)).font(E.body(13)).foregroundStyle(E.text3).monospacedDigit()
                    }
                }
                .frame(minHeight: 40)
                .overlay(alignment: .top) { Hairline(color: E.line2).allowsHitTesting(false) }
            }
        }
    }

    private var legacyChecklist: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array((todo.items ?? []).enumerated()), id: \.offset) { i, item in
                let on = checked.contains(i)
                Button { toggleStep(i, on: !on) } label: {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle().fill(on ? E.text : Color.clear)
                            Circle().strokeBorder(on ? E.text : E.stroke, lineWidth: 1)
                            if on { Image(systemName: "checkmark").font(.system(size: 9, weight: .semibold)).foregroundStyle(Color.black) }
                        }
                        .frame(width: 18, height: 18)
                        Text(item).font(E.body(14)).foregroundStyle(on ? E.text3 : E.text).strikethrough(on, color: E.text3)
                        Spacer(minLength: 0)
                    }
                    .frame(minHeight: 40)
                    .contentShape(Rectangle())
                }
                .buttonStyle(EPress())
                .accessibilityLabel(item)
                .accessibilityAddTraits(on ? .isSelected : [])
                .accessibilityIdentifier("todo-step-\(i)")
            }
        }
    }

    /// 数值输入先填默认值：default="last" 用项目里上一次记的数，或者 P-Health 给的数
    private func prefillDefaults() {
        for i in todo.inputs where i.type == "number" && values[i.id] == nil {
            switch i.defaultValue {
            case .str("last")?:
                if let v = todo.last?.values?[i.id] { values[i.id] = .text(v.text) }
            case .num(let d)?:
                values[i.id] = .text(LooseValue.num(d).text)
            default: break
            }
        }
    }

    private var count: Int { localCount ?? todo.record?.count ?? 0 }
    private var checked: Set<Int> { localChecked ?? Set(todo.record?.checked ?? []) }

    private var timerSummary: String {
        guard let s = todo.record?.startedAt, let d = PTime.parse(s) else { return "做完了" }
        let m = max(1, Int(Date().timeIntervalSince(d) / 60))
        return "\(m) 分钟"
    }

    private var practiceSummary: String {
        let d = todo.durationMin ?? todo.practiceVideo?.durationMin ?? 0
        return d > 0 ? "做完了 · \(Int(d.rounded())) 分钟" : "做完了"
    }

    private func increment() {
        let next = count + 1
        localCount = next
        submit(action: "inc", settle: next >= (todo.target ?? 1))
    }

    private func toggleStep(_ i: Int, on: Bool) {
        var set = checked
        if on { set.insert(i) } else { set.remove(i) }
        localChecked = set
        submit(action: "check", values: ["index": i, "on": on], settle: set.count == (todo.items?.count ?? 0))
    }

    // MARK: 文案
    /// 副标题：P-Health 写的备注；练习卡没备注时放时长；计数放进度。不写操作说明。
    private var hint: String {
        if TodoOutbox.shared.waiting(todo.id) { return "等网络 · 连上自动发" }
        if todo.kind == "counter" { return "\(count) / \(todo.target ?? 1) \(todo.unit ?? "")" }
        if todo.kind == "done", todo.auto != nil, todo.note.isEmpty { return "设备会自动记" }
        if todo.kind == "number", let last = todo.last, !last.summary.isEmpty, todo.note.isEmpty { return "上次 \(last.summary)" }
        if todo.kind == "timer", let a = todo.alarm, todo.note.isEmpty { return "\(a) 叫你" }
        if !todo.note.isEmpty { return todo.note }
        if todo.kind == "follow" {
            let total = todo.durationMin ?? todo.allSteps.compactMap { $0.durationMin ?? $0.media?.durationMin }.reduce(0, +)
            return total > 0 ? "\(Int(total.rounded())) 分钟" : ""
        }
        return ""
    }

    private var ready: Bool {
        fields.allSatisfy { f in
            if f.type == "text" { return true }
            guard let v = values[f.id] else { return false }
            return !v.isEmpty
        }
    }

    /// 只有一个选项题的卡（单选、打分、提议、追问）：点一个就交
    private var autoSubmits: Bool {
        fields.count == 1 && ["options", "scale"].contains(fields[0].type)
            && ["options", "proposal", "scale"].contains(todo.kind)
    }

    private func binding(_ id: String) -> Binding<GenValue?> {
        Binding(get: { values[id] }, set: { values[id] = $0 })
    }

    // MARK: 提交
    private func start() {
        NotificationCenter.default.post(name: .pivisStartTodo, object: todo)
    }

    private func submitFields() {
        let fs = fields
        let chatFields = fs.filter { f in todo.inputs.first { $0.id == f.id }?.submit == "chat" && values[f.id] != nil }
        if !chatFields.isEmpty {
            openChat(context: contextFor(todo.board), pending: "关于待办「\(todo.title)」：\(summaryText())")
            return
        }
        // 有照片：先上传，拿到服务器路径再交给 P-Health 看图
        let photoIds = values.compactMap { k, v -> String? in if case .photo = v { return k } else { return nil } }
        if !photoIds.isEmpty {
            guard !busy else { return }
            busy = true
            errorText = nil
            Task {
                var resolved = payload()
                do {
                    for id in photoIds {
                        if case .photo(let d)? = values[id] { resolved[id] = try await V3API.uploadPhoto(todo.id, data: d) }
                    }
                    await MainActor.run {
                        busy = false
                        submit(action: "agent", values: resolved)
                    }
                } catch {
                    await MainActor.run { busy = false; errorText = "照片没传上去，再试一次" }
                }
            }
            return
        }
        let agentNeeded = todo.inputs.contains { $0.submit == "agent" && values[$0.id].map { !$0.isEmpty } == true }
        if agentNeeded {
            submit(action: "agent", values: payload())
        } else {
            submit(action: "done", values: payload(), summary: summaryText())
        }
    }

    private func payload() -> [String: Any] {
        var out: [String: Any] = [:]
        for (k, v) in values where !v.isEmpty { out[k] = v.json }
        return out
    }

    private func summaryText() -> String {
        fields.compactMap { f -> String? in
            guard let v = values[f.id], !v.isEmpty else { return nil }
            let short = f.label.replacingOccurrences(of: "？", with: "")
            return short.isEmpty ? v.display(f) : "\(short) \(v.display(f))"
        }.joined(separator: " · ")
    }

    /// 所有动作：先在本地生效（不等服务器），再进发送队列在后台发；断网就存着，连上自动补发。
    private func submit(action: String, values: [String: Any] = [:], text: String? = nil, summary: String? = nil,
                        settle: Bool? = nil) {
        errorText = nil
        Haptic.tap()
        if todo.kind == "timer" {
            switch action {
            // 计时开始：闹钟在手机上排好（静音也响），不靠网络
            case "start": Reminders.shared.scheduleTimerAlarm(todo: todo)
            case "done": Reminders.shared.cancelAlarm(todoId: todo.id)
            default: break
            }
        }
        TodoOutbox.shared.enqueue(todo.id, action: action, values: values, text: text, summary: summary)
        localCount = nil
        localChecked = nil
        if settle ?? (action == "done") { settleNow() }
    }

    /// 点对勾：对勾变实心，原位停两秒，然后由列表收进「已完成」
    private func settleNow() {
        withAnimation(.easeOut(duration: 0.2)) { settled = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.4) { settled = false }
    }
}

func minutes(_ hm: String) -> Int? {
    let p = hm.split(separator: ":")
    guard p.count == 2, let h = Int(p[0]), let m = Int(p[1]) else { return nil }
    return h * 60 + m
}

func minutesText(_ m: Double) -> String {
    if m >= 60 {   // 长内容（白噪音、陪睡）按小时说
        let h = Int(m) / 60, rest = Int(m) % 60
        return rest == 0 ? "\(h) 小时" : "\(h) 小时 \(rest) 分"
    }
    let total = Int((m * 60).rounded())
    return String(format: "%d:%02d", total / 60, total % 60)
}


/// 计时卡：从开始时间倒数（每秒刷新一次；看不见的页、App 在后台时停）
struct TimerText: View {
    let startedAt: String?
    let minutes: Double
    var size: CGFloat = 15
    @Environment(\.motionPaused) private var paused
    var body: some View {
        TimelineView(.animation(minimumInterval: 1, paused: paused)) { ctx in
            Text(Self.remaining(startedAt: startedAt, minutes: minutes, at: ctx.date))
                .font(size > 20 ? E.thin(size) : E.body(size))
                .foregroundStyle(E.text).monospacedDigit()
        }
        .accessibilityLabel("还剩 \(Self.remaining(startedAt: startedAt, minutes: minutes, at: Date()))")
    }
    static func remaining(startedAt: String?, minutes: Double, at now: Date) -> String {
        guard let s = startedAt, let d = PTime.parse(s) else { return "—" }
        let left = max(0, Int(minutes * 60 - now.timeIntervalSince(d)))
        return String(format: "%d:%02d", left / 60, left % 60)
    }
}

/// 点卡片的轻震：复用一个预热好的发生器（每次新建要先唤起震动引擎，偶尔会拖慢第一帧）
@MainActor
enum Haptic {
    private static let light: UIImpactFeedbackGenerator = {
        let g = UIImpactFeedbackGenerator(style: .light)
        g.prepare()
        return g
    }()
    static func tap() {
        light.impactOccurred()
        light.prepare()
    }
}
