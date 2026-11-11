"""对话卡片检查：坏 JSON、App 画不了的 type、缺字段、占位地址；常见笔误给出修好的 JSON；服务器记坏卡片。"""
from __future__ import annotations

import json

from pivis_health import cards

# 11-06 18:50 让 App 打开对话就闪退的那张：选择题少写了 "options" 键
BROKEN = '{"type":"question","title":"今晚试哪个","fields":[{"id":"pick","label":"用哪个","type":"options":["A 拉伸视频 15 分钟","B 拉伸+呼吸 15 分钟"]}]}'


def test_missing_options_key_is_repaired():
    obj, err, fixed = cards.parse(BROKEN)
    assert err and "JSON" in err
    assert obj["fields"][0]["options"] == ["A 拉伸视频 15 分钟", "B 拉伸+呼吸 15 分钟"]
    assert cards.check(json.loads(fixed)) == []


def test_trailing_comma_is_repaired():
    obj, err, fixed = cards.parse('{"type":"receipt","change":"今晚起换成身体扫描","remembered":true,}')
    assert obj and err and cards.check(obj) == []


def test_unfixable_json_reports_error():
    obj, err, fixed = cards.parse('{"type":"plan","title":"x" "items":')
    assert obj is None and fixed is None and "JSON" in err


def test_field_level_problems():
    assert "缺 type" in cards.check({"title": "x"})[0]
    assert "画不了" in cards.check({"type": "carousel"})[0]
    q = {"type": "question", "fields": [{"id": "a", "type": "options"}, {"id": "b", "type": "scale"}, {"type": "date"}]}
    probs = " ".join(cards.check(q))
    assert "要写 \"options\"" in probs and "min 和 max" in probs and "缺 id" in probs and "不认识" in probs
    assert cards.check({"type": "media", "kind": "audio", "url": "<media-library 里的 url>"})
    assert cards.check({"type": "media", "kind": "audio", "url": "/media/sleep-audio/a.m4a"}) == []
    assert cards.check({"type": "chart", "points": [{"label": "a", "value": "6.5"}]})
    assert cards.check({"type": "receipt", "change": "改了", "effective": "今晚起"}) == []


def test_layout_uses_canvas_validator():
    assert cards.check({"type": "layout", "layout": {"t": "v", "children": [{"t": "value", "bind": "sleep", "size": "xl"}]}}) == []
    assert "layout 不合规范" in cards.check({"type": "layout", "layout": {"t": "v", "children": [{"t": "nope"}]}})[0]


def test_check_text_whole_reply():
    good = '好的。\n```phealth-ui\n{"type":"receipt","change":"今晚起换成身体扫描"}\n```\n'
    assert cards.check_text(good) == {"ok": True, "cards": [{"index": 1, "type": "receipt", "ok": True, "problems": []}], "count": 1,
                                      "problems": [], "outside_chars": 3}
    res = cards.check_text(good + "再选一个：\n```phealth-ui\n" + BROKEN + "\n```")
    assert res["ok"] is False and res["cards"][1].get("fixed")
    res = cards.check_text('```phealth-ui\n{"type":"receipt","change":"x"}')   # 没收尾
    assert res["ok"] is False and "收尾" in res["cards"][0]["problems"][0]
    assert cards.check_text("没有卡片")["count"] == 0


def test_log_broken_once(tmp_path):
    msgs = [{"role": "phealth", "time": "2026-11-06T18:50", "text": "```phealth-ui\n" + BROKEN + "\n```"},
            {"role": "phealth", "time": "2026-11-06T18:51", "text": "```phealth-ui\n{\"type\":\"receipt\",\"change\":\"x\"}\n```"},
            {"role": "me", "time": "2026-11-06T18:52", "text": "```phealth-ui\n{bad\n```"}]
    assert cards.log_broken(tmp_path, msgs) == 1
    assert cards.log_broken(tmp_path, msgs) == 0          # 轮询再读到不重复记
    rec = json.loads((tmp_path / "card_errors.jsonl").read_text(encoding="utf-8").strip())
    assert rec["message_time"] == "2026-11-06T18:50" and rec["problems"][0]["auto_fixable"] is True
