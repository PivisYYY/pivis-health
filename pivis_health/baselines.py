"""个人滚动基线与 z 分数。数字只在这里算，模型不许碰。"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import fmean, median, pstdev
from typing import Iterable

MIN_BASELINE_DAYS = 7
MAX_BASELINE_DAYS = 30


@dataclass(frozen=True)
class Baseline:
    metric: str
    center: float
    spread: float  # 总体标准差；为 0 时 z 不可用
    n: int
    window_days: int

    def z(self, value: float) -> float | None:
        if self.spread <= 1e-9:
            return None
        return (value - self.center) / self.spread

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "center": round(self.center, 3),
            "spread": round(self.spread, 3),
            "n": self.n,
            "window_days": self.window_days,
        }


def rolling_baseline(
    daily: dict[date, float] | Iterable[tuple[date, float]],
    end_exclusive: date,
    window: int = 30,
    min_days: int = MIN_BASELINE_DAYS,
    metric: str = "",
) -> Baseline | None:
    """end_exclusive 当日不进基线（用于"今天 vs 自己的近 N 天"）。"""
    from datetime import timedelta

    items = dict(daily) if isinstance(daily, dict) else dict(daily)
    vals = [items[d] for d in sorted(items) if end_exclusive - timedelta(days=window) <= d < end_exclusive]
    vals = [v for v in vals if v is not None and math.isfinite(v)]
    if len(vals) < min_days:
        return None
    return Baseline(metric=metric, center=fmean(vals), spread=pstdev(vals), n=len(vals), window_days=window)


def daily_aggregate(
    rows: Iterable[dict],
    tz_name: str = "Asia/Shanghai",
    agg: str = "mean",
) -> dict[date, float]:
    """samples 行 → 本地日聚合（mean/sum/max/min），时间戳自行解析为本地日。"""
    from .readonly import parse_ts
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    buckets: dict[date, list[float]] = {}
    for r in rows:
        v = r.get("numeric_value")
        if v is None:
            continue
        try:
            d = parse_ts(str(r["start_at"])).astimezone(tz).date()
        except Exception:
            continue
        buckets.setdefault(d, []).append(float(v))
    out: dict[date, float] = {}
    for d, vals in buckets.items():
        if agg == "sum":
            out[d] = sum(vals)
        elif agg == "max":
            out[d] = max(vals)
        elif agg == "min":
            out[d] = min(vals)
        else:
            out[d] = fmean(vals)
    return out


def direction(value: float, baseline: Baseline | None) -> str:
    """展示口径（2026-08-29 教训）：方向词必须按 delta 正负判定，不许硬编码。"""
    if baseline is None:
        return "unknown"
    delta = value - baseline.center
    if delta > 0:
        return "above"
    if delta < 0:
        return "below"
    return "flat"


def median_of(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return median(vals) if vals else None
