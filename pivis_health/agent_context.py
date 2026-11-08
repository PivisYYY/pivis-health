"""P-Health 共享上下文：带 revision 的 append-only 决定/偏好集合（Agent 方案 P0-1）。

职责（对应目标架构 §4/§5 agent_context 模块）：
- 记录跨 Session 共享的决定与偏好：scope + payload + 来源 Session + 原因。
- 每次有意义的修改全局递增 revision；同 scope 新决定替代（supersede）旧决定，
  但旧条目与原因完整保留，历史可查询，不无声覆盖。
- snapshot() 给页面编排 Agent 提供当前生效决定；下一次发布必须声明基于哪个 revision。
- 持久化与 experience/publications 同纪律：临时文件 + os.replace 原子落盘，
  读改写全程持 fcntl 文件锁，多入口（主 Session / 编排 Session）并发追加不丢更新。
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from .config import Config

ACTIVE = "active"
SUPERSEDED = "superseded"
UNKNOWN_SESSION = "unknown"


def _empty() -> dict:
    return {"schema_version": 1, "revision": 0, "entries": []}


# 记忆只收这几类（以前随便起名，三天长出 21 个分类，学到的规律散在 habit.* 里别的会话看不到）
SCOPE_PREFIXES = ("pref.", "profile.", "learn.", "request.", "ask.", "plan.", "device.",
                  "sleep.", "sport.", "stress.", "life.",
                  "correction.")   # 老大纠正过的专业要点：correction.<领域>.<主题>，渲染进 AGENTS.md，不再犯


def check_agent_scope(scope: str) -> str:
    """P-Health 用 context-record 写记忆时的分类检查（内部老代码写的 ui.* 等不走这里）。"""
    text = str(scope or "").strip()
    if not text.startswith(SCOPE_PREFIXES):
        raise ValueError(f"scope 要以这些开头之一：{'、'.join(SCOPE_PREFIXES)}。学到的规律用 learn.（比如 learn.habit.late_bath），"
                         "偏好用 pref.，关于老大的事实用 profile.；habit. / ui. / dialogue. 已停用")
    return text


class AgentContextStore:
    def __init__(self, cfg: Config) -> None:
        self.path = cfg.data_dir / "agent_context.json"
        self.lock_path = cfg.data_dir / "agent-context.lock"

    def all(self) -> dict:
        if not self.path.exists():
            return _empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"agent context unreadable: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
            raise ValueError("agent context must be an object with an entries array")
        revision = raw.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("agent context revision must be a non-negative integer")
        return raw

    def revision(self) -> int:
        return int(self.all()["revision"])

    def snapshot(self) -> dict:
        """当前生效决定（active 条目）+ 全局 revision，喂给编排 Agent 的形态。"""
        raw = self.all()
        return {"revision": raw["revision"],
                "entries": [e for e in raw["entries"] if e.get("status") == ACTIVE]}

    def history(self, scope: str | None = None) -> list[dict]:
        """append-only 全量历史（含已替代条目），可按 scope 过滤。"""
        entries = self.all()["entries"]
        return [e for e in entries if scope is None or e.get("scope") == scope]

    def record(self, scope: str, payload: dict, source_session: str = UNKNOWN_SESSION,
               reason: str = "") -> dict:
        scope = self._scope(scope)
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        session = source_session or UNKNOWN_SESSION
        if not isinstance(session, str) or len(session) > 100:
            raise ValueError("source_session must be a string of at most 100 characters")
        if not isinstance(reason, str) or len(reason) > 1000:
            raise ValueError("reason must be a string of at most 1000 characters")
        with self.lock():
            raw = self.all()
            revision = int(raw["revision"]) + 1
            prev = next((e for e in reversed(raw["entries"])
                         if e.get("scope") == scope and e.get("status") == ACTIVE), None)
            if prev is not None:
                prev["status"] = SUPERSEDED
                prev["superseded_by"] = revision
            entry = {"revision": revision,
                     "recorded_at": datetime.now().isoformat(timespec="seconds"),
                     "source_session": session, "scope": scope,
                     "payload": payload, "status": ACTIVE,
                     "supersedes": prev["revision"] if prev else 0,
                     "superseded_by": 0, "reason": reason}
            raw["entries"].append(entry)
            raw["revision"] = revision
            self._write(raw)
            return entry

    @staticmethod
    def _scope(scope: str) -> str:
        if not isinstance(scope, str):
            raise ValueError("scope must be a string")
        text = scope.strip()
        if not text or len(text) > 200:
            raise ValueError("scope must contain 1–200 characters")
        return text

    def retire(self, scope: str, reason: str = "") -> int:
        """把某个 scope 的生效条目标成 retired（历史保留）。返回改了几条。用于把停用的分类迁走。"""
        with self.lock():
            raw = self.all()
            n = 0
            for e in raw["entries"]:
                if e.get("scope") == scope and e.get("status") == ACTIVE:
                    e["status"] = "retired"
                    e["retired_reason"] = reason
                    n += 1
            if n:
                raw["revision"] = int(raw["revision"]) + 1
                self._write(raw)
            return n

    def _write(self, raw: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="agent-context-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)
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
