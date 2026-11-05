"""五日推演剧本 · 可执行验收（真实数据 10-28 → 11-01）。

这是《v2-five-day-walkthrough.md》的机器可执行版：每条断言对应剧本里的一天。
真实客观库与 WHOOP 快照只读；主观库复制到临时目录，验收写入不污染生产。
"""
from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from pivis_health.config import load_config
from pivis_health.pages import V2Pages
from pivis_health.tools import HealthTools
from pivis_health.web_v2 import render_today

REAL_DB = Path.home() / "PivisVault/.pivis/health/db/health.sqlite3"
REAL_SNAP = Path.home() / ".hermes/profiles/pivis/integrations/whoop/runtime/whoop-snapshot.json"
REAL_SUBJ = Path.home() / ".dsh/bot/workspace/pivis-runtime/subjective.sqlite3"

pytestmark = pytest.mark.skipif(
    not (REAL_DB.exists() and REAL_SNAP.exists()), reason="本机无真实健康数据"
)


@pytest.fixture()
def real(tmp_path, monkeypatch):
    data_dir = tmp_path / "acc"
    data_dir.mkdir()
    if REAL_SUBJ.exists():
        shutil.copy(REAL_SUBJ, data_dir / "subjective.sqlite3")
    monkeypatch.setenv("PIVIS_HEALTH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PIVIS_HEALTH_VAULT_DB", str(REAL_DB))
    monkeypatch.setenv("PIVIS_HEALTH_WHOOP_SNAPSHOT", str(REAL_SNAP))
    monkeypatch.delenv("PIVIS_HEALTH_CONFIG", raising=False)
    tools = HealthTools(load_config())
    return V2Pages(tools)


D28, D29, D30, D31, D01 = (date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30),
                            date(2026, 10, 31), date(2026, 11, 1))


def _types(needs):
    return [n["need_type"] for n in needs]


# ---------- Day 1 · 10-28 ----------
def test_day1_hero_45_and_range_learning(real):
    p = real.today(D28)
    assert p["hero"]["value"] == 45.0
    assert p["hero"]["range"]["ready"] is False
    assert "还在学习" in p["hero"]["range"]["label"]
    assert "9" in p["hero"]["range"]["label"]  # 已有 9 天（10-20 起）


def test_day1_apple_gap_card_first_day(real):
    p = real.today(D28)
    assert "data_sync" in _types(p["needs"])
    card = next(n for n in p["needs"] if n["need_type"] == "data_sync")
    assert "3 天" in card["evidence"]          # 断更第 3 天首次进卡（剧本 Day1）


def test_day1_top_need_is_catch_up_sleep(real):
    p = real.today(D28)
    assert _types(p["needs"])[0] == "catch_up_sleep"


# ---------- Day 2 · 10-29 ----------
def test_day2_hero_35_low(real):
    p = real.today(D29)
    assert p["hero"]["value"] == 35.0


def test_day2_play_verdict_light(real):
    play = real._play_ok(D29)
    assert play["verdict"] == "可以但轻一点"
    names = [c["name"] for c in play["checks"]]
    assert names == ["恢复", "不连续两天高强度", "周负荷 < 预算"]


def test_day2_debt_high_severity(real):
    p = real.today(D29)
    card = next(n for n in p["needs"] if n["need_type"] == "catch_up_sleep")
    assert card["evidence_fields"]["sleep_debt_h"] > 3.0


# ---------- Day 3 · 10-30 ----------
def test_day3_hq_difficulty_5_all_q1(real):
    p = real.sleep(D30)
    assert p["tiles"]["hq"]["score"] == 5
    assert p["tiles"]["hq"]["nights_pass"] == 0
    assert max(p["hq_fail_counts"], key=p["hq_fail_counts"].get) == "Q1"


def test_day3_friday_bedtime_grace(real):
    p = real.sleep(D30)
    t = p["tonight"]["target"]
    assert t["grace_applied"] == 60
    # 真实需求 9.92h：08:20 − 595′ − 20′ − 30′ + 60′ = 22:35
    assert t["bedtime"] == "22:35"
    assert p["tonight"]["caffeine_cutoff"] == "14:35"


def test_day3_chart14_short_night_marked(real):
    p = real.sleep(D30)
    rows = {r["date"]: r for r in p["chart14"]}
    assert rows["2026-10-30"]["actual"] == 5.45 and rows["2026-10-30"]["short"] is True
    assert rows["2026-10-28"]["short"] is True   # 5.79 vs 9.0


# ---------- Day 4 · 10-31 ----------
def test_day4_recovery_missing_no_fabrication(real):
    p = real.today(D31)
    assert p["hero"]["value"] is None
    assert "数据不足" in render_today(p)


def test_day4_sources_separate(real):
    cov = real.t.coverage(now=datetime(2026, 10, 31, 20, 0,
                                       tzinfo=real.t.tz))
    by = {s["type"]: s for s in cov["sources"]}
    assert by["sleep_analysis"]["gap_days"] == 5 and by["sleep_analysis"]["notify"] is True
    # WHOOP 当天凌晨 01:17 还同步过 → gap 0：断更只报 Apple，不误伤 WHOOP
    whoop = next(s for s in cov["sources"] if s["source"] == "whoop")
    assert whoop["gap_days"] == 0 and whoop["notify"] is False


# ---------- Day 5 · 11-01 ----------
def test_day5_big_load_rest_card(real):
    p = real.today(D01)
    assert "big_load_rest" in _types(p["needs"])
    card = next(n for n in p["needs"] if n["need_type"] == "big_load_rest")
    assert card["evidence_fields"]["yesterday_strain"] == 13.2


def test_day5_play_data_insufficient(real):
    assert real._play_ok(D01)["verdict"] == "数据不足"


def test_day5_stress_page_degrades(real):
    p = real.stress(D01)
    assert p["work_signals"]["available"] is False
    assert "接入" in p["work_signals"]["label"]


def test_day5_latency_rating_day(real):
    p = real.sleep(D01)
    assert p["rating_card"]["ask_latency_today"] is True  # 单日问入睡难度


def test_day5_apple_gap_6(real):
    cov = real.t.coverage(now=datetime(2026, 11, 1, 20, 0, tzinfo=real.t.tz))
    assert next(s for s in cov["sources"] if s["type"] == "sleep_analysis")["gap_days"] == 6


# ---------- 全程红线 ----------
def test_never_more_than_three_and_specialty_cap(real):
    for d in (D28, D29, D30, D31, D01):
        needs = real.today(d)["needs"]
        assert len(needs) <= 3
        from collections import Counter
        spec = Counter(n["specialty"] for n in needs)
        assert all(v <= 2 for v in spec.values()), f"{d}: {spec}"


def test_hero_always_matches_real_series(real):
    for d in (D28, D29, D30, D31, D01):
        series = real._recovery_daily(d)
        assert real.today(d)["hero"]["value"] == series.get(d)


def test_push_cap_and_dnd_params(real):
    p = real.params.all()
    assert p["push_daily_cap"] == 5
    assert p["dnd_mode"] == "bed_to_wake"
    assert p["wake_target"] == "08:20"
