"""此刻页：待办超过 3 张时先排再截，截下来的放 more（App 显示「另有 N 件」，提醒照排）。"""
from __future__ import annotations

from pivis_health import v3
from pivis_health.todos import TodoStore


def test_now_page_sorts_before_capping(tools_env):
    tools = tools_env
    day = tools._today()
    st = TodoStore(tools.cfg)
    # 存储顺序故意和时间顺序反着：最早到点的喝水卡（日常）最后建
    for i, (when, board, title) in enumerate([("22:30", "sleep", "关灯"), ("21:00", "stress", "慢呼吸"),
                                              ("20:00", "sport", "力量 A"), ("19:00", "sleep", "记一下"),
                                              ("14:45", "life", "喝水")]):
        st.add({"id": f"n{i}", "board": board, "when": when, "title": title, "kind": "done"}, day)

    doc = v3.page_doc(tools, "now")
    shown = [t["title"] for t in doc["todos"]]
    assert shown == ["喝水", "记一下", "力量 A"]                 # 最早到点的三张，日常卡没被挤掉
    assert [t["title"] for t in doc["more"]] == ["慢呼吸", "关灯"]
    assert doc["hidden"] == 2


def test_board_pages_and_short_lists_have_no_more(tools_env):
    tools = tools_env
    day = tools._today()
    st = TodoStore(tools.cfg)
    st.add({"id": "s1", "board": "sleep", "when": "22:00", "title": "关灯", "kind": "done"}, day)
    st.add({"id": "s2", "board": "life", "when": "14:45", "title": "喝水", "kind": "done"}, day)
    now = v3.page_doc(tools, "now")
    assert [t["title"] for t in now["todos"]] == ["喝水", "关灯"] and now["more"] == [] and now["hidden"] == 0
    sleep = v3.page_doc(tools, "sleep")
    assert [t["title"] for t in sleep["todos"]] == ["关灯"] and sleep["more"] == []
