import SwiftUI

// MARK: - 对话流式文字（S2 流动渐显）
// 最前面一段字从透明、模糊流到清楚，像墨水往前流。只动刚到的字，前面的字和屏幕都不动。
// 字按稳定的速度「流过」：到得快就跟着快（不会一直落后），到得慢就匀速流完。

struct FlowingText: View {
    let text: AttributedString
    /// 这段字创建时是否正在流式到达。只有正在到达的才流；历史消息、缓存里的直接显示
    let live: Bool
    @State private var clock = FlowClock()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let count = text.characters.count
        let _ = clock.tick   // 流完时切回普通 Text（停掉逐帧刷新）
        // 注意：可选中的 Text（textSelection）不走自定义 TextRenderer，所以只在流完后的普通 Text 上打开选中
        if reduceMotion || !clock.flowing(count: count, live: live) {
            Text(text).textSelection(.enabled)
        } else {
            TimelineView(.animation(minimumInterval: 1.0 / 60)) { ctx in
                Text(text)
                    .textRenderer(clock.frame(target: count, now: ctx.date.timeIntervalSinceReferenceDate))
            }
        }
    }
}

@Observable
final class FlowClock {
    /// 只在「流完了」时变一次，让外层换回普通 Text
    var tick = 0

    @ObservationIgnored private var started = false
    @ObservationIgnored private var off = false
    /// 流到第几个字（带小数）
    @ObservationIgnored private var head: Double = 0
    @ObservationIgnored private var last: Double = 0
    /// 前面这么多字已经完全清楚
    @ObservationIgnored private var solid = 0
    /// solid 之后、head 之前每个字被流过的时刻
    @ObservationIgnored private var crossed: [Double] = []
    @ObservationIgnored private var notified = false

    /// 每个字从模糊到清楚用多久；速度 26 字/秒时，渐变正好约 15 个字长
    static let fade = 0.6
    static let minRate = 26.0
    /// 积压的字最多用这么久流完（越短，已到但还没流出来的空白越少）
    static let catchUp = 0.5
    /// 最多落后多少字（断线重连拿到整段时，只流最后这一截）
    static let maxLag = 120.0
    static let blur = 5.0

    func flowing(count: Int, live: Bool) -> Bool {
        if !started {
            started = true
            off = !live
            // 刚出现时已经有一大段（重连后拿到的整段）：前面的直接显示，只流最后 40 个字
            solid = live ? max(0, count - 40) : count
            head = Double(solid)
        }
        if off { return false }
        let done = crossed.isEmpty && solid >= count
        if !done { notified = false }
        return !done
    }

    func frame(target: Int, now: Double) -> FlowRenderer {
        let dt = last == 0 ? 0 : min(0.1, max(0, now - last))
        last = now
        let t = Double(target)
        if head > t {                       // 文字被整段替换、变短了
            head = t
            solid = min(solid, target)
            crossed = Array(crossed.prefix(max(0, target - solid)))
        }
        if t - head > Self.maxLag {         // 落后太多：跳到最后一截
            head = t - Self.maxLag
            if Int(head) > solid + crossed.count { solid = Int(head); crossed.removeAll() }
        }
        let rate = max(Self.minRate, (t - head) / Self.catchUp)
        head = min(t, head + rate * dt)
        let passed = Int(head.rounded(.up)) - solid - crossed.count
        if passed > 0 { crossed.append(contentsOf: repeatElement(now, count: passed)) }

        var alphas: [Double] = []
        alphas.reserveCapacity(crossed.count)
        for c in crossed { alphas.append(min(1, max(0, (now - c) / Self.fade))) }
        // 已经完全清楚的从前面挪进 solid
        var drop = 0
        while drop < alphas.count, alphas[drop] >= 1 { drop += 1 }
        if drop > 0 {
            solid += drop
            crossed.removeFirst(drop)
            alphas.removeFirst(drop)
        }
        if crossed.isEmpty && solid >= target && !notified {
            notified = true
            DispatchQueue.main.async { self.tick &+= 1 }
        }
        return FlowRenderer(solid: solid, alphas: alphas, blur: Self.blur)
    }
}

/// 前 solid 个字照常画；后面 alphas.count 个字按各自的透明度 + 模糊画；再往后的还没流到，不画（但占位，不会撑高跳动）
struct FlowRenderer: TextRenderer {
    let solid: Int
    let alphas: [Double]
    let blur: Double

    func draw(layout: Text.Layout, in ctx: inout GraphicsContext) {
        let end = solid + alphas.count
        var i = 0
        for line in layout {
            let n = line.reduce(0) { $0 + $1.count }
            if i + n <= solid {             // 整行都已清楚
                ctx.draw(line)
                i += n
                continue
            }
            if i >= end { break }           // 后面都还没流到
            for run in line {
                for glyph in run {
                    defer { i += 1 }
                    if i < solid {
                        ctx.draw(glyph)
                    } else if i < end {
                        let a = alphas[i - solid]
                        guard a > 0.01 else { continue }
                        var c = ctx
                        c.opacity = a
                        c.addFilter(.blur(radius: (1 - a) * blur))
                        c.draw(glyph)
                    }
                }
            }
        }
    }
}
