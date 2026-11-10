import SwiftUI
import WebKit

// MARK: - 在手机上重新登录 WHOOP（build 53）
// 只有服务器说 WHOOP 登录真失效（needs_login）时才走得到：下拉刷新给的那句话、或者页面上「重新登录 WHOOP」那条提示。
// 服务器给授权地址和回调地址 → 网页里登录 → 跳到回调地址时拦下来（不真的打开），把完整地址交回服务器换令牌。

@MainActor
final class WhoopLoginModel: ObservableObject {
    enum Phase: Equatable {
        case starting
        case web(URL, redirect: String)
        case finishing
        case done
        case failed(String)
    }
    @Published private(set) var phase: Phase = .starting
    private var finished = false

    func start() async {
        finished = false
        phase = .starting
        do {
            let (data, resp) = try await PivisAPI.send(PivisAPI.request("api/v3/whoop/login", method: "POST", json: [:]),
                                                       checkStatus: false)
            let obj = PivisAPI.object(data) ?? [:]
            guard (200..<300).contains(resp.statusCode),
                  let s = obj["url"] as? String, let url = URL(string: s),
                  let redirect = obj["redirect"] as? String, !redirect.isEmpty else {
                phase = .failed(Self.errorText(obj) ?? "没打开 WHOOP 登录")
                return
            }
            phase = .web(url, redirect: redirect)
        } catch {
            DshAPI.dbg("whoop login start failed: \(error.localizedDescription)")
            phase = .failed("连不上服务器")
        }
    }

    /// 网页跳到回调地址：交给服务器换令牌（同一次登录只交一次）
    func finish(callback: String) {
        guard !finished else { return }
        finished = true
        phase = .finishing
        Task {
            do {
                let req = PivisAPI.request("api/v3/whoop/login/finish", method: "POST", json: ["callback": callback], timeout: 30)
                let (data, resp) = try await PivisAPI.send(req, checkStatus: false)
                let obj = PivisAPI.object(data) ?? [:]
                if (200..<300).contains(resp.statusCode), obj["ok"] as? Bool == true {
                    phase = .done
                } else {
                    phase = .failed(Self.errorText(obj) ?? "WHOOP 没登录上")
                }
            } catch {
                DshAPI.dbg("whoop login finish failed: \(error.localizedDescription)")
                phase = .failed("连不上服务器")
            }
        }
    }

    /// 服务器的错：WHOOP 的错是 {error: 一句中文}；别的异常是 {error: 类型名, message: 一句话}
    private static func errorText(_ obj: [String: Any]) -> String? {
        if let m = obj["message"] as? String, !m.isEmpty { return m }
        if let e = obj["error"] as? String, !e.isEmpty { return e }
        return nil
    }
}

struct WhoopLoginSheet: View {
    @StateObject private var model = WhoopLoginModel()
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("WHOOP").font(E.body(13)).kerning(1).foregroundStyle(E.text2)
                Spacer()
                Button { dismiss() } label: {
                    Image(systemName: "xmark").font(.system(size: 13, weight: .light)).foregroundStyle(E.text)
                        .frame(width: 36, height: 36)
                        .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
                        .frame(width: 44, height: 44)
                        .contentShape(Circle())
                }
                .buttonStyle(EPress())
                .accessibilityLabel("关闭")
                .accessibilityIdentifier("whoop-login-close")
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            Hairline()
            ZStack {
                E.bg
                switch model.phase {
                case .starting, .finishing:
                    WorkingLine().padding(.horizontal, E.gutter)
                case .web(let url, let redirect):
                    WhoopWebView(url: url, redirect: redirect) { model.finish(callback: $0) }
                case .done:
                    resultGlyph("checkmark", label: "WHOOP 已经重新登录")
                case .failed(let message):
                    VStack(spacing: 18) {
                        resultGlyph("xmark", label: "WHOOP 没登录上")
                        // 失败的原因是信息（超时、授权被拒），照服务器的话说
                        Text(message).font(E.body(13)).foregroundStyle(E.text2)
                            .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, E.gutter)
                            .accessibilityIdentifier("whoop-login-error")
                        OutlinePill(title: "再试一次") { Task { await model.start() } }
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(E.bg)
        .preferredColorScheme(.dark)
        .task { await model.start() }
        .onChange(of: model.phase) { _, phase in
            guard phase == .done else { return }
            Haptic.tap()
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { dismiss() }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("whoop-login")
    }

    private func resultGlyph(_ system: String, label: String) -> some View {
        Image(systemName: system).font(.system(size: 18, weight: .light)).foregroundStyle(E.text)
            .frame(width: 56, height: 56)
            .overlay(Circle().strokeBorder(E.text, lineWidth: 1))
            .accessibilityElement()
            .accessibilityLabel(label)
            .accessibilityIdentifier("whoop-login-result")
    }
}

/// 登录网页：跳到回调地址（本机地址，手机上打不开）时取消这次跳转，把完整地址交出去
struct WhoopWebView: UIViewRepresentable {
    let url: URL
    let redirect: String
    let onCallback: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(redirect: redirect, onCallback: onCallback) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()      // 登录过的 Cookie 不留在手机上
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.isOpaque = false
        web.backgroundColor = .black
        web.load(URLRequest(url: url))
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        let redirect: String
        let onCallback: (String) -> Void
        private var handed = false

        init(redirect: String, onCallback: @escaping (String) -> Void) {
            self.redirect = redirect
            self.onCallback = onCallback
        }

        private func catchCallback(_ s: String?) -> Bool {
            guard let s, s.hasPrefix(redirect) else { return false }
            if !handed {
                handed = true
                onCallback(s)
            }
            return true
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
            decisionHandler(catchCallback(navigationAction.request.url?.absoluteString) ? .cancel : .allow)
        }

        /// 兜底：服务器端 302 直接跳到回调地址、没走到上面那步时，在这里认出来
        func webView(_ webView: WKWebView, didReceiveServerRedirectForProvisionalNavigation navigation: WKNavigation!) {
            if catchCallback(webView.url?.absoluteString) { webView.stopLoading() }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            let failing = (error as NSError).userInfo[NSURLErrorFailingURLStringErrorKey] as? String
            _ = catchCallback(failing)
        }
    }
}
