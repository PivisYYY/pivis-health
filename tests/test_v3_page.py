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
