"""端到端工具层：晨报 / 周报 / 覆盖核对 / 只读性（F0 验收口径）。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

BASE = date(2026, 10, 28)


def test_readonly_never_writes(tools_env):
    con = tools_env.store.connect()
    try:
        con.execute("CREATE TABLE _t(x)")
        raise AssertionError("query_only 连接居然能建表")
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()


def test_morning_report_full(tools_env):
    rep = tools_env.morning_report(BASE)
    assert rep["local_date"] == BASE.isoformat()
    assert rep["completeness"]["sleep_arrived"] is True
    assert 6.0 <= rep["sleep"]["night"]["hours"] <= 7.5
    assert rep["metrics"]["hrv"]["today"] < 50  # 夹具：最近 3 天 HRV=40
    assert rep["metrics"]["hrv"]["z"] < -1
    assert rep["whoop"]["sleep_need_h"] == 8.3  # 7.5+0.5+0.3
    assert rep["whoop"]["suggested_bedtime"]  # 08:30 − 8.5h − 30min = 23:30
    assert rep["questions"], "晨报必须带点选问题（P2 可交互）"
    assert rep["advice_inputs"]
    assert rep["charts"]["hrv_trend_14d"]["values"]
    assert rep["charts"]["recovery_trend_14d"]["values"]
    assert rep["contract"]["non_diagnostic"]


def test_morning_report_race_marked(tools_env):
    """睡眠未同步的早晨：如实标注 + race_note，不编造。"""
    day = BASE - timedelta(days=5)  # 夹具中无睡眠的夜
    rep = tools_env.morning_report(day)
    assert rep["completeness"]["sleep_arrived"] is False
    assert rep["completeness"]["race_note"]


def test_monitor_levels_and_dnd_flag(tools_env):
    mon = tools_env.monitor(BASE, now_hour=3)
    assert mon["findings"]
    for f in mon["findings"]:
        if f["level"] in ("notice", "alert"):
            assert f["dnd_blocked"] is True
    mon_day = tools_env.monitor(BASE, now_hour=10)
    assert all(not f["dnd_blocked"] for f in mon_day["findings"])


def test_weekly_report(tools_env):
    monday = BASE - timedelta(days=7 + BASE.weekday())  # 上一整周（数据完整）
    rep = tools_env.weekly_report(monday)
    assert rep["week_of"] == monday.isoformat()
    assert rep["window"]["nights_n"] >= 4
    assert rep["correlation_not_causation"] is True
    # 行为样本不足时相关性必须为空（样本量门禁）
    assert rep["correlation_candidates"] == []


def test_weekly_correlation_appears_after_answers(tools_env):
    monday = BASE - timedelta(days=7 + BASE.weekday())
    # 行为答案记在周窗口内（周报回看 21 天），10 天、晚/不晚各半
    for i, d in enumerate([monday - timedelta(days=3) + timedelta(days=k) for k in range(10)]):
        tools_env.subj.record(d.isoformat(), "behavior_answer", {
            "question_id": "dinner_time", "answer": "20点后" if i % 2 == 0 else "18点前"})
    rep = tools_env.weekly_report(monday)
    assert rep["correlation_candidates"], "样本够时相关性候选应出现且带样本量"
    c = rep["correlation_candidates"][0]
    assert c["n_late"] >= 3 and c["n_not_late"] >= 3


def test_coverage_gap_only_after_3_days(tools_env):
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    now = datetime.combine(BASE, time(20), tzinfo=ZoneInfo("Asia/Shanghai"))
    cov = tools_env.coverage(now)
    assert cov["sources"]
    assert cov["notify"] is False  # 数据止于 BASE 当天 → 不误报


def test_series_and_baseline(tools_env):
    s = tools_env.series("hrv", 30, BASE)
    assert len(s["values"]) == 31
    b = tools_env.baseline("hrv", BASE)
    assert b["baseline"]["n"] >= 7
    assert b["z"] < -1
    w = tools_env.series("whoop_recovery", 14, BASE)
    assert w["values"]


def test_answer_question_persists(tools_env):
    out = tools_env.answer_question("subjective_sleep", "4 不错", BASE)
    assert out["ok"] is True
    entries = tools_env.subj.entries(kinds=["subjective_sleep"], since=BASE, until=BASE)
    assert entries[0]["payload"]["score"] == 4
