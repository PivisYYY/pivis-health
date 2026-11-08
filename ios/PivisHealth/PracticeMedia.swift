import SwiftUI

// MARK: - 练习视频（follow 出的片，9:16）只有这一套：封面 → 点了才建播放器
// 待办卡（点了全屏）、习惯卡 / 对话里的视频卡（就地播）、画布里的跟练入口（点了全屏）都用这里的组件，
// 播放都走 PracticePlayer，地址都走 PivisAPI.resolve。

/// 封面：服务器给了 poster 就画它，没有就是一块深色框（不再按视频地址去猜封面）
struct PracticeCover: View {
    let poster: String?
    var body: some View {
        ZStack {
            E.surface
            if let url = PivisAPI.resolve(poster) {
                ServerImage(url: url, contentMode: .fit) { _ in E.grey14.aspectRatio(9 / 16, contentMode: .fit) }
            }
        }
    }
}

/// 练习视频就地播：先是封面 + 播放钮，点了才建播放器；播放器可以由外面拿着（习惯卡收起来也不断）
struct PracticeVideoView: View {
    let media: V3Media
    @ObservedObject var player: PracticePlayer
    var height: CGFloat = 440

    private var url: URL? { PivisAPI.resolve(media.url) }
    private var active: Bool { url != nil && player.url == url && player.player != nil }

    var body: some View {
        ZStack(alignment: .bottom) {
            if active, let p = player.player {
                E.surface
                PlayerLayerView(player: p, gravity: .resizeAspect)
                    .contentShape(Rectangle())
                    .onTapGesture { player.toggle() }
                    .accessibilityElement()
                    .accessibilityLabel(player.playing ? "暂停" : "播放")
                    .accessibilityAddTraits(.isButton)
                    .accessibilityAction { player.toggle() }
                if !player.playing { PlayBadge().frame(maxHeight: .infinity) }
                progressLine
            } else {
                Button {
                    guard let url else { return }
                    player.load(url: url, title: media.title ?? "", minutes: media.durationMin)
                    player.play()
                } label: {
                    ZStack {
                        PracticeCover(poster: media.poster)
                        PlayBadge()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(EPress())
                .disabled(url == nil)
                .accessibilityLabel("播放视频" + (media.title.map { "：\($0)" } ?? ""))
            }
        }
        .frame(height: height)
        .frame(maxWidth: .infinity)
        .background(E.surface)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        // 右上角全屏：同一个播放器接着放，关掉回到这里还在原来的位置
        .overlay(alignment: .topTrailing) {
            if url != nil {
                Button {
                    if !active, let url {
                        player.load(url: url, title: media.title ?? "", minutes: media.durationMin)
                        player.play()
                    }
                    FullscreenVideo.present(player)
                } label: {
                    Image(systemName: "arrow.up.left.and.arrow.down.right").font(.system(size: 12, weight: .light))
                        .foregroundStyle(E.text)
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(Color.black.opacity(0.45)))
                        .overlay(Circle().strokeBorder(E.text2, lineWidth: 1))
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(EPress())
                .padding(4)
                .accessibilityLabel("全屏播放")
                .accessibilityIdentifier("practice-video-fullscreen")
            }
        }
        // 看到封面就在 Wi-Fi 下把片下到手机上：出门在外（连不上家里的服务器）也能放
        .onAppear { if let url { VideoCache.shared.prefetch(url) } }
        // 先当成容器：不然外面这个标识会盖掉里面按钮（全屏）的标识
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("practice-video")
    }

    private var progressLine: some View {
        GeometryReader { g in
            let frac = player.duration > 0 ? min(1, player.elapsed / player.duration) : 0
            ZStack(alignment: .leading) {
                Rectangle().fill(E.stroke)
                Rectangle().fill(E.text).frame(width: g.size.width * frac)
            }
        }
        .frame(height: 2)
        .allowsHitTesting(false)
    }
}

/// 全屏从最上面那层窗口弹出来，不挂在习惯卡 / 对话卡上：以前挂在卡上，全屏期间卡一收起（对话里滚动会收起习惯卡），
/// 全屏就没了主人，右上角 × 点了没反应（老大 11-08）。现在自己拿着这一层，× 直接关掉它
@MainActor
enum FullscreenVideo {
    private final class Holder { weak var vc: UIViewController? }

    static func present(_ player: PracticePlayer) {
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
        guard var top = (windows.first { $0.isKeyWindow } ?? windows.first)?.rootViewController else { return }
        while let next = top.presentedViewController, !next.isBeingDismissed { top = next }
        let holder = Holder()
        let host = UIHostingController(rootView: PracticeFullscreen(player: player, onClose: { holder.vc?.dismiss(animated: true) }))
        holder.vc = host
        host.modalPresentationStyle = .fullScreen
        host.view.backgroundColor = .black
        top.present(host, animated: true)
    }
}

/// 全屏看练习视频：黑底、原比例，点画面暂停 / 继续，底下一根细进度线，右上角关掉
struct PracticeFullscreen: View {
    @ObservedObject var player: PracticePlayer
    var onClose: () -> Void

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let p = player.player {
                PlayerLayerView(player: p, gravity: .resizeAspect)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture { player.toggle() }
                    .accessibilityElement()
                    .accessibilityLabel(player.playing ? "暂停" : "播放")
                    .accessibilityAddTraits(.isButton)
                    .accessibilityAction { player.toggle() }
                if !player.playing { PlayBadge().allowsHitTesting(false) }
            }
            VStack {
                HStack {
                    Spacer()
                    Button { onClose() } label: {
                        Image(systemName: "xmark").font(.system(size: 14, weight: .light)).foregroundStyle(E.text)
                            .frame(width: 44, height: 44)
                            .overlay(Circle().strokeBorder(E.text2, lineWidth: 1))
                    }
                    .buttonStyle(EPress())
                    .accessibilityLabel("退出全屏")
                    .accessibilityIdentifier("practice-fullscreen-close")
                }
                .padding(.horizontal, 16)
                Spacer()
                GeometryReader { g in
                    let frac = player.duration > 0 ? min(1, player.elapsed / player.duration) : 0
                    ZStack(alignment: .leading) {
                        Rectangle().fill(E.stroke)
                        Rectangle().fill(E.text).frame(width: g.size.width * frac)
                    }
                }
                .frame(height: 2)
                .padding(.horizontal, 16)
                .padding(.bottom, 12)
                .allowsHitTesting(false)
            }
        }
        .statusBarHidden()
    }
}

/// 自己拿着播放器的练习视频（对话里的视频卡：每张卡一个，离开对话就停）
struct OwnedPracticeVideo: View {
    let media: V3Media
    var height: CGFloat = 440
    @StateObject private var player = PracticePlayer()
    var body: some View {
        PracticeVideoView(media: media, player: player, height: height)
            .onDisappear { player.stop() }
    }
}

/// 练习卡展开：整宽一个视频框（封面 + 播放钮），点了全屏播放
struct PracticePoster: View {
    let video: V3Media
    let onPlay: () -> Void
    var body: some View {
        Button(action: onPlay) {
            ZStack {
                PracticeCover(poster: video.poster)
                PlayBadge()
            }
            .frame(height: 360)
            .frame(maxWidth: .infinity)
            .background(E.surface)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(EPress())
        .accessibilityLabel("全屏播放")
        .accessibilityIdentifier("todo-play")
    }
}

extension V3Todo {
    /// 练习卡的视频（follow 出的片）：新卡只有一段视频
    var practiceVideo: V3Media? {
        guard kind == "follow" else { return nil }
        return allSteps.compactMap(\.media).first { $0.isFollowVideo }
    }
    /// 新的练习卡（项目 + 一个视频）；老的多步 / 音频跟做卡只读显示
    var isPracticeVideo: Bool { kind == "follow" && allSteps.count == 1 && practiceVideo != nil }
}

extension V3HabitDoc.Video {
    var media: V3Media { V3Media(kind: "video", url: url, title: title, durationMin: durationMin, poster: poster) }
}
