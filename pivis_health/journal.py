"""长期日志（洞察引擎的数据底子，build 49）：只追加、不清。

- push_log.jsonl      每条推送（sent）和每次点推送（tap）
- agent_actions.jsonl P-Health 做过什么：discover（主卡档位变成需要处理 / 留意）、suggest（提议卡、问卡、选项卡）、
                      remind（推送）、plan（加 / 改待办、改项目）。从现有命令和卡片检查里顺手记，不靠 P-Health 自己写
- todo_log.jsonl      待办的每次操作，带当时的日期、钟点、板块、项目：用来算提醒到动手的间隔

notify_state.json 只留 3 天、todos_v3.json 的 log 只留 500 条；这几份不跟着清。都在数据目录里，不进仓库。
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PUSH = "push_log.jsonl"
ACTIONS = "agent_actions.jsonl"
TODOS = "todo_log.jsonl"


def _path(cfg, name: str) -> Path:
    return Path(cfg.data_dir) / name


def append(cfg, name: str, entry: dict[str, Any]) -> None:
    """追加一行。写日志失败不能影响主流程（推送、改待办照常）。"""
    try:
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        fd = os.open(_path(cfg, name), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001
        pass


def read(cfg, name: str, since: str | None = None) -> Iterator[dict]:
    """按行读；since（ISO 时间或日期）之前的跳过。坏行跳过。"""
    p = _path(cfg, name)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if since and str(d.get("at") or "") < since:
                continue
            yield d


def new_push_id() -> str:
    return f"p{int(time.time() * 1000):x}{secrets.token_hex(2)}"


def now_iso(cfg=None) -> str:
    """老大那边的钟（config 的 timezone；模拟环境用模拟时钟），不带时区。
    这台机器的系统时区不一定是北京（实际是太平洋时间）：日志要和待办的钟点放在同一条时间轴上。"""
    if cfg is not None and getattr(cfg, "timezone", None):
        from .clock import now as clock_now
        return clock_now(cfg).replace(tzinfo=None).isoformat(timespec="seconds")
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 推送
def push_sent(cfg, push_id: str, title: str, body: str, data: dict, result: dict, at: str | None = None) -> None:
    append(cfg, PUSH, {"type": "sent", "id": push_id, "at": at or now_iso(cfg), "why": data.get("why") or data.get("kind"),
                       "todo": data.get("todo"), "context": data.get("context"), "insight": data.get("insight"),
                       "title": title, "body": body[:80], "ok": bool(result.get("ok")),
                       "skipped": result.get("skipped")})


def push_tap(cfg, push_id: str, action: str, client_at: str | None) -> dict:
    push_id = str(push_id or "")[:40]
    if not push_id:
        raise ValueError("push_id required")
    entry = {"type": "tap", "id": push_id, "action": str(action or "open")[:40], "at": now_iso(cfg),
             "client_at": str(client_at or "")[:40] or None}
    append(cfg, PUSH, entry)
    return {"ok": True}


# ---------------------------------------------------------------- P-Health 做过什么
SUGGEST_KINDS = {"proposal", "options", "question", "plan", "decision", "decisioncard", "confirm"}


def action(cfg, kind: str, *, board: str | None = None, project: str | None = None, ref: str | None = None,
           detail: str | None = None, topic: str | None = None, day: str | None = None, at: str | None = None) -> None:
    at = at or now_iso(cfg)
    append(cfg, ACTIONS, {"at": at, "date": day or at[:10], "kind": kind, "board": board, "project": project,
                          "topic": topic, "ref": ref, "detail": (detail or "")[:80]})


# ---------------------------------------------------------------- 待办
def todo(cfg, op: str, t: dict | None, todo_id: str, by: str | None = None, at: str | None = None,
         **extra: Any) -> None:
    t = t or {}
    rec = t.get("record") or {}
    key = t.get("key")
    pre = f"{t.get('project')}-{t.get('date')}-"
    if not key and t.get("project") and str(todo_id).startswith(pre):
        key = str(todo_id)[len(pre):]                 # 项目待办的 id = <项目>-<日期>-<模板 key>
    append(cfg, TODOS, {"at": at or now_iso(cfg), "op": op, "id": todo_id, "by": by, "date": t.get("date"),
                        "when": t.get("when"), "board": t.get("board"), "kind": t.get("kind"),
                        "title": t.get("title"), "project": t.get("project"), "key": key,
                        "source": t.get("source"), "status": t.get("status"),
                        "started_at": rec.get("started_at"), "done_at": rec.get("at"), **extra})
