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
# 页面编排单独一个工作目录 + 轻量预设：不带聊天人设、P-Health 的规则和工具，只按格式出 JSON。
# 编排会话也因此不再堆在 P-Health 的会话列表里（DeepSeek Harness 客户端里看得到那个列表）
COMPOSER_CWD = os.environ.get("PIVIS_DSH_COMPOSER_CWD", DSH_CWD.rstrip("/") + "-composer")
COMPOSER_PRESET = "phealth-composer"
COMPOSER_SESSIONS_DIR = Path.home() / ".dsh/sessions" / ("-" + COMPOSER_CWD.replace("/", "-") + "--")
COMPOSER_AGENTS_MD = """# 页面编排

你是 P-Health 的页面编排器：根据消息里的证据和格式说明，为一页写主卡和结论。
- 只输出一个 JSON 对象：不聊天、不解释、不加代码块之外的文字，不调用任何工具。
- 数字只能抄证据里的值；钟点、日期照抄。
- 校验没通过时会告诉你原因：按原因改，重新输出完整 JSON。
"""


def ensure_composer_cwd() -> str:
    d = Path(COMPOSER_CWD)
    d.mkdir(parents=True, exist_ok=True)
    md = d / "AGENTS.md"
    if not md.exists() or md.read_text(encoding="utf-8") != COMPOSER_AGENTS_MD:
        md.write_text(COMPOSER_AGENTS_MD, encoding="utf-8")
    return str(d)
LOG_FILE = Path.home() / ".dsh/bot/workspace/pivis-runtime/dshweb.log"

TZ = ZoneInfo("Asia/Shanghai")


# 待办提交时发给 P-Health 的照片引用：「照片 <路径>（用 read_image 看这张图）」，对话里只显示「照片」
_PHOTO_REF = re.compile(r"照片 (\S+?\.(?:jpe?g|png))（用 read_image 看这张图）")


def _photo_marker(m: re.Match) -> str:
    """把服务器路径换成 [[photo:文件名]]：客户端据此从 /api/v3/photo/<文件名> 取缩略图显示，路径不露给老大。"""
    return f"[[photo:{Path(m.group(1)).name}]]"


# App 带着习惯 / 待办发的消息，正文前有一行标记：【习惯 <项目 id> · <名字>】或【待办 <待办 id> · <标题>】
_CTX = re.compile(r"^【(习惯|待办) (\S+?) · ([^】\n]*)】[ \t]*\n?")


def split_context(text: str) -> tuple[str, dict | None]:
    """历史里把标记拆出来：正文不带标记，context = {kind: habit|todo, id, name}（App 在气泡下写「带着：名字」）。"""
    m = _CTX.match(text or "")
    if not m:
        return text, None
    return text[m.end():], {"kind": "habit" if m.group(1) == "习惯" else "todo", "id": m.group(2), "name": m.group(3).strip()}


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
    if context.startswith("验收:"):
        # 验收用例：每个用例一个独立会话（只在模拟 / 演示工作区用），互不串话
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", context.split(":", 1)[1]).strip("-")[:48]
        return f"{DSH_PREFIX or 'phealth-'}accept-{slug}"
    return SESSION_BY_CONTEXT.get(context, SESSION_MAIN)


def _session_dir(context: str = "") -> Path:
    if context.startswith("组件编排:"):
        return COMPOSER_SESSIONS_DIR / _session_id(context)
    return SESSIONS_DIR / _session_id(context)


def _get_token() -> str | None:
    """dsh web 的登录 token：它启动时打印在自己的日志里，取最新一条（全系统只在这里读）。"""
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
        tokens = re.findall(r"token=([A-Za-z0-9_-]+)", text)
        return tokens[-1] if tokens else None
    except OSError:
        return None


def dsh_api(method: str, request: dict, timeout: int = 30) -> dict:
    """调 dsh web 的 client-request 接口（token 换 cookie → POST /api/<method>），返回 result.value。
    出错（拿不到 token、连不上、返回不是 JSON、ok=false）一律抛 DshChatError，不再把 DSH 不通当成「没数据」。"""
    token = _get_token()
    if not token:
        raise DshChatError("无法获取 dsh web token（DSH web 可能没在运行）")
    ck = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    ck.close()
    try:
        subprocess.run(["/usr/bin/curl", "-s", "-m", "5", "-c", ck.name, "-o", "/dev/null",
                        f"{DSH_WEB}/?token={token}"], timeout=8, capture_output=True)
        body = json.dumps({"rpcId": f"pivis-{method}-{int(time.time() * 1000)}", "type": "client-request",
                           "method": method, "payload": {"args": {"request": request}}})
        proc = subprocess.run(["/usr/bin/curl", "-s", "-m", str(timeout), "-b", ck.name, "-X", "POST",
                               "-H", "Content-Type: application/json", "-d", body, f"{DSH_WEB}/api/{method}"],
                              timeout=timeout + 5, capture_output=True, text=True)
        try:
            result = json.loads(proc.stdout or "").get("result", {})
        except json.JSONDecodeError as exc:
            raise DshChatError(f"dsh web 没有正常回应（{method}）：{(proc.stdout or proc.stderr or '')[:120]}") from exc
        if not result.get("ok"):
            err = result.get("error") or {}
            raise DshChatError(f"{method}: {err.get('code', '')} {err.get('message', '')}".strip())
        return result.get("value") or {}
    except subprocess.TimeoutExpired as exc:
        raise DshChatError(f"dsh web 超时（{method}）") from exc
    finally:
        os.unlink(ck.name)


def ensure_session(context: str, cwd: str = DSH_CWD) -> str:
    """确保内部 Agent Session 存在；返回实际 session id。"""
    session_id = _session_id(context)
    if _session_dir(context).exists():
        return session_id
    dsh_api("session/create", {"sessionId": session_id, "cwd": cwd, "agentPreset": AGENT_PRESET})
    return session_id


def send_message(text: str, context: str = "") -> dict:
    """发一条消息到 context 对应的会话（"" 主 / 休息 / 运动 / 压力 / 组件编排:…）。"""
    text = text.strip()
    if not text:
        raise DshChatError("empty message")
    session_id = ensure_session(context)   # 新会话第一次发消息时先建好
    request_id = f"pivis-{int(time.time() * 1000)}"
    dsh_api("session/prompt", {"requestId": request_id, "sessionId": session_id, "mode": "queue",
                               "content": [{"type": "text", "text": text}], "clientTimeZone": "Asia/Shanghai"})
    return {"ok": True, "requestId": request_id}


_EVENTS_CACHE: dict[str, tuple[tuple, list[dict]]] = {}


def _load_events(context: str = "") -> list[dict]:
    """一个会话的全部事件（zstd JSONL）。文件大小和修改时间没变就直接用上次解析的结果
    （以前每次轮询都把整份解压、解析两遍，会话越长越慢）。缺解压库时明确报错，不再当成「没有消息」。"""
    zst_file = _session_dir(context) / "session.v4.jsonl.zstd"
    try:
        st = zst_file.stat()
    except OSError:
        return []
    sig = (st.st_size, st.st_mtime_ns)
    hit = _EVENTS_CACHE.get(str(zst_file))
    if hit and hit[0] == sig:
        return hit[1]
    try:
        import zstandard
    except ImportError as exc:
        raise DshChatError("缺少 zstandard，读不了对话记录（/usr/bin/python3 -m pip install zstandard）") from exc
    import io
    try:
        text_data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(zst_file.read_bytes())).read() \
            .decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001  正在写的半截文件：这次先不更新
        return hit[1] if hit else []
    out = []
    for line in text_data.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if len(_EVENTS_CACHE) > 64:
        _EVENTS_CACHE.clear()
    _EVENTS_CACHE[str(zst_file)] = (sig, out)
    return out


def read_messages(limit: int = 20, after_time: str | None = None, context: str = "") -> list[dict]:
    """从会话文件读取消息（解压 zstd JSONL）。

    返回 [{role: 'me'|'phealth', text, time}]
    """
    events = _load_events(context)
    msgs = []
    after_ts = None
    if after_time:
        try:
            after_ts = datetime.fromisoformat(after_time)
            if after_ts.tzinfo is None:
                after_ts = after_ts.replace(tzinfo=TZ)
        except (ValueError, TypeError):
            pass

    for d in events:
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
            src = data.get("source")
            if isinstance(src, dict) and src.get("kind") not in (None, "user"):
                continue    # DSH 自己插的（重复调用提醒「You are repeating…」、时间快照、规则注入）：不是老大说的话
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
                    body, ctx = split_context(c["text"])
                    msg = {
                        "role": "me",
                        "text": _PHOTO_REF.sub(_photo_marker, body),   # 不把服务器上的照片路径给老大看，换成缩略图标记
                        "time": ts.isoformat() if ts else "",
                        "type": "user"
                    }
                    if ctx:
                        msg["context"] = ctx
                    msgs.append(msg)
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

    if limit and after_ts:
        # 增量拉取：从最早的新消息开始给，客户端下次从这页最后一条接着拉。以前给最后 N 条，两次拉取之间多于 N 条时，前面的永远拿不到
        return msgs[:limit]
    return msgs[-limit:] if limit else msgs


def chat_send(text: str, context: str = "") -> dict:
    """对话发送入口。context = 板块标签（"" 主 / 休息 / 运动 / 压力），路由到对应 dsh session。"""
    try:
        return send_message(text, context)
    except DshChatError as e:
        return {"ok": False, "error": "dsh_api", "message": str(e)}


def read_session_events(context: str = "") -> list[dict]:
    """原始事件流（turn/start|end 判断回合是否在进行，tool/call 给进度提示素材）。"""
    return _load_events(context)


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
