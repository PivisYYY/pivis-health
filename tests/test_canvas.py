"""开放画布：零件树校验（规范、文字长度、零件数、估算高度、手写数字）和内核现算。"""
from __future__ import annotations

import pytest

from pivis_health import canvas, v3
from pivis_health.canvas import CanvasError


def test_normalizes_aliases_and_tokens():
    lay = canvas.validate({"type": "vstack", "gap": 13, "children": [
        {"t": "text", "text": "最近几晚都欠觉", "role": "title"},
        {"t": "hstack", "justify": "between", "children": [{"t": "value", "bind": "sleep", "size": "xl"},
                                                            {"t": "stat", "label": "需要", "bind": "sleep.need"}]},
        {"t": "spacer", "size": 22}, {"t": "rule"}]})
    assert lay["t"] == "v" and lay["gap"] == 12
    assert lay["children"][1]["t"] == "h" and lay["children"][1]["justify"] == "between"
    assert lay["children"][2]["size"] == 24


@pytest.mark.parametrize("bad,msg", [
    ({"t": "text", "text": "x" * 19, "role": "title"}, "最多 18"),
    ({"t": "h", "children": [{"t": "rule"}] * 5}, "横排最多 4"),
    ({"t": "value"}, "bind"),
    ({"t": "value", "bind": "mood"}, "不认识"),
    ({"t": "dots", "bind": "hrv"}, "不认识"),
    ({"t": "chart", "metric": "hrv", "kind": "pie"}, "chart"),
    ({"t": "picture", "url": "x"}, "不认识的零件"),
    ({"t": "v", "children": [{"t": "chart", "metric": "hrv", "height": "l"}] * 3}, "超过画布"),
    ({"t": "v", "children": [{"t": "rule"}] * 41}, "零件太多"),
])
def test_rejects_out_of_spec(bad, msg):
    with pytest.raises(CanvasError, match=msg):
        canvas.validate(bad)


def test_handwritten_numbers_must_come_from_evidence():
    pool = [6.7, 9.4, 2.7]
    canvas.validate({"t": "text", "text": "昨晚缺 2.7 小时"}, "hero", pool, v3._has_number)
    with pytest.raises(CanvasError, match="3.5"):
        canvas.validate({"t": "text", "text": "昨晚缺 3.5 小时"}, "hero", pool, v3._has_number)


def test_validate_page_accepts_layout_and_forbids_mixing(monkeypatch):
    evidence = {"facts": {"sleep": 6.7}, "viz": {"sleep": {"ok": True, "board": "sleep"}}}
    doc = {"headline": {"text": "今晚早点睡"},
           "hero": {"level": "act", "board": "sleep", "label": "昨晚睡了",
                    "layout": {"t": "v", "children": [{"t": "value", "bind": "sleep", "size": "xl"}, {"t": "bar", "bind": "sleep"}]}}}
    out = v3.validate_page("sleep", doc, evidence)
    assert out["hero"]["layout"]["children"][0]["bind"] == "sleep" and out["hero"]["value"] == ""
    doc["hero"]["fields"] = [{"label": "需要", "value": "6.7"}]
    with pytest.raises(ValueError, match="layout"):
        v3.validate_page("sleep", doc, evidence)
    doc["hero"].pop("fields")
    doc["hero"]["layout"]["children"].append({"t": "timeline", "n": 2})     # 主卡里放「接下来」会和页面下面重复
    with pytest.raises(ValueError, match="timeline"):
        v3.validate_page("sleep", doc, evidence)


class FakeTools:
    cfg = None

    def _now(self):
        import datetime as dt
        return dt.datetime(2026, 11, 5, 21, 0)


def test_resolve_falls_back_per_part(monkeypatch):
    from pivis_health import viz

    def fake_build(tools, spec, day=None, now=None):
        if spec["metric"] == "hrv":
            raise viz.VizUnavailable("HRV 断了")
        return {"metric": "sleep", "kind": "need", "label": "昨晚睡了", "unit": "小时", "value": 6.7, "value_text": "6.7",
                "zone": "act", "need": 9.4, "nights": [{"night_of": "2026-11-04", "ok": False}]}
    monkeypatch.setattr(viz, "build", fake_build)
    lay = canvas.validate({"t": "v", "children": [{"t": "value", "bind": "sleep"}, {"t": "stat", "label": "HRV", "bind": "hrv"},
                                                  {"t": "bar", "bind": "sleep"}, {"t": "dots", "bind": "sleep.nights"}]})
    out = canvas.resolve(FakeTools(), lay)
    kids = out["children"]
    assert kids[0]["text"] == "6.7" and kids[0]["unit"] == "小时"
    assert kids[1]["t"] == "text" and "算不出来" in kids[1]["text"]          # HRV 断了只影响这一格
    assert kids[2]["left"] == "睡了 6.7 小时" and kids[2]["fraction"] == round(6.7 / 9.4, 3)
    assert kids[3]["caption"] == "近 1 晚 · 1 晚没睡够"


def test_columns_validates_metric_days_and_height():
    n = canvas.validate({"t": "columns", "metric": "steps", "days": 30, "height": "xl"}, "chat")
    assert n == {"t": "columns", "metric": "steps", "days": 14, "height": "s"}
    assert canvas.estimate(n) == canvas.CHART_H["s"] + 36
    with pytest.raises(CanvasError, match="columns 的 metric"):
        canvas.validate({"t": "columns", "metric": "sleep_debt"}, "chat")


def test_columns_resolve_sleep_marks_need_and_steps_goal():
    def vz(metric, kind=None, days=None):
        if metric == "sleep":
            return {"nights": [{"night_of": "2026-11-03", "slept": 7.9, "need": 8.0, "ok": True},
                               {"night_of": "2026-11-04", "slept": 6.7, "need": 9.4, "ok": False}]}
        if kind == "trend":
            return {"series": [{"date": "2026-11-04", "value": 9354}, {"date": "2026-11-05", "value": 6240}]}
        return {"goal": 8000}
    from datetime import date
    s = canvas._columns("sleep", 7, date(2026, 11, 5), vz)
    assert [(i["text"], i["ref"], i["on"]) for i in s["items"]] == [("7.9", 8.0, True), ("6.7", 9.4, False)]
    assert s["ref_label"] == "需要 9.4" and s["max"] == 9.4 and s["caption"] == "近 2 晚 · 1 晚没睡够"
    st = canvas._columns("steps", 7, date(2026, 11, 5), vz)
    assert st["ref"] == 8000 and [i["on"] for i in st["items"]] == [True, False]
    assert st["caption"] == "前 1 天 1 天走够 · 今天还在走"
