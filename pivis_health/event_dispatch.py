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


PENDING_WINDOW = 500
DELIVERED_KEEP = 5000


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
            # 只看最近到达的 500 条（以前每 30 秒把整张事件表扫两遍，越用越慢）
            recent = list(reversed(store.query(order_by="received_at", ascending=False, limit=PENDING_WINDOW)))
        return [e for e in recent if e["event_id"] not in delivered]

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
                raw["delivered"] = raw["delivered"][-DELIVERED_KEEP:]     # 只留最近的，文件不再一直长
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


# ---------------------------------------------------------------- build 52：先筛再交给 P-Health
# 以前每条事件一轮：一天几十条同一位置、蓝牙扫描，每轮还带 14 KB 共享上下文，78 轮里只有 2 轮做了事。
# 现在：蓝牙扫描不交（场景标签每天另算）；位置只在挪动 1.5 km 以上、或离上次交过去 6 小时以上才交；
# 其他类型内容没变就不交。留下的几条合成一轮，只带跟事件有关的几条记忆。
FILTER_STATE = "event_filter.json"
MOVE_KM = 1.5
LOCATION_EVERY_H = 6
SKIP_TYPES = {"bluetooth_scan"}
CONTEXT_PREFIXES = ("device.", "profile.home_place", "profile.travel", "learn.habit.wearable_off", "profile.work")


def _km(a, b) -> float:
    import math
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _payload(event: dict) -> dict:
    p = event.get("payload")
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except ValueError:
            p = {}
    return p if isinstance(p, dict) else {}


def _ts(event: dict) -> float:
    for k in ("received_ts", "occurred_ts"):
        try:
            if event.get(k) is not None:
                return float(event[k])
        except (TypeError, ValueError):
            pass
    from datetime import datetime
    for k in ("occurred_at", "received_at"):
        try:
            return datetime.fromisoformat(str(event.get(k)).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return 0.0


def classify(events: list[dict], state: dict) -> tuple[list[dict], list[dict], dict]:
    """（要交给 P-Health 的，直接标成已处理的，新的筛选状态）。"""
    keep, skip = [], []
    st = json.loads(json.dumps(state or {}))
    for e in events:
        typ = str(e.get("type") or "")
        p = _payload(e)
        if typ in SKIP_TYPES:
            skip.append(e)
            continue
        if typ == "location" and isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float)):
            last = st.get("location")
            here = (float(p["lat"]), float(p["lon"]))
            if last and _km(here, tuple(last["at"])) < MOVE_KM and _ts(e) - float(last["ts"]) < LOCATION_EVERY_H * 3600:
                skip.append(e)
                continue
            st["location"] = {"at": list(here), "ts": _ts(e)}
            keep.append(e)
            continue
        sig = json.dumps(p, sort_keys=True, ensure_ascii=False, default=str)
        if st.get("sig", {}).get(typ) == sig:
            skip.append(e)
            continue
        st.setdefault("sig", {})[typ] = sig
        keep.append(e)
    return keep, skip, st


def event_prompt(cfg: Config, events: list[dict]) -> str:
    ctx = [e for e in AgentContextStore(cfg).snapshot()["entries"] if str(e.get("scope", "")).startswith(CONTEXT_PREFIXES)]
    slim = [{"type": e.get("type"), "occurred_at": e.get("occurred_at"), "payload": _payload(e)} for e in events]
    return ("你是 P-Health 的事件处理 Agent。下面是手机这一阵上报的、服务器筛过的事件（重复的位置、蓝牙扫描已经去掉）。\n"
            "要求：结合个人习惯和全盘简报（CLAUDE.local.md）判断含义；证据不足时保留不确定性；不从位置变化推断在开车；"
            "不得把单一信号写成诊断；需要行动时更新待办或计划。没有要做的就只回一句「不用处理」。\n"
            f"相关记忆：{json.dumps(ctx, ensure_ascii=False, default=str)}\n"
            f"事件：{json.dumps(slim, ensure_ascii=False, default=str)}")


def dispatch_filtered(cfg: Config, send_text: Callable[[str], bool] | None = None, limit: int = 50) -> dict:
    """筛过再交：要交的合成一轮发出去，成功后连同筛掉的一起标成已处理。"""
    delivery = EventDelivery(cfg)
    st_path = Path(cfg.data_dir) / FILTER_STATE
    try:
        state = json.loads(st_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    events = delivery.pending()[:limit]
    if not events:
        return {"dispatched": 0, "skipped": 0, "sent": False, "pending": 0}
    keep, skip, new_state = classify(events, state)
    sent = False
    if keep:
        if send_text is None:
            def send_text(text: str) -> bool:
                from . import dsh_chat
                dsh_chat.ensure_session(EVENT_CONTEXT)
                return bool(dsh_chat.send_message(text, EVENT_CONTEXT).get("ok"))
        try:
            sent = bool(send_text(event_prompt(cfg, keep[-10:])))
        except Exception as exc:  # noqa: BLE001
            return {"dispatched": 0, "skipped": 0, "sent": False, "error": f"{type(exc).__name__}: {exc}",
                    "pending": len(events)}
        if not sent:
            return {"dispatched": 0, "skipped": 0, "sent": False, "pending": len(events)}
    done_ids = {e["event_id"] for e in keep + skip}
    delivery.dispatch(lambda e: e["event_id"] in done_ids)
    st_path.write_text(json.dumps(new_state, ensure_ascii=False), encoding="utf-8")
    return {"dispatched": len(keep), "skipped": len(skip), "sent": sent, "pending": len(delivery.pending())}
