"""客观健康库（health.sqlite3）的只读访问层。

并行只读期契约（v1.1 方案 §3）：
- 连接强制 mode=ro + PRAGMA query_only，绝不写入；
- 库身份（dev+inode）在连接期间校验，防替换攻击（移植自 hermes ReadOnlyStore）；
- projection_rows 的日期归属语义与 hermes store 完全一致：
  睡眠 = 本地日 d 的 12:00 → d+1 12:00（次日中午前醒的夜睡归 d）；
  其余类型 = 本地日 d 的 00:00 → d+1 00:00；
  tombstones 永远排除。
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class ObjectiveStoreError(RuntimeError):
    pass


_FRACTION = re.compile(r"\.(\d{1,6})\d*")


def parse_ts(text: str) -> datetime:
    """解析库内 ISO 时间戳；纳秒级小数截断到微秒（Apple 导出是 9 位小数）。"""
    s = str(text).replace("Z", "+00:00")
    s = _FRACTION.sub(lambda m: "." + m.group(1), s, count=1)
    return datetime.fromisoformat(s)


class ReadOnlyObjectiveStore:
    """health.sqlite3 的只读门面。"""

    def __init__(self, db_path: Path | str, tz: str = "Asia/Shanghai") -> None:
        self.db_path = Path(db_path)
        self.tz = ZoneInfo(tz)
        if not self.db_path.exists():
            raise ObjectiveStoreError(f"objective db not found: {self.db_path}")

    # -- 连接 ------------------------------------------------------------
    def _identity(self) -> tuple[int, int]:
        st = self.db_path.stat()
        return st.st_dev, st.st_ino

    def connect(self) -> sqlite3.Connection:
        expected = self._identity()
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        if self._identity() != expected:
            con.close()
            raise ObjectiveStoreError("database identity changed during connect")
        con.execute("PRAGMA query_only=ON")
        return con

    # -- 时间窗（语义与 hermes store.py 一致） ---------------------------
    def _utc_bounds(self, local_date: date) -> tuple[str, str]:
        start = datetime.combine(local_date, time.min, tzinfo=self.tz)
        end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=self.tz)
        return (
            start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    def _sleep_utc_bounds(self, local_date: date) -> tuple[str, str]:
        start = datetime.combine(local_date, time(hour=12), tzinfo=self.tz)
        end = start + timedelta(days=1)
        return (
            start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    # -- 查询 ------------------------------------------------------------
    def projection_rows(self, local_date: date) -> tuple[dict[str, Any], ...]:
        start_at, end_at = self._utc_bounds(local_date)
        sleep_start, sleep_end = self._sleep_utc_bounds(local_date)
        con = self.connect()
        try:
            rows = con.execute(
                """
                SELECT s.sample_id, s.type, s.start_at, s.end_at, s.unit,
                       s.numeric_value, s.category_value
                FROM samples AS s
                WHERE (
                    (s.type = 'sleep_analysis' AND s.start_at >= ? AND s.start_at < ?)
                    OR
                    (s.type <> 'sleep_analysis' AND s.start_at >= ? AND s.start_at < ?)
                )
                  AND NOT EXISTS (
                      SELECT 1 FROM tombstones AS t
                      WHERE t.device_id = s.device_id AND t.sample_id = s.sample_id
                  )
                ORDER BY s.start_at, s.type, s.sample_id
                """,
                (sleep_start, sleep_end, start_at, end_at),
            ).fetchall()
        finally:
            con.close()
        return tuple(
            {
                "sample_id": r[0],
                "type": r[1],
                "start_at": r[2],
                "end_at": r[3],
                "unit": r[4],
                "numeric_value": r[5],
                "category_value": r[6],
            }
            for r in rows
        )

    def rows_of_type(self, sample_type: str, since_local: date, until_local: date) -> list[dict[str, Any]]:
        """按投影语义逐日取数再合并（保证睡眠归属一致）。"""
        out: list[dict[str, Any]] = []
        day = since_local
        while day <= until_local:
            for row in self.projection_rows(day):
                if row["type"] == sample_type:
                    out.append(row)
            day += timedelta(days=1)
        return out

    def latest_sample_at_by_type(self) -> dict[str, datetime]:
        con = self.connect()
        try:
            rows = con.execute(
                """
                SELECT s.type, MAX(s.start_at) FROM samples AS s
                WHERE NOT EXISTS (
                    SELECT 1 FROM tombstones AS t
                    WHERE t.device_id = s.device_id AND t.sample_id = s.sample_id
                )
                GROUP BY s.type ORDER BY s.type
                """
            ).fetchall()
        finally:
            con.close()
        return {t: parse_ts(ts).astimezone(timezone.utc) for t, ts in rows}
