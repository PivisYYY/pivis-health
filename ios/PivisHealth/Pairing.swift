import SwiftUI
import AVFoundation
import UIKit

// MARK: - 根：没配对 → 引导页；配对过 / 演示 → 主界面（换服务器时整个重建）。配对的弹层都挂在这一层
struct AppGate: View {
    @ObservedObject private var link = ServerLink.shared

    var body: some View {
        ZStack {
            E.bg.ignoresSafeArea()
            switch link.mode {
            case .unpaired:
                OnboardingView().transition(.opacity)
            case .ready, .demo:
                V3Root().id(link.generation).transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.3), value: link.mode)
        .sheet(item: $link.sheet) { sheet in
            Group {
                switch sheet {
                case .confirm(let l):
                    PairConfirmSheet(pair: l).presentationDetents([.height(320)])
                case .paste:
                    PasteLinkSheet(initial: link.pasteDraft).presentationDetents([.height(360), .large])
                case .connection:
                    ConnectionSheet().presentationDetents([.height(380)])
                }
            }
            .presentationDragIndicator(.visible)
            .presentationBackground(Color.black)
            .preferredColorScheme(.dark)
        }
        .fullScreenCover(isPresented: $link.scanning, onDismiss: { link.scanClosed() }) {
            ScannerScreen().preferredColorScheme(.dark)
        }
        .confirmationDialog("断开 \(ServerConfig.resolved?.name ?? "这台电脑")？", isPresented: $link.confirmUnpair,
                            titleVisibility: .visible) {
            Button("断开", role: .destructive) { link.unpair() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("之后要重新扫码才能连上")
        }
        // 系统相机扫码 / 点配对链接打开 App：phealth://pair?…（别的 phealth:// 链接由主界面处理）
        .onOpenURL { url in link.handleOpenURL(url) }
        .task {
            #if DEBUG
            // UI 测试：-pairURL <链接>，和从系统相机打开同一条路
            let a = ProcessInfo.processInfo.arguments
            if let i = a.firstIndex(of: "-pairURL"), i + 1 < a.count, let u = URL(string: a[i + 1]) {
                try? await Task.sleep(for: .milliseconds(600))
                link.handleOpenURL(u)
            }
            #endif
        }
    }
}

// MARK: - 引导页：P-Health 跑在你自己的电脑上；三步；扫码 / 粘贴 / 先看看演示
struct OnboardingView: View {
    @ObservedObject private var link = ServerLink.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer(minLength: 24)
            MobiusMark(lineWidth: 1)
                .frame(width: 64)
                .accessibilityHidden(true)
            Text("P-Health")
                .font(E.light(34)).foregroundStyle(E.text)
                .padding(.top, 28)
                .accessibilityAddTraits(.isHeader)
            Text("跑在你自己的电脑上")
                .font(E.body(15)).foregroundStyle(E.text2)
                .padding(.top, 8)
            VStack(spacing: 0) {
                step(1, "在 DeepSeek Harness 里安装 P-Health 插件")
                step(2, "电脑上会出现配对二维码")
                step(3, "用手机扫码")
            }
            .overlay(alignment: .bottom) { Hairline(color: E.line2) }
            .padding(.top, 44)
            Spacer(minLength: 32)
            VStack(spacing: 12) {
                WidePill(title: "扫码配对", filled: true) { link.startScan() }
                    .accessibilityIdentifier("onboard-scan")
                WidePill(title: "粘贴链接") { link.showPaste() }
                    .accessibilityIdentifier("onboard-paste")
                if DemoStore.available {
                    QuietButton(title: "先看看演示") { link.enterDemo() }
                        .accessibilityIdentifier("onboard-demo")
                }
            }
            .padding(.bottom, 16)
        }
        .padding(.horizontal, E.gutter)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(E.bg.ignoresSafeArea())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("onboarding")
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(spacing: 14) {
            Text("\(n)")
                .font(E.light(13)).foregroundStyle(E.text)
                .frame(width: 26, height: 26)
                .overlay(Circle().strokeBorder(E.text, lineWidth: 1))
            Text(text).font(E.body(15)).foregroundStyle(E.text)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.vertical, 14)
        .frame(minHeight: 56)
        .overlay(alignment: .top) { Hairline(color: E.line2) }
        .accessibilityElement(children: .combine)
    }
}

/// 整行宽的胶囊按钮（引导页、配对弹层）
struct WidePill: View {
    let title: String
    var filled = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title)
                .font(E.body(16))
                .foregroundStyle(filled ? Color.black : E.text)
                .frame(maxWidth: .infinity, minHeight: 50)
                .background(Capsule().fill(filled ? E.text : Color.clear))
                .overlay(Capsule().strokeBorder(E.text, lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(EPress())
    }
}

// MARK: - 「连接到 X？」：试连 → 存下 → 换成这台电脑。连不上 / 密钥不对：说清楚，什么都不存
struct PairConfirmSheet: View {
    let pair: PairLink
    private enum Phase: Equatable { case idle, probing, failed(String), done }
    @State private var phase: Phase = .idle
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("连接到 \(pair.name)？")
                .font(E.light(26)).foregroundStyle(E.text)
                .lineLimit(2).minimumScaleFactor(0.7)
                .padding(.top, 36)
                .accessibilityIdentifier("pair-title")
            Text(pair.hosts.joined(separator: " · "))
                .font(E.body(12)).foregroundStyle(E.text3).lineLimit(1).truncationMode(.middle)
                .padding(.top, 8)
            Group {
                switch phase {
                case .idle:
                    Color.clear.frame(height: 1)
                case .probing:
                    WorkingLine().frame(width: 120)
                case .failed(let m):
                    Text(m).font(E.body(13)).foregroundStyle(E.text2).lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("pair-error")
                case .done:
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark").font(.system(size: 12, weight: .light))
                            .frame(width: 22, height: 22).overlay(Circle().strokeBorder(E.text, lineWidth: 1))
                        Text("已连接").font(E.body(14))
                    }
                    .foregroundStyle(E.text)
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("pair-done")
                }
            }
            .frame(minHeight: 44, alignment: .leading)
            .padding(.top, 20)
            Spacer(minLength: 12)
            HStack(spacing: 12) {
                QuietButton(title: "取消") { dismiss() }
                    .accessibilityIdentifier("pair-cancel")
                WidePill(title: phase == .idle || phase == .probing ? "连接" : "重试", filled: true) { connect() }
                    .disabled(phase == .probing || phase == .done)
                    .opacity(phase == .probing ? 0.5 : 1)
                    .accessibilityIdentifier("pair-connect")
            }
            .padding(.bottom, 12)
        }
        .padding(.horizontal, E.gutter)
        .animation(.easeOut(duration: 0.2), value: phase)
        .interactiveDismissDisabled(phase == .probing)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("pair-confirm")
    }

    private func connect() {
        phase = .probing
        Task { @MainActor in
            if let err = await ServerLink.shared.pairProbe(pair) {
                Haptic.tap()
                phase = .failed(err.message)
            } else {
                phase = .done
                Haptic.tap()
                try? await Task.sleep(for: .milliseconds(700))
                ServerLink.shared.commitPair()
            }
        }
    }
}

// MARK: - 粘贴配对链接（电脑上的配对页、终端里都有这条链接）
struct PasteLinkSheet: View {
    @State private var text: String
    @State private var error: String?
    @FocusState private var focused: Bool

    init(initial: String) { _text = State(initialValue: initial) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("粘贴配对链接").font(E.light(26)).foregroundStyle(E.text)
                .padding(.top, 36)
            TextField("", text: $text, prompt: Text("phealth://pair?…").foregroundStyle(E.hint), axis: .vertical)
                .lineLimit(1...4)
                .font(E.body(14)).foregroundStyle(E.text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .focused($focused)
                .padding(.horizontal, 16).padding(.vertical, 13)
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(E.stroke, lineWidth: 1))
                .padding(.top, 20)
                .accessibilityIdentifier("pair-paste-field")
                .onChange(of: text) { _, _ in if error != nil { error = nil } }
            Text(error ?? " ")
                .font(E.body(13)).foregroundStyle(E.text2)
                .frame(minHeight: 30, alignment: .leading)
                .padding(.top, 6)
                .accessibilityIdentifier("pair-paste-error")
            Spacer(minLength: 8)
            HStack(spacing: 12) {
                // 系统的粘贴按钮：不弹「允许粘贴」
                PasteButton(payloadType: String.self) { strings in
                    if let s = strings.first { text = s.trimmingCharacters(in: .whitespacesAndNewlines) }
                }
                .labelStyle(.titleOnly)
                .buttonBorderShape(.capsule)
                .tint(E.grey1E)
                WidePill(title: "连接", filled: true) { submit() }
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .opacity(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.4 : 1)
                    .accessibilityIdentifier("pair-paste-connect")
            }
            .padding(.bottom, 12)
        }
        .padding(.horizontal, E.gutter)
        .onAppear { if text.isEmpty { focused = true } }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("pair-paste")
    }

    private func submit() {
        guard let l = PairLink(text: text) else {
            error = "这不是 P-Health 的配对链接"
            return
        }
        ServerLink.shared.offer(l)
    }
}

// MARK: - 连接设置：现在连的哪台电脑；换一台 / 断开
struct ConnectionSheet: View {
    @ObservedObject private var link = ServerLink.shared

    var body: some View {
        let r = ServerConfig.resolved
        VStack(alignment: .leading, spacing: 0) {
            Text(r == nil ? "没连电脑" : "已连接").font(E.body(13)).foregroundStyle(E.text2)
                .padding(.top, 36)
            Text(r?.name ?? "P-Health").font(E.light(28)).foregroundStyle(E.text)
                .lineLimit(1).minimumScaleFactor(0.7)
                .padding(.top, 6)
            if let r {
                Text("\(r.host) · \(ServerConfig.pushMode == .local ? "手机自己提醒" : "电脑推送提醒")")
                    .font(E.body(12)).foregroundStyle(E.text3).lineLimit(1)
                    .padding(.top, 8)
            }
            if link.keyRejected {
                Text("这台电脑不认这个配对了，重新扫码").font(E.body(13)).foregroundStyle(E.text2).padding(.top, 10)
            }
            VStack(spacing: 0) {
                row("qrcode.viewfinder", "换一台电脑") { link.startScan() }
                    .accessibilityIdentifier("conn-rescan")
                row("doc.on.clipboard", "粘贴配对链接") { link.showPaste() }
                if Self.canUnpair {
                    row("xmark", "断开") {
                        link.sheet = nil
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { link.confirmUnpair = true }
                    }
                    .accessibilityIdentifier("conn-unpair")
                }
            }
            .overlay(alignment: .bottom) { Hairline(color: E.line2) }
            .padding(.top, 24)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, E.gutter)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("connection")
    }

    /// 能断开的：配对过的电脑，或者开发版编进去的那份（模拟回放的测试环境不断）
    static var canUnpair: Bool {
        switch ServerConfig.source {
        case .paired: return true
        case .local: return !Profile.isSim
        case .none: return false
        }
    }

    private func row(_ icon: String, _ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: icon).font(.system(size: 12, weight: .light))
                    .frame(width: 28, height: 28).overlay(Circle().strokeBorder(E.text, lineWidth: 1))
                Text(title).font(E.body(15))
                Spacer(minLength: 0)
            }
            .foregroundStyle(E.text)
            .frame(minHeight: 54)
            .overlay(alignment: .top) { Hairline(color: E.line2) }
            .contentShape(Rectangle())
        }
        .buttonStyle(EPress())
    }
}

// MARK: - 扫码（全屏）：相机对准电脑上的二维码
struct ScannerScreen: View {
    @ObservedObject private var link = ServerLink.shared
    @State private var status = AVCaptureDevice.authorizationStatus(for: .video)
    @State private var hint: String?
    @State private var found = false

    private var hasCamera: Bool { AVCaptureDevice.default(for: .video) != nil }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if !hasCamera {
                message("这台设备没有相机")
            } else if status == .authorized {
                QRScannerView { code in handle(code) }
                    .ignoresSafeArea()
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .strokeBorder(E.text, lineWidth: 1)
                    .frame(width: 248, height: 248)
                    .accessibilityHidden(true)
            } else if status == .denied || status == .restricted {
                VStack(spacing: 16) {
                    message("相机没打开")
                    OutlinePill(title: "去设置") {
                        if let u = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(u) }
                    }
                }
            }
            VStack(spacing: 0) {
                HStack {
                    Spacer()
                    Button { link.scanning = false } label: {
                        Image(systemName: "xmark").font(.system(size: 13, weight: .light)).foregroundStyle(E.text)
                            .frame(width: 36, height: 36)
                            .background(Circle().fill(Color.black.opacity(0.5)))
                            .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                            .hitArea(4, 4)
                    }
                    .buttonStyle(EPress())
                    .accessibilityLabel("关闭")
                    .accessibilityIdentifier("scan-close")
                }
                .padding(.horizontal, 20).padding(.top, 12)
                Spacer()
                if hasCamera && status == .authorized {
                    Text(hint ?? "对准电脑上的二维码")
                        .font(E.body(14)).foregroundStyle(E.text)
                        .padding(.horizontal, 14).frame(minHeight: 32)
                        .background(Capsule().fill(Color.black.opacity(0.55)))
                        .accessibilityIdentifier("scan-hint")
                }
                QuietButton(title: "粘贴链接") {
                    link.afterScanSheet = .paste
                    link.scanning = false
                }
                .padding(.top, 10).padding(.bottom, 20)
            }
        }
        .task {
            guard hasCamera, status == .notDetermined else { return }
            let ok = await AVCaptureDevice.requestAccess(for: .video)
            status = ok ? .authorized : .denied
        }
    }

    private func message(_ s: String) -> some View {
        Text(s).font(E.body(15)).foregroundStyle(E.text2)
    }

    private func handle(_ code: String) {
        guard !found else { return }
        if let l = PairLink(text: code) {
            found = true
            Haptic.tap()
            link.offer(l)
        } else if hint == nil {
            hint = "这不是 P-Health 的配对码"
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { hint = nil }
        }
    }
}

/// AVFoundation 的二维码识别：只认二维码，识别到的字交给 onCode（主线程）
struct QRScannerView: UIViewRepresentable {
    let onCode: (String) -> Void

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }

    final class Coordinator: NSObject, AVCaptureMetadataOutputObjectsDelegate {
        let session = AVCaptureSession()
        let queue = DispatchQueue(label: "phealth.qr-scan")
        var onCode: (String) -> Void
        init(onCode: @escaping (String) -> Void) { self.onCode = onCode }

        func configure() {
            queue.async { [session] in
                session.beginConfiguration()
                if let device = AVCaptureDevice.default(for: .video),
                   let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) {
                    session.addInput(input)
                }
                let output = AVCaptureMetadataOutput()
                if session.canAddOutput(output) {
                    session.addOutput(output)
                    output.setMetadataObjectsDelegate(self, queue: .main)
                    if output.availableMetadataObjectTypes.contains(.qr) { output.metadataObjectTypes = [.qr] }
                }
                session.commitConfiguration()
                session.startRunning()
            }
        }

        func stop() { queue.async { [session] in if session.isRunning { session.stopRunning() } } }

        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject],
                            from connection: AVCaptureConnection) {
            for o in objects {
                if let code = (o as? AVMetadataMachineReadableCodeObject)?.stringValue { onCode(code) }
            }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(onCode: onCode) }

    func makeUIView(context: Context) -> PreviewView {
        let v = PreviewView()
        v.backgroundColor = .black
        v.preview.session = context.coordinator.session
        v.preview.videoGravity = .resizeAspectFill
        context.coordinator.configure()
        return v
    }

    func updateUIView(_ uiView: PreviewView, context: Context) { context.coordinator.onCode = onCode }

    static func dismantleUIView(_ uiView: PreviewView, coordinator: Coordinator) { coordinator.stop() }
}

// MARK: - 演示里：页面顶上的小标记（点了回到引导页）；对话里输入框的位置换成一句话
struct DemoBadge: View {
    var body: some View {
        Button { ServerLink.shared.exitDemo() } label: {
            HStack(spacing: 6) {
                Text("演示").font(E.body(12))
                Image(systemName: "xmark").font(.system(size: 8, weight: .light))
            }
            .foregroundStyle(E.text2)
            .padding(.horizontal, 12)
            .frame(height: 26)
            .background(Capsule().fill(Color.black))
            .overlay(Capsule().strokeBorder(E.stroke, lineWidth: 1))
            .hitArea(8, 9)
        }
        .buttonStyle(EPress())
        .accessibilityLabel("演示中，点一下回到配对")
        .accessibilityIdentifier("demo-badge")
    }
}

struct DemoChatNote: View {
    let onPair: () -> Void
    var body: some View {
        HStack(spacing: 12) {
            Text("对话要连上你自己的电脑").font(E.body(14)).foregroundStyle(E.text2)
            Spacer(minLength: 8)
            OutlinePill(title: "去配对", width: 88, action: onPair)
                .accessibilityIdentifier("demo-chat-pair")
        }
        .padding(.horizontal, E.chatGutter)
        .padding(.top, 10)
        .padding(.bottom, 8)
        .background(Color.black.ignoresSafeArea(edges: .bottom).overlay(alignment: .top) { Hairline(color: E.line2) })
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("demo-chat-note")
    }
}

extension Notification.Name {
    /// 配对链接从外面打开：主界面先把自己开着的抽屉、全屏页收起来，配对弹层才出得来
    static let pivisDismissForPairing = Notification.Name("pivisDismissForPairing")
}
