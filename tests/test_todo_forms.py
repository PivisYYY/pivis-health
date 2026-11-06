"""待办的新形式：计数、计时、子清单、确认时间，选项加自己写、数值的步长和默认值，项目卡的「上次」。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest

from pivis_health.config import Config
from pivis_health.todos import TodoError, TodoStore, normalize

D = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 10, 0)


def _st(tmp_path):
    return TodoStore(replace(Config(), data_dir=tmp_path))


def test_counter_counts_up_and_finishes(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "life", "date": D.isoformat(), "title": "喝水", "kind": "counter", "target": 3, "unit": "杯"}, D)
    assert t["verbs"] == ["skip"] and t["target"] == 3
    t = st.user_submit(t["id"], "inc", {}, None, None, NOW)
    assert t["record"]["count"] == 1 and t["summary"] == "1 / 3 杯" and t["status"] == "scheduled"
    t = st.user_submit(t["id"], "inc", {"n": 2}, None, None, NOW)
    assert t["status"] == "done"
    with pytest.raises(TodoError, match="target"):
        normalize({"board": "life", "date": D.isoformat(), "title": "喝水", "kind": "counter"})


def test_timer_records_start(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "sleep", "date": D.isoformat(), "when": "13:30", "title": "午睡", "kind": "timer",
                "duration_min": 20, "alarm": "13:50"}, D)
    assert t["verbs"] == ["start", "later", "skip"]
    t = st.user_submit(t["id"], "start", {}, None, None, NOW)
    assert t["status"] == "in_progress" and t["record"]["started_at"].startswith("2026-11-05T10:00")
    with pytest.raises(TodoError, match="duration_min"):
        normalize({"board": "sleep", "date": D.isoformat(), "title": "午睡", "kind": "timer"})


def test_checklist_steps(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "sleep", "date": D.isoformat(), "title": "睡前流程", "kind": "checklist",
                "items": ["写明天", "调暗灯", "手机放外面"]}, D)
    t = st.user_submit(t["id"], "check", {"index": 0}, None, None, NOW)
    assert t["status"] == "in_progress" and t["summary"] == "1 / 3"
    t = st.user_submit(t["id"], "check", {"index": 0, "on": False}, None, None, NOW)
    assert t["status"] == "scheduled" and t["record"]["checked"] == []
    for i in range(3):
        t = st.user_submit(t["id"], "check", {"index": i}, None, None, NOW)
    assert t["status"] == "done"
    with pytest.raises(TodoError, match="没有这一步"):
        st.user_submit(t["id"], "check", {"index": 9}, None, None, NOW)


def test_confirm_and_input_extras():
    t = normalize({"board": "life", "date": D.isoformat(), "when": "08:00", "title": "按医嘱打针", "kind": "confirm"})
    assert t["verbs"] == ["later", "skip"]
    t = normalize({"board": "sleep", "date": D.isoformat(), "title": "起晚了，是什么原因", "kind": "options",
                   "inputs": [{"id": "why", "type": "options", "options": ["没听到闹钟", "别的原因"], "allow_text": True,
                               "submit": "agent"}]})
    assert t["inputs"][0]["allow_text"] is True
    t = normalize({"board": "life", "date": D.isoformat(), "title": "称体重", "kind": "number",
                   "inputs": [{"id": "kg", "type": "number", "unit": "kg", "step": 0.1, "default": "last"}]})
    assert t["inputs"][0]["step"] == 0.1 and t["inputs"][0]["default"] == "last"


def test_last_record_for_project_items(tmp_path):
    st = _st(tmp_path)
    st.project_set({"id": "w", "name": "称重", "board": "life", "start": "2026-11-03", "days": 30,
                    "daily": [{"key": "kg", "when": "07:40", "title": "称体重", "kind": "number",
                               "inputs": [{"id": "kg", "type": "number", "unit": "kg", "default": "last"}]}]},
                   date(2026, 11, 3))
    st.materialize(date(2026, 11, 4))
    st.user_submit("w-2026-11-04-kg", "done", {"kg": 77.6}, None, "77.6 kg", datetime(2026, 11, 4, 7, 45))
    st.materialize(D)
    last = st.last_record(st.get("w-2026-11-05-kg"))
    assert last == {"date": "11/4", "summary": "77.6 kg", "status": "done", "values": {"kg": 77.6}}


def test_every_form_template_is_valid():
    from pivis_health.todos import TODO_FORMS
    assert len(TODO_FORMS) == 14 and len({f["form"] for f in TODO_FORMS}) == 14
    import json
    for f in TODO_FORMS:
        tpl = json.loads(json.dumps(f["template"], ensure_ascii=False).replace("<media-library 里的 url>", "/media/body-scan.m4a"))
        t = normalize({**tpl, "date": D.isoformat()})
        assert t["kind"] == f["kind"], f["form"]
