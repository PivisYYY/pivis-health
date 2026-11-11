import SwiftUI
import AVFoundation
import MediaPlayer

// MARK: - 练习视频播放器（全屏、对话里、习惯卡里都用这一个）
// - playing 跟着 AVPlayer 的真实状态走（KVO timeControlStatus），不只是记自己调过 play / pause；
// - 来电、闹钟打断后按系统建议接着放；耳机拔掉就停；
// - 锁屏 / 控制中心显示标题和进度，能播放、暂停；
// - 同一时间只放一个：新的开始放，上一个自动暂停；
// - 关掉时释放音频会话（notifyOthersOnDeactivation），别的 App 的声音能接着放。
@MainActor
final class PracticePlayer: ObservableObject {
    @Published private(set) var elapsed: Double = 0
    @Published private(set) var duration: Double = 0
    @Published private(set) var playing = false
    @Published private(set) var finished = false
    @Published private(set) var muted = false
    /// 正在全屏看：画面只交给全屏那一层，卡里的小窗先放手（同一个播放器同时挂两层，全屏那层会黑屏，老大 11-11）
    @Published var fullscreen = false
    /// 点了封面才建；没建时外面显示封面
    @Published private(set) var player: AVPlayer?
    private(set) var url: URL?
    private var title = ""
    private var timeObserver: Any?
    private var statusObservation: NSKeyValueObservation?
    private var observers: [NSObjectProtocol] = []
    private var remoteTargets: [(MPRemoteCommand, Any)] = []
    private var resumeAfterInterruption = false

    /// 正在占着音频会话和锁屏控制的那个
    private static weak var current: PracticePlayer?

    func load(url: URL, title: String, minutes: Double?) {
        stop()
        self.url = url
        self.title = title
        elapsed = 0
        finished = false
        duration = (minutes ?? 0) * 60
        let item = AVPlayerItem(url: VideoCache.shared.playableURL(for: url))   // 下到手机上的直接播本地；没下好先在线播、后台下
        let p = AVPlayer(playerItem: item)
        p.audiovisualBackgroundPlaybackPolicy = .continuesIfPossible   // 锁屏 / 切到后台声音接着放（睡前可以锁屏只听）
        p.isMuted = muted
        player = p
        timeObserver = p.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.5, preferredTimescale: 600), queue: .main) { [weak self] t in
            let d = p.currentItem?.duration.seconds
            Task { @MainActor in
                guard let self, self.player === p else { return }
                self.elapsed = t.seconds
                if let d, d.isFinite, d > 0, abs(d - self.duration) > 0.5 {
                    self.duration = d
                    self.publishNowPlaying()
                }
            }
        }
        statusObservation = p.observe(\.timeControlStatus, options: [.initial, .new]) { [weak self] obj, _ in
            let status = obj.timeControlStatus
            Task { @MainActor in
                guard let self, self.player === p else { return }
                let on = status != .paused
                if self.playing != on { self.playing = on }
                self.keepAwake()
                self.publishNowPlaying()
            }
        }
        let nc = NotificationCenter.default
        observers = [
            nc.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.finished = true; self?.keepAwake(); self?.publishNowPlaying() }
            },
            nc.addObserver(forName: AVAudioSession.interruptionNotification, object: AVAudioSession.sharedInstance(), queue: .main) { [weak self] note in
                let type = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt).flatMap(AVAudioSession.InterruptionType.init)
                let options = AVAudioSession.InterruptionOptions(rawValue: note.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0)
                Task { @MainActor in self?.interrupted(type, options) }
            },
            nc.addObserver(forName: AVAudioSession.routeChangeNotification, object: AVAudioSession.sharedInstance(), queue: .main) { [weak self] note in
                let reason = (note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt).flatMap(AVAudioSession.RouteChangeReason.init)
                // 耳机拔掉 / 蓝牙断开：停下，不让声音突然从外放出来
                if reason == .oldDeviceUnavailable { Task { @MainActor in self?.pause() } }
            },
        ]
    }

    func play() {
        guard let player else { return }
        claim()
        if finished { player.seek(to: .zero); finished = false; elapsed = 0 }   // 放完了再点：从头再来一遍
        player.play()
    }

    func pause() { player?.pause() }

    func toggle() { playing ? pause() : play() }

    func toggleMute() {
        muted.toggle()
        player?.isMuted = muted
    }

    /// 关掉：放掉播放器、观察者；占着音频会话的话还回去，锁屏上的控制也撤掉
    func stop() {
        player?.pause()
        if let timeObserver, let player { player.removeTimeObserver(timeObserver) }
        timeObserver = nil
        statusObservation?.invalidate()
        statusObservation = nil
        for o in observers { NotificationCenter.default.removeObserver(o) }
        observers = []
        player = nil
        url = nil
        playing = false
        resumeAfterInterruption = false
        if Self.current === self {
            Self.current = nil
            UIApplication.shared.isIdleTimerDisabled = false
            releaseRemote()
            MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    /// 放着的时候不自动锁屏（跟练十几分钟，看着看着屏幕熄了就跟不下去）；停了、放完了交还系统
    private func keepAwake() {
        guard Self.current === self else { return }
        UIApplication.shared.isIdleTimerDisabled = playing && !finished
    }

    // MARK: 音频会话、锁屏控制
    private func claim() {
        if let prev = Self.current, prev !== self {
            prev.pause()
            prev.releaseRemote()
        }
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .moviePlayback)
        try? session.setActive(true)
        if Self.current !== self || remoteTargets.isEmpty {
            Self.current = self
            registerRemote()
        }
    }

    private func registerRemote() {
        releaseRemote()
        let c = MPRemoteCommandCenter.shared()
        func on(_ cmd: MPRemoteCommand, _ action: @escaping @MainActor (PracticePlayer) -> Void) {
            cmd.isEnabled = true
            let token = cmd.addTarget { [weak self] _ in
                Task { @MainActor in if let self { action(self) } }
                return .success
            }
            remoteTargets.append((cmd, token))
        }
        on(c.playCommand) { $0.play() }
        on(c.pauseCommand) { $0.pause() }
        on(c.togglePlayPauseCommand) { $0.toggle() }
    }

    private func releaseRemote() {
        for (cmd, token) in remoteTargets { cmd.removeTarget(token) }
        remoteTargets = []
    }

    private func publishNowPlaying() {
        guard Self.current === self, player != nil else { return }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: "P-Health",
            MPNowPlayingInfoPropertyElapsedPlaybackTime: elapsed,
            MPNowPlayingInfoPropertyPlaybackRate: playing ? 1.0 : 0.0,
        ]
        if duration > 0 { info[MPMediaItemPropertyPlaybackDuration] = duration }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func interrupted(_ type: AVAudioSession.InterruptionType?, _ options: AVAudioSession.InterruptionOptions) {
        switch type {
        case .began:
            resumeAfterInterruption = playing      // 系统已经替我们停了；记下来，结束后看要不要接着放
        case .ended:
            if resumeAfterInterruption, options.contains(.shouldResume) { play() }
            resumeAfterInterruption = false
        default:
            break
        }
    }
}

// MARK: - 练习视频全屏播放（待办卡、提醒、小组件、画布里的跟练入口都进这里）
// 只有：「先到这」（关掉，不记任何东西）、标题、静音、进度条。做完了在卡上点对勾才算；打开播放器不改待办的状态。
struct ExecView: View {
    let title: String
    let media: V3Media?
    var fallbackMinutes: Double? = nil
    @Environment(\.dismiss) private var dismiss
    @StateObject private var pp = PracticePlayer()

    init(todo: V3Todo) {
        title = todo.title
        media = todo.practiceVideo
        fallbackMinutes = todo.durationMin
    }

    init(media: V3Media, title: String? = nil) {
        self.title = title ?? media.title ?? ""
        self.media = media
        fallbackMinutes = media.durationMin
    }

    var body: some View {
        ZStack {
            E.surface.ignoresSafeArea()
            if let player = pp.player {
                PlayerLayerView(player: player, gravity: .resizeAspect)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture { pp.toggle() }
                    .accessibilityIdentifier("exec-video")
                    .accessibilityLabel(pp.playing ? "暂停" : "继续")
                    .accessibilityAddTraits(.isButton)
                if !pp.playing { PlayBadge(size: 64) }
            } else {
                Text("这张卡没有练习视频").font(E.body(15)).foregroundStyle(E.text2)
            }
            VStack(spacing: 0) {
                topBar
                Spacer()
                progress
            }
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .onAppear {
            guard pp.player == nil, let v = media, let url = PivisAPI.resolve(v.url) else { return }
            pp.load(url: url, title: title, minutes: v.durationMin ?? fallbackMinutes)
            pp.play()
        }
        .onDisappear { pp.stop() }
    }

    private var topBar: some View {
        HStack {
            // 先到这：只是关掉，不记任何东西；做完了在卡上点对勾
            Button { dismiss() } label: {
                Text("先到这").font(E.body(13)).foregroundStyle(E.text)
                    .padding(.horizontal, 14).frame(height: 36)
                    .background(Capsule().fill(Color.black.opacity(0.5)))
                    .overlay(Capsule().strokeBorder(E.stroke, lineWidth: 1))
                    .hitArea(0, 4)          // 画出来 36 高，点的范围 44
            }
            .buttonStyle(EPress())
            .accessibilityIdentifier("exec-close")
            Spacer()
            Text(title).font(E.body(15)).foregroundStyle(E.text).lineLimit(1)
            Spacer()
            Button { pp.toggleMute() } label: {
                Image(systemName: pp.muted ? "speaker.slash" : "speaker.wave.2")
                    .font(.system(size: 13, weight: .light)).foregroundStyle(E.text)
                    .frame(width: 36, height: 36)
                    .background(Circle().fill(Color.black.opacity(0.5)))
                    .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                    .frame(width: 44, height: 44)
                    .contentShape(Circle())
            }
            .buttonStyle(EPress())
            .accessibilityLabel(pp.muted ? "打开声音" : "静音")
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
    }

    private var progress: some View {
        let total = max(pp.duration, 1)
        let frac = min(1, pp.elapsed / total)
        return VStack(spacing: 10) {
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Rectangle().fill(E.stroke)
                    Rectangle().fill(E.text).frame(width: g.size.width * frac)
                        .animation(.linear(duration: 0.5), value: frac)
                }
            }
            .frame(height: 2)
            HStack {
                Text(clockText(pp.elapsed))
                Spacer()
                Text(pp.duration > 0 ? clockText(pp.duration) : "")
            }
            .font(E.body(12)).foregroundStyle(E.text2).monospacedDigit()
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 24)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("exec-progress")
    }
}

/// 0:00 这样的播放时间
func clockText(_ s: Double) -> String {
    let t = max(0, Int(s.rounded()))
    return String(format: "%d:%02d", t / 60, t % 60)
}

/// 视频上的白色播放钮（暂停时）
struct PlayBadge: View {
    var size: CGFloat = 52
    var body: some View {
        Image(systemName: "play.fill").font(.system(size: size * 0.31)).foregroundStyle(Color.black)
            .frame(width: size, height: size)
            .background(Circle().fill(Color.white.opacity(0.85)))
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}

// MARK: - 原生视频层（不带系统控件）
struct PlayerLayerView: UIViewRepresentable {
    /// nil = 这一层先不出画面（画面交给了别的层，比如全屏）
    let player: AVPlayer?
    var gravity: AVLayerVideoGravity = .resizeAspectFill
    func makeUIView(context: Context) -> PlayerUIView {
        let v = PlayerUIView()
        v.backgroundColor = .clear
        v.playerLayer.videoGravity = gravity
        v.playerLayer.player = player
        return v
    }
    func updateUIView(_ v: PlayerUIView, context: Context) {
        if v.playerLayer.player !== player { v.playerLayer.player = player }
    }
    /// 视图拆掉时放手：不然离场动画期间它还挂着播放器，和新的那层抢画面
    static func dismantleUIView(_ v: PlayerUIView, coordinator: ()) {
        v.playerLayer.player = nil
    }
    final class PlayerUIView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }
}
