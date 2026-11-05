"""个人范围（§6.6/§7.2）：P25–P75 常见范围 + 偏离状态 + 连续偏出。

纪律：样本 < range_min_days 时不给范围（页面显示"还在学习你的范围"，绝不画带）；
生病/出差日在 v1 先通过 exclude_dates 占位剔除。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

RANGE_WINDOW = 30
RANGE_MIN_DAYS = 14
RANGE_P_LOW, RANGE_P_HIGH = 25, 75


@dataclass(frozen=True)
class Range:
    low: float
    high: float
    n: int
    ready: bool
    learning_days: int

    def to_dict(self) -> dict:
        return {
            "low": round(self.low, 2), "high": round(self.high, 2),
            "n": self.n, "ready": self.ready, "learning_days": self.learning_days,
            "label": f"常见范围 {self.low:.0f}–{self.high:.0f}" if self.ready
                     else f"还在学习你的范围（已有 {self.learning_days} 天，满 {RANGE_MIN_DAYS} 天后显示）",
        }


def _percentile(sorted_vals: list[float], p: int) -> float:
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def personal_range(
    daily: dict[date, float] | Iterable[tuple[date, float]],
    end_inclusive: date,
    exclude: set[date] | None = None,
    window: int = RANGE_WINDOW,
    min_days: int = RANGE_MIN_DAYS,
) -> Range:
    items = dict(daily) if isinstance(daily, dict) else dict(daily)
    exclude = exclude or set()
    vals = sorted(v for d, v in items.items()
                  if end_inclusive - timedelta(days=window) <= d <= end_inclusive
                  and d not in exclude and v is not None)
    total_days = len(vals)
    if total_days < min_days:
        return Range(0.0, 0.0, total_days, ready=False, learning_days=total_days)
    return Range(
        low=_percentile(vals, RANGE_P_LOW),
        high=_percentile(vals, RANGE_P_HIGH),
        n=total_days, ready=True, learning_days=total_days,
    )


def deviation(value: float | None, rng: Range) -> dict:
    """偏离状态：below / in / high / learning，以及距边界多少。"""
    if value is None:
        return {"state": "no_data", "distance": None}
    if not rng.ready:
        return {"state": "learning", "distance": None}
    if value < rng.low:
        return {"state": "below", "distance": round(rng.low - value, 2)}
    if value > rng.high:
        return {"state": "high", "distance": round(value - rng.high, 2)}
    return {"state": "in", "distance": round(min(value - rng.low, rng.high - value), 2)}


def streak_out(
    daily: dict[date, float],
    rng: Range,
    end_inclusive: date,
    direction: str = "below",
    max_days: int = 30,
) -> int:
    """连续偏出范围的天数（只统计有数据且范围已就绪）。"""
    if not rng.ready:
        return 0
    streak = 0
    for i in range(max_days):
        d = end_inclusive - timedelta(days=i)
        v = daily.get(d)
        if v is None:
            break
        out = v < rng.low if direction == "below" else v > rng.high
        if out:
            streak += 1
        else:
            break
    return streak
