"""老大对 P-Health 回复的一键反馈（build 52）：👍 / 👎（可选原因、可写一句）。每周对话复盘先看点踩的。

存 data_dir/feedback.jsonl（只追加；同一条回复改主意就再记一行，以最后一行为准）。
点踩并写了一句话：同时把这句转给那个对话里的 P-Health，让它当场改、记成纠正。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import journal

FILE = "feedback.jsonl"
REASONS = ("不专业", "没结合我的数据", "太空泛", "说错了", "没照做", "太长")
FORWARD_PREFIX = "【反馈"


def _find(context: str, reply_time: str, text_hint: str = "") -> tuple[dict | None, dict | None]:
    """按时间（差 3 秒内）找到那条回复和它前面老大说的那句；时间对不上就按开头文字找。"""
    from . import dsh_chat
    msgs = dsh_chat.read_messages(0, None, context)
    try:
        target = datetime.fromisoformat(reply_time)
    except (TypeError, ValueError):
        target = None
    best = None
    for i, m in enumerate(msgs):
        if m["role"] != "phealth":
            continue
        try:
            t = datetime.fromisoformat(m["time"]) if m.get("time") else None
        except ValueError:
            t = None
        if target and t and abs((t - target).total_seconds()) <= 3:
            best = i
            break
        if text_hint and m["text"].strip().startswith(text_hint.strip()[:40]):
            best = i
    if best is None:
        return None, None
    user = next((msgs[j] for j in range(best - 1, -1, -1) if msgs[j]["role"] == "me"), None)
    return msgs[best], user


def record(cfg, context: str, reply_time: str, rating: str, reasons: list[str] | None = None,
           note: str = "", text_hint: str = "", forward: bool = True) -> dict:
    if rating not in ("up", "down", "none"):
        raise ValueError("rating 只能是 up / down / none")
    reasons = [r for r in (reasons or []) if r in REASONS]
    note = (note or "").strip()[:500]
    reply, user = _find(context, reply_time, text_hint)
    row = {"at": journal.now_iso(cfg), "context": context or "", "reply_time": reply_time, "rating": rating,
           "reasons": reasons, "note": note,
           "reply": (reply or {}).get("text", text_hint)[:4000], "user": ((user or {}).get("text") or "")[:1000]}
    journal.append(cfg, FILE, row)
    forwarded = False
    if forward and rating == "down" and note:
        from . import dsh_chat
        hhmm = reply_time[11:16] if len(reply_time) >= 16 else ""
        msg = (f"{FORWARD_PREFIX} {hhmm}】老大对你 {hhmm} 那条回复点了踩"
               + (f"（{'、'.join(reasons)}）" if reasons else "") + f"，他说：「{note}」\n"
               "按 growth-memory「老大纠正你时」处理：先认，再给改正后的回答（按 AGENTS 2.5 的结构），"
               "该记 correction / profile / pref 的当场记上。不要解释为什么之前那样答。")
        try:
            forwarded = bool(dsh_chat.send_message(msg, context).get("ok"))
        except Exception:  # noqa: BLE001
            forwarded = False
    return {"ok": True, "found": reply is not None, "forwarded": forwarded}


def rows(cfg, since: str | None = None) -> list[dict]:
    out = journal.read(cfg, FILE)
    return [r for r in out if not since or str(r.get("at", "")) >= since]


def latest(cfg, context: str | None = None, since: str | None = None) -> list[dict]:
    """每条回复最后一次的评价（改成 none 的去掉）。"""
    last: dict[tuple, dict] = {}
    for r in rows(cfg, since):
        if context is not None and r.get("context", "") != context:
            continue
        last[(r.get("context", ""), r.get("reply_time"))] = r
    return [r for r in last.values() if r.get("rating") in ("up", "down")]


def ratings(cfg, context: str) -> dict:
    """App 打开对话时用：{回复时间: up / down}。"""
    return {r["reply_time"]: r["rating"] for r in latest(cfg, context)}
