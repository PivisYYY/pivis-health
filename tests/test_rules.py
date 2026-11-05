"""基线 / 规则引擎 / DND 回归。"""
from __future__ import annotations

from datetime import date, timedelta

from pivis_health.baselines import direction, rolling_baseline
from pivis_health.rules import MetricSeries, dnd_allows, evaluate

BASE = date(2026, 10, 28)


def _hrv_series(end: date, drop_last_days: int = 0):
    daily = {}
    for back in range(40, -1, -1):
        d = end - timedelta(days=back)
        wiggle = ((back * 7) % 5) - 2  # 保证基线有方差，z 才有意义
        daily[d] = (40 + wiggle) if (back < drop_last_days) else (60 + wiggle)
    return MetricSeries(daily, "ms")


def test_baseline_window_and_gate():
    daily = {date(2026, 10, 1) + timedelta(days=i): 60.0 for i in range(7)}
    assert rolling_baseline(daily, date(2026, 10, 8)) is not None
    few = {date(2026, 10, 1) + timedelta(days=i): 60.0 for i in range(3)}
    assert rolling_baseline(few, date(2026, 10, 4)) is None  # 样本不足不给基线


def test_direction_words_follow_sign():
    b = rolling_baseline({date(2026, 10, i + 1): 60.0 for i in range(10)}, date(2026, 10, 11))
    assert direction(55, b) == "below"
    assert direction(65, b) == "above"
    assert direction(60, b) == "flat"


def test_hrv_3d_low_triggers_alert():
    series = _hrv_series(BASE, drop_last_days=3)
    findings = evaluate(BASE, hrv=series)
    ids = [f.rule_id for f in findings]
    assert any(":hrv:low_3d" in i for i in ids)
    assert any(":hrv:low_1d" in i for i in ids)
    assert findings[0].level in ("alert",)


def test_no_finding_when_normal():
    findings = evaluate(BASE, hrv=_hrv_series(BASE))
    assert not [f for f in findings if "hrv" in f.metric]


def test_custom_rule_persistence_condition():
    daily = {BASE - timedelta(days=i): (30.0 if i < 3 else 60.0) for i in range(15)}
    custom = [{"id": 99, "metric": "hrv_sdnn", "comparator": "below", "threshold": 35.0,
               "days": 3, "level": "alert", "note": "测试自定义"}]
    findings = evaluate(BASE, hrv=MetricSeries(daily, "ms"), custom_rules=custom)
    assert any("custom:99" in f.rule_id for f in findings)
    # 只持续 1 天不触发 3 天规则
    daily1 = dict(daily)
    daily1[BASE - timedelta(days=1)] = 60.0
    daily1[BASE - timedelta(days=2)] = 60.0
    findings1 = evaluate(BASE, hrv=MetricSeries(daily1, "ms"), custom_rules=custom)
    assert not any("custom:99" in f.rule_id for f in findings1)


def test_dnd_only_allows_see_doctor():
    assert dnd_allows("alert", 3) is False
    assert dnd_allows("notice", 7) is False
    assert dnd_allows("see_doctor", 3) is True
    assert dnd_allows("alert", 10) is True
    assert dnd_allows("alert", 23) is True  # 免打扰 00:00–08:00，23 点不受限


def test_rhr_resp_combo_escalates_to_see_doctor():
    rhr = MetricSeries({BASE - timedelta(days=i): (72.0 if i < 3 else 60.0) for i in range(15)}, "count/min")
    resp = MetricSeries({BASE - timedelta(days=i): (17.5 if i < 3 else 16.0) for i in range(15)}, "count/min")
    findings = evaluate(BASE, resting_heart_rate=rhr, respiratory_rate=resp)
    assert any(f.level == "see_doctor" for f in findings)


def test_whoop_recovery_red_zone(tools_env):
    mon = tools_env.monitor(BASE)  # 夹具里最近 3 晚恢复分 25
    assert any("whoop_recovery" in f["rule_id"] and f["level"] == "alert" for f in mon["findings"])
