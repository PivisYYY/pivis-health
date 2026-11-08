"""build 45：WHOOP 数据要及时、按醒来那天算；运动页拿得到训练；主卡不再是一行「算不出来」。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from conftest import BASE
from pivis_health import canvas, v3
from pivis_health import whoop as whoop_mod

CN = ZoneInfo("Asia/Shanghai")


def _utc(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _sleep(sid: str, start: datetime, hours: float) -> dict:
    return {"id": sid, "start": _utc(start), "end": _utc(start + timedelta(hours=hours)), "score_state": "SCORED",
            "nap": False, "score": {}}


def test_this_mornings_recovery_is_today():
    """11-08 凌晨 01:24 睡、07:49 醒：WHOOP App 里这是 11-08 的恢复，以前被记成 11-07，页面上「今天」一直是空的。"""
    late = datetime(2026, 11, 8, 1, 24, tzinfo=CN)
    early = datetime(2026, 11, 8, 23, 30, tzinfo=CN)
    snap = {"sleep": [_sleep("a", late, 6.4), _sleep("b", early, 7.5)],
            "recovery": [{"sleep_id": "a", "score": {"recovery_score": 87}, "score_state": "SCORED"},
                         {"sleep_id": "b", "score": {"recovery_score": 60}, "score_state": "SCORED"}]}
    by_day = whoop_mod.recovery_by_day(snap, "Asia/Shanghai")
    assert by_day[date(2026, 11, 8)]["recovery_score"] == 87
    assert by_day[date(2026, 11, 9)]["recovery_score"] == 60          # 23:30 睡的那晚 → 第二天早上的恢复


def test_strain_cycle_starting_before_midnight_keeps_both_days():
    """周期从入睡开始：23:30 睡的那个周期属于第二天，不能盖掉当天的 strain。"""
    snap = {"cycle": [{"start": _utc(datetime(2026, 11, 7, 2, 0, tzinfo=CN)), "score": {"strain": 2.8}},
                      {"start": _utc(datetime(2026, 11, 7, 23, 30, tzinfo=CN)), "score": {"strain": 0.1}}]}
    s = whoop_mod.strain_by_day(snap, "Asia/Shanghai")
    assert s[date(2026, 11, 7)]["strain"] == 2.8 and s[date(2026, 11, 8)]["strain"] == 0.1


def test_workouts_listed_in_chinese():
    start = datetime(2026, 11, 6, 11, 16, tzinfo=CN)
    snap = {"workout": [{"start": _utc(start), "end": _utc(start + timedelta(minutes=25)), "sport_name": "tennis",
                         "score_state": "SCORED", "score": {"strain": 4.14, "average_heart_rate": 121.6}},
                        {"start": _utc(start), "end": _utc(start + timedelta(minutes=5)), "sport_name": "running",
                         "score_state": "PENDING_SCORE", "score": {}}]}
    assert whoop_mod.workouts(snap, "Asia/Shanghai") == [
        {"date": "2026-11-06", "start": "11:16", "sport": "网球", "min": 25, "strain": 4.1, "avg_hr": 122}]


def test_facts_have_today_recovery_and_workouts(tools_env):
    f = v3.facts(tools_env, BASE)
    assert f["recovery_pct"]["today"] == 25                            # 前一晚（最近 3 晚红区）测出的恢复就是今天的
    assert f["workouts"]["count_7d"] == 0 and f["workouts"]["source"] == "WHOOP"


def test_same_failure_shown_once(tools_env):
    """以前主卡两格都绑「今天步数」、都算不出来，App 上同一句「算不出来」出现两遍。"""
    layout = {"t": "v", "gap": 12, "children": [{"t": "value", "bind": "weight"}, {"t": "value", "bind": "weight"}]}
    out = canvas.resolve(tools_env, layout, BASE)
    assert len(out["children"]) == 1 and out["children"][0]["fallback"]
    assert canvas.live_gaps(layout, out) == (2, [out["children"][0]["text"]])


def test_hero_with_no_live_numbers_is_sent_back(tools_env):
    doc = {"hero": {"board": "sport", "layout": {"t": "v", "gap": 12, "children": [{"t": "value", "bind": "weight"}]}}}
    with pytest.raises(ValueError, match="换一个"):
        v3._check_live_hero(tools_env, "sport", doc)
    ok = {"hero": {"board": "sport", "layout": {"t": "v", "gap": 12, "children": [{"t": "value", "bind": "recovery"}]}}}
    v3._check_live_hero(tools_env, "sport", ok)


class _StepsOnly:
    """只有 daily_series 的假 tools：前两天有步数，今天还没传。"""
    def __init__(self, values):
        self.values = values

    def daily_series(self, name, end, days):
        return {d: v for d, v in self.values.items() if end - timedelta(days=days) < d <= end}


def test_morning_steps_are_zero_not_missing():
    """早上 8 点今天还没走：步数主卡显示 0，下面照样画前几天的柱（以前整张卡只剩一行「算不出来」）。"""
    from pivis_health import viz
    day = date(2026, 11, 8)
    now = datetime(2026, 11, 8, 8, 10, tzinfo=CN)
    out = viz._progress(_StepsOnly({day - timedelta(days=1): 2591.0}), "steps", day, now, {}, {})
    assert out["value"] == 0
    with pytest.raises(viz.VizUnavailable, match="没有数据"):      # 好几天都没数：是手机没传，照实说
        viz._progress(_StepsOnly({}), "steps", day, now, {}, {})
