"""原始事件到 P-Health 的可靠分发：按 received_at 顺序，成功才标记，重启不丢。

关键路径模块：后端只负责把原始事件交给 Agent；事件含义、是否行动由 P-Health 判断。
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .agent_context import AgentContextStore
from .config import Config
from .event_ingest import EventStore

EVENT_CONTEXT = "事件处理"


def _empty_state() -> dict:
    return {"schema_version": 1, "delivered": []}


class EventDelivery:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.store_path = cfg.data_dir / "events.sqlite3"
        self.state_path = cfg.data_dir / "event_delivery.json"
        self.lock_path = cfg.data_dir / "event-delivery.lock"

    def state(self) -> dict:
        if not self.state_path.exists():
            return _empty_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_state()
        delivered = raw.get("delivered")
        if not isinstance(delivered, list):
            return _empty_state()
        return {"schema_version": 1, "delivered": [str(i) for i in delivered]}

    def pending(self) -> list[dict]:
        delivered = set(self.state()["delivered"])
        with EventStore(self.store_path) as store:
            return [e for e in store.query(order_by="received_at")
                    if e["event_id"] not in delivered]

    def dispatch(self, send: Callable[[dict], bool], limit: int | None = None) -> dict:
        """逐条分发未处理事件；失败继续下一条，只有 send 返回 True 才标记。"""
        events = self.pending()[: int(limit)] if limit else self.pending()
        delivered: list[str] = []
        failed: list[dict] = []
        for event in events:
            try:
                ok = bool(send(event))
            except Exception as exc:  # 单条失败不得阻断后续事件
                failed.append({"event_id": event["event_id"],
                               "error": f"{type(exc).__name__}: {exc}"})
                continue
            if ok:
                delivered.append(event["event_id"])
            else:
                failed.append({"event_id": event["event_id"], "error": "send returned false"})
        if delivered:
            with self.lock():
                raw = self.state()
                known = set(raw["delivered"])
                raw["delivered"].extend(i for i in delivered if i not in known)
                self._write(raw)
        return {"dispatched": len(delivered), "failed": failed, "pending": len(self.pending())}

    def _write(self, raw: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="event-delivery-", suffix=".json", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.state_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @contextmanager
    def lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def send_event_to_agent(cfg: Config, event: dict) -> bool:
    """把原始事件交给内部事件处理 Session；投递成功不等于已采纳行动。"""
    from . import dsh_chat
    dsh_chat.ensure_session(EVENT_CONTEXT)
    context = AgentContextStore(cfg).snapshot()
    prompt = (
        "你是 P-Health 的事件处理 Agent。根据原始事件和共享上下文判断事件含义。\n"
        "要求：结合个人习惯；证据不足时保留不确定性；不得把单一信号写成诊断；"
        "可能驾驶时不得即时打扰；需要行动时更新共享计划并发布相关页面。\n"
        f"shared_context：{json.dumps(context, ensure_ascii=False, default=str)}\n"
        f"原始事件：{json.dumps(event, ensure_ascii=False, default=str)}"
    )
    result = dsh_chat.send_message(prompt, EVENT_CONTEXT)
    return bool(result.get("ok"))
