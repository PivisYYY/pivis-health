"""三级监测规则引擎（全部非诊断）。

级别：notice（关注）< alert（提醒）< see_doctor（建议就医）。
夜间免打扰（00:00–08:00）只放行 see_doctor —— 由 dnd_allows 判定，任务层负责执行。
连续条件必须逐日满足；样本不足一律不触发（缺数据 ≠ 异常）。
内置六指标 + 自定义规则（存主观库，对话可加）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from .baselines import Baseline, rolling_baseline

RULESET_VERSION = "pivis-health-rules-v2"
LEVELS = {"notice": 1, "alert": 2, "see_doctor": 3}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    level: str
    metric: str
    observed: Any
    unit: str
    window: str
    reason: str
    non_diagnostic: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


# 工程合理性边界（继承 risk_rules v1：检测畸形数据，不是临床阈值）
PLAUSIBILITY = {
    "heart_rate": (0, 300, "count/min"),
    "resting_heart_rate": (0, 300, "count/min"),
    "heart_rate_variability_sdnn": (0, 1000, "ms"),
    "oxygen_saturation": (0, 100, "%"),
    "respiratory_rate": (0, 100, "count/min"),
    "body_mass": (0, 500, "kg"),
    "step_count": (0, 200_000, "count"),
}


def implausible(metric: str, value: float) -> Finding | None:
    rule = PLAUSIBILITY.get(metric)
    if rule is None:
        return None
    lo, hi, unit = rule
    if lo <= value <= hi:
        return None
    return Finding(
        rule_id=f"{RULESET_VERSION}:implausible:{metric}",
        level="notice",
        metric=metric,
        observed=value,
        unit=unit,
        window="current_day",
        reason="数值超出工程合理性边界，疑似导入异常（非生理判断）",
    )


def _tail(daily: dict[date, float], end: date, n: int) -> list[float | None]:
    """按日往前取 n 个值；缺数据的日为 None（连续条件会被 None 打断）。"""
    return [daily.get(end - timedelta(days=i)) for i in range(n - 1, -1, -1)]


def _streak(vals: list[float | None], pred) -> bool:
    return len(vals) > 0 and all(v is not None and pred(v) for v in vals)


@dataclass
class MetricSeries:
    daily: dict[date, float] = field(default_factory=dict)
    unit: str = ""

    def baseline(self, end: date, window: int = 30) -> Baseline | None:
        return rolling_baseline(self.daily, end_exclusive=end, window=window, metric="metric")


def evaluate(
    day: date,
    *,
    hrv: MetricSeries | None = None,               # Apple SDNN 日均
    resting_heart_rate: MetricSeries | None = None,
    respiratory_rate: MetricSeries | None = None,
    whoop_skin_temp: MetricSeries | None = None,    # WHOOP 皮温（仅参考）
    whoop_recovery: MetricSeries | None = None,     # WHOOP 恢复分
    whoop_strain: MetricSeries | None = None,       # WHOOP 日负荷
    sleep_debt_h: float | None = None,
    custom_rules: list[dict] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []

    def base_of(series: MetricSeries | None) -> Baseline | None:
        return series.baseline(day) if series else None

    # --- HRV（Apple SDNN，z 分数口径） ---
    if hrv and hrv.daily:
        b = base_of(hrv)
        if b is not None:
            today_val = hrv.daily.get(day)
            if today_val is not None:
                z = b.z(today_val)
                if implausible("heart_rate_variability_sdnn", today_val):
                    findings.append(implausible("heart_rate_variability_sdnn", today_val))
                if z is not None and z <= -1.5:
                    findings.append(Finding(
                        f"{RULESET_VERSION}:hrv:low_1d", "notice", "hrv_sdnn",
                        round(today_val, 1), "ms", f"z={z:.2f}",
                        f"HRV {today_val:.0f}ms 较个人基线 {b.center:.0f}ms 偏低 {z:.1f}σ（单日）",
                    ))
            zs = []
            for d in sorted(hrv.daily):
                if day - timedelta(days=2) <= d <= day:  # 近 3 个日历日（含当日）
                    v = hrv.daily[d]
                    zz = b.z(v)
                    zs.append(zz if zz is not None else 0.0)
            if len(zs) == 3 and all(z_ <= -1.0 for z_ in zs):
                findings.append(Finding(
                    f"{RULESET_VERSION}:hrv:low_3d", "alert", "hrv_sdnn",
                    round(hrv.daily.get(day, 0), 1), "ms", "3d",
                    "HRV 连续 3 天低于个人基线 1σ —— 身体在扛东西（疲劳/压力/生病前兆都可能）",
                ))

    # --- 静息心率 ---
    if resting_heart_rate and resting_heart_rate.daily:
        b = base_of(resting_heart_rate)
        if b is not None:
            vals3 = _tail(resting_heart_rate.daily, day, 3)
            if _streak(vals3, lambda v: v > b.center * 1.075):
                findings.append(Finding(
                    f"{RULESET_VERSION}:rhr:high_3d", "alert", "resting_heart_rate",
                    round(vals3[-1], 1), "count/min", "3d",
                    f"静息心率连续 3 天高于个人基线 7.5%（基线 {b.center:.0f}）",
                ))
            resp_alert = False
            if respiratory_rate and respiratory_rate.daily:
                rb = base_of(respiratory_rate)
                if rb is not None:
                    rvals3 = _tail(respiratory_rate.daily, day, 3)
                    resp_alert = _streak(rvals3, lambda v: v > rb.center + 1.0)
            if _streak(vals3, lambda v: v > b.center * 1.15) and resp_alert:
                findings.append(Finding(
                    f"{RULESET_VERSION}:rhr_resp:combo", "see_doctor", "resting_heart_rate",
                    round(vals3[-1], 1), "count/min", "3d",
                    "静息心率连续 3 天显著高于基线且呼吸率同步抬升 —— 建议就医检查（不判断病因）",
                ))

    # --- 呼吸率 ---
    if respiratory_rate and respiratory_rate.daily:
        b = base_of(respiratory_rate)
        if b is not None:
            vals3 = _tail(respiratory_rate.daily, day, 3)
            if _streak(vals3, lambda v: v > b.center + 1.0):
                findings.append(Finding(
                    f"{RULESET_VERSION}:resp:high_3d", "alert", "respiratory_rate",
                    round(vals3[-1], 2), "count/min", "3d",
                    f"呼吸率连续 3 天高于个人基线 1 次/分以上（基线 {b.center:.1f}）",
                ))

    # --- WHOOP 皮温（仅参考级） ---
    if whoop_skin_temp and whoop_skin_temp.daily:
        b = base_of(whoop_skin_temp)
        if b is not None:
            vals3 = _tail(whoop_skin_temp.daily, day, 3)
            if _streak(vals3, lambda v: v > b.center + 0.5):
                findings.append(Finding(
                    f"{RULESET_VERSION}:skin_temp:high_3d", "notice", "whoop_skin_temp",
                    round(vals3[-1], 2), "°C", "3d",
                    "WHOOP 皮温连续 3 天高于个人基线 0.5°C（可能有炎症/饮酒/环境因素，仅参考）",
                ))

    # --- WHOOP 恢复分（<33 红区口径） ---
    if whoop_recovery and whoop_recovery.daily:
        vals3 = _tail(whoop_recovery.daily, day, 3)
        today_rec = whoop_recovery.daily.get(day)
        if today_rec is not None and today_rec < 33:
            findings.append(Finding(
                f"{RULESET_VERSION}:whoop_recovery:red_1d", "notice", "whoop_recovery",
                round(today_rec, 0), "%", "1d",
                f"WHOOP 恢复分 {today_rec:.0f}%（红区）—— 身体在还债，今天别加量",
            ))
        if _streak(vals3, lambda v: v < 33):
            findings.append(Finding(
                f"{RULESET_VERSION}:whoop_recovery:red_3d", "alert", "whoop_recovery",
                round(vals3[-1], 0), "%", "3d",
                "WHOOP 恢复分连续 3 天红区 —— 连续欠恢复，需要主动减载/补觉",
            ))

    # --- 睡眠债 ---
    if sleep_debt_h is not None and sleep_debt_h > 8:
        findings.append(Finding(
            f"{RULESET_VERSION}:sleep_debt:high", "alert", "sleep_debt",
            round(sleep_debt_h, 1), "h", "7d",
            f"近 7 天累计睡眠债约 {sleep_debt_h:.1f} 小时 —— 今晚优先还觉，别排高强度",
        ))

    # --- 过度训练（负荷涨 + 恢复差同时出现才算） ---
    if whoop_strain and whoop_strain.daily and whoop_recovery and whoop_recovery.daily:
        recent = [whoop_strain.daily.get(day - timedelta(days=i)) for i in range(1, 8)]
        prior = [whoop_strain.daily.get(day - timedelta(days=i)) for i in range(8, 15)]
        rec3 = _tail(whoop_recovery.daily, day, 3)
        if all(v is not None for v in recent) and all(v is not None for v in prior):
            r_avg, p_avg = sum(recent) / 7, sum(prior) / 7
            if p_avg > 0 and r_avg > p_avg * 1.3 and _streak(rec3, lambda v: v < 40):
                findings.append(Finding(
                    f"{RULESET_VERSION}:overtraining:load_up_recovery_down", "notice", "whoop_strain",
                    round(r_avg, 1), "strain", "7d_vs_prior7d",
                    f"近 7 天负荷均值较前一周高 30%（{r_avg:.1f} vs {p_avg:.1f}）且恢复连续偏低 —— 疑似练过头",
                ))

    # --- 自定义规则（对话添加，持久化在主观库） ---
    series_map = {
        "hrv_sdnn": hrv,
        "resting_heart_rate": resting_heart_rate,
        "respiratory_rate": respiratory_rate,
        "whoop_skin_temp": whoop_skin_temp,
        "whoop_recovery": whoop_recovery,
        "whoop_strain": whoop_strain,
    }
    for cr in custom_rules or []:
        metric = str(cr.get("metric") or "")
        series = series_map.get(metric)
        if series is None:
            continue
        try:
            threshold = float(cr.get("threshold"))
            days = max(1, int(cr.get("days") or 1))
            level = str(cr.get("level") or "notice")
            if level not in LEVELS:
                level = "notice"
            comparator = str(cr.get("comparator") or "below")
        except (TypeError, ValueError):
            continue
        vals = _tail(series.daily, day, days)
        pred = (lambda v: v < threshold) if comparator == "below" else (lambda v: v > threshold)
        if _streak(vals, pred):
            findings.append(Finding(
                f"{RULESET_VERSION}:custom:{cr.get('id', metric)}",
                level,
                metric,
                round(vals[-1], 2),
                series.unit,
                f"{days}d",
                str(cr.get("note") or f"自定义规则：{metric} {comparator} {threshold} 持续 {days} 天"),
            ))

    findings.sort(key=lambda f: -LEVELS.get(f.level, 0))
    return findings


def dnd_allows(level: str, hour: int, dnd_hours: tuple[int, int] = (0, 8)) -> bool:
    """免打扰窗口内只放行 see_doctor。支持跨 0 点的窗口。"""
    start, end = dnd_hours
    in_dnd = (start <= hour < end) if start <= end else (hour >= start or hour < end)
    if not in_dnd:
        return True
    return LEVELS.get(level, 0) >= LEVELS["see_doctor"]
