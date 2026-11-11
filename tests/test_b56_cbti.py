"""build 56：CBT-I 看板由 P-Health 用生成式 UI 拼（内核现算 facts.cbti + cbti.* 绑定），此刻页按时段挑「现在最该做的事」。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from pivis_health import canvas, cbti, v3
from test_canvas_parts import DAY, NOW, env  # noqa: F401  合成数据 + 一个 CBT-I 项目（08:30 起床、01:30 后上床）

CN = ZoneInfo("Asia/Shanghai")


def test_state_from_project_memory_and_device(env):  # noqa: F811
    st = cbti.state(env, DAY, NOW)
    assert st["project"]["id"] == "cbti" and st["project"]["week"] == 2 and st["project"]["weeks"] == 6
    assert st["phase"] == "适应期"                                   # 头两周
    assert st["rx"] == {"wake": "08:30", "earliest_bed": "01:30", "window_h": 7.0,
                        "caffeine_cutoff": "17:30", "winddown": "00:30"}
    assert st["efficiency"]["median_7n"] == 93 and st["efficiency"]["bands"]["ge90"] == 7
    # 合成的每晚都是 23:20 睡、06:20 起：比 01:30 早上床，起床不晚
    adh = st["adherence"]
    assert adh["early_bed"] == 7 and adh["late_rise"] == 0 and adh["kept"] == 0 and adh["nights"] == 7
    assert st["level"] == "act"                                     # 这周破例 ≥3
    assert st["review"]["suggest"] == "不变" and st["review"]["reason"] == "先把执行做到"
    assert st["last_night"]["in_bed_h"] == 7.6 and st["last_night"]["awake_in_bed_min"] > 0
    assert st["tonight"]["to_bed_text"] == "4:20"                   # 21:10 → 01:30
    assert [w["week"] for w in st["weeks"]] == [1, 2]


def test_no_project_no_state(tools_env):
    assert cbti.state(tools_env) is None
    assert "cbti" not in v3.facts(tools_env, v3.day_of(tools_env._now()))


def test_binds_resolve(env):  # noqa: F811
    lay = canvas.validate({"t": "v", "gap": 12, "children": [
        {"t": "h", "justify": "between", "align": "baseline", "children": [
            {"t": "value", "bind": "cbti.efficiency", "size": "xl"}, {"t": "stat", "bind": "cbti.kept", "label": "守住窗口"}]},
        {"t": "chart", "metric": "sleep_efficiency", "kind": "trend", "days": 7, "height": "s"},
        {"t": "stack", "bind": "cbti.lastnight"},
        {"t": "table", "bind": "cbti.weeks"},
    ]}, "chat")
    r = canvas.resolve(env, lay, DAY, NOW, "sleep")
    row, chart, stack, table = r["children"]
    assert row["children"][0]["text"] == "93" and row["children"][0]["unit"] == "%"
    assert row["children"][1]["text"] == "0" and row["children"][1]["unit"] == "/ 7 晚"
    vz = chart["viz"]
    assert vz["band"] == [90, 100] and vz["warn"] == 85
    assert vz["band_label"] == "≥90 加窗口" and vz["warn_label"] == "<85 减窗口"
    assert stack["title"] == "在床 7.6 小时" and [i["label"] for i in stack["items"]] == ["睡着", "醒着"]
    assert table["columns"] == ["", "窗口", "效率", "调整"] and table["rows"][-1][0] == "第 2 周"


def test_cbti_binds_need_project(tools_env):
    lay = canvas.validate({"t": "v", "children": [{"t": "value", "bind": "cbti.efficiency", "size": "xl"}]}, "chat")
    r = canvas.resolve(tools_env, lay, DAY, NOW, "sleep")
    assert r["children"][0].get("fallback")                         # 没在做 CBT-I：这一格说明算不出来，不挂


@pytest.mark.parametrize("hm,name,rest", [("07:30", "早上", False), ("11:20", "白天", False), ("12:40", "午休", True),
                                          ("16:00", "下午", False), ("19:00", "傍晚", False), ("21:30", "晚上", True),
                                          ("02:00", "晚上", True)])
def test_slots(hm, name, rest):
    h, m = map(int, hm.split(":"))
    s = v3.slot_of(datetime(2026, 11, 5, h, m, tzinfo=CN))
    assert s["name"] == name and s["rest_ok"] is rest


def _doc(board: str, layout: dict | None = None, viz: dict | None = None) -> dict:
    hero = {"level": "steady", "board": board, "label": "指标"}
    if layout:
        hero["layout"] = layout
    if viz:
        hero["viz"] = viz
    return {"headline": {"text": "去走一走"}, "hero": hero}


EFF = {"t": "v", "children": [{"t": "value", "bind": "cbti.efficiency", "size": "xl"}]}


def test_now_page_keeps_rest_for_noon_and_night():
    morning = {"slot": v3.slot_of(datetime(2026, 11, 5, 9, 0, tzinfo=CN))}
    night = {"slot": v3.slot_of(datetime(2026, 11, 5, 21, 0, tzinfo=CN))}
    with pytest.raises(ValueError, match="此刻页不放休息"):
        v3.validate_page("now", _doc("sleep", EFF), morning)
    assert v3.validate_page("now", _doc("sleep", EFF), night)["hero"]["board"] == "sleep"
    assert v3.validate_page("now", _doc("sleep", EFF), morning, strict=False)["hero"]["board"] == "sleep"   # 最后一次放行
    assert v3.validate_page("now", _doc("sport", {"t": "v", "children": [{"t": "value", "bind": "steps", "size": "xl"}]}),
                            morning)["hero"]["board"] == "sport"


def test_cbti_bans_sleep_debt_on_rest_page():
    facts = {"cbti": {"level": "steady"}, "viz": {"sleep_debt": {"ok": True, "board": "sleep", "value_text": "10.0"}}}
    with pytest.raises(ValueError, match="在做 CBT-I"):
        v3.validate_page("sleep", _doc("sleep", viz={"metric": "sleep_debt"}), facts)
    for bad in ({"t": "value", "bind": "sleep_debt", "size": "xl"}, {"t": "diverging", "bind": "sleep.need", "days": 7},
                {"t": "columns", "metric": "sleep", "days": 7}, {"t": "dots", "bind": "sleep.nights", "days": 7}):
        with pytest.raises(ValueError, match="在做 CBT-I"):
            v3.validate_page("sleep", _doc("sleep", {"t": "v", "children": [bad]}), facts)
    ok = {"t": "v", "children": [{"t": "value", "bind": "cbti.efficiency", "size": "xl"},
                                 {"t": "chart", "metric": "sleep_efficiency", "kind": "trend", "days": 7, "height": "s"},
                                 {"t": "stack", "bind": "cbti.lastnight"}]}
    assert v3.validate_page("sleep", _doc("sleep", ok), facts)["hero"]["layout"]
    # 没在做 CBT-I：睡眠债照常能用
    assert v3.validate_page("sleep", _doc("sleep", {"t": "v", "children": [{"t": "value", "bind": "sleep_debt", "size": "xl"}]}),
                            {})["hero"]["layout"]


def test_countdown_to_earliest_bed(env):  # noqa: F811
    lay = canvas.validate({"t": "v", "children": [{"t": "countdown", "to": "cbti.bed", "label": "离最早上床还有"},
                                                  {"t": "time_range", "bind": "project:cbti"}]}, "chat")
    cd, tr = canvas.resolve(env, lay, DAY, NOW, "sleep")["children"]
    assert cd["to"] == "01:30" and cd["text"] == "4:20" and cd["sub"] == "到 01:30"
    assert "01:30" in tr["text"]


def test_hero_layout_drops_explanations():
    lay = {"t": "v", "children": [{"t": "value", "bind": "cbti.efficiency", "size": "xl"},
                                  {"t": "text", "text": "在床的时间对上睡着的时间", "role": "caption"},
                                  {"t": "text", "text": "效率中位", "role": "label"}]}
    out = v3.validate_page("sleep", _doc("sleep", lay), {"cbti": {"level": "steady"}})["hero"]["layout"]
    assert [k.get("text") for k in out["children"] if k["t"] == "text"] == ["效率中位"]


def test_review_day_table_and_no_duplicate_week():
    st = {"review": {"today": True, "in_days": 0},
          "weeks": [{"week": 1, "window_h": 7.5, "median": 92, "decision": "+15"},
                    {"week": 2, "window_h": 7.75, "median": 92, "decision": "+15"},
                    {"week": 3, "window_h": 8.0, "median": 88, "decision": None}]}
    rows = cbti.weeks_table(st)["rows"]
    assert rows[-1] == ["第 3 周", "8h", "88%", "今天"] and rows[0][3] == "+15分"
    lay = {"t": "v", "children": [{"t": "value", "text": "第 4 周", "unit": "/ 6 周"},
                                  {"t": "segments", "text": "第 4 周", "sub": "/ 6 周", "label": "CBT-I", "total": 6, "done": 3.0}]}
    out = v3._drop_dup_parts(lay, "CBT-I")
    assert [k["t"] for k in out["children"]] == ["segments"] and out["children"][0]["label"] == ""


def test_sleep_prefs_pause_during_cbti(tools_env):
    from pivis_health.agent_context import AgentContextStore
    lay = {"t": "v", "children": [{"t": "columns", "metric": "sleep", "days": 7}]}
    store = AgentContextStore(tools_env.cfg)
    store.record("pref.page.sleep", {"rule": "休息页主卡用竖柱看睡眠", "layout": lay})
    store.record("pref.page.sport", {"rule": "运动页主卡用竖柱看步数"})
    rules, confirmed, paused = v3.prefs_for_page(tools_env.cfg, "sleep", {"cbti": {"level": "watch"}})
    assert paused and confirmed is None and rules == ["运动页主卡用竖柱看步数"]
    rules, confirmed, paused = v3.prefs_for_page(tools_env.cfg, "sleep", {})
    assert not paused and confirmed["layout"] == lay and "休息页主卡用竖柱看睡眠" in rules


def test_tidy_puts_stats_in_a_row():
    stat = lambda n: {"t": "stat", "label": n, "text": "1", "unit": "晚"}
    lay = {"t": "v", "children": [{"t": "rule"}, {"t": "value", "text": "5"}, {"t": "rule"}, {"t": "rule"},
                                  stat("早上床"), stat("起晚"), stat("起床偏差"), {"t": "rule"}]}
    out = v3._tidy_layout(lay)
    assert [k["t"] for k in out["children"]] == ["value", "rule", "h"]
    assert [k["label"] for k in out["children"][2]["children"]] == ["早上床", "起晚", "起床偏差"]
    assert out["children"][2]["justify"] == "between"


def test_now_page_not_same_as_board_page(tools_env):
    lay = {"t": "v", "children": [{"t": "value", "bind": "cbti.kept", "size": "l"}, {"t": "sleep_window", "days": 7}]}
    v3.V3PageStore(tools_env.cfg).save("sleep", {"hero": {"board": "sleep", "label": "守窗口", "layout": lay}})
    with pytest.raises(ValueError, match="此刻页和休息页的主卡一样了"):
        v3._check_not_same_as_board(tools_env, "now", {"hero": {"board": "sleep", "label": "守窗口", "layout": lay}})
    tonight = {"t": "v", "children": [{"t": "countdown", "to": "cbti.bed"}, {"t": "time_range", "bind": "project:cbti"}]}
    v3._check_not_same_as_board(tools_env, "now", {"hero": {"board": "sleep", "label": "今晚", "layout": tonight}})


def test_card_check_text_budget_and_cbti_words():
    from pivis_health import cards
    card = '```phealth-ui\n{"type":"list","title":"接下来","items":["醒了能睡回去就继续睡"]}\n```'
    ok = "昨晚守住了窗口，今晚照旧。\n" + card
    assert cards.check_text(ok, cbti_active=True)["ok"]
    long = "判断先说：" + "这不是失眠，" * 20 + "\n" + card
    res = cards.check_text(long)
    assert not res["ok"] and "卡片外的文字" in res["problems"][0]
    debt = "昨晚睡 7 小时、需要 8 小时。\n" + card
    assert not cards.check_text(debt, cbti_active=True)["ok"]
    assert cards.check_text(debt, cbti_active=False)["ok"]
    assert cards.check_text("醒了别补觉也别早上床。\n" + card, cbti_active=True)["ok"]           # 劝「别补觉」不算
    assert not cards.check_text("今天中午补觉一小时。\n" + card, cbti_active=True)["ok"]
    assert cards.check_text("不补觉，照常起床。\n" + card, cbti_active=True)["ok"]
