"""睡眠重建回归：三起历史事故 + 归属语义。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from pivis_health.sleep import (
    SleepPlausibilityError,
    sleep_from_rows,
    validate_sleep_plausibility,
)

BASE = date(2026, 10, 28)


def test_normal_night_no_double_count(tools_env):
    """09-18 事故：unspec 汇总段与明细重叠，不得双计。"""
    rows = tools_env.store.projection_rows(BASE - timedelta(days=10))
    res = sleep_from_rows(rows, BASE - timedelta(days=10))
    night = res["night"]
    assert 6.5 <= night["hours"] <= 7.0  # 明细口径 ≈ 6.75h，unspec 不叠加


def test_parallel_tracks_not_doubled(tools_env):
    """09-28 事故：两套完整平行分期轨，取最长轨，其余整轨忽略。"""
    day = BASE - timedelta(days=30)
    rows = tools_env.store.projection_rows(day)
    res = sleep_from_rows(rows, day)
    assert any("平行分期轨" in n for n in res["notes"])
    assert 6.5 <= res["night"]["hours"] <= 7.1  # 约 6.75 + 平移轨尾 5min 的补缺


def test_nap_and_night_separated(tools_env):
    """展示口径：夜间与小憩双数字，不合并。"""
    day = BASE - timedelta(days=3)
    res = sleep_from_rows(tools_env.store.projection_rows(day), day)
    assert res["night"]["hours"] > 5
    assert 0.3 <= res["nap"]["hours"] <= 0.8


def test_sleep_projection_attribution(tools_env):
    """次日 12 点前醒的夜睡归投影日 d，不会出现在 d+1。"""
    day = BASE - timedelta(days=4)
    rows_d = tools_env.store.projection_rows(day)
    rows_d1 = tools_env.store.projection_rows(day + timedelta(days=1))
    assert any(r["type"] == "sleep_analysis" and str(r["start_at"])[:10] <= day.isoformat()
               for r in rows_d if r["type"] == "sleep_analysis")
    # d+1 的睡眠窗从 d+1 12:00 开始，昨晚的段不属于它
    starts_d1 = [r["start_at"] for r in rows_d1 if r["type"] == "sleep_analysis"]
    assert all(str(s) >= f"{(day + timedelta(days=1)).isoformat()}T04:00" for s in starts_d1)


def test_missing_sleep_marked_not_invented(tools_env):
    """缺数据的夜如实标注，不推断（race 场景）。"""
    day = BASE - timedelta(days=5)
    res = sleep_from_rows(tools_env.store.projection_rows(day), day)
    assert res["source_count"] == 0
    assert res["night"]["hours"] == 0.0


def test_plausibility_gate_raises_on_double_count():
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    cn = ZoneInfo("Asia/Shanghai")
    s = datetime(2026, 10, 1, 23, 0, tzinfo=cn)
    e = s + timedelta(hours=7)
    with pytest.raises(SleepPlausibilityError):
        validate_sleep_plausibility(
            {"night": {"hours": 9.5}, "nap": {"hours": 0}},
            date(2026, 10, 1),
            {"night": [(s, e, "asleep_core")], "nap": []},
            {},
        )


def test_zero_hours_with_source_rejected(tools_env):
    """有输入却渲染 0 小时 → 抛错（不把处理错误伪装成数据缺失）。"""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    cn = ZoneInfo("Asia/Shanghai")
    rows = [{
        "type": "sleep_analysis",
        "start_at": datetime.combine(BASE, time(23), tzinfo=cn).isoformat(),
        "end_at": (datetime.combine(BASE, time(23), tzinfo=cn) + timedelta(hours=7)).isoformat(),
        "category_value": "in_bed",
        "numeric_value": None,
    }]
    with pytest.raises(SleepPlausibilityError):
        sleep_from_rows(rows, BASE)
