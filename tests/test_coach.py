"""教练用的统计和记忆：提交的答案不丢、项目执行率、素材库扩充、周日复盘提示、了解到的老大同步进 AGENTS。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pivis_health import coach, prefs
from pivis_health.config import Config
from pivis_health.todos import TodoStore

D1 = date(2026, 10, 27)


def _cfg(tmp_path):
    return replace(Config(), data_dir=tmp_path)


def _project():
    return {"id": "cbti", "name": "CBT-I", "board": "sleep", "start": D1.isoformat(), "days": 30,
            "daily": [{"key": "diary", "when": "08:40", "title": "记一下昨晚", "kind": "fields",
                       "inputs": [{"id": "latency", "label": "多久睡着", "type": "options", "options": ["15 分内", "30+"],
                                   "submit": "agent"}]},
                      {"key": "bed", "when": "00:00", "title": "上床", "kind": "done"}]}


def test_submitted_answers_survive_agent_update(tmp_path):
    st = TodoStore(_cfg(tmp_path))
    st.project_set(_project(), D1, datetime(2026, 10, 27, 8, 0))
    diary = next(t for t in st.for_date(D1, "sleep") if t["title"] == "记一下昨晚")
    st.user_submit(diary["id"], "agent", {"latency": "30+"}, "半夜醒了两次", None, datetime(2026, 10, 27, 8, 45))
    t = st.update(diary["id"], {"status": "done", "summary": "入睡 30+ 分"}, by="agent")
    assert t["request"] is None
    assert t["record"]["values"] == {"latency": "30+"} and t["record"]["submitted"][-1]["text"] == "半夜醒了两次"
    t = st.update(diary["id"], {"record": {"note": "P-Health 改写"}}, by="agent")       # 改写 record 也保留提交历史
    assert t["record"]["submitted"][-1]["values"] == {"latency": "30+"}


def test_project_stats_counts_past_days_only(tmp_path):
    cfg = _cfg(tmp_path)
    st = TodoStore(cfg)
    st.project_set(_project(), D1, datetime(2026, 10, 27, 8, 0))
    for i in range(3):
        d = D1 + timedelta(days=i)
        st.materialize(d, datetime.combine(d, datetime.min.time()))
        for t in st.for_date(d, "sleep"):
            if i < 2 and t["title"] == "上床":
                st.user_submit(t["id"], "done", {}, None, None, datetime.combine(d, datetime.min.time()))
    tools = SimpleNamespace(cfg=cfg, _now=lambda: datetime(2026, 10, 29, 20, 0))
    out = coach.project_stats(tools, "cbti", 7)
    bed = next(i for i in out["items"] if i["title"] == "上床")
    assert bed == {"title": "上床", "done": 2, "skipped": 0, "missed": 0, "total": 2, "rate_pct": 100}
    assert out["by_day"][-1]["today"] is True
    with pytest.raises(ValueError, match="没有项目"):
        coach.project_stats(tools, "nope")


def test_media_add_cleans_and_dedupes(tmp_path):
    tools = SimpleNamespace(cfg=_cfg(tmp_path), _now=lambda: datetime(2026, 11, 5, 21, 0))
    a = coach.media_add(tools, {"title": "身体扫描", "url": "https://www.bilibili.com/video/BV1ab?spm=x", "duration_min": 12})
    assert a["url"] == "https://www.bilibili.com/video/BV1ab" and a["kind"] == "video"
    coach.media_add(tools, {"title": "身体扫描 v2", "url": "https://www.bilibili.com/video/BV1ab"})
    assert len(coach.user_media(tools)) == 1
    with pytest.raises(ValueError):
        coach.media_add(tools, {"title": "x", "url": "/media/local.m4a"})


def test_weekly_review_note_only_on_sunday(tmp_path):
    cfg = _cfg(tmp_path)
    TodoStore(cfg).project_set(_project(), D1, datetime(2026, 10, 27, 8, 0))
    tools = SimpleNamespace(cfg=cfg)
    assert coach.weekly_review_note(tools, "sleep", date(2026, 11, 7)) == ""          # 周六
    note = coach.weekly_review_note(tools, "sleep", date(2026, 11, 8))                 # 周日
    assert "project-stats --id <id>" in note and "CBT-I（cbti）" in note
    assert coach.weekly_review_note(tools, "sport", date(2026, 11, 8)) == ""


def test_known_facts_render_into_agents_block():
    block = prefs.render_block([{"scope": "pref.chart", "payload": {"rule": "图一律用折线"}, "recorded_at": "2026-11-05"}],
                               [{"scope": "learn.sleep", "payload": {"rule": "做了床外放松的晚上入睡更快"}, "recorded_at": "2026-11-05"}])
    assert "图一律用折线" in block and "你已经了解到的老大" in block and "入睡更快（learn.sleep" in block


def test_pause_and_template_change_clean_future_instances(tmp_path):
    st = TodoStore(_cfg(tmp_path))
    today = date(2026, 11, 5)
    tomorrow = today + timedelta(days=1)
    st.project_set(_project(), today)
    st.materialize(tomorrow)                     # 别的地方先把明天展开了
    assert {t["title"] for t in st.for_date(tomorrow)} == {"记一下昨晚", "上床"}
    # 改模板：删掉「上床」，日记改时间
    p = _project()
    p["daily"] = [{**p["daily"][0], "when": "09:00"}]
    st.project_set(p, today)
    left = st.for_date(tomorrow)
    assert [(t["title"], t["when"]) for t in left] == [("记一下昨晚", "09:00")]
    # 暂停：今天和明天还没开始的实例都撤掉，做完的留着
    first = st.for_date(today)[0]
    st.user_submit(first["id"], "done", {}, None, None, datetime(2026, 11, 5, 9, 5))
    st.project_set({"id": p["id"], "status": "paused"}, today)
    assert [t["status"] for t in st.for_date(today)] == ["done"]
    assert st.for_date(tomorrow) == []


def test_known_facts_without_rule_still_render():
    block = prefs.render_block([], [
        {"scope": "learn.exp", "recorded_at": "2026-11-05T21:00:00", "payload": {"items": [
            {"id": "a", "change": "每天 15:30 慢呼吸 5 分钟", "result": None},
            {"id": "b", "change": "旧实验", "result": "有效"}]}},
        {"scope": "profile.safety", "recorded_at": "2026-11-05T21:00:00",
         "payload": {"cbti_ok": True, "flags": ["晚上胸口闷"], "advised": "11-06 心内科"}}])
    assert "在试：每天 15:30 慢呼吸 5 分钟（learn.exp" in block and "旧实验" not in block
    assert "晚上胸口闷；11-06 心内科（profile.safety" in block


def test_projects_truth_uses_current_start(tmp_path):
    cfg = _cfg(tmp_path)
    st = TodoStore(cfg)
    now = datetime(2026, 11, 7, 8, 0)
    st.project_set({"id": "tennis", "name": "网球力量", "board": "sport", "start": "2026-11-16", "days": 28,
                    "daily": [{"key": "a", "when": "20:00", "title": "全身力量 A", "kind": "done"}]}, now.date(), now)
    st.project_set({"id": "wind", "name": "睡前放松", "board": "sleep", "start": "2026-11-05", "days": 14,
                    "daily": [{"key": "b", "when": "22:30", "title": "关灯", "kind": "done"}]}, now.date(), now)
    tools = SimpleNamespace(cfg=cfg)
    text = coach.projects_truth(tools, date(2026, 11, 9))
    assert "网球力量（tennis）：2026-11-16 开始，7 天后，今天还没开始" in text
    assert "睡前放松（wind）：第 5 天 / 共 14 天" in text
    assert "明天，今天还没开始" in coach.projects_truth(tools, date(2026, 11, 15), "sport")
    assert coach.projects_truth(tools, date(2026, 11, 9), "stress") == ""
