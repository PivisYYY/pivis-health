"""可靠原始事件存储：append-only 事件信封落库（独立后端模块，不依赖其他业务代码）。

信封字段：event_id / type / occurred_at / source / payload（payload 为自由扩展的 JSON）。

- 至少一次投递 → 同 event_id 同内容幂等去重（不重复存储、不报错）
- 同 event_id 不同内容（type / occurred_at / source / payload 任一不同）→ EventConflictError，
  绝不静默覆盖，已存事件保持原样
- occurred_at 字符串原样保留；另存 UTC 归一化排序键，乱序到达后查询仍按真实发生时间排序
- SQLite 单事务写入（synchronous=FULL）：原子持久化，新实例 / 重启后按同一 db_path 可直接读取
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__all__ = ["EventStore", "EventConflictError", "InvalidEventError"]

# canonical JSON：键序无关，幂等比较与摘要都基于它
_CANON = {"sort_keys": True, "ensure_ascii": False, "separators": (",", ":")}

# occurred_at：ISO-8601（Z / z / ±hh:mm / ±hhmm / 无时区均可；无时区按 UTC 参与排序）
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|z|[+-]\d{2}:?\d{2})?$"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    occurred_ts REAL NOT NULL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    envelope_digest TEXT NOT NULL,
    received_at TEXT NOT NULL,
    received_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_events_occurred ON raw_events (occurred_ts, seq);
CREATE INDEX IF NOT EXISTS idx_raw_events_type_time ON raw_events (type, occurred_ts);
"""

_EVENT_COLS = "event_id, type, occurred_at, source, payload_json, received_at"


class InvalidEventError(ValueError):
    """事件信封不合法（空字段 / 非法时间戳 / payload 不可序列化）。"""


class EventConflictError(Exception):
    """同 event_id 不同内容：拒绝覆盖，已存事件保持不变。"""

    def __init__(self, event_id: str, diff_fields: list[str], message: str):
        super().__init__(message)
        self.event_id = event_id
        self.diff_fields = tuple(diff_fields)


def _parse_occurred_at(value: Any) -> float:
    """ISO-8601 → UTC epoch 秒（排序键）。解析失败抛 InvalidEventError。"""
    m = _TS_RE.match(value) if isinstance(value, str) else None
    if m is None:
        raise InvalidEventError(
            f"occurred_at 非法: {value!r}（需 ISO-8601，如 2026-11-04T08:00:00Z）")
    year, month, day, hour, minute, second, frac, offset = m.groups()
    micro = int((frac or "").ljust(6, "0")[:6])
    try:
        if offset in (None, "Z", "z"):
            tz = timezone.utc
        else:
            sign = -1 if offset[0] == "-" else 1
            digits = offset[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute),
                      int(second), micro, tzinfo=tz)
    except ValueError as exc:  # 如 2026-02-30、25:00、±99:00
        raise InvalidEventError(f"occurred_at 非法: {value!r} ({exc})") from None
    return dt.timestamp()


def _prepare(event: Any) -> dict:
    """校验并规范化事件信封 → 可入库的内部行（canonical payload / 排序键 / 摘要）。"""
    if not isinstance(event, Mapping):
        raise InvalidEventError(f"event 需为 dict，得到 {type(event).__name__}")
    prepared: dict[str, Any] = {}
    for name in ("event_id", "type", "occurred_at", "source"):
        value = event.get(name)
        if not isinstance(value, str) or not value.strip():
            raise InvalidEventError(f"字段 {name} 不能为空（得到 {value!r}）")
        prepared[name] = value
    payload = event.get("payload")
    if payload is None:
        payload = {}
    try:
        payload_json = json.dumps(payload, **_CANON)
    except (TypeError, ValueError) as exc:
        raise InvalidEventError(f"payload 不可 JSON 序列化: {exc}") from None
    prepared["payload_json"] = payload_json
    prepared["occurred_ts"] = _parse_occurred_at(prepared["occurred_at"])
    envelope = json.dumps(
        {"type": prepared["type"], "occurred_at": prepared["occurred_at"],
         "source": prepared["source"], "payload": payload}, **_CANON)
    prepared["envelope_digest"] = hashlib.sha256(envelope.encode("utf-8")).hexdigest()
    return prepared


def _conflict_error(event_id: str, stored: Mapping[str, str],
                    incoming: Mapping[str, str]) -> EventConflictError:
    """组装冲突异常：列出差异字段，绝不覆盖已存事件。"""
    labels = {"payload_json": "payload"}
    diff = [labels.get(f, f) for f in ("type", "occurred_at", "source", "payload_json")
            if stored[f] != incoming[f]]
    detail = (f"（已存 {stored['occurred_at']} vs 新增 {incoming['occurred_at']}）"
              if "occurred_at" in diff else "")
    return EventConflictError(
        event_id, diff,
        f"event_id={event_id!r} 已存在且内容不同，差异字段: {', '.join(diff)}{detail}；"
        f"拒绝覆盖，已存事件保持不变",
    )


def _row_to_event(row: tuple) -> dict:
    """库行 → 事件信封（payload 还原为对象；occurred_at 原样保留）。"""
    return {
        "event_id": row[0], "type": row[1], "occurred_at": row[2], "source": row[3],
        "payload": json.loads(row[4]), "received_at": row[5],
    }


class EventStore:
    """原始事件存储（append-only）。同一 db_path 可被多个实例先后或同时打开。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self.db_path))
        self._con.execute("PRAGMA busy_timeout = 5000")
        self._con.executescript(_SCHEMA)
        self._con.commit()

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __len__(self) -> int:
        return int(self._con.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0])

    def append(self, event: Mapping[str, Any]) -> dict:
        """写入单个事件。返回 {"status": "stored"|"duplicate", "event_id": ...}。"""
        prepared = _prepare(event)
        with self._con:
            stored, _ = self._insert_all([prepared])
        return {"status": "stored" if stored else "duplicate",
                "event_id": prepared["event_id"]}

    def append_batch(self, events: Iterable[Mapping[str, Any]]) -> dict:
        """批量写入（全有或全无）：任一事件非法或冲突则整批拒绝、不留部分写入。"""
        batch = list(events)
        unique: dict[str, dict] = {}
        in_batch_dup = 0
        for event in batch:
            prepared = _prepare(event)
            prior = unique.get(prepared["event_id"])
            if prior is None:
                unique[prepared["event_id"]] = prepared
            elif prior["envelope_digest"] != prepared["envelope_digest"]:
                raise _conflict_error(prepared["event_id"], prior, prepared)  # 批内同 ID 不同内容
            else:
                in_batch_dup += 1  # 批内重传：只保留一份
        with self._con:
            stored, existing_dup = self._insert_all(list(unique.values()))
        return {"stored": stored, "duplicates": in_batch_dup + existing_dup,
                "received": len(batch)}

    def _insert_all(self, prepared: list[dict]) -> tuple[int, int]:
        """在当前事务内插入；返回 (新存数, 幂等重复数)。冲突则抛错，事务回滚。"""
        now = datetime.now(timezone.utc)
        received_at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        received_ts = now.timestamp()
        stored = duplicates = 0
        for p in prepared:
            row = self._con.execute(
                "SELECT type, occurred_at, source, payload_json, envelope_digest"
                " FROM raw_events WHERE event_id = ?", (p["event_id"],)
            ).fetchone()
            if row is not None:
                if row[4] == p["envelope_digest"]:
                    duplicates += 1  # 至少一次投递的重传：幂等吸收
                    continue
                raise _conflict_error(
                    p["event_id"],
                    {"type": row[0], "occurred_at": row[1], "source": row[2],
                     "payload_json": row[3]},
                    p,
                )
            self._con.execute(
                "INSERT INTO raw_events (event_id, type, occurred_at, occurred_ts, source,"
                " payload_json, envelope_digest, received_at, received_ts)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (p["event_id"], p["type"], p["occurred_at"], p["occurred_ts"], p["source"],
                 p["payload_json"], p["envelope_digest"], received_at, received_ts),
            )
            stored += 1
        return stored, duplicates

    def get(self, event_id: str) -> dict | None:
        """按 event_id 取完整信封；不存在返回 None。"""
        row = self._con.execute(
            f"SELECT {_EVENT_COLS} FROM raw_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return _row_to_event(row) if row is not None else None

    def query(self, *, event_type: str | None = None, source: str | None = None,
              order_by: str = "occurred_at", ascending: bool = True,
              limit: int | None = None) -> list[dict]:
        """按条件查询事件。order_by: "occurred_at"（真实发生时间，默认）| "received_at"（到达顺序）。"""
        if order_by not in ("occurred_at", "received_at"):
            raise ValueError(f"未知排序键: {order_by}")
        where, params = [], []
        if event_type is not None:
            where.append("type = ?")
            params.append(event_type)
        if source is not None:
            where.append("source = ?")
            params.append(source)
        order_col = "occurred_ts" if order_by == "occurred_at" else "seq"
        direction = "ASC" if ascending else "DESC"
        sql = f"SELECT {_EVENT_COLS} FROM raw_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_col} {direction}, seq {direction}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [_row_to_event(r) for r in self._con.execute(sql, params).fetchall()]
