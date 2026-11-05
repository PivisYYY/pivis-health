"""派生指标计算器 —— 从 hermes health_insight_engine.py 移植为纯函数（去文案）。

数字在这里算，叙事在模型侧。所有函数不落盘、无状态。
"""
from __future__ import annotations

import bisect
import statistics
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any

from .readonly import parse_ts


def sri_index(asleep_sets: dict[date, set[int]], end_day: date, window: int = 14) -> float | None:
    """睡眠规律指数 SRI（0-100）：window 天内逐分钟对照前后两天入睡状态的一致率。"""
    days = [end_day - timedelta(days=i) for i in range(window, 0, -1)]
    sets = {d: asleep_sets.get(d, set()) for d in days}
    agree = tot = 0
    for a, b in zip(days, days[1:]):
        sa, sb = sets[a], sets[b]
        for k in range(1440):
            if k in sa or k in sb:
                tot += 1
                agree += (k in sa) == (k in sb)
    return round(100 * agree / tot, 1) if tot else None


def night_intervals(rows_by_day: dict[date, list[dict]]) -> dict[date, list[tuple[datetime, datetime]]]:
    """按夜归档的入睡区间（awake/in_bed 排除），供社交时差等使用。"""
    from .sleep import _to_local
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    out: dict[date, list[tuple[datetime, datetime]]] = {}
    for day, rows in rows_by_day.items():
        for r in rows:
            if r.get("type") != "sleep_analysis":
                continue
            cat = str(r.get("category_value") or "")
            if cat in ("awake", "in_bed"):
                continue
            try:
                s = _to_local(str(r["start_at"]), tz)
                e = _to_local(str(r["end_at"]), tz)
            except Exception:
                continue
            night = s.date() if s.hour >= 12 else s.date() - timedelta(days=1)
            out.setdefault(night, []).append((s, e))
    return out


def social_jetlag(intervals: dict[date, list[tuple[datetime, datetime]]]) -> dict | None:
    """工作日 vs 周末睡眠中点差（小时）。样本不足返回 None，不硬给数。"""
    mids: dict[str, list[float]] = {"work": [], "end": []}
    for night, lst in intervals.items():
        if not lst:
            continue
        lst.sort()
        st, en = lst[0][0], max(x[1] for x in lst)
        mid = st + (en - st) / 2
        m = mid.hour * 60 + mid.minute
        if m < 720:
            m += 1440
        (mids["end"] if night.weekday() >= 5 else mids["work"]).append(m / 60)
    if len(mids["work"]) < 5 or len(mids["end"]) < 3:
        return None
    return {
        "work_midpoint_h": round(fmean(mids["work"]), 1),
        "weekend_midpoint_h": round(fmean(mids["end"]), 1),
        "diff_h": round(abs(fmean(mids["work"]) - fmean(mids["end"])), 1),
        "n_work": len(mids["work"]),
        "n_weekend": len(mids["end"]),
    }


def weekend_warrior(daily_steps: dict[date, float], today: date) -> list[dict]:
    """逐周 ≥8000 步天数（JAMA 2023 weekend-warrior 口径）。"""
    weeks = []
    for back in (7, 14, 21, 0):
        anchor = today - timedelta(days=back)
        mon = anchor - timedelta(days=anchor.weekday())
        if mon >= today:
            continue
        vals = [daily_steps.get(mon + timedelta(days=i), 0.0) for i in range(7)]
        weeks.append(
            {
                "week_of": mon.isoformat(),
                "days_8k": sum(1 for v in vals if v >= 8000),
                "data_days": sum(1 for v in vals if v > 0),
                "total": int(sum(vals)),
            }
        )
    return weeks


def workout_hrr(workout_rows: list[dict], hr_rows: list[dict], tz_name: str = "Asia/Shanghai") -> list[dict]:
    """运动后心率恢复：结束后 50s–3min 内最低心率相对结束前 2min 均值的回落。"""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    hr_ts = [(parse_ts(str(s)).astimezone(tz), float(v)) for s, v in
             ((r["start_at"], r["numeric_value"]) for r in hr_rows if r.get("numeric_value") is not None)]
    hr_ts.sort()
    ts = [t for t, _ in hr_ts]
    out = []
    for w in workout_rows:
        try:
            start = parse_ts(str(w["start_at"])).astimezone(tz)
            end = parse_ts(str(w["end_at"])).astimezone(tz)
        except Exception:
            continue
        i = bisect.bisect_right(ts, end)
        base_vals = [v for t, v in hr_ts if end - timedelta(minutes=2) <= t <= end][-5:]
        win = [v for t, v in hr_ts if end + timedelta(seconds=50) <= t <= end + timedelta(minutes=3)]
        after = [v for t, v in hr_ts if end < t <= end + timedelta(minutes=75)]
        if not base_vals or not win:
            continue
        base = statistics.mean(base_vals)
        out.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "base_bpm": round(base),
                "hrr_1min": round(base - min(win)),
                "hrr_best_75min": round(base - min(after)) if after else None,
            }
        )
    return out


def sleep_debt(night_hours: dict[date, float], end_day: date, target_h: float = 7.5) -> dict | None:
    """近 7 天睡眠债（只统计有数据的夜）。样本 <5 晚不给数。"""
    days = sorted(dight for dight in night_hours if end_day - timedelta(days=7) <= dight < end_day)
    if len(days) < 5:
        return None
    debt = sum(max(0.0, target_h - night_hours[d]) for d in days)
    return {
        "n_nights": len(days),
        "avg_h": round(fmean(night_hours[d] for d in days), 2),
        "debt_h": round(debt, 1),
        "target_h": target_h,
    }


def sleep_need_from_debt(night_hours: dict[date, float], daily_steps: dict[date, float], end_day: date) -> float | None:
    """无 WHOOP sleep_needed 时的降级估算（继承旧引擎公式）：7.0 + min(1, 债/7) + 高负荷 0.5。"""
    debt = sleep_debt(night_hours, end_day)
    if debt is None:
        return None
    load = sum(daily_steps.get(end_day - timedelta(days=i), 0.0) for i in range(1, 3))
    need = 7.0 + min(1.0, debt["debt_h"] / 7) + (0.5 if load > 15000 else 0.0)
    return round(need, 2)


def suggested_bedtime(need_h: float, wake_time: str = "08:30", buffer_minutes: int = 30) -> str:
    """目标就寝 = 固定起床 − 睡眠需求 − 收尾缓冲（2026-10-31 确认：缓冲 30 分钟）。"""
    wh, wm = map(int, wake_time.split(":"))
    wake_min = wh * 60 + wm
    bed = wake_min - int(round(need_h * 60)) - buffer_minutes
    bed %= 24 * 60
    return f"{bed // 60:02d}:{bed % 60:02d}"


def hrv_verdict(z: float | None) -> dict:
    """HRV 相对个人基线的判定素材（方向词按 z 正负判定，不许硬编码）。"""
    if z is None:
        return {"grade": "unknown", "verdict": "基线数据不足", "dir": "unknown"}
    if z < -1:
        return {"grade": "low", "verdict": "低于个人基线 1σ 以上，建议低强度", "dir": "below"}
    if z > 1:
        return {"grade": "high", "verdict": "高于个人基线 1σ 以上，状态可承强度", "dir": "above"}
    return {"grade": "mid", "verdict": "在个人基线附近", "dir": "flat"}
