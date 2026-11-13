import SwiftUI

// MARK: - 下拉刷新后的两个小圆点（build 53）：WHOOP、Apple 健康的数据新不新。不写字。
// 实心 = 新的；空心 = 不是最新（不等于「没连上」：服务器在后台补拉、手机没开 App 都会这样，不用 Psir 做什么）；
// 服务器在后台补拉 WHOOP 时那个点慢慢呼吸。只有服务器说要 Psir 动手（action）时下面才出一句话，
// WHOOP 登录失效那句可以点，直接重新登录。

struct HealthDots: Equatable {
    let whoopFresh: Bool
    let appleFresh: Bool
    let pulling: Bool
    let action: String?
    let needsLogin: Bool

    init(sync w: V3API.HealthSync, appleUploaded: Bool) {
        whoopFresh = w.whoop == "fresh"
        // 手机这次传上去、服务器收下了，或者服务器那边本来就是新的
        appleFresh = appleUploaded || w.apple == "fresh"
        pulling = w.pulling == true
        action = w.action.flatMap { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : $0 }
        needsLogin = w.whoop == "needs_login"
    }

    /// 读屏读的（画面上没有字）
    var spoken: String {
        let whoop = (whoopFresh ? "WHOOP 数据是最新的" : "WHOOP 数据不是最新的") + (pulling ? "，正在补拉" : "")
        let apple = appleFresh ? "Apple 健康数据是最新的" : "Apple 健康数据不是最新的"
        return "\(whoop)；\(apple)"
    }
}

struct HealthDotsView: View {
    let dots: HealthDots
    let onLogin: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 14) {
                item("waveform.path.ecg", fresh: dots.whoopFresh, pulse: dots.pulling)
                item("heart", fresh: dots.appleFresh, pulse: false)
            }
            .padding(.horizontal, 12)
            .frame(height: 28)
            .background(Capsule().fill(Color.black))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(dots.spoken)
            .accessibilityIdentifier("sync-dots")
            if let action = dots.action { actionLine(action) }
        }
    }

    private func item(_ glyph: String, fresh: Bool, pulse: Bool) -> some View {
        HStack(spacing: 5) {
            Image(systemName: glyph).font(.system(size: 10, weight: .light)).foregroundStyle(E.text2)
            PulseDot(filled: fresh, pulsing: pulse)
        }
    }

    /// 要 Psir 动手的那一句（服务器的原话）；WHOOP 登录失效那句点了直接重新登录
    @ViewBuilder
    private func actionLine(_ text: String) -> some View {
        let line = HStack(spacing: 6) {
            Text(text).font(E.body(12)).foregroundStyle(E.text)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
            if dots.needsLogin {
                Image(systemName: "chevron.right").font(.system(size: 10, weight: .light)).foregroundStyle(E.text2)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 9)
        .background(Capsule().fill(Color.black))
        .overlay(Capsule().strokeBorder(E.stroke, lineWidth: 1))
        if dots.needsLogin {
            Button(action: onLogin) { line.contentShape(Capsule()) }
                .buttonStyle(EPress())
                .accessibilityHint("点一下重新登录 WHOOP")
                .accessibilityIdentifier("sync-action")
        } else {
            line.accessibilityElement(children: .combine).accessibilityIdentifier("sync-action")
        }
    }
}

/// 一个小圆点：实心 / 空心细线；pulsing 时慢慢明暗（减弱动态效果时不动）
private struct PulseDot: View {
    let filled: Bool
    let pulsing: Bool
    @State private var dim = false
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        ZStack {
            Circle().fill(filled ? E.text : Color.clear)
            Circle().strokeBorder(E.text, lineWidth: 1)
        }
        .frame(width: 7, height: 7)
        .opacity(pulsing && dim ? 0.3 : 1)
        .onAppear {
            guard pulsing, !reduce else { return }
            withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) { dim = true }
        }
    }
}
