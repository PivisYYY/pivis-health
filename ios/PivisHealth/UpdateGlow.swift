import SwiftUI

// MARK: - 正在改的那一块：框住它，白色流光沿边框走、外圈柔光呼吸，框里内容朦胧（6A 白色流光）
// 只用在真正在变的那块上（整张主卡 / 正在处理的几条待办），不影响页面其他地方，也不写任何字。

// MARK: - 动效开关：看不见的页、App 不在前台、内容正被框住时，里面的循环动效全部停下
private struct MotionPausedKey: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    /// true 时 LevelDot、RiskBlink、流光框等循环动效停在静止的一帧，不再每帧重画
    var motionPaused: Bool {
        get { self[MotionPausedKey.self] }
        set { self[MotionPausedKey.self] = newValue }
    }
}

/// 循环动效的帧率：这些都是慢的明暗、绕圈，30 帧看不出差别，比跟着屏幕 120 帧省四倍
let ambientFrame: Double = 1.0 / 30

/// 框住 + 朦胧。active 变 false 时光先亮一下，再淡出（新内容在这期间换上）。
/// 性能：朦胧只压暗、不做实时模糊（模糊整张卡每帧要重算一遍）；框里的内容同时冻结，流光框 30 帧、不做模糊。
struct UpdateGlow: ViewModifier {
    let active: Bool
    var cornerRadius: CGFloat = 18
    var outset: CGFloat = 9
    @State private var shown = false
    @State private var flare = false
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Environment(\.motionPaused) private var paused

    func body(content: Content) -> some View {
        content
            // 朦胧即可：压暗一点，里面的动效停住（App 本身很素，不能糊成一片）
            .environment(\.motionPaused, paused || active)
            .blur(radius: active ? 2 : 0)
            .opacity(active ? 0.6 : 1)
            .animation(.easeOut(duration: 0.4), value: active)
            .overlay {
                if shown {
                    GlowFrame(flare: flare, reduce: reduce || paused, radius: cornerRadius)
                        .padding(-outset)
                        .allowsHitTesting(false)
                        .transition(.opacity)
                        .accessibilityHidden(true)
                }
            }
            .onAppear { shown = active }
            .onChange(of: active) { _, on in
                if on {
                    flare = false
                    withAnimation(.easeOut(duration: 0.35)) { shown = true }
                } else if shown {
                    withAnimation(.easeOut(duration: 0.2)) { flare = true }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
                        withAnimation(.easeOut(duration: 0.55)) { shown = false }
                        flare = false
                    }
                }
            }
    }
}

extension View {
    func updateGlow(_ active: Bool, cornerRadius: CGFloat = 18, outset: CGFloat = 9) -> some View {
        modifier(UpdateGlow(active: active, cornerRadius: cornerRadius, outset: outset))
    }
}

/// 一道白光沿圆角框绕圈（2.8 秒一圈），外面一层柔光一明一暗（2.4 秒一呼吸）
struct GlowFrame: View {
    let flare: Bool
    let reduce: Bool
    let radius: CGFloat

    var body: some View {
        TimelineView(.animation(minimumInterval: ambientFrame, paused: reduce)) { ctx in
            let t = ctx.date.timeIntervalSinceReferenceDate
            let turn = reduce ? 0.75 : (t / 2.8).truncatingRemainder(dividingBy: 1)
            let breath = reduce ? 0.7 : 0.3 + 0.7 * (0.5 - 0.5 * cos(t / 2.4 * 2 * .pi))
            let dim = E.stroke
            let grad = AngularGradient(gradient: Gradient(stops: [
                .init(color: dim, location: 0),
                .init(color: dim, location: 0.58),
                .init(color: .white, location: 0.75),
                .init(color: dim, location: 0.92),
                .init(color: dim, location: 1),
            ]), center: .center, angle: .degrees(turn * 360))
            let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
            // 外圈柔光用三层越来越宽、越来越淡的描边叠出来，不做模糊（模糊每帧都要离屏重算）
            let glow = flare ? 1 : breath
            ZStack {
                shape.stroke(grad, lineWidth: 14).opacity(0.05 * glow)
                shape.stroke(grad, lineWidth: 8).opacity(0.10 * glow)
                shape.stroke(grad, lineWidth: 3.5).opacity(0.22 * glow)
                shape.stroke(grad, lineWidth: 1.2)
            }
            .drawingGroup()
        }
    }
}

/// 换内容：旧的朦胧淡出，新的从朦胧变清楚
struct HazeFade: ViewModifier {
    let radius: CGFloat
    let opacity: Double
    func body(content: Content) -> some View { content.blur(radius: radius).opacity(opacity) }
}

extension AnyTransition {
    static var haze: AnyTransition {
        .asymmetric(insertion: .modifier(active: HazeFade(radius: 5.2, opacity: 0), identity: HazeFade(radius: 0, opacity: 1))
                        .animation(.easeOut(duration: 0.6).delay(0.15)),
                    removal: .modifier(active: HazeFade(radius: 5.2, opacity: 0), identity: HazeFade(radius: 0, opacity: 1))
                        .animation(.easeOut(duration: 0.35)))
    }
}
