"""小组件数据：此刻主卡、今天没做的待办（带绝对时间、能不能直接打勾）、上床时间、近 7 晚。"""
from __future__ import annotations

from pivis_health import v3
from pivis_health.todos import TodoStore


def test_widget_doc_shape_and_todos(tools_env):
    tools = tools_env
    day = tools._now().date()
    st = TodoStore(tools.cfg)
    st.add({"id": "w1", "board": "stress", "when": "21:45", "title": "慢呼吸 5 分钟", "kind": "follow",
            "steps": [{"title": "慢呼吸", "duration_min": 5}]}, day)
    st.add({"id": "w2", "board": "sleep", "when": "21:50", "title": "把明天写下来", "kind": "done", "note": "写完合上纸"}, day)
    st.add({"id": "w3", "board": "sleep", "when": "00:15", "title": "上床", "kind": "done", "auto": "bedtime"}, day)
    done = st.add({"id": "w4", "board": "sleep", "when": "08:40", "title": "记一下昨晚", "kind": "done"}, day)
    st.user_submit(done["id"], "done", {}, None, None, tools._now())

    doc = v3.widget_doc(tools)
    assert set(doc) >= {"now", "date", "hero", "todos", "count", "bed", "sleep"}
    titles = [t["title"] for t in doc["todos"]]
    assert "记一下昨晚" not in titles                      # 做完的不进小组件
    assert titles.index("慢呼吸 5 分钟") < titles.index("把明天写下来") < titles.index("上床")
    by = {t["title"]: t for t in doc["todos"]}
    assert by["把明天写下来"]["check"] is True             # 打勾类：小组件上直接 ✓
    assert by["慢呼吸 5 分钟"]["check"] is False           # 跟做要进 App
    assert by["上床"]["check"] is False and by["上床"]["auto"] is True   # 设备自动记的不让手点
    assert by["把明天写下来"]["at"].startswith(f"{day.isoformat()}T21:50")
    assert by["把明天写下来"]["board_label"] == "休息"
    # 00:15 算当晚：绝对时间是第二天
    assert doc["bed"]["when"] == "00:15" and not doc["bed"]["at"].startswith(day.isoformat())
    assert isinstance(doc["sleep"]["nights"], list) and len(doc["sleep"]["nights"]) <= 7
    assert {"label", "value", "unit", "note"} <= set(doc["hero"])


def test_abs_time_rules():
    from datetime import timedelta, timezone
    tz = timezone(timedelta(hours=8))
    assert v3._abs_time("2026-11-06", "21:50", tz) == "2026-11-06T21:50+08:00"
    assert v3._abs_time("2026-11-06", "00:30", tz) == "2026-11-07T00:30+08:00"
    assert v3._abs_time("2026-11-06", "", tz) is None
    assert v3._abs_time("bad", "12:00", tz) is None
