"""Agent 组件发布：结构、真实数据来源、Session 与持久化校验。"""
from __future__ import annotations

import pytest

from pivis_health.config import Config
from pivis_health.publications import PublicationStore, validate_components
from pivis_health.web import _ensure_now_hero


def _doc():
    return {
        "recovery": 42.0,
        "tiles": {"debt": {"debt_h": 16.3, "avg_h": 6.3, "target_h": 9.6}},
        "chart14": [{"date": "2026-10-31", "actual": 7.12, "need": 10.31}],
        "whoopConfirm": {"pending": False},
        "tonight": {"planSetToday": False},
    }


def _page():
    return [
        {"type": "headline", "kicker": "休息专项", "text": "今晚先补觉", "session": "休息"},
        {"type": "hero_risk", "kicker": "睡眠债", "value": "16.3", "unit": "h",
         "source": "tiles.debt.debt_h", "status": "显著偏高"},
        {"type": "tiles", "items": [
            {"label": "Recovery", "value": "42%", "source": "recovery"},
            {"label": "平均睡眠", "value": "6.3h", "source": "tiles.debt.avg_h"},
            {"label": "今晚计划", "value": "已生成", "note": "由 P-Health 决定"},
        ]},
        {"type": "need_section", "needs": [{
            "need_type": "walk_for_sleep", "title": "走 10 分钟", "specialty": "运动",
            "evidence": "入睡难度偏高且今天尚未运动", "action": "回家后在小区走 10 分钟",
            "window": "现在", "top": True,
        }]},
        {"type": "evidence", "title": "真实记录", "chart": {
            "type": "table", "nights": [{"date": "2026-10-31", "actual": 7.12, "need": 10.31}],
        }},
    ]


def test_agent_can_generate_new_need_outside_rule_pool():
    out = validate_components("sleep", _page(), _doc())
    assert out[3]["needs"][0]["need_type"] == "walk_for_sleep"
    assert out[3]["needs"][0]["action"] == "回家后在小区走 10 分钟"


def test_rejects_fabricated_numeric_value_and_wrong_session():
    doc = _doc()
    bad = _page()
    bad[0]["session"] = "运动"
    with pytest.raises(ValueError, match="session"):
        validate_components("sleep", bad, doc)
    bad = _page()
    bad[1]["value"] = "99.9"
    with pytest.raises(ValueError, match="does not match"):
        validate_components("sleep", bad, doc)
    bad = _page()
    bad[1]["value"] = "16.30001"
    with pytest.raises(ValueError, match="does not match"):
        validate_components("sleep", bad, doc)
    bad = _page()
    bad[1].pop("source")
    with pytest.raises(ValueError, match="requires source"):
        validate_components("sleep", bad, doc)
    bad = _page()
    bad[1]["source"] = "chart14"
    with pytest.raises(ValueError, match="does not match"):
        validate_components("sleep", bad, doc)
    bad = _page()
    doc["headline"] = "没有对应数值"
    bad[1]["source"] = "headline"
    with pytest.raises(ValueError, match="does not match"):
        validate_components("sleep", bad, doc)


def test_numeric_value_can_come_from_text_evidence():
    doc = _doc()
    doc["on_time"] = {"label": "按时上床 0/3 晚"}
    page = _page()
    page[2]["items"][2] = {"label": "按时上床", "value": "0/3", "source": "on_time.label"}
    assert validate_components("sleep", page, doc)[2]["items"][2]["value"] == "0/3"


def test_rejects_structure_and_fake_chart():
    bad = _page()
    bad[2]["items"] = bad[2]["items"] * 2
    with pytest.raises(ValueError, match="exactly 3"):
        validate_components("sleep", bad, _doc())
    for count in (0, 1, 2):
        bad = _page()
        bad[2]["items"] = bad[2]["items"][:count]
        with pytest.raises(ValueError, match="exactly 3"):
            validate_components("sleep", bad, _doc())
    bad = _page()
    bad.pop(2)
    with pytest.raises(ValueError, match="one tiles"):
        validate_components("sleep", bad, _doc())
    bad = _page()
    bad[4]["chart"]["nights"][0]["actual"] = 99.0
    with pytest.raises(ValueError, match="not in evidence"):
        validate_components("sleep", bad, _doc())


def test_relax_items_must_come_from_real_library():
    doc = {"items": [{"id": "breathing-478", "title": "呼吸", "category": "呼吸",
                      "duration_min": 6, "url": "https://example.com"}]}
    out = validate_components("relax", [{"type": "relax_library", "items": [
        {"id": "breathing-478", "reason": "当前适合短练习", "selected": True},
    ]}], doc)
    assert out[0]["relax_items"][0]["url"] == "https://example.com"
    assert "items" not in out[0]
    with pytest.raises(ValueError, match="invalid or duplicate"):
        validate_components("relax", [{"type": "relax_library", "items": [{"id": "invented"}]}], doc)


def test_publication_store_keeps_agent_producer(tmp_path):
    store = PublicationStore(Config(data_dir=tmp_path))
    store.save("sleep", _page(), "composer-session")
    loaded = store.get("sleep")
    assert loaded["producer"] == "P-Health Agent"
    assert loaded["session"] == "composer-session"
    assert loaded["components"][0]["text"] == "今晚先补觉"


def test_normalizes_specialty_alias_duplicate_needs_and_style_shorthand():
    page = _page()
    need = page[3]["needs"][0]
    need["specialty"] = "exercise"
    need["style"] = "glass"
    page[3]["needs"].append(dict(need))
    out = validate_components("sleep", page, _doc())
    assert len(out[3]["needs"]) == 1
    assert out[3]["needs"][0]["specialty"] == "运动"
    assert out[3]["needs"][0]["style"] == {"material": "glass"}


def test_source_path_can_reference_array_items():
    page = _page()
    doc = _doc()
    doc["play"] = {"checks": [{"value": 16.3}]}
    page[1]["source"] = "play.checks[0].value"
    assert validate_components("sleep", page, doc)[1]["value"] == "16.3"


# ---------- 媒体槽位（固定槽位、自由表现）----------

BILI_URL = "https://www.bilibili.com/video/BV1U34y1R7pz/"
AUDIO_URL = "https://www.sleepfoundation.org/sleep-hygiene/healthy-sleep-tips"


def _media_doc():
    doc = _doc()
    doc["media_library"] = [
        {"id": "stretch-bedtime", "title": "睡前轻拉伸（15 分钟）", "duration_min": 15, "url": BILI_URL},
        {"id": "breathing-478", "title": "4-7-8 呼吸法", "duration_min": 6, "url": AUDIO_URL},
    ]
    return doc


def test_media_can_be_the_specialty_big_card():
    page = _page()
    page[1] = {"type": "media", "title": "睡前轻拉伸", "description": "跟练 15 分钟温和拉伸",
               "media_type": "video", "url": BILI_URL}
    out = validate_components("sleep", page, _media_doc())
    assert out[1]["type"] == "media"
    assert out[1]["url"] == BILI_URL
    assert out[1]["media_type"] == "video"


def test_tile_media_slot_does_not_require_numeric_source():
    page = _page()
    page[2]["items"][2] = {"label": "呼吸跟练", "value": "6 分钟",
                           "media_type": "embed", "url": AUDIO_URL}
    out = validate_components("sleep", page, _media_doc())
    assert out[2]["items"][2]["url"] == AUDIO_URL
    # 对比：不带媒体的小卡有数字仍必须给 source
    bad = _page()
    bad[2]["items"][1] = {"label": "平均睡眠", "value": "6.3h"}
    with pytest.raises(ValueError, match="requires source"):
        validate_components("sleep", bad, _media_doc())


def test_need_media_keeps_action_semantics():
    page = _page()
    page[3]["needs"][0].update({"media_type": "audio", "url": AUDIO_URL})
    out = validate_components("sleep", page, _media_doc())
    assert out[3]["needs"][0]["action"] == "回家后在小区走 10 分钟"
    assert out[3]["needs"][0]["media_type"] == "audio"
    bad = _page()
    bad[3]["needs"][0].update({"media_type": "audio", "url": AUDIO_URL})
    bad[3]["needs"][0].pop("action")
    with pytest.raises(ValueError, match="action"):
        validate_components("sleep", bad, _media_doc())


def test_rejects_youtube_media_even_when_present_in_evidence():
    for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"):
        doc = _media_doc()
        doc["media_library"].append({"id": "yt", "title": "境外视频", "url": url})
        page = _page()
        page[1] = {"type": "media", "title": "跟练", "media_type": "video", "url": url}
        with pytest.raises(ValueError, match="cannot use YouTube"):
            validate_components("sleep", page, doc)
    page = _page()
    page[2]["items"][2] = {"label": "跟练", "media_type": "video",
                           "url": "https://youtu.be/dQw4w9WgXcQ"}
    with pytest.raises(ValueError, match="cannot use YouTube"):
        validate_components("sleep", page, _media_doc())


def test_rejects_dual_big_card_missing_big_card_and_media_on_now():
    page = _page()
    page.insert(2, {"type": "media", "title": "拉伸", "media_type": "video", "url": BILI_URL})
    with pytest.raises(ValueError, match="exactly one hero_risk or media"):
        validate_components("sleep", page, _media_doc())
    page = _page()
    page.pop(1)  # 没有大卡同样非法
    with pytest.raises(ValueError, match="exactly one hero_risk or media"):
        validate_components("sleep", page, _media_doc())
    # now 页规则不变：media 不是 now 的合法组件
    now_page = [
        {"type": "headline", "kicker": "当前", "text": "一句话", "session": ""},
        {"type": "hero_status", "kicker": "状态", "label": "恢复", "value": "42%",
         "source": "recovery", "status": "注意", "tone": "amber"},
        {"type": "media", "title": "拉伸", "media_type": "video", "url": BILI_URL},
    ]
    with pytest.raises(ValueError, match="unknown component"):
        validate_components("now", now_page, _media_doc())


def test_now_requires_hero_and_old_publication_gets_structural_fallback():
    doc = {
        "headline": "今晚先补两件事",
        "hero": {"value": 34.3, "unit": "ms", "label": "HRV",
                 "deviation": {"state": "learning"},
                 "range": {"label": "范围学习中"}},
        "needs": [],
    }
    now_page = [
        {"type": "headline", "kicker": "当前判断", "text": "今晚先补两件事", "session": ""},
        {"type": "hero_status", "kicker": "当前状态", "label": "HRV", "value": "34ms",
         "source": "hero.value", "status": "需要关注", "tone": "accent"},
        {"type": "quiet_note", "text": "指标平稳"},
    ]
    assert [c["type"] for c in validate_components("now", now_page, doc)] == [
        "headline", "hero_status", "quiet_note"]

    without_hero = [now_page[0], now_page[2]]
    with pytest.raises(ValueError, match="exactly one hero_status"):
        validate_components("now", without_hero, doc)

    fallback = _ensure_now_hero("now", doc, without_hero)
    assert [c["type"] for c in fallback] == ["headline", "hero_status", "quiet_note"]
    assert fallback[1]["label"] == "HRV"


def test_rejects_illegal_protocol_and_fabricated_media():
    cases = [
        ({"type": "media", "title": "拉伸", "media_type": "video",
          "url": "javascript:alert(1)"}, "http/https"),
        ({"type": "media", "title": "拉伸", "media_type": "audio",
          "url": "ftp://example.com/audio.mp3"}, "http/https"),
        ({"type": "media", "title": "拉伸", "media_type": "video",
          "url": "https://evil.example.com/video"}, "not in evidence"),
        ({"type": "media", "title": "拉伸", "media_type": "image", "url": BILI_URL}, "media_type"),
        ({"type": "media", "title": "拉伸", "url": BILI_URL}, "media_type"),
        ({"type": "media", "media_type": "video", "url": BILI_URL}, "requires title"),
    ]
    for media, pattern in cases:
        page = _page()
        page[1] = media
        with pytest.raises(ValueError, match=pattern):
            validate_components("sleep", page, _media_doc())
    # 小卡/待办的媒体链接同样不得编造
    page = _page()
    page[2]["items"][2] = {"label": "冥想", "media_type": "audio",
                           "url": "https://evil.example.com/audio.mp3"}
    with pytest.raises(ValueError, match="not in evidence"):
        validate_components("sleep", page, _media_doc())
