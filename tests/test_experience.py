"""客户端对话配置：持久化、结构边界、真实字段映射与样式覆盖。"""
from __future__ import annotations

import pytest

from pivis_health.config import Config
from pivis_health.experience import Experience
from pivis_health.layout import components_for
from pivis_health.subjective import SubjectiveStore


def _doc():
    return {
        "headline": "今晚先补觉",
        "recovery": 42.0,
        "tiles": {
            "debt": {"debt_h": 8.2, "avg_h": 6.1, "target_h": 9.2, "n_nights": 7},
            "latency": {"mean": 3.5, "target": 2},
            "hq": {"score": 4, "n_nights": 7, "nights_pass": 2},
        },
        "tonight": {"target": {"bedtime": "22:40"}},
        "chart14": [{"date": "2026-11-02", "actual": 6.1, "need": 9.2, "short": True}],
        "needs": [],
    }


def test_dialogue_rules_persist_and_leave_audit(tmp_path):
    cfg = Config(data_dir=tmp_path)
    store = SubjectiveStore(cfg.subjective_db)
    exp = Experience(cfg, store)
    added = exp.dialogue_add("休息", "先给一段结论，再给可点选项")
    assert added["index"] == 0
    assert Experience(cfg).dialogue_list("休息")["rules"] == ["先给一段结论，再给可点选项"]
    assert store.entries(kinds=["experience_change"])[-1]["payload"]["kind"] == "dialogue_add"
    exp.dialogue_remove("休息", 0)
    assert exp.dialogue_list("休息")["rules"] == []


def test_ui_override_changes_source_fields_style_not_structure(tmp_path):
    cfg = Config(data_dir=tmp_path)
    exp = Experience(cfg)
    exp.ui_set("sleep", "hero_risk", {
        "source": "recovery",
        "fields": {"kicker": "今晚恢复", "note": "来自 WHOOP"},
        "style": {"corner": 18, "material": "solid", "accent_color": "#AABBCC"},
        "viz_type": "mini_bars",
    }, "客户端对话调整")
    exp.ui_set("sleep", "tiles", {
        "sources": ["debt", "avg_sleep", "bedtime"],
        "items": {"0": {"fields": {"label": "累计缺口"}, "style": {"value_size": 24}}},
    })
    components = components_for("sleep", _doc(), cfg)
    hero = next(c for c in components if c["type"] == "hero_risk")
    tiles = next(c for c in components if c["type"] == "tiles")
    assert hero["value"] == "42" and hero["unit"] == "%"
    assert hero["kicker"] == "今晚恢复" and hero["style"]["material"] == "solid"
    assert hero["viz"] == {"type": "mini_bars", "values": [6.1]}
    assert [i["value"] for i in tiles["items"]] == ["8.2h", "6.1h", "22:40"]
    assert tiles["items"][0]["label"] == "累计缺口"
    assert len(tiles["items"]) == 3


def test_ui_rejects_fake_values_and_extra_cards(tmp_path):
    exp = Experience(Config(data_dir=tmp_path))
    with pytest.raises(ValueError):
        exp.ui_set("sleep", "hero_risk", {"fields": {"value": "100"}})
    with pytest.raises(ValueError):
        exp.ui_set("sleep", "tiles", {"sources": ["recovery", "latency", "hq", "debt"]})
    with pytest.raises(ValueError):
        exp.ui_set("sleep", "hero_risk", {"style": {"corner": 80}})


def test_evidence_can_switch_between_chart_and_table(tmp_path):
    cfg = Config(data_dir=tmp_path)
    Experience(cfg).ui_set("sleep", "evidence", {"chart_type": "table", "fields": {"title": "睡眠明细"}})
    evidence = next(c for c in components_for("sleep", _doc(), cfg) if c["type"] == "evidence")
    assert evidence["title"] == "睡眠明细"
    assert evidence["chart"]["type"] == "table"
    assert evidence["chart"]["nights"][0]["actual"] == 6.1


def test_now_alias_still_uses_today_layout(tmp_path):
    components = components_for("now", {"headline": "当前正常", "needs": []}, Config(data_dir=tmp_path))
    assert components[0]["type"] == "headline"
    assert components[0]["text"] == "当前正常"


def test_selected_source_missing_does_not_become_risk(tmp_path):
    cfg = Config(data_dir=tmp_path)
    Experience(cfg).ui_set("sleep", "hero_risk", {"source": "recovery"})
    doc = _doc()
    doc["recovery"] = None
    hero = next(c for c in components_for("sleep", doc, cfg) if c["type"] == "hero_risk")
    assert hero["value"] == "—" and hero["status"] == "数据未到"
    assert hero["warning"] is False and hero["tone"] == "accent"
