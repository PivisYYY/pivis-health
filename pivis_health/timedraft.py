"""待办不留空时间（build 53，老大 11-10：「不要出现时间是空的这种状态，可以拟一个时间，主动弹消息让我确认」）。

P-Health 加卡没写时间：先按老大今晚的时间线拟一个（都从上床时间倒推，依据同 brief.timeline），
卡标上 time_draft，通知线程推一条「先给 X 排了 HH:MM，行吗？」（带「好」「换个时间」）。不回就按这个时间提醒。
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .clock import NIGHT_END_HOUR

# 关键词 → 相对上床（分钟，负数是之前）或固定钟点
_RULES: list[tuple[tuple[str, ...], str, int | str]] = [
    (("灯", "手机", "屏幕", "放松", "冥想", "呼吸", "助眠", "白噪音"), "bed", -60),
    (("洗澡", "泡脚", "热水澡", "淋浴"), "bed", -90),
    (("咖啡", "浓茶", "奶茶", "可乐", "咖啡因"), "bed", -8 * 60),
    (("晚饭", "晚餐"), "bed", -3 * 60),
    (("拉伸", "瑜伽", "放松操"), "bed", -75),
    (("练", "训练", "力量", "跑", "运动", "健身", "球"), "bed", -3 * 60 - 30),
    (("喝水", "补水"), "bed", -150),
    (("称", "体重"), "wake", 10),
    (("见光", "晒", "阳光"), "wake", 30),
    (("午睡", "闭眼", "歇", "小憩"), "fixed", "13:30"),
    (("午饭", "午餐"), "fixed", "12:00"),
    (("早饭", "早餐"), "wake", 30),
    (("走", "散步", "出门"), "fixed", "13:00"),
]
DEFAULT_BED = "23:30"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _night(hhmm: str) -> int:
    """分钟数，凌晨（00–05 点）算当晚，排在 24 点之后。"""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return (h + 24 if h < NIGHT_END_HOUR else h) * 60 + m


def _hm(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def bed_wake(cfg, todos: list[dict] | None = None) -> tuple[str, str]:
    from .agent_context import AgentContextStore
    bed = wake = None
    try:
        for e in AgentContextStore(cfg).snapshot()["entries"]:
            if e.get("scope") == "sleep.cbti":
                p = e.get("payload") or {}
                bed, wake = p.get("earliest_bed") or bed, p.get("wake") or wake
    except Exception:  # noqa: BLE001
        pass
    if not bed:
        for t in todos or []:
            if (t.get("auto") == "bedtime" or str(t.get("title", "")).startswith("上床")) and t.get("when"):
                bed = t["when"]
    bed = bed if bed and _HHMM.match(str(bed)) else DEFAULT_BED
    wake = wake if wake and _HHMM.match(str(wake)) else (getattr(cfg, "fixed_wake_time", None) or "08:30")
    return bed, wake


def pick(cfg, t: dict, day_todos: list[dict], now: datetime | None = None, today: date | None = None) -> tuple[str, str]:
    """拟一个时间，返回 (HH:MM, 依据)。今天的卡：拟出的点已经过了，就排到 15 分钟后（还在上床前的话）。"""
    bed, wake = bed_wake(cfg, day_todos)
    text = f"{t.get('title', '')} {t.get('note', '')}"
    when, why = None, ""
    for words, anchor, val in _RULES:
        if any(w in text for w in words):
            if anchor == "bed":
                when, why = _hm(_night(bed) + int(val)), f"按 {bed} 上床倒推"
            elif anchor == "wake":
                when, why = _hm(_night(wake) + int(val)), f"按 {wake} 起床"
            else:
                when, why = str(val), "按平常的作息"
            break
    taken = {x.get("when") for x in day_todos if x.get("when") and x.get("id") != t.get("id")}
    if when is None:
        why = "挑了个空档"
    if now is not None and today is not None and str(t.get("date")) == today.isoformat():
        soon = _night(now.strftime("%H:%M")) + 15
        soon += (-soon) % 5
        if when is None or _night(when) < soon:
            if when is not None:
                why += "，原定的点已经过了"
            when = _hm(soon)
    if when is None:
        when = "20:00"
    # 避开同一分钟已有的卡：往后挪 5 分钟
    while when in taken:
        when = _hm(_night(when) + 5)
    return when, why
