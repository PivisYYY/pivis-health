"""与"真P-Health"的对话通道（经飞书群桥接）。

链路：App → pivis-health /api/chat → lark-cli 以用户身份发进 P-Health 飞书群
→ dsh 桌面端（dsh-feishu 集成路由到P-Health会话）→ P-Health处理 → 群里以应用身份回复
→ 本模块轮询群消息 → 带回 App。

身份识别：sender.id_type == 'app_id'（机器人应用）= P-Health 投递；
sender.id_type == 'open_id' 且等于配置的 user_open_id = 用户本人。
用户身份发送需要一次性设备码授权（App 的"登录"），未授权时返回结构化提示。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_HOME = Path.home()
LARK_CLI = os.environ.get("PIVIS_LARK_CLI", str(_HOME / ".local/bin/lark-cli"))
# launchd 环境只有精简 PATH（node/lark-cli 依赖），这里显式补齐
_EXTRA_PATH = [
    str(_HOME / ".local/bin"),
    str(_HOME / ".local/node-current/bin"),
    "/usr/local/bin",
    "/opt/homebrew/bin",
]
DEFAULT_GROUP = os.environ.get("PIVIS_LARK_GROUP", "")   # 旧飞书通道，已停用；群 ID 不进仓库
DEFAULT_USER_OPEN_ID = os.environ.get("PIVIS_LARK_USER", "")


class ChatError(RuntimeError):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # "need_auth" | "error"


@dataclass
class ChatMessage:
    message_id: str
    role: str  # "me" | "xiaojian" | "other"
    text: str
    create_time: str
    position: int

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "text": self.text,
            "create_time": self.create_time,
            "position": self.position,
        }


def _run_cli(args: list[str], timeout: int = 25) -> dict:
    env = dict(os.environ)
    env["PATH"] = ":".join(_EXTRA_PATH + [env.get("PATH", "/usr/bin:/bin")])
    env.setdefault("HOME", str(_HOME))
    try:
        proc = subprocess.run(
            [LARK_CLI, *args], capture_output=True, text=True, timeout=timeout, env=env
        )
    except FileNotFoundError as exc:
        raise ChatError(f"lark-cli not found: {LARK_CLI}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ChatError("lark-cli timeout") from exc
    out = proc.stdout.strip() or "{}"
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        parsed = {"ok": False, "error": {"message": (out + " STDERR:" + proc.stderr.strip()[:300])[:400]}}
    if not parsed.get("ok") and proc.stderr.strip() and not parsed.get("error"):
        parsed["error"] = {"message": proc.stderr.strip()[:300]}
    return parsed


def _sender_role(sender: dict | None, user_open_id: str) -> str:
    sender = sender or {}
    if sender.get("id_type") == "app_id":
        return "xiaojian"
    if sender.get("id_type") == "open_id":
        return "me" if sender.get("id") == user_open_id else "other"
    return "other"


def fetch_group_messages(group_id: str, limit: int = 20) -> list[ChatMessage]:
    """读群消息（bot 身份即可读；按 position 升序返回）。"""
    res = _run_cli([
        "im", "+chat-messages-list", "--chat-id", group_id, "--limit", str(max(1, min(limit, 50))),
    ])
    if not res.get("ok"):
        err = res.get("error", {})
        raise ChatError(str(err.get("message") or res)[:200])
    raw = (res.get("data") or {}).get("messages") or []
    msgs = []
    for m in raw:
        text = str(m.get("content") or "")
        if m.get("deleted"):
            continue
        role = _sender_role(m.get("sender"), DEFAULT_USER_OPEN_ID)
        try:
            pos = int(m.get("message_position") or 0)
        except (TypeError, ValueError):
            pos = 0
        msgs.append(ChatMessage(
            message_id=str(m.get("message_id") or ""),
            role=role,
            text=text,
            create_time=str(m.get("create_time") or ""),
            position=pos,
        ))
    msgs.sort(key=lambda x: x.position)
    return msgs


def send_as_user(group_id: str, text: str) -> dict:
    """以用户身份发送（需要一次性设备码授权）。"""
    if not text.strip():
        raise ChatError("empty message")
    res = _run_cli([
        "im", "+messages-send", "--as", "user",
        "--chat-id", group_id, "--text", text.strip(),
    ])
    if res.get("ok"):
        data = res.get("data") or {}
        return {"ok": True, "message_id": data.get("message_id") or ""}
    err = res.get("error", {})
    if err.get("subtype") == "token_missing" or "need_user_authorization" in str(err.get("message", "")):
        raise ChatError("需要一次性用户授权（App 登录）：运行 lark-cli auth login 获取验证链接后完成授权", "need_auth")
    raise ChatError(str(err.get("message") or res)[:200])


def chat_history(group_id: str, limit: int = 20, after_position: int | None = None) -> dict:
    """群消息视图 + 本地镜像合并；after_position 用于增量轮询。"""
    msgs = fetch_group_messages(group_id, limit)
    if after_position is not None:
        msgs = [m for m in msgs if m.position > after_position]
    return {
        "group_id": group_id,
        "counterpart": "P-Health (P-Health)",
        "messages": [m.to_dict() for m in msgs],
        "latest_position": max((m.position for m in msgs), default=after_position or 0),
    }
