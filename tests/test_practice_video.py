"""2026-11-07 起：练习只用视频（项目 + 一个 follow 出的片）；做完只认对勾，没有「看了一部分」。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest

from pivis_health.config import Config
from pivis_health.todos import TODO_FORMS, TodoError, TodoStore, normalize

D = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 21, 0)
VIDEO = {"kind": "video", "title": "睡前拉伸 · 8 分钟", "url": "/media/follow/s1/out.mp4", "duration_min": 8}


def _st(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    clip = tmp_path / "follow" / "sessions" / "s1"
    clip.mkdir(parents=True)
    (clip / "out.mp4").write_bytes(b"\0" * 16)
    return TodoStore(cfg)


def test_practice_must_be_one_follow_video(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "sleep", "when": "22:40", "title": "睡前拉伸", "kind": "follow", "media": VIDEO}, D)
    assert len(t["steps"]) == 1 and t["steps"][0]["media"]["kind"] == "video" and t["media"] is None
    assert t["duration_min"] == 8
    for bad in (
        {"steps": [{"title": "靠墙静蹲", "duration_min": 3}, {"title": "臀桥", "duration_min": 3}]},          # 文字步骤
        {"steps": [{"title": "4-7-8 呼吸", "media": {"kind": "audio", "url": "/media/sleep-audio/a.m4a"}}]},  # 纯音频
        {"steps": [{"title": "a", "media": VIDEO}, {"title": "b", "media": VIDEO}]},                          # 两段
        {"media": {"kind": "embed", "url": "https://www.bilibili.com/video/BV1xx411c7mD"}},                 # B 站嵌入
        {"media": {"kind": "video", "url": "https://www.bilibili.com/video/BV1xx411c7mD"}},                 # 公开链接
    ):
        with pytest.raises(TodoError, match="视频"):
            st.add({"board": "sport", "title": "力量", "kind": "follow", **bad}, D)


def make_clip_in(st, ssid):
    d = st.cfg.data_dir / "follow" / "sessions" / ssid
    d.mkdir(parents=True, exist_ok=True)
    (d / "out.mp4").write_bytes(b"\0" * 16)
    return {**VIDEO, "url": f"/media/follow/{ssid}/out.mp4"}


def test_video_file_must_exist(tmp_path):
    st = _st(tmp_path)
    with pytest.raises(TodoError, match="还不在素材库"):
        st.add({"board": "sport", "title": "力量 A", "kind": "follow",
                "media": {**VIDEO, "url": "/media/follow/nope/out.mp4"}}, D)


def test_update_checks_only_when_practice_changes(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "sleep", "when": "22:40", "title": "睡前拉伸", "kind": "follow", "media": VIDEO}, D)
    assert st.update(t["id"], {"when": "23:00"})["when"] == "23:00"
    with pytest.raises(TodoError, match="视频"):
        st.update(t["id"], {"steps": [{"title": "拉伸", "duration_min": 8}]})
    # 只给 media 换视频：替换原来那一段
    other = make_clip_in(st, "s2")
    u = st.update(t["id"], {"media": other})
    assert len(u["steps"]) == 1 and u["steps"][0]["media"]["url"] == "/media/follow/s2/out.mp4"


def test_project_templates_follow_the_rule(tmp_path):
    st = _st(tmp_path)
    ok = {"id": "wind", "name": "睡前放松", "board": "sleep", "start": D.isoformat(), "days": 14,
          "daily": [{"key": "s", "when": "22:40", "title": "睡前拉伸", "kind": "follow", "media": VIDEO}]}
    st.project_set(ok, D, NOW)
    bad = {**ok, "daily": [{"key": "s", "when": "22:40", "title": "睡前流程", "kind": "checklist", "items": ["a", "b"]}]}
    with pytest.raises(TodoError, match="视频"):
        st.project_set(bad, D, NOW)


def test_done_is_the_only_completion(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "sleep", "when": "22:40", "title": "睡前拉伸", "kind": "follow", "media": VIDEO}, D)
    t = st.user_submit(t["id"], "start", {}, None, None, NOW)
    assert t["status"] == "in_progress"
    with pytest.raises(TodoError, match="未知动作"):
        st.user_submit(t["id"], "partial", {"watched_min": 2.5}, None, None, NOW)
    t = st.user_submit(t["id"], "done", {}, None, None, NOW)
    assert t["status"] == "done"


def test_cards_have_one_main_action():
    base = {"board": "sleep", "date": D.isoformat(), "title": "x"}
    assert normalize({**base, "kind": "done"})["verbs"] == ["done"]
    assert normalize({**base, "kind": "timer", "duration_min": 20})["verbs"] == ["start"]
    assert normalize({**base, "kind": "follow", "media": VIDEO})["verbs"] == ["start", "done"]
    assert normalize({**base, "kind": "done", "verbs": ["done", "later", "skip"]})["verbs"] == ["done"]
    ask = next(f for f in TODO_FORMS if f["form"] == "ask")
    assert not any(i.get("allow_text") for i in ask["template"]["inputs"])


def test_nap_timer_still_allowed(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "sleep", "when": "13:30", "title": "午睡 20 分钟", "kind": "timer", "duration_min": 20}, D)
    assert t["kind"] == "timer"
