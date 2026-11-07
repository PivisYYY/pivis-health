"""坚持习惯：主卡下面每个习惯一行（页面 habits），点进去对话顶部是习惯卡（GET /api/v3/habit/<id>）。"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from clips import make_clip
from pivis_health import v3
from pivis_health.todos import TodoStore

CN = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 11, 19, 15, 30, tzinfo=CN)          # 周四，力量训练第 11 天


@pytest.fixture()
def env(tools_env, monkeypatch):
    tools = tools_env
    monkeypatch.setattr(type(tools), "_now", lambda self: NOW)
    dd = tools.cfg.data_dir
    st = TodoStore(tools.cfg)
    daily = [{"key": k, "weekdays": [wd], "when": "20:00", "title": f"全身力量 {k.upper()}", "kind": "follow",
              "media": make_clip(dd, f"s{k}", 20, f"全身力量 {k.upper()}")} for k, wd in (("a", 1), ("b", 4), ("c", 6))]
    st.project_set({"id": "strength", "name": "力量训练", "board": "sport", "start": "2026-11-09", "days": 56,
                    "daily": daily}, date(2026, 11, 9))
    st.project_set({"id": "neck", "name": "肩颈放松 · 56 天", "board": "sport", "start": "2026-11-23", "days": 56,
                    "daily": [{"key": "k", "when": "21:30", "title": "肩颈六动作", "kind": "follow",
                               "media": make_clip(dd, "neck", 17, "肩颈六动作")}]}, date(2026, 11, 19))
    st.project_set({"id": "food", "name": "饮食和身体记录", "board": "life", "start": "2026-11-05", "days": 365,
                    "daily": [{"key": "kg", "when": "07:40", "title": "称体重", "kind": "number",
                               "inputs": [{"id": "kg", "type": "number", "unit": "kg"}]}]}, date(2026, 11, 5))
    # 周一的 A 做完了
    st.materialize(date(2026, 11, 16), datetime(2026, 11, 16, 8, 0))
    st.user_submit("strength-2026-11-16-a", "done", {}, None, None, datetime(2026, 11, 16, 20, 30))
    return tools


def test_page_rows(env):
    now = v3.page_doc(env, "now")
    assert "handling" not in now["hero"]
    rows = {r["id"]: r for r in now["habits"]}
    assert rows["strength"]["label"] == "力量训练 · 第 11 天 / 56" and rows["strength"]["today"] == "今天 20:00"
    assert rows["neck"]["label"] == "肩颈放松" and rows["neck"]["today"] == "11-23 开始" and rows["neck"]["state"] == "not_started"
    assert rows["food"]["board_label"] == "日常"
    sport = v3.page_doc(env, "sport")
    assert [r["id"] for r in sport["habits"]] == ["strength", "neck"]         # 别的板块不进来
    assert v3.page_doc(env, "sleep")["habits"] == []


def test_habit_card(env):
    h = v3.habit_doc(env, "strength")
    assert h["name"] == "力量训练" and h["day"] == 11 and h["days"] == 56
    assert [(d["wd"], d["state"], d["label"]) for d in h["week"]] == [
        ("一", "done", "A"), ("二", "rest", ""), ("三", "rest", ""), ("四", "today", "B"),
        ("五", "rest", ""), ("六", "plan", "C"), ("日", "rest", "")]
    assert [(s["title"], s["next"]) for s in h["sessions"]] == [
        ("全身力量 B", "今天 20:00"), ("全身力量 C", "周六 20:00"), ("全身力量 A", "下周一 20:00")]
    b = h["sessions"][0]
    assert b["today"] is True and b["meta"] == "今天 20:00 · 20 分钟"
    assert b["video"]["url"] == "/media/follow/sb/out.mp4" and b["video"]["duration_min"] == 20
    assert h["summary"] == "第 11 天 · 下次 今天 20:00 全身力量 B"
    assert v3.habit_doc(env, "nope") is None


def test_today_done_moves_next(env):
    st = TodoStore(env.cfg)
    st.user_submit("strength-2026-11-19-b", "done", {}, None, None, NOW)
    h = v3.habit_doc(env, "strength")
    assert h["week"][3]["state"] == "done"
    assert h["summary"] == "第 11 天 · 下次 周六 20:00 全身力量 C"
    assert {r["id"]: r for r in v3.page_doc(env, "now")["habits"]}["strength"]["today"] == "今天做完了"


def test_record_project_has_no_video(env):
    h = v3.habit_doc(env, "food")
    assert h["sessions"][0]["video"] is None and h["sessions"][0]["title"] == "称体重"
    assert all(d["label"] == "" for d in h["week"])


def test_widget_plays_practice(env):
    w = v3.widget_doc(env)
    b = next(t for t in w["todos"] if t["id"] == "strength-2026-11-19-b")
    assert b["play"] is True and b["duration_min"] == 20 and b["check"] is False


def test_expired_today_shows_next_time(env):
    """今天的卡都过点了（没做）：不能写「今天做完了」，写下一次"""
    st = TodoStore(env.cfg)
    st.update("strength-2026-11-19-b", {"status": "expired"})
    row = {r["id"]: r for r in v3.page_doc(env, "now")["habits"]}["strength"]
    assert row["today"] == "周六 20:00"
