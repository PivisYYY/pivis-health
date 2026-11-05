"""主卡图表：P-Health 写描述，内核填数；每种画法、偏好覆盖、页面校验。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from pivis_health import viz
from pivis_health.v3 import validate_page

TZ = timezone(timedelta(hours=8))
DAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 15, 0, tzinfo=TZ)


class FakeTools:
    def __init__(self, series: dict[str, list[float]], baselines: dict[str, tuple[float, float]] | None = None):
        self.series = series
        self.baselines = baselines or {}
        self.cfg = None
        self.subj = None

    def _now(self):
        return NOW

    def daily_series(self, canonical, end_day, days):
        vals = self.series.get(canonical, [])
        n = len(vals)
        return {end_day - timedelta(days=n - 1 - i): v for i, v in enumerate(vals)}

    def baseline(self, canonical, end_day=None):
        if canonical not in self.baselines:
            return {"baseline": None}
        c, s = self.baselines[canonical]
        return {"baseline": {"center": c, "spread": s}}


@pytest.fixture(autouse=True)
def no_prefs(monkeypatch):
    monkeypatch.setattr(viz, "prefs_for", lambda cfg: {})


def nights(slept, need=8.4):
    start = DAY - timedelta(days=len(slept))
    return [{"date": (start + timedelta(days=i)).isoformat(), "actual": h, "need": need} for i, h in enumerate(slept)]


def test_trend_band_warn_zone_and_delta():
    hrv = [46, 45, 47, 44, 46, 44, 42, 40, 37, 35, 33, 31, 30, 29]
    t = FakeTools({"whoop_hrv_rmssd": hrv}, {"whoop_hrv_rmssd": (45.0, 5.0)})
    v = viz.build(t, {"metric": "hrv"}, DAY, NOW)
    assert v["kind"] == "trend" and v["days"] == 14 and len(v["series"]) == 14
    assert v["band"] == [40.0, 50.0] and v["warn"] == 37.5
    assert v["zone"] == "act" and v["value_text"] == "29.0"
    assert v["aside"]["text"] == "↘ 28%"


def test_high_bad_range_for_resting_hr():
    t = FakeTools({"resting_heart_rate": [63, 64, 66, 67, 69, 70, 72]}, {"resting_heart_rate": (58.0, 4.0)})
    v = viz.build(t, {"metric": "resting_hr"}, DAY, NOW)
    assert v["kind"] == "range" and v["warn"] == 64 and v["band"] == [54, 62]
    assert v["zone"] == "act" and v["aside"]["text"] == "一周前 63"
    assert v["scale"][0] < 54 and v["scale"][1] > 72


def test_gauge_zones():
    for val, zone in ((28, "act"), (50, "watch"), (78, "steady")):
        v = viz.build(FakeTools({"whoop_recovery": [60, val]}), {"metric": "recovery"}, DAY, NOW)
        assert v["kind"] == "gauge" and v["zone"] == zone and v["warn"] == 33


def test_need_and_stack(monkeypatch):
    monkeypatch.setattr(viz, "_sleep_nights", lambda tools, day: nights([8.1, 7.1, 8.0, 6.2, 6.0, 5.8, 5.5]))
    v = viz.build(FakeTools({}), {"metric": "sleep"}, DAY, NOW)
    assert v["kind"] == "need" and v["short"] == 2.9 and v["zone"] == "act" and v["short_nights"] == 5
    d = viz.build(FakeTools({}), {"metric": "sleep_debt"}, DAY, NOW)
    assert d["kind"] == "stack" and len(d["blocks"]) == 5 and d["value"] == 10.5 and d["zone"] == "act"


def test_progress_pace():
    v = viz.build(FakeTools({"steps": [1200]}), {"metric": "steps"}, DAY, NOW)
    assert v["kind"] == "progress" and v["goal"] == 8000 and 0 < v["pace"] < 8000 and v["zone"] == "act"


def test_route_needs_target_then_uses_pref(monkeypatch):
    t = FakeTools({"weight": [90.0, 89.6, 89.9, 90.4, 90.9, 91.2]})
    with pytest.raises(viz.VizUnavailable):
        viz.build(t, {"metric": "weight"}, DAY, NOW)
    monkeypatch.setattr(viz, "prefs_for", lambda cfg: {"weight": {"target": 80, "rate_kg_week": 0.5}})
    v = viz.build(t, {"metric": "weight"}, DAY, NOW)
    assert v["kind"] == "route" and v["target"] == 80.0 and v["start"] == 90.0 and v["weeks_total"] == 20


def test_pref_overrides_warn_and_goal(monkeypatch):
    monkeypatch.setattr(viz, "prefs_for", lambda cfg: {"hrv": {"warn": 30}, "steps": {"goal": 10000}})
    t = FakeTools({"whoop_hrv_rmssd": [40, 38, 36, 35, 34, 33, 31], "steps": [1800]}, {"whoop_hrv_rmssd": (40.0, 4.0)})
    assert viz.build(t, {"metric": "hrv", "days": 7}, DAY, NOW)["warn"] == 30
    assert viz.build(t, {"metric": "steps"}, DAY, NOW)["goal"] == 10000


def test_agent_controls_kind_days_show():
    t = FakeTools({"whoop_recovery": list(range(40, 70))}, {"whoop_recovery": (50.0, 10.0)})
    v = viz.build(t, {"metric": "recovery", "kind": "trend", "days": 30, "show": ["warn"]}, DAY, NOW)
    assert v["kind"] == "trend" and len(v["series"]) == 30 and v["show"] == ["warn"]
    with pytest.raises(ValueError):
        viz.normalize({"metric": "recovery", "kind": "stack"})
    with pytest.raises(ValueError):
        viz.normalize({"metric": "hrv", "days": 9})
    with pytest.raises(ValueError):
        viz.normalize({"metric": "hrv", "show": ["sparkles"]})


def _evidence(zone="act"):
    return {"facts": {"viz": {"hrv": {"ok": True, "board": "stress", "kinds": ["trend", "range"], "value": 29.0,
                                      "value_text": "29.0", "unit": "ms", "zone": zone, "band": [40, 50], "warn": 37.5},
                              "weight": {"ok": False, "reason": "还没定目标体重", "board": "sport"}}}}


def test_validate_page_accepts_viz_and_takes_kernel_value():
    doc = {"headline": {"text": "压力信号偏高，今晚别加练"},
           "hero": {"level": "act", "board": "stress", "label": "HRV", "value": "", "viz": {"metric": "hrv"}}}
    for ev in (_evidence(), _evidence()["facts"]):        # publish 传的是 facts 本身
        out = validate_page("stress", doc, ev)
        assert out["hero"]["viz"] == {"metric": "hrv", "kind": "trend", "days": 14}
        assert out["hero"]["value"] == "29.0" and out["hero"]["unit"] == "ms"


@pytest.mark.parametrize("hero,msg", [
    ({"level": "steady", "board": "stress", "label": "HRV", "viz": {"metric": "hrv"}}, "steady"),
    ({"level": "act", "board": "sport", "label": "体重", "viz": {"metric": "weight"}}, "画不了"),
    ({"level": "act", "board": "sleep", "label": "HRV", "viz": {"metric": "hrv"}}, "板块"),
    ({"level": "act", "board": "stress", "label": "HRV", "viz": {"metric": "hrv"},
      "fields": [{"label": "近 3 天", "value": "29.0"}]}, "fields"),
])
def test_validate_page_rejects_bad_viz(hero, msg):
    page = hero["board"]
    with pytest.raises(ValueError, match=msg):
        validate_page(page, {"headline": {"text": "今晚早点睡"}, "hero": hero}, _evidence())
