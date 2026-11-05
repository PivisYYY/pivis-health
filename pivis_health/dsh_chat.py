"""ChatBar 直连通道：dsh web API（session/prompt）发送 + 会话文件读取。

链路：App ChatBar → POST /api/chat/send → dsh web API session/prompt → P-Health 会话
回复读取：解压 session.v4.jsonl.zstd → 解析 JSONL → 轮询返回新消息

零飞书依赖。协议来源：deepseek-harness 开源源码 packages/api/session-controller。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

def _dsh_web() -> str:
    from .config import load_config
    try:
        return load_config().dsh_web
    except Exception:
        return os.environ.get("PIVIS_DSH_WEB", "http://127.0.0.1:8960")


DSH_WEB = _dsh_web()   # 真实地址在 config.local.json 的 dsh_web（不进仓库）
# 四个 session：主 + 三个专项（同一工作区，记忆经 pivis-health 内核共享）
# 会话都建在 DSH 的「phealth」Agent 预设上（人设、工具、skill 来源见 ~/.dsh/profiles/web/cordis.patch.yml）。
# r2（11-04 从头聊）→ r3（11-05 phealth 预设）→ r4（11-05 工作目录搬到 workspace/p-health）。更早的会话原样留在 DSH 里。
AGENT_PRESET = "phealth"
SESSION_MAIN = "phealth-r4-main"
SESSION_BY_CONTEXT = {
    "": SESSION_MAIN,
    "休息": "phealth-r4-sleep",
    "运动": "phealth-r4-sport",
    "压力": "phealth-r4-stress",
    "组件编排": "phealth-component-composer",
    "事件处理": "phealth-r4-events",
}
# 模拟回放：PIVIS_DSH_CWD 指向独立工作区、PIVIS_DSH_PREFIX 给 Session 加前缀，和真实会话完全隔离
DSH_CWD = os.environ.get("PIVIS_DSH_CWD", str(Path.home() / ".dsh/bot/workspace/p-health"))   # P-Health 自己的目录（团队里的 P-Health Bot 也在这）
DSH_PREFIX = os.environ.get("PIVIS_DSH_PREFIX", "")
if DSH_PREFIX:
    SESSION_MAIN = f"{DSH_PREFIX}r3-main"
    SESSION_BY_CONTEXT = {"": SESSION_MAIN, "休息": f"{DSH_PREFIX}r3-sleep", "运动": f"{DSH_PREFIX}r3-sport",
                          "压力": f"{DSH_PREFIX}r3-stress", "组件编排": f"{DSH_PREFIX}composer",
                          "事件处理": f"{DSH_PREFIX}r3-events"}
SESSIONS_DIR = Path.home() / ".dsh/sessions" / ("-" + DSH_CWD.replace("/", "-") + "--")
COOKIE_FILE = Path("/tmp/dsh_chat_cookie.txt")
LOG_FILE = Path.home() / ".dsh/bot/workspace/pivis-runtime/dshweb.log"

TZ = ZoneInfo("Asia/Shanghai")


# 待办提交时发给 P-Health 的照片引用：「照片 <路径>（用 read_image 看这张图）」，对话里只显示「照片」
_PHOTO_REF = re.compile(r"照片 \S+?\.(?:jpe?g|png)（用 read_image 看这张图）")


class DshChatError(RuntimeError):
    pass


def _session_id(context: str = "") -> str:
    if context.startswith("组件编排:"):
        parts = context.split(":", 2)[1:]
        page = parts[0]
        suffix = re.sub(r"[^A-Za-z0-9_-]+", "-", parts[1]).strip("-") if len(parts) > 1 else ""
        if page in ("now", "sleep", "sport", "stress", "relax"):
            base = f"{DSH_PREFIX or 'phealth-'}component-composer-v3-{page}"
            return f"{base}-{suffix}" if suffix else base
    return SESSION_BY_CONTEXT.get(context, SESSION_MAIN)


def _session_dir(context: str = "") -> Path:
    return SESSIONS_DIR / _session_id(context)


def _get_token() -> str | None:
    """从 dsh web 日志拿最新 token。"""
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
        tokens = re.findall(r"token=([A-Za-z0-9_-]+)", text)
        return tokens[-1] if tokens else None
    except OSError:
        return None


def _ensure_auth() -> bool:
    """确保有有效的 auth cookie（token → cookie 交换）。"""
    if COOKIE_FILE.exists():
        # 检查 cookie 是否还有效（简单方式：试调一个 API）
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{DSH_WEB}/api/session/list",
                method="POST",
                headers={"Content-Type": "application/json"},
                data=json.dumps({
                    "rpcId": "auth-check",
                    "type": "client-request",
                    "method": "session/list",
                    "payload": {"args": {"_request": {}}}
                }).encode()
            )
            cookies = COOKIE_FILE.read_text().strip()
            req.add_header("Cookie", cookies)
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            pass

    # 重新获取 cookie
    token = _get_token()
    if not token:
        return False
    try:
        import urllib.request
        req = urllib.request.Request(f"{DSH_WEB}/?token={token}")
        resp = urllib.request.urlopen(req, timeout=5)
        set_cookie = resp.headers.get("Set-Cookie", "")
        if set_cookie:
            # 提取 cookie 键值对
            cookie_parts = []
            for part in set_cookie.split(";"):
                part = part.strip()
                if "=" in part and not part.startswith(("Path", "Expires", "Max-Age", "HttpOnly", "SameSite", "Secure")):
                    cookie_parts.append(part)
            cookie_str = "; ".join(cookie_parts)
            COOKIE_FILE.write_text(cookie_str)
            return True
    except Exception:
        pass
    return False


def ensure_session(context: str, cwd: str = DSH_CWD) -> str:
    """确保内部 Agent Session 存在；返回实际 session id。"""
    session_id = _session_id(context)
    if _session_dir(context).exists():
        return session_id
    token = _get_token()
    if not token:
        raise DshChatError("无法获取 dsh web token")
    ck = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    ck.close()
    try:
        subprocess.run(
            ["/usr/bin/curl", "-s", "-m", "5", "-c", ck.name, "-o", "/dev/null",
             f"{DSH_WEB}/?token={token}"], timeout=8, capture_output=True)
        body = json.dumps({
            "rpcId": f"ensure-{int(time.time()*1000)}",
            "type": "client-request",
            "method": "session/create",
            "payload": {"args": {"request": {
                "sessionId": session_id, "cwd": cwd, "agentPreset": AGENT_PRESET}}},
        })
        proc = subprocess.run(
            ["/usr/bin/curl", "-s", "-m", "30", "-b", ck.name,
             "-X", "POST", "-H", "Content-Type: application/json",
             "-d", body, f"{DSH_WEB}/api/session/create"],
            timeout=35, capture_output=True, text=True)
        result = json.loads(proc.stdout).get("result", {})
        if not result.get("ok"):
            err = result.get("error") or {}
            raise DshChatError(f"session/create: {err.get('code')} {err.get('message')}")
        return session_id
    finally:
        os.unlink(ck.name)


def send_message(text: str, context: str = "") -> dict:
    """通过 dsh web API 发送消息（curl 方式，复用之前验证通过的路径）。

    context = 板块标签（"" 主 / 休息 / 运动 / 压力），决定路由到哪个 session。
    """
    text = text.strip()
    if not text:
        raise DshChatError("empty message")

    token = _get_token()
    if not token:
        raise DshChatError("无法获取 dsh web token")

    session_id = ensure_session(context)   # 新会话第一次发消息时先建好

    # 先用 token 获取 auth cookie（写临时文件）
    ck = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    ck.close()
    try:
        subprocess.run(
            ["/usr/bin/curl", "-s", "-m", "5", "-c", ck.name, "-o", "/dev/null",
             f"{DSH_WEB}/?token={token}"],
            timeout=8, capture_output=True
        )

        request_id = f"pivis-{int(time.time()*1000)}"
        body = json.dumps({
            "rpcId": f"send-{request_id}",
            "type": "client-request",
            "method": "session/prompt",
            "payload": {
                "args": {
                    "request": {
                        "requestId": request_id,
                        "sessionId": session_id,
                        "mode": "queue",
                        "content": [{"type": "text", "text": text}],
                        "clientTimeZone": "Asia/Shanghai"
                    }
                }
            }
        })

        # 用 cookie 发送
        proc = subprocess.run(
            ["/usr/bin/curl", "-s", "-m", "30", "-b", ck.name,
             "-X", "POST", "-H", "Content-Type: application/json",
             "-d", body, f"{DSH_WEB}/api/session/prompt"],
            timeout=35, capture_output=True, text=True
        )
        result = json.loads(proc.stdout)
        r = result.get("result", {})
        if r.get("ok"):
            return {"ok": True, "requestId": request_id}
        err = r.get("error", {})
        raise DshChatError(f"dsh API: {err.get('code','')} {err.get('message','')}")
    finally:
        os.unlink(ck.name)


def read_messages(limit: int = 20, after_time: str | None = None, context: str = "") -> list[dict]:
    """从会话文件读取消息（解压 zstd JSONL）。

    返回 [{role: 'me'|'phealth', text, time}]
    """
    zst_file = _session_dir(context) / "session.v4.jsonl.zstd"
    if not zst_file.exists():
        return []

    try:
        import zstandard
        import io
    except ImportError:
        return []

    try:
        compressed = zst_file.read_bytes()
        dctx = zstandard.ZstdDecompressor()
        reader = dctx.stream_reader(io.BytesIO(compressed))
        text_data = reader.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    msgs = []
    after_ts = None
    if after_time:
        try:
            after_ts = datetime.fromisoformat(after_time)
            if after_ts.tzinfo is None:
                after_ts = after_ts.replace(tzinfo=TZ)
        except (ValueError, TypeError):
            pass

    for line in text_data.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        t = d.get("type", "")
        ts_ms = d.get("time")
        ts = None
        if ts_ms:
            try:
                ts = datetime.fromtimestamp(int(ts_ms) / 1000, tz=TZ)
            except (ValueError, OSError):
                pass

        if after_ts and ts and ts <= after_ts:
            continue

        if t == "user/message":
            data = d.get("data", d)
            content = data.get("content", [])
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                    # 过滤 dsh 内部注入（系统提醒 / 运行时上下文 / 时间工件 / 种子约定）
                    if c["text"].startswith(("Time sampled while preparing turn",
                                             "【系统约定",
                                             "【补充约定",
                                             "<system-reminder>",
                                             "Current runtime context",
                                             "[model changed:",
                                             "The approval policy changed",
                                             "The sandbox mode changed",
                                             "Sandbox mode changed")):
                        continue
                    msgs.append({
                        "role": "me",
                        "text": _PHOTO_REF.sub("照片", c["text"]),   # 不把服务器上的照片路径给老大看
                        "time": ts.isoformat() if ts else "",
                        "type": "user"
                    })
        elif t == "assistant/message":
            data = d.get("data", d)
            message = data.get("message", data)
            content = message.get("content", [])
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                    # 过滤模型切换工件（"[model changed: ...]"）
                    if c["text"].startswith("[model changed:"):
                        continue
                    msgs.append({
                        "role": "phealth",
                        "text": c["text"],
                        "time": ts.isoformat() if ts else "",
                        "type": "assistant"
                    })

    return msgs[-limit:] if limit else msgs


def chat_send(text: str, context: str = "") -> dict:
    """对话发送入口。context = 板块标签（"" 主 / 休息 / 运动 / 压力），路由到对应 dsh session。"""
    try:
        return send_message(text, context)
    except DshChatError as e:
        return {"ok": False, "error": "dsh_api", "message": str(e)}


def read_session_events(context: str = "") -> list[dict]:
    """读原始事件流（zstd JSONL），损坏/缺文件返回 []。

    read_messages 只挑用户与助手成品消息；但「阶段性回复」需要完整事件序列：
    turn/start|end 判断回合是否在进行，tool/call 给出进度提示素材。
    """
    zst_file = _session_dir(context) / "session.v4.jsonl.zstd"
    if not zst_file.exists():
        return []
    try:
        import zstandard
        import io
    except ImportError:
        return []
    try:
        compressed = zst_file.read_bytes()
        dctx = zstandard.ZstdDecompressor()
        text_data = dctx.stream_reader(io.BytesIO(compressed)).read().decode("utf-8", errors="replace")
    except Exception:
        return []
    out = []
    for line in text_data.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def turn_status(context: str = "") -> dict:
    """当前回合状态：busy = 最后一个 turn/start 之后还没有 turn/end。

    last_tool = 本轮最近一次工具调用名；last_args = 它的参数（客户端据此显示「看今天的待办…」这类进度）。
    客户端发消息后快轮询：busy 期间每来一条 assistant/message 就展示一段，
    busy 结束即收尾——这就是 hermesbot 式的阶段性回复。
    """
    events = read_session_events(context)
    busy = False
    last_tool = None
    last_args = None
    for d in events:
        t = d.get("type", "")
        if t == "turn/start":
            busy = True
        elif t == "turn/end":
            busy = False
        elif t == "tool/call" and busy:
            data = d.get("data", d)
            name = data.get("name") or data.get("tool")
            if isinstance(name, str) and name:
                last_tool = name
                args = data.get("arguments")
                last_args = args[:2000] if isinstance(args, str) else None
    # last_args 给客户端把「bash」翻成「看今天的待办」这类话（P-Health 写的 description 或子命令）
    return {"busy": busy, "last_tool": last_tool, "last_args": last_args}


def chat_history(limit: int = 20, after_time: str | None = None, context: str = "") -> dict:
    """对话历史读取（按 session）。附 busy/last_tool：客户端用它驱动阶段性回复。"""
    msgs = read_messages(limit, after_time, context)
    return {
        "counterpart": "P-Health",
        "session": _session_id(context),
        "messages": msgs,
        "latest_time": msgs[-1]["time"] if msgs else None,
        **turn_status(context),
    }
