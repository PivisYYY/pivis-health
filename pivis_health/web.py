"""Web 层：App 用的 JSON 接口 + 安装页。

- /api/v3/*            页面、待办、照片、画布、小组件、同步状态（App 的全部日常接口）
- /media/*             跟练视频、睡眠音频（支持 Range）
- /api/v3/habit/<id>   习惯卡（对话顶部）：本周 7 天、每套训练和它的视频
- /api/chat、/api/chat/send   对话历史与发送（会话不存在时先建好）
- /api/v2/apns-token、/api/v2/device-data、/api/v2/push-test   推送令牌、设备数据上报、推送自测（带密钥）
- /api/dsh-token、/dsh  只给本机和带设备密钥的 App
- /install             安装页（公网隧道只放行这一项）
老的网页客户端（/app、/v2、/view、晨报页等）2026-11-07 删掉了。

安全边界：仅限本机/Tailnet（默认绑 Tailscale IP），公网隧道只开放 /install。
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import dsh_chat
from .config import Config
from .tools import HealthTools

# 公网安装链接（cloudflared 快速隧道）只开放安装页：其余接口（对话、健康数据、待办……）一律当不存在。
# 从隧道进来的请求带 Cloudflare 加的头；走 Tailscale / 本机直连的没有。
_TUNNEL_HEADERS = ("cf-ray", "cf-connecting-ip", "cf-ipcountry", "cdn-loop")
_PUBLIC_PREFIXES = ("/install",)


def tunnel_blocked(headers, path: str) -> bool:
    """这个请求是不是从公网隧道来的、又要访问安装页以外的东西。"""
    keys = {str(k).lower() for k in headers.keys()}
    host = str(headers.get("Host") or "").lower()
    via_tunnel = any(h in keys for h in _TUNNEL_HEADERS) or host.endswith(".trycloudflare.com")
    if not via_tunnel:
        return False
    clean = path.split("?", 1)[0]
    return not any(clean == p or clean.startswith(p + "/") for p in _PUBLIC_PREFIXES)


_LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
OPEN_API = ("/api/v3/app-version",)      # 不带设备密钥也能读：老版本 App 靠它提示更新


def app_trusted(cfg: Config, client_ip: str, headers) -> bool:
    """能不能把 DSH 令牌给这个请求：本机直连，或带着 App 设备密钥。内网别的设备一律不给。"""
    if client_ip in _LOOPBACK:
        return True
    import hmac
    given = str(headers.get("X-Pivis-Key") or "")
    return bool(cfg.app_key) and bool(given) and hmac.compare_digest(given.encode(), cfg.app_key.encode())


def make_handler(cfg: Config, tools: HealthTools, v2=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, f: Path, ctype: str):
            """支持 Range（播放器拖进度、分段拉流）；一次只读要的那一段"""
            size = f.stat().st_size
            rng = self.headers.get("Range")
            start, end, code = 0, size - 1, 200
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].split(",")[0].partition("-")
                if a:
                    start = int(a); end = min(size - 1, int(b)) if b else size - 1
                elif b:
                    start = max(0, size - int(b))
                code = 206
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "max-age=86400")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False, indent=1, default=str).encode(),
                       "application/json; charset=utf-8")

        # ---------------- v3：主卡 + 生成式待办 ----------------
        def _v3_get(self, u, q) -> bool:
            from . import v3 as v3mod
            from .todos import TodoStore
            from urllib.parse import unquote
            if u.path.startswith("/media/follow/"):
                from .follow import media_path
                f = media_path(cfg, u.path)
                if f is None:
                    self._json({"error": "not_found"}, 404)
                    return True
                self._send_file(f, "video/mp4" if f.suffix == ".mp4" else "image/jpeg")
                return True
            if u.path.startswith("/media/sleep-audio/"):
                name = unquote(u.path.rsplit("/", 1)[-1])
                f = Path.home() / ".dsh/bot/workspace/sleep-audio" / name
                if "/" in name or not f.is_file():
                    self._json({"error": "not_found"}, 404)
                    return True
                # 和跟练视频共用一套 Range：越界回 416，只读要的那一段
                self._send_file(f, "audio/mpeg" if f.suffix == ".mp3" else "audio/mp4")
                return True
            if u.path.startswith("/api/v3/habit/"):
                doc = v3mod.habit_doc(tools, unquote(u.path.rsplit("/", 1)[-1]))
                self._json(doc if doc else {"error": "not_found"}, 200 if doc else 404)
                return True
            if u.path.startswith("/api/v3/page/"):
                self._json(v3mod.page_doc(tools, u.path.rsplit("/", 1)[-1]))
                return True
            if u.path.startswith("/api/v3/todo/"):
                t = TodoStore(cfg).get(u.path.rsplit("/", 1)[-1])
                self._json(t or {"error": "not_found"}, 200 if t else 404)
                return True
            if u.path == "/api/v3/clock":
                self._json({"now": tools._now().isoformat(timespec="seconds"), "sim": cfg.sim_mode})
                return True
            if u.path == "/api/v3/app-version":
                # App 自己检查有没有新版本：只回安装页上的 build 号（不回任何地址）
                import plistlib
                from pathlib import Path as _P
                mf = _P(__file__).parent.parent / "install" / "manifest.plist"
                build = None
                try:
                    items = plistlib.loads(mf.read_bytes()).get("items") or []
                    build = int(items[0]["metadata"]["bundle-version"])
                except Exception:  # noqa: BLE001
                    build = None
                self._json({"build": build})
                return True
            if u.path == "/api/v3/widget":
                # 小组件：此刻主卡、接下来几件、上床时间、近 7 晚（App 存进 App Group，小组件自己也会来拿）
                self._json(v3mod.widget_doc(tools))
                return True
            if u.path == "/api/v3/truth":
                # 开屏：一条反直觉、但是对的健康观（点开看解释和依据）
                from . import truths
                self._json(truths.pick(cfg))
                return True
            if u.path == "/api/v3/status":
                self._json(v3mod.sync_status(tools))
                return True
            if u.path == "/api/v3/viz":
                # 对话里的图表预览：和主卡同一套计算，数字由内核算，P-Health 只给画法
                from . import viz as vizmod
                spec = {"metric": (q.get("metric") or [""])[0]}
                for k in ("kind", "days"):
                    if q.get(k):
                        spec[k] = int(q[k][0]) if k == "days" else q[k][0]
                if q.get("show"):
                    spec["show"] = [x for x in q["show"][0].split(",") if x]
                try:
                    self._json(vizmod.build(tools, spec))
                except (ValueError, KeyError) as exc:
                    self._json({"error": "unavailable", "message": str(exc)}, 422)
                return True
            if u.path.startswith("/api/v3/photo/"):
                f = v3mod.photo_file(tools, unquote(u.path.rsplit("/", 1)[-1]))
                if f is None:
                    self._json({"error": "not_found"}, 404)
                    return True
                self.send_response(200)
                self.send_header("Content-Type", "image/png" if f.suffix == ".png" else "image/jpeg")
                self.send_header("Cache-Control", "private, max-age=31536000, immutable")
                data = f.read_bytes()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return True
            return False

        def _v3_post(self, u) -> None:
            from . import v3 as v3mod
            from .clock import set_now
            if u.path == "/api/v3/photo":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 12 * 1024 * 1024:
                    self._json({"error": "too_large"}, 413)
                    return
                self._json(v3mod.save_chat_photo(tools, self.rfile.read(n)))
                return
            if u.path.startswith("/api/v3/todo/") and u.path.endswith("/photo"):
                n = int(self.headers.get("Content-Length") or 0)
                if n > 12 * 1024 * 1024:
                    self._json({"error": "too_large"}, 413)
                    return
                todo_id = u.path[len("/api/v3/todo/"):-len("/photo")]
                self._json(v3mod.save_photo(tools, todo_id, self.rfile.read(n)))
                return
            body = self._read_body_json() if int(self.headers.get("Content-Length") or 0) else {}
            if u.path == "/api/v3/canvas":
                # 对话里的画布卡：校验 + 现算，App 拿到就画
                from . import canvas
                try:
                    lay = canvas.validate(body.get("layout"), str(body.get("slot") or "chat"))
                    self._json({"layout": canvas.resolve(tools, lay, board=body.get("board"))})
                except canvas.CanvasError as exc:
                    self._json({"error": "invalid", "message": str(exc)}, 422)
                return
            if u.path == "/api/v3/push-tap":
                # 点了哪条推送（App 离线时排队补发）：洞察引擎用它算提醒后多久动手
                from . import journal
                self._json(journal.push_tap(cfg, body.get("push_id"), body.get("action"), body.get("at")))
                return
            if u.path.startswith("/api/v3/insight/"):
                # 洞察：点「聊聊」/ 点推送 → open（那段话发进主对话）；侧滑收起 → dismiss
                from . import insight
                parts = u.path.strip("/").split("/")
                if len(parts) != 5 or parts[4] not in ("open", "dismiss"):
                    self._json({"error": "not_found"}, 404)
                    return
                fn = insight.open_pending if parts[4] == "open" else insight.dismiss_pending
                self._json(fn(tools, parts[3]))
                return
            if u.path == "/api/v3/sync-health":
                # 下拉刷新：拉一次 WHOOP（Apple 健康由 App 自己同时上传）
                self._json(v3mod.sync_health(tools))
                return
            if u.path.startswith("/api/v3/todo/"):
                self._json(v3mod.submit(tools, u.path.rsplit("/", 1)[-1], body))
            elif u.path == "/api/v3/clock":
                self._json({"now": set_now(cfg, str(body["now"])).isoformat(timespec="seconds")})
            else:
                self._json({"error": "not_found"}, 404)

        def _deny_tunnel(self) -> bool:
            if not tunnel_blocked(self.headers, self.path):
                return False
            self.close_connection = True
            self._send(404, b"not found", "text/plain")
            return True

        def _deny_untrusted(self) -> bool:
            """/api 下的接口只给本机和带设备密钥的 App（对话、待办提交都能驱动 P-Health，不能让内网别的设备调）。
            放行：应用内更新要读的版本号；/install 和 /media 不在 /api 下。"""
            path = urlparse(self.path).path
            if not path.startswith("/api/") or path in OPEN_API or app_trusted(cfg, self.client_address[0], self.headers):
                return False
            self._json({"error": "forbidden", "message": "只有 P-Health App 和本机能用"}, 403)
            return True

        def do_GET(self):
            if self._deny_tunnel() or self._deny_untrusted():
                return
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path.startswith("/api/v3/") or u.path.startswith("/media/"):
                try:
                    if self._v3_get(u, q):
                        return
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": type(exc).__name__, "message": str(exc)}, 400)
                    return
            if u.path.startswith("/install"):
                from pathlib import Path as _P
                import mimetypes as _mt
                root = _P(__file__).parent.parent / "install"
                rel = u.path[len("/install"):].lstrip("/") or "index.html"
                f = (root / rel).resolve()
                if not str(f).startswith(str(root.resolve())) or not f.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                ctype = _mt.guess_type(str(f))[0] or "application/octet-stream"
                if f.suffix in (".plist", ".html"):
                    # manifest/页面里的绝对地址跟随当前请求 Host（公网隧道/内网域名自适应）
                    host = (self.headers.get("Host") or u.netloc).encode()
                    body = f.read_bytes().replace(b"__HOST__", host)
                    self._send(200, body, "text/xml" if f.suffix == ".plist" else "text/html; charset=utf-8")
                    return
                elif f.suffix == ".ipa":
                    ctype = "application/octet-stream"
                self._send(200, f.read_bytes(), ctype)
                return
            if u.path == "/api/dsh-token":
                if not app_trusted(cfg, self.client_address[0], self.headers):
                    self._json({"error": "forbidden", "message": "只有 P-Health App 和本机能用"}, 403)
                    return
                self._json({"token": dsh_chat._get_token()})
                return
            if u.path == "/dsh":
                # 直连入口：从 dshweb 日志读最新 token，302 到 P-Health 会话（只给本机 / 带设备密钥的）
                if not app_trusted(cfg, self.client_address[0], self.headers):
                    self._json({"error": "forbidden", "message": "只有 P-Health App 和本机能用"}, 403)
                    return
                token = dsh_chat._get_token()
                if token:
                    self.send_response(302)
                    self.send_header(
                        "Location",
                        dsh_chat.DSH_WEB + "/?token=" + token
                        + "&session=" + dsh_chat.SESSION_MAIN,
                    )
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._send(200, "dsh web 未就绪，稍后刷新".encode(), "text/html; charset=utf-8")
                return
            try:
                if u.path == "/":
                    # 老网页（/v2、/view、晨报页…）build 42 后删掉了：首页只报服务在跑
                    self._json({"service": "pivis-health", "ok": True})
                elif u.path == "/api/chat":
                    after = q.get("after", [None])[0]
                    limit = int(q.get("limit", [20])[0])
                    session = q.get("session", [""])[0]
                    print(f"[chat-req] path={u.path} session={session!r} after={after!r}", flush=True)
                    hist = tools.chat_history(limit, after, session)
                    try:
                        from . import cards
                        cards.log_broken(cfg.data_dir, hist.get("messages") or [])   # 坏卡片记进 card_errors.jsonl
                    except Exception:  # noqa: BLE001
                        pass
                    self._json(hist)
                else:
                    self._json({"error": "not_found", "path": u.path}, 404)
            except Exception as exc:
                self._json({"error": type(exc).__name__, "message": str(exc)}, 500)

        def _read_body_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8")
            ctype = self.headers.get("Content-Type", "")
            if "application/json" in ctype:
                return json.loads(raw)
            return {k: v[0] for k, v in parse_qs(raw).items()}

        def do_POST(self):
            if self._deny_tunnel() or self._deny_untrusted():
                return
            u = urlparse(self.path)
            if u.path.startswith("/api/v3/"):
                try:
                    self._v3_post(u)
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": type(exc).__name__, "message": str(exc)}, 400)
                return
            try:
                if u.path == "/api/v2/apns-token":
                    data = self._read_body_json()
                    token = str(data.get("token") or "").strip()
                    if not token:
                        raise ValueError("token required")
                    env = str(data.get("env") or "development")
                    tools.subj.apns_token_save(token, env)
                    self._json({"ok": True, "tokens": len(tools.subj.apns_tokens_list())})
                elif u.path == "/api/v2/push-test":
                    key = self.headers.get("X-Push-Key") or ""
                    if not cfg.apns.get("push_key") or key != cfg.apns["push_key"]:
                        self._json({"error": "unauthorized"}, 401)
                        return
                    from .push import send_push
                    data = self._read_body_json()
                    result = send_push(
                        tools,
                        title=str(data.get("title") or "P-Health"),
                        body=str(data.get("body") or "推送测试"),
                        page=data.get("page"),
                        pending=data.get("pending"),
                        kind="push-test",
                    )
                    self._json(result)
                elif u.path == "/api/v2/device-data":
                    data = self._read_body_json()
                    from . import ingest
                    device_id = str(data.get("device_id") or "iphone-native")[:64]
                    result = ingest.ingest_samples(Path(tools.cfg.vault_db),
                                                   list(data.get("samples") or []),
                                                   device_id)
                    for obs in list(data.get("observations") or [])[:50]:
                        kind = str(obs.get("kind") or "unknown")[:32]
                        payload = obs.get("data") if isinstance(obs.get("data"), dict) else {}
                        ingest.log_observation(
                            Path(tools.cfg.data_dir), kind, payload,
                            source=device_id,
                            event_id=(str(obs.get("event_id"))[:128] if obs.get("event_id") else None),
                            occurred_at=(str(obs.get("occurred_at") or obs.get("ts"))[:80]
                                         if obs.get("occurred_at") or obs.get("ts") else None))
                    self._json(result)
                elif u.path == "/api/chat/send":
                    data = self._read_body_json()
                    text = str(data.get("text") or "")
                    if not text.strip():
                        raise ValueError("text required")
                    context = str(data.get("context") or "")
                    self._json(tools.chat_send(text, context))
                else:
                    self._json({"error": "not_found"}, 404)
            except Exception as exc:
                self._json({"error": type(exc).__name__, "message": str(exc)}, 400)

    return Handler


_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)


class QuietServer(ThreadingHTTPServer):
    """客户端中途断开（App 切后台、播放器换段、手机断网）很常见：不打堆栈，免得真错误被淹没。"""
    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_GONE) or (exc is not None and type(exc).__name__ in ("SSLEOFError", "SSLZeroReturnError")):
            return
        super().handle_error(request, client_address)


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8943,
          tls_cert: str | None = None, tls_key: str | None = None) -> None:
    tools = HealthTools(cfg)
    handler = make_handler(cfg, tools)
    httpd = QuietServer((host, port), handler)
    if tls_cert and tls_key:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tls_cert, tls_key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(json.dumps({"serving": f"http://{host}:{port}", "app": f"http://{host}:{port}/v2"}, ensure_ascii=False))
    from . import notify
    notify.start_background(tools)     # 回复 / 待办到点 / 新问的推送（两个服务进程都起，flock 保证只一个在巡）
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
