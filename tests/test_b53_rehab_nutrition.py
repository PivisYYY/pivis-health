"""build 53：康复师（伤病档案、疼痛记录、红黄绿灯、进阶 / 退一步）和营养师（目标、手掌份量记饭、范围、日 / 周汇总）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from pivis_health import brief, nutrition, rehab
from pivis_health.agent_context import AgentContextStore
from pivis_health.todos import TodoError, TodoStore

D = date(2026, 11, 10)


def _injury(cfg, **kw):
    return rehab.injury_set(cfg, {"id": "knee-r", "area": "knee", "side": "right", "name": "右膝半月板损伤",
                                  "onset": "2026-11-01", "phase": "load", "limits": ["不深蹲到底"], **kw})


def test_injury_validation_and_phase_history(tools_env):
    cfg = tools_env.cfg
    with pytest.raises(rehab.RehabError):
        rehab.injury_set(cfg, {"id": "Knee R", "area": "knee", "name": "x"})
    with pytest.raises(rehab.RehabError):
        rehab.injury_set(cfg, {"id": "k", "area": "toe", "name": "x"})
    i = _injury(cfg)
    assert i["phase"] == "load" and len(i["phase_history"]) == 1
    i = rehab.injury_set(cfg, {"id": "knee-r", "phase": "strength"})
    assert [h["phase"] for h in i["phase_history"]] == ["load", "strength"] and i["limits"] == ["不深蹲到底"]


def test_pain_lights_and_advice(tools_env):
    cfg = tools_env.cfg
    _injury(cfg)
    assert rehab.light({"activity": 2, "morning_after": 1}, 1) == "green"
    assert rehab.light({"activity": 4, "morning_after": 1}, 1) == "amber"
    assert rehab.light({"activity": 6}, None) == "red"
    assert rehab.light({"activity": 3, "morning_after": 4}, 2) == "red"        # 第二天早上比平时重
    for i in range(6, -1, -1):
        rehab.pain_log(cfg, {"injury": "knee-r", "date": (D - timedelta(days=i)).isoformat(), "rest": 0, "activity": 2, "morning_after": 1})
    s, = rehab.status(cfg, "knee-r", D)
    assert s["last7"]["days_logged"] == 7 and s["last7"]["lights"]["green"] == 7 and s["advice"].startswith("可以进阶")
    rehab.pain_log(cfg, {"injury": "knee-r", "date": D.isoformat(), "activity": 7})
    s, = rehab.status(cfg, "knee-r", D)
    assert s["advice"].startswith("退一步") and s["light_today"] == "red"
    with pytest.raises(rehab.RehabError):
        rehab.pain_log(cfg, {"injury": "knee-r", "activity": 11})
    with pytest.raises(rehab.RehabError):
        rehab.pain_log(cfg, {"injury": "nope", "activity": 1})


def test_pain_card_logs_on_submit(tools_env):
    from pivis_health import v3
    cfg = tools_env.cfg
    _injury(cfg)
    st = TodoStore(cfg)
    with pytest.raises(TodoError):
        st.add({"board": "sport", "when": "21:00", "title": "膝盖打卡", "kind": "fields", "log": {"type": "food"},
                "inputs": [{"id": "rest", "type": "scale", "label": "休息时"}]}, D)
    t = st.add({"board": "sport", "date": D.isoformat(), "when": "21:00", "title": "膝盖打卡", "kind": "fields",
                "log": {"type": "pain", "injury": "knee-r"},
                "inputs": [{"id": "rest", "type": "scale", "label": "休息时疼几分", "min": 0, "max": 10},
                           {"id": "activity", "type": "scale", "label": "练的时候疼几分", "min": 0, "max": 10}]}, D)
    v3.submit(tools_env, t["id"], {"action": "done", "values": {"rest": 1, "activity": 3}})
    row, = rehab.logs(cfg, "knee-r")
    assert row["rest"] == 1 and row["activity"] == 3 and row["source"] == "card"


def test_targets_and_hand_portions(tools_env, monkeypatch):
    cfg = tools_env.cfg
    t = nutrition.targets(tools_env, D)
    assert set(t["missing"]) >= {"性别", "年龄", "身高"} and "kcal_target" not in t
    AgentContextStore(cfg).record("profile.body", {"sex": "male", "age": 35, "height_cm": 178})
    monkeypatch.setattr(nutrition, "_weight", lambda tools, today: (85.0, "2026-11-09"))
    monkeypatch.setattr(nutrition, "_activity", lambda tools, today: (1.375, "近 7 天平均 6000 步"))
    from pivis_health import goals
    goals.set_goal(cfg, {"id": "weight", "title": "减到 75 kg", "metric": "weight", "target": 75}, D)
    t = nutrition.targets(tools_env, D)
    assert t["missing"] == [] and t["goal"] == "减重" and t["bmr"] == 1792          # 10*85 + 6.25*178 - 5*35 + 5
    lo, hi = t["kcal_target"]
    assert 1790 <= lo < hi <= round(1792 * 1.375 * 0.85, -1)
    assert t["protein_g"] == [136, 170] and t["hands_per_day"]["protein_palms"] == 6.0
    _injury(cfg)
    t2 = nutrition.targets(tools_env, D)
    assert t2["injured"] and t2["kcal_target"][0] >= round(1792 * 1.375 * 0.85, -1) - 10   # 有伤：缺口不超过 15%


def test_meal_log_ranges_and_day_week(tools_env, monkeypatch):
    cfg = tools_env.cfg
    monkeypatch.setattr(nutrition, "_weight", lambda tools, today: (85.0, "2026-11-09"))
    with pytest.raises(nutrition.NutritionError):
        nutrition.log(cfg, {"date": D.isoformat(), "meal": "dinner", "portions": {"protein_palms": 1.3}})
    with pytest.raises(nutrition.NutritionError):
        nutrition.log(cfg, {"date": D.isoformat(), "meal": "dinner", "portions": {}})
    r = nutrition.log(cfg, {"date": D.isoformat(), "meal": "lunch", "at": "12:30", "dishes": ["米饭", "鸡腿"],
                            "portions": {"protein_palms": 1, "carb_hands": 2, "veg_fists": 0.5, "fat_thumbs": 1}})
    assert r["est"]["protein_g"] == [24, 39] and r["est"]["kcal"][0] < r["est"]["kcal"][1]
    nutrition.log(cfg, {"date": D.isoformat(), "meal": "dinner", "at": "22:30", "dishes": ["面"],
                        "portions": {"carb_hands": 2, "fat_thumbs": 1}})
    d = nutrition.day_summary(tools_env, D)
    assert len(d["meals"]) == 2 and any("蛋白质不到 25 g" in f for f in d["flags"])
    assert any("离" in f and "上床" in f for f in d["flags"])                     # 22:30 吃，离 23:30 上床 1 小时
    nutrition.log(cfg, {"id": r["id"], "deleted": True, "date": D.isoformat(), "meal": "lunch", "portions": {"protein_palms": 1}})
    assert len(nutrition.entries(cfg, D.isoformat())) == 1
    w = nutrition.week_summary(tools_env, D)
    assert w["days_logged"] == 1 and w["late_dinner_days"] == 1


def test_brief_has_rehab_and_nutrition(tools_env):
    cfg = tools_env.cfg
    _injury(cfg)
    rehab.pain_log(cfg, {"injury": "knee-r", "date": D.isoformat(), "rest": 0, "activity": 2, "morning_after": 1})
    b = brief.build(tools_env, datetime(2026, 11, 10, 20, 0))
    assert "康复（rehab-status 算的" in b["text"] and "右膝半月板损伤（恢复负荷" in b["text"]
    assert "营养目标" in b["text"] and "身高、年龄、性别" in b["text"]
