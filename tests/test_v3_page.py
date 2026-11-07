"""v3 主卡校验：一页一个问题、字段/小表的数字只能来自 facts、不再有「数据不足」主卡。"""
from __future__ import annotations

import pytest

from pivis_health.v3 import validate_page

FACTS = {"last_night": {"slept_h": 5.5, "need_h": 9.9, "short_h": 4.4},
         "sleep_nights": [{"night_of": "2026-10-29", "slept_h": 5.8, "need_h": 9.0},
                          {"night_of": "2026-10-30", "slept_h": 5.5, "need_h": 9.9}],
         "hrv_trend": {"last3_avg": 32.7, "prev_avg": 39.6, "change_pct": -17.0, "days": 12}}


def _doc(**hero):
    base = {"level": "act", "board": "sleep", "label": "昨晚睡眠", "value": "5.5", "unit": "小时"}
    base.update(hero)
    return {"headline": {"text": "今晚提前上床，别再欠了"}, "hero": base}


def test_fields_with_fact_numbers_pass():
    out = validate_page("sleep", _doc(fields=[{"label": "需要", "value": "9.9", "unit": "小时"},
                                              {"label": "缺", "value": "4.4", "unit": "小时"}]), FACTS)
    assert [f["label"] for f in out["hero"]["fields"]] == ["需要", "缺"]
    assert out["details"] == [] and out["hero"]["others"] == []


def test_table_first_column_free_other_cells_checked():
    ok = _doc(table={"columns": ["", "睡了", "需要"], "rows": [["10-29", "5.8", "9.0"], ["10-30", "5.5", "9.9"]]})
    assert validate_page("sleep", ok, FACTS)["hero"]["table"]["rows"][0][0] == "10-29"
    bad = _doc(table={"columns": ["", "睡了"], "rows": [["10-29", "6.4"]]})
    with pytest.raises(ValueError):
        validate_page("sleep", bad, FACTS)


def test_nodata_and_headline_repeating_value_rejected():
    with pytest.raises(ValueError, match="nodata"):
        validate_page("sleep", _doc(level="nodata"), FACTS)
    doc = _doc()
    doc["headline"]["text"] = "昨晚只睡 5.5 小时"
    with pytest.raises(ValueError, match="重复"):
        validate_page("sleep", doc, FACTS)


def test_fields_and_table_together_rejected_and_negative_change_matches():
    both = _doc(fields=[{"label": "需要", "value": "9.9"}], table={"columns": ["", "睡了"], "rows": [["10-30", "5.5"]]})
    with pytest.raises(ValueError, match="二选一"):
        validate_page("sleep", both, FACTS)
    stress = {"headline": {"text": "最近几天身体绷得有点紧，今晚早点放松"},
              "hero": {"level": "watch", "board": "stress", "label": "HRV 近 3 天", "value": "32.7", "unit": "ms",
                       "fields": [{"label": "之前", "value": "39.6", "unit": "ms"}, {"label": "下降", "value": "17", "unit": "%"}]}}
    assert validate_page("stress", stress, FACTS)["hero"]["level"] == "watch"


# ---- 老大确认过的主卡样子（pref.page.<page>.layout）：发布前代码核对
from pivis_health.v3 import enforce_page_pref  # noqa: E402

SPORT_PREF = {"rule": "运动页主卡用竖柱看步数",
              "layout": {"t": "v", "gap": 12, "children": [{"t": "value", "bind": "steps", "size": "l"},
                                                           {"t": "columns", "metric": "steps", "days": 7, "height": "s"}]}}


def _sport(layout=None, viz=None):
    hero = {"level": "watch", "board": "sport", "label": "恢复", "value": "", "unit": "", "viz": viz,
            "fields": [], "table": None, "layout": layout}
    return {"headline": {"text": "今天多走走"}, "hero": hero}


def test_page_pref_matching_layout_passes_with_text_tweaks():
    tweaked = {"t": "v", "gap": 8, "children": [{"t": "text", "text": "今天走了", "role": "caption"},
                                                {"t": "value", "bind": "steps", "size": "l"},
                                                {"t": "columns", "metric": "steps", "days": 7, "height": "m"}]}
    doc = _sport(layout=tweaked)
    assert enforce_page_pref("sport", doc, SPORT_PREF, FACTS, final=False) is doc


def test_page_pref_mismatch_retries_then_forces_confirmed_layout():
    gauge = _sport(viz={"metric": "recovery", "kind": "gauge"})
    with pytest.raises(ValueError, match="确认过"):
        enforce_page_pref("sport", gauge, SPORT_PREF, FACTS, final=False)
    wrong_days = _sport(layout={"t": "v", "children": [{"t": "value", "bind": "steps"},
                                                       {"t": "columns", "metric": "steps", "days": 14}]})
    with pytest.raises(ValueError):
        enforce_page_pref("sport", wrong_days, SPORT_PREF, FACTS, final=False)
    forced = enforce_page_pref("sport", gauge, SPORT_PREF, FACTS, final=True)
    h = forced["hero"]
    assert h["viz"] is None and h["board"] == "sport" and h["label"] == "今天步数"
    assert [k["t"] for k in h["layout"]["children"]] == ["value", "columns"]
    assert forced["headline"] == gauge["headline"] and forced["pref_forced"] is True


def test_no_page_pref_leaves_doc_alone():
    doc = _sport(viz={"metric": "recovery"})
    assert enforce_page_pref("sport", doc, None, FACTS, final=True) is doc
