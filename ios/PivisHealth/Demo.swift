import Foundation
import os

// MARK: - 演示模式（build 55）：没配对也能把 App 翻一遍（好奇的人、TestFlight 审核）
// 页面来自包里的样例 Demo/<页面>.json（和 GET /api/v3/page/<页面> 同一个样子），习惯卡来自 Demo/habit-<id>.json。
// 待办点了只在手机上生效（这次打开 App 内有效）；对话要连上自己的电脑才能用；不连任何服务器。
enum DemoStore {
    /// 包里有样例（至少有此刻页）才给「先看看演示」
    static var available: Bool { url("now") != nil }

    /// 样例文件：Debug 可以用 -demoDir <目录> 指到别处（模拟器上直接读 Mac 上的文件）；
    /// 包里先找 Demo/ 子目录（文件夹引用），再找包的根目录（同步文件夹会把资源拍平放进根目录）
    static func url(_ name: String) -> URL? {
        #if DEBUG
        let a = ProcessInfo.processInfo.arguments
        if let i = a.firstIndex(of: "-demoDir"), i + 1 < a.count {
            let u = URL(fileURLWithPath: a[i + 1]).appendingPathComponent("\(name).json")
            if FileManager.default.fileExists(atPath: u.path) { return u }
        }
        #endif
        return Bundle.main.url(forResource: name, withExtension: "json", subdirectory: "Demo")
            ?? Bundle.main.url(forResource: name, withExtension: "json")
    }

    private static func data(_ name: String) throws -> Data {
        guard let u = url(name) else { throw PivisAPI.Failure.http(404, "演示里没有这一页") }
        return try Data(contentsOf: u)
    }

    /// 在演示里点过的待办（只在这次打开 App 内有效）
    private static let overlay = OSAllocatedUnfairLock(initialState: [String: V3Todo]())

    static func page(_ name: String) throws -> V3Page {
        var d = try PivisAPI.decode(V3Page.self, try data(name))
        let changed = overlay.withLock { $0 }
        guard !changed.isEmpty else { return d }
        func swap(_ list: [V3Todo]) -> [V3Todo] { list.map { changed[$0.id] ?? $0 } }
        let finished: (V3Todo) -> Bool = { ["done", "skipped"].contains($0.status) }
        let todos = swap(d.todos), more = swap(d.more ?? [])
        d.todos = todos.filter { !finished($0) }
        if d.more != nil { d.more = more.filter { !finished($0) } }
        d.done = (todos + more).filter(finished) + swap(d.done)
        return d
    }

    /// 演示里所有的待办（各页 + 做完的）
    private static func allTodos() -> [V3Todo] {
        ["now", "sleep", "sport", "stress"].flatMap { n -> [V3Todo] in
            guard let d = try? page(n) else { return [] }
            return d.todos + (d.more ?? []) + d.done
        }
    }

    static func todo(_ id: String) throws -> V3Todo {
        if let t = overlay.withLock({ $0[id] }) { return t }
        guard let t = allTodos().first(where: { $0.id == id }) else { throw PivisAPI.Failure.http(404, "演示里没有这件事") }
        return t
    }

    static func habit(_ id: String) throws -> V3HabitDoc {
        try PivisAPI.decode(V3HabitDoc.self, try data("habit-\(id)"))
    }

    /// 待办动作：照发送队列的规则在本地算出新样子记下来。
    /// 不是演示里的待办（真实队列里断网时排下的）：当成没送到、留在队列里，不在这里吞掉
    static func submit(_ id: String, action: String, values: [String: Any], text: String?, summary: String?) throws -> V3Todo {
        guard let cur = try? todo(id) else { throw URLError(.notConnectedToInternet) }
        if action == "agent" { return cur }       // 「交给 P-Health」要连上电脑
        let op = TodoOutbox.Op(id: UUID().uuidString, todoId: id, action: action,
                               values: (try? JSONSerialization.data(withJSONObject: values)) ?? Data("{}".utf8),
                               text: text, summary: summary, at: Date())
        let next = TodoOutbox.apply(op, to: cur)
        overlay.withLock { $0[id] = next }
        return next
    }

    /// 退出演示：点过的都不算了
    static func reset() { overlay.withLock { $0.removeAll() } }
}
