"""build 51：老大的「今天」到早上 6 点才翻页；数据断了的提示由服务器按真实状态写。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from pivis_health import v3
from pivis_health.clock import day_of
from pivis_health.todos import TodoStore

CN = timezone(timedelta(hours=8))


def at(tools, monkeypatch, text):
    monkeypatch.setattr(type(tools), "_now", lambda self: datetime.fromisoformat(text).replace(tzinfo=CN))


def test_day_of_rolls_at_six():
    assert day_of(datetime(2026, 11, 10, 0, 20)) == date(2026, 11, 9)
    assert day_of(datetime(2026, 11, 10, 5, 59)) == date(2026, 11, 9)
    assert day_of(datetime(2026, 11, 10, 6, 0)) == date(2026, 11, 10)


def test_after_midnight_page_still_shows_tonight(tools_env, monkeypatch):
    tools = tools_env
    at(tools, monkeypatch, "2026-11-10T00:20:00")
    st = TodoStore(tools.cfg)
    st.add({"id": "s9", "board": "sleep", "when": "23:30", "title": "床外拉伸", "kind": "done"}, date(2026, 11, 9))
    st.add({"id": "b9", "board": "sleep", "when": "00:05", "title": "上床", "kind": "done"}, date(2026, 11, 9))
    st.add({"id": "s10", "board": "sleep", "when": "23:30", "title": "明晚拉伸", "kind": "done"}, date(2026, 11, 10))
    doc = v3.page_doc(tools, "now")
    assert doc["date"] == "2026-11-09"
    titles = [t["title"] for t in doc["todos"] + doc["more"]]
    assert "上床" in titles and "床外拉伸" in titles          # 今晚的还在，没被零点收起
    assert "明晚拉伸" not in titles                          # 明天的不提前出来
    assert st.get("s9")["status"] == "scheduled"             # 零点一过不算过期
    # 早上 6 点后翻到新的一天
    at(tools, monkeypatch, "2026-11-10T07:00:00")
    doc = v3.page_doc(tools, "now")
    assert doc["date"] == "2026-11-10"
    assert "明晚拉伸" in [t["title"] for t in doc["todos"] + doc["more"]]


def test_page_published_after_midnight_counts_for_previous_day():
    assert v3._pub_day({"published_at": "2026-11-10T00:22:08+08:00"}) == date(2026, 11, 9)
    assert v3._pub_day({"published_at": "2026-11-10T08:05:00+08:00"}) == date(2026, 11, 10)
    assert v3._pub_day({}) == date.min


def test_model_outage_notices_hidden_server_ones_shown(tools_env, monkeypatch):
    tools = tools_env
    v3.V3PageStore(tools.cfg).save("now", {
        "headline": {"text": "今晚早点睡"}, "hero": {"level": "watch", "board": "sleep", "label": "睡眠", "value": "",
                                                    "unit": "", "note": "", "others": []},
        "details": [], "notices": [{"text": "睡眠数据已经停了两晚"}, {"text": "周末别熬夜"}], "published_at": "2026-11-10T08:00:00+08:00"})
    monkeypatch.setattr(v3, "data_notices", lambda tools, page, day: [{"text": "WHOOP 授权掉了", "source": "server"}])
    texts = [n["text"] for n in v3.page_doc(tools, "now")["notices"]]
    assert texts == ["WHOOP 授权掉了", "周末别熬夜"]


def test_apple_health_notice_only_when_permission_confirmed(tools_env, monkeypatch):
    """build 53：只有 App 在前台查 HealthKit 查到 0 条、一天多没收到过样本，才提示开权限；服务器拒收不提示老大。"""
    from datetime import datetime, timezone
    from pivis_health import ingest
    tools = tools_env
    day = date(2026, 11, 9)
    d = tools.cfg.data_dir
    assert not [n for n in v3.data_notices(tools, "now", day) if "Apple" in n["text"]]          # 什么都没记：手机没开 App
    ingest.note_result(d, 3, {"accepted": 0, "rejected": 3, "reject_reasons": [{"reason": "bad_timestamp"}]})
    assert not [n for n in v3.data_notices(tools, "now", day) if "Apple" in n["text"]]          # 服务器拒收：是我们的 bug
    (d / ingest.STATE_FILE).unlink()
    ingest.note_result(d, 0, {"accepted": 0, "rejected": 0}, {"foreground": True, "samples": 0})
    assert [n for n in v3.data_notices(tools, "now", day) if "Apple 健康" in n["text"]]
    ingest.note_result(d, 5, {"accepted": 5, "rejected": 0}, {"foreground": True, "samples": 5})
    assert not [n for n in v3.data_notices(tools, "now", day) if "Apple" in n["text"]]


def test_length_limits_on_agent_writes(tools_env):
    import pytest
    from pivis_health.todos import TodoError, clean_project_name
    tools = tools_env
    st = TodoStore(tools.cfg)
    day = date(2026, 11, 9)
    with pytest.raises(TodoError, match="标题"):
        st.add({"board": "sleep", "when": "22:00", "title": "睡前把手机放到客厅充电再上床", "kind": "done"}, day)
    with pytest.raises(TodoError, match="note"):
        st.add({"board": "sleep", "when": "22:00", "title": "手机放客厅", "kind": "done",
                "note": "放远一点，睡前一小时不看屏幕，床只用来睡觉"}, day)
    t = st.add({"board": "sleep", "when": "22:00", "title": "手机放客厅", "kind": "done"}, day)
    st.update(t["id"], {"status": "done"}, by="user")                   # 老大的操作不查字数
    with pytest.raises(TodoError, match="括号"):
        st.project_set({"id": "back", "name": "腰背放松（每周三次）", "board": "sport"}, day)
    st.project_set({"id": "cbt", "name": "CBT-I · 42 天", "board": "sleep"}, day)   # 天数后缀不算字数
    assert clean_project_name("腰背放松（每周三次）") == "腰背放松"
    assert clean_project_name("CBT-I 一个月") == "CBT-I"
