"""工作信号（§6.4）：由主 agent（Pivis/Chief）计算后写入共享文件。

隐私分层：健康 agent 只读派生值，不接触会议标题/正文/联系人。
Chief 接入前文件不存在 → 压力页与时间窗建议进入降级态（如实标注，不空白不造假）。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path.home() / ".dsh/bot/workspace/pivis-runtime/work_signals.json"

FIELDS = ("meeting_hours", "meeting_blocks_2h", "late_online", "first_meeting_next",
          "free_slots", "travel")


def load(path: Path | None = None, day: date | None = None) -> dict | None:
    """返回 {date_iso: {...}}；文件缺失或无该日数据返回 None。"""
    p = path or DEFAULT_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if day is not None:
        entry = data.get(day.isoformat())
        return {k: entry.get(k) for k in FIELDS} if isinstance(entry, dict) else None
    return data


def status(day: date | None = None) -> dict:
    data = load(day=day)
    if data is None:
        return {"available": False,
                "label": "数据源接入中",
                "note": "工作信号由主 agent 计算后自动接入；接入前本页只展示 WHOOP/主观数据，不推测"}
    return {"available": True, "data": data}
