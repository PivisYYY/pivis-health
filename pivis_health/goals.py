"""Psir 的目标（build 52）：每个目标写清看哪个数、目标值、截止日。全盘简报和周复盘按它算进度。

metric：weight（kg）/ sleep_h（每晚睡着小时数）/ steps（日均步数）/ project:<项目 id>（执行率）/ none（只记文字）
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

FILE = "goals.json"
METRICS = ("weight", "sleep_h", "steps", "none")


def _path(cfg) -> Path:
    return Path(cfg.data_dir) / FILE


def load(cfg, include_done: bool = False) -> list[dict]:
    try:
        items = json.loads(_path(cfg).read_text(encoding="utf-8")).get("goals") or []
    except (OSError, ValueError):
        return []
    return [g for g in items if include_done or g.get("status", "active") == "active"]


def _save(cfg, items: list[dict]) -> None:
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".goals-", suffix=".json", dir=p.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"goals": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def set_goal(cfg, goal: dict, today: date) -> dict:
    """新建或修改（同 id 覆盖给出的字段）。"""
    gid = str(goal.get("id") or "").strip()
    if not gid:
        raise ValueError("目标要有 id（英文短名，比如 weight、sleep8）")
    items = load(cfg, include_done=True)
    cur = next((g for g in items if g["id"] == gid), None)
    merged = {**(cur or {"created": today.isoformat(), "status": "active"}), **goal}
    if not str(merged.get("title") or "").strip():
        raise ValueError("目标要有 title（一句话，比如「减到 70 kg」）")
    m = str(merged.get("metric") or "none")
    if m not in METRICS and not m.startswith("project:"):
        raise ValueError(f"metric 只能是 {METRICS} 或 project:<项目 id>")
    if m != "none":
        try:
            float(merged.get("target"))
        except (TypeError, ValueError) as exc:
            raise ValueError("有 metric 的目标要写 target（数字）") from exc
    if merged.get("deadline"):
        date.fromisoformat(merged["deadline"])
    if merged.get("status") not in ("active", "done", "dropped"):
        raise ValueError("status 只能是 active / done / dropped")
    merged["metric"] = m
    items = [g for g in items if g["id"] != gid] + [merged]
    _save(cfg, items)
    return merged
