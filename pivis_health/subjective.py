"""主观库（pivis 自有，唯一写入权限的库）。

存：行为问题答案、主观睡眠打分、摘表时段标注、自定义监测规则、推送去重 marker。
工程纪律（继承 vault 门禁教训）：
- 文件 0600，目录 0700；
- 原子写（tempfile + os.replace），不留半截库；
- schema 版本化迁移，向前兼容。
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 5

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        local_date TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_entries_date_kind ON entries(local_date, kind);
    CREATE TABLE IF NOT EXISTS custom_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric TEXT NOT NULL,
        comparator TEXT NOT NULL DEFAULT 'below',
        threshold REAL NOT NULL,
        unit TEXT DEFAULT '',
        days INTEGER NOT NULL DEFAULT 1,
        level TEXT NOT NULL DEFAULT 'notice',
        note TEXT DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS push_log (
        local_date TEXT NOT NULL,
        dedup_key TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (local_date, dedup_key)
    );
    """,
    # v2：本地聊天镜像（断网/离线时 App 仍能看到最后同步的对话）
    """
    CREATE TABLE IF NOT EXISTS chat_mirror (
        message_id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        text TEXT NOT NULL,
        create_time TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        synced_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_chat_mirror_pos ON chat_mirror(position);
    """,
    # v4：Web Push 订阅
    """
    CREATE TABLE IF NOT EXISTS push_subs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    # v3：参数表（§7，对话可改，每次留痕）
    """
    CREATE TABLE IF NOT EXISTS params (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS params_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT NOT NULL,
        reason TEXT DEFAULT '',
        changed_at TEXT NOT NULL
    );
    """,
    # v5：APNs 设备 token（锁屏触达）
    """
    CREATE TABLE IF NOT EXISTS apns_tokens (
        token TEXT PRIMARY KEY,
        env TEXT NOT NULL DEFAULT 'development',
        created_at TEXT NOT NULL,
        last_seen TEXT NOT NULL
    );
    """,
]


class SubjectiveStore:
    def __init__(self, db_path: Path | str, tz_name: str = "Asia/Shanghai") -> None:
        self.db_path = Path(db_path)
        self.tz = ZoneInfo(tz_name)
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._migrate()

    # -- 基础 ------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _migrate(self) -> None:
        con = self._connect()
        try:
            with con:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                current = 0
                row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if row:
                    current = int(row[0])
                for version in range(current, SCHEMA_VERSION):
                    for statement in MIGRATIONS[version].split(";"):
                        if statement.strip():
                            con.execute(statement)
                con.execute(
                    "INSERT INTO meta(key,value) VALUES('schema_version',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(SCHEMA_VERSION),),
                )
        finally:
            con.close()
        os.chmod(self.db_path, 0o600)

    def _now(self) -> str:
        return datetime.now(self.tz).isoformat(timespec="seconds")

    # -- 记录 ------------------------------------------------------------
    def record(self, local_date: str, kind: str, payload: dict[str, Any]) -> int:
        con = self._connect()
        try:
            with con:
                cur = con.execute(
                    "INSERT INTO entries(local_date, kind, payload, created_at) VALUES(?,?,?,?)",
                    (local_date, kind, json.dumps(payload, ensure_ascii=False), self._now()),
                )
                return int(cur.lastrowid)
        finally:
            con.close()

    def entries(self, kinds: list[str] | None = None, since: date | None = None, until: date | None = None) -> list[dict]:
        con = self._connect()
        try:
            q = "SELECT id, local_date, kind, payload, created_at FROM entries WHERE 1=1"
            args: list[Any] = []
            if kinds:
                q += f" AND kind IN ({','.join('?' * len(kinds))})"
                args += kinds
            if since:
                q += " AND local_date >= ?"
                args.append(since.isoformat())
            if until:
                q += " AND local_date <= ?"
                args.append(until.isoformat())
            q += " ORDER BY id"
            return [
                {**dict(r), "payload": json.loads(r["payload"])}
                for r in con.execute(q, args).fetchall()
            ]
        finally:
            con.close()

    def last_answered_dates(self, question_ids: list[str]) -> dict[str, str]:
        rows = self.entries(kinds=["behavior_answer"])
        out: dict[str, str] = {}
        for r in rows:
            qid = str((r["payload"] or {}).get("question_id") or "")
            if qid in question_ids:
                out[qid] = max(out.get(qid, ""), r["local_date"])
        return out

    def rotation_pick(self, pool: list[dict], local_date: str, k: int = 2) -> list[dict]:
        """轮换问题池：优先最久没问的；同一天内已答过的跳过。"""
        ids = [q["id"] for q in pool]
        last = self.last_answered_dates(ids)
        answered_today = {
            qid for qid in ids if last.get(qid) == local_date
        }
        pending = [q for q in pool if q["id"] not in answered_today]
        pending.sort(key=lambda q: last.get(q["id"], "0000-00-00"))
        return pending[:k]

    # -- 自定义规则 --------------------------------------------------------
    def add_rule(self, metric: str, comparator: str, threshold: float, days: int, level: str, note: str = "", unit: str = "") -> int:
        con = self._connect()
        try:
            with con:
                cur = con.execute(
                    "INSERT INTO custom_rules(metric,comparator,threshold,unit,days,level,note,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (metric, comparator, threshold, unit, days, level, note, self._now()),
                )
                return int(cur.lastrowid)
        finally:
            con.close()

    def list_rules(self, active_only: bool = True) -> list[dict]:
        con = self._connect()
        try:
            q = "SELECT * FROM custom_rules"
            if active_only:
                q += " WHERE active=1"
            return [dict(r) for r in con.execute(q + " ORDER BY id").fetchall()]
        finally:
            con.close()

    def remove_rule(self, rule_id: int) -> bool:
        con = self._connect()
        try:
            with con:
                cur = con.execute("UPDATE custom_rules SET active=0 WHERE id=?", (rule_id,))
                return cur.rowcount == 1
        finally:
            con.close()

    # -- 参数表（v3，§7）------------------------------------------------------
    def param_set(self, key: str, value: str, old_value: str | None, reason: str) -> None:
        con = self._connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO params(key, value, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value, self._now()),
                )
                con.execute(
                    "INSERT INTO params_history(key, old_value, new_value, reason, changed_at) VALUES(?,?,?,?,?)",
                    (key, old_value, value, reason, self._now()),
                )
        finally:
            con.close()

    def params_list(self) -> list[dict]:
        con = self._connect()
        try:
            return [dict(r) for r in con.execute("SELECT key, value, updated_at FROM params").fetchall()]
        finally:
            con.close()

    def params_history(self) -> list[dict]:
        con = self._connect()
        try:
            return [dict(r) for r in con.execute(
                "SELECT key, old_value, new_value, reason, changed_at FROM params_history ORDER BY id").fetchall()]
        finally:
            con.close()

    # -- Web Push 订阅（v4）--------------------------------------------------
    def push_sub_add(self, endpoint: str, p256dh: str, auth: str) -> None:
        if not endpoint or not p256dh or not auth:
            raise ValueError("endpoint/p256dh/auth required")
        con = self._connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO push_subs(endpoint, p256dh, auth, created_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth",
                    (endpoint, p256dh, auth, self._now()))
        finally:
            con.close()

    def push_subs_list(self) -> list[dict]:
        con = self._connect()
        try:
            return [dict(r) for r in con.execute(
                "SELECT endpoint, p256dh, auth FROM push_subs").fetchall()]
        finally:
            con.close()

    # -- 聊天镜像（v2）-------------------------------------------------------
    def chat_mirror_upsert(self, msgs: list[dict]) -> None:
        con = self._connect()
        try:
            with con:
                for m in msgs:
                    con.execute(
                        "INSERT INTO chat_mirror(message_id, role, text, create_time, position, synced_at) "
                        "VALUES(?,?,?,?,?,?) ON CONFLICT(message_id) DO NOTHING",
                        (m.get("message_id"), m.get("role"), m.get("text"),
                         m.get("create_time"), int(m.get("position") or 0), self._now()),
                    )
        finally:
            con.close()

    def chat_mirror_history(self, limit: int = 50) -> list[dict]:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT message_id, role, text, create_time, position FROM chat_mirror "
                "ORDER BY position DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            con.close()

    # -- 推送去重 / 配额 -----------------------------------------------------
    def push_once(self, local_date: str, dedup_key: str) -> bool:
        """当日同 key 只允许一次（marker 防重复，继承断更告警教训）。True=首次。"""
        con = self._connect()
        try:
            with con:
                cur = con.execute(
                    "INSERT OR IGNORE INTO push_log(local_date,dedup_key,created_at) VALUES(?,?,?)",
                    (local_date, dedup_key, self._now()),
                )
                return cur.rowcount == 1
        finally:
            con.close()

    def push_count(self, local_date: str) -> int:
        con = self._connect()
        try:
            row = con.execute("SELECT COUNT(*) FROM push_log WHERE local_date=?", (local_date,)).fetchone()
            return int(row[0])
        finally:
            con.close()

    # -- APNs 设备 token -----------------------------------------------------
    def apns_token_save(self, token: str, env: str = "development") -> None:
        token = token.strip()
        if not token:
            return
        con = self._connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO apns_tokens(token,env,created_at,last_seen) VALUES(?,?,?,?) "
                    "ON CONFLICT(token) DO UPDATE SET last_seen=excluded.last_seen, env=excluded.env",
                    (token, env or "development", self._now(), self._now()),
                )
        finally:
            con.close()

    def apns_tokens_list(self) -> list[dict]:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT token, env, created_at, last_seen FROM apns_tokens ORDER BY last_seen DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def apns_token_drop(self, token: str) -> None:
        con = self._connect()
        try:
            with con:
                con.execute("DELETE FROM apns_tokens WHERE token=?", (token,))
        finally:
            con.close()
