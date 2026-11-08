"""build 44 审阅修复的回归测试：刷新死循环、凌晨的卡、项目模板改动、旧模板、健康缓存、编排解析、记忆分类。"""
from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from clips import make_clip
from pivis_health import v3
from pivis_health.config import Config
from pivis_health.todos import TodoError, TodoStore, due_at

D = date(2026, 11, 8)


def _st(tmp_path) -> TodoStore:
    return TodoStore(replace(Config(), data_dir=tmp_path))


def test_reads_do_not_rewrite_the_todo_file(tmp_path):
    """以前每次读页面都重写 todos_v3.json，状态版本号一直变，App 每 15 秒把四页全部重拉"""
    st = _st(tmp_path)
    st.add({"board": "sleep", "date": D.isoformat(), "when": "22:00", "title": "关灯", "kind": "done"}, D)
    before = st.path.stat().st_mtime_ns
    time.sleep(0.01)
    st.materialize(D, datetime(2026, 11, 8, 9, 0))
    st.for_date(D)
    assert st.path.stat().st_mtime_ns == before


def test_due_at_after_midnight():
    assert due_at("2026-11-08", "00:30") == datetime(2026, 11, 9, 0, 30)
    assert due_at("2026-11-08", "22:30") == datetime(2026, 11, 8, 22, 30)


def test_after_midnight_card_not_expired_before_due(tmp_path):
    st = _st(tmp_path)
    st.add({"id": "late", "board": "sleep", "date": D.isoformat(), "when": "00:30", "title": "上床前呼吸", "kind": "done"}, D)
    st.add({"id": "eve", "board": "sleep", "date": D.isoformat(), "when": "21:00", "title": "放下手机", "kind": "done"}, D)
    v3._expire(st, date(2026, 11, 9), datetime(2026, 11, 9, 0, 5))      # 零点刚过：00:30 那张还没到点
    assert st.get("late")["status"] == "scheduled" and st.get("eve")["status"] == "expired"
    v3._expire(st, date(2026, 11, 9), datetime(2026, 11, 9, 3, 0))      # 到点两小时后才收起
    assert st.get("late")["status"] == "expired"


def test_until_after_midnight(tmp_path):
    st = _st(tmp_path)
    st.add({"id": "p", "board": "sleep", "date": D.isoformat(), "title": "今晚早点睡？", "kind": "proposal", "until": "00:30",
            "inputs": [{"id": "x", "type": "options", "options": ["好", "不"]}]}, D)
    v3._expire(st, D, datetime(2026, 11, 8, 23, 0))
    assert st.get("p")["status"] == "proposed"


def test_template_change_keeps_edited_and_progress(tmp_path):
    st = _st(tmp_path)
    now = datetime(2026, 11, 8, 9, 0)
    proj = {"id": "w", "name": "喝水", "board": "life", "start": D.isoformat(), "days": 30,
            "daily": [{"key": "water", "title": "喝水", "kind": "counter", "target": 6, "unit": "杯"},
                      {"key": "walk", "when": "22:40", "title": "散步", "kind": "done"}]}
    st.project_set(proj, D, now)
    st.materialize(D, now)
    st.user_submit("w-2026-11-08-water", "inc", {}, None, None, now)
    st.update("w-2026-11-08-walk", {"when": "23:10"})                    # P-Health 只改了今天这张
    st.project_set({**proj, "rules": ["多喝水"]}, D, now)                   # 模板改版
    st.materialize(D, now)
    assert st.get("w-2026-11-08-water")["record"]["count"] == 1
    assert st.get("w-2026-11-08-walk")["when"] == "23:10"


def test_legacy_template_does_not_block_status_change(tmp_path):
    st = _st(tmp_path)
    with st._locked() as data:      # 11-07 以前建的老项目：模板是子清单
        data["projects"]["old"] = {"id": "old", "name": "睡前流程", "board": "sleep", "start": "2026-11-01", "days": 30,
                                   "status": "active", "revision": 1, "rules": [], "reviews": [],
                                   "daily": [{"key": "c", "title": "睡前流程", "kind": "checklist", "items": ["a", "b"],
                                              "board": "sleep", "date": "2026-11-01"}]}
    p = st.project_set({"id": "old", "status": "paused"}, D)
    assert p["status"] == "paused"
    make_clip(tmp_path, "s1")
    with pytest.raises(TodoError, match="视频"):     # 但新加的模板照样要守规矩
        st.project_set({"id": "old", "daily": [{"key": "x", "title": "拉伸", "kind": "follow",
                                                 "steps": [{"title": "a", "duration_min": 3}]}]}, D)


def test_vault_cache_refreshes_when_db_changes(tools_env):
    t = tools_env
    day = t._now().date()
    first = t._rows(day)
    assert t._rows(day) is first                       # 没变：用缓存
    vault = Path(t.cfg.vault_db)
    os.utime(vault, ns=(vault.stat().st_atime_ns, vault.stat().st_mtime_ns + 10_000_000))
    assert t._rows(day) is not first                   # 库变了（新数据进来）：重读


def test_composer_reply_parsing():
    from pivis_health.publications import _new_assistant_text, _parse_json
    events = [{"type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "我先看看证据。"}]}}},
              {"type": "assistant/message", "data": {"message": {"content": [{"type": "text",
               "text": "好的，下面是结果：\n```json\n{\"headline\": {\"text\": \"x\"}}\n```"}]}}}]
    assert _parse_json(_new_assistant_text(events)) == {"headline": {"text": "x"}}


def test_agent_memory_scopes_whitelisted():
    from pivis_health.agent_context import check_agent_scope
    assert check_agent_scope("learn.habit.late_bath") == "learn.habit.late_bath"
    for bad in ("habit.wearable_off", "ui.sleep.hero", "dialogue.presentation", "random"):
        with pytest.raises(ValueError, match="learn."):
            check_agent_scope(bad)


def test_location_not_synced_and_prefs_red_line_first(tmp_path):
    from pivis_health import prefs
    block = prefs.render_block([{"scope": "pref.media", "payload": {"rule": "睡前用视频"}, "recorded_at": "2026-11-07"}], [])
    assert "红线优先" in block
    assert "profile.home_place" in prefs.SENSITIVE_PROFILE and "profile.travel" in prefs.SENSITIVE_PROFILE


def test_agent_push_disabled(tools_env, capsys):
    from pivis_health import cli
    code = cli.main(["push", "--title", "x", "--body", "y"])
    out = capsys.readouterr().out
    assert code == 1 and "不推送" in out
