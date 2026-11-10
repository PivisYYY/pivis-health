"""build 53：P-Health 加的卡不留空时间（拟一个 + 推送请老大确认）、P-Health 能改怎么提醒、推送失败重试、漏推自检、单独的到点提醒。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from pivis_health import notify, timedraft
from pivis_health.config import Config
from pivis_health.todos import TodoError, TodoStore

D = date(2026, 11, 10)


class _Sent(list):
    def __init__(self, ok=True):
        super().__init__()
        self.ok = ok

    def __call__(self, title, body, data):
        self.append((title, body, data))
        return {"ok": self.ok}


def _cfg(tmp_path):
    return replace(Config(), data_dir=tmp_path)


def _store(tmp_path) -> TodoStore:
    st = TodoStore(_cfg(tmp_path))
    st.add({"id": "bed", "board": "sleep", "date": D.isoformat(), "when": "23:30", "title": "上床", "kind": "done",
            "auto": "bedtime", "source": "project"}, D)
    return st


def test_agent_card_without_time_gets_a_draft_from_bedtime(tmp_path):
    st = _store(tmp_path)
    t = st.add({"board": "sleep", "date": D.isoformat(), "title": "灯调暗，手机放远", "kind": "done"}, D,
               datetime(2026, 11, 10, 18, 0))
    assert t["when"] == "22:30" and t["time_draft"] is True and "23:30" in t["draft_why"]
    bath = st.add({"board": "sleep", "date": D.isoformat(), "title": "洗个热水澡", "kind": "done"}, D, datetime(2026, 11, 10, 18, 0))
    assert bath["when"] == "22:00"


def test_time_in_note_is_used_and_question_cards_stay_untimed(tmp_path):
    st = _store(tmp_path)
    t = st.add({"board": "sleep", "date": D.isoformat(), "title": "灯调暗", "note": "22:30 开始，离上床一小时", "kind": "done"}, D)
    assert t["when"] == "22:30" and not t["time_draft"]
    q = st.add({"board": "sport", "date": D.isoformat(), "title": "膝盖跟练有用吗", "kind": "options",
                "inputs": [{"type": "options", "options": ["有用", "没用"]}]}, D)
    assert q["when"] == "" and not q["time_draft"]


def test_draft_already_passed_goes_15_minutes_out(tmp_path):
    st = _store(tmp_path)
    t = st.add({"board": "life", "date": D.isoformat(), "title": "出门走 10 分钟", "kind": "done"}, D,
               datetime(2026, 11, 10, 15, 2))
    assert t["when"] == "15:20" and "过了" in t["draft_why"]
    other = st.add({"board": "life", "date": D.isoformat(), "title": "记一笔", "kind": "done"}, D, datetime(2026, 11, 10, 15, 2))
    assert other["when"] == "15:25"                                     # 同一分钟已有卡：往后挪


def test_confirm_time_and_agent_edit_settle_the_draft(tmp_path):
    st = _store(tmp_path)
    t = st.add({"board": "sleep", "date": D.isoformat(), "title": "灯调暗", "kind": "done"}, D, datetime(2026, 11, 10, 18, 0))
    t2 = st.user_submit(t["id"], "confirm_time", {"when": "23:15"}, None, None, datetime(2026, 11, 10, 18, 1))
    assert t2["when"] == "23:15" and not t2["time_draft"] and "draft_why" not in t2
    u = st.add({"board": "sleep", "date": D.isoformat(), "title": "放下手机", "kind": "done"}, D, datetime(2026, 11, 10, 18, 0))
    assert st.update(u["id"], {"when": "23:20"})["time_draft"] is False
    with pytest.raises(TodoError):
        st.user_submit(u["id"], "confirm_time", {"when": "25:00"}, None, None, datetime(2026, 11, 10, 18, 2))


def test_draft_push_has_buttons_and_reminders_still_fire(tmp_path):
    st = _store(tmp_path)
    t = st.add({"board": "sleep", "date": D.isoformat(), "title": "灯调暗", "kind": "done"}, D, datetime(2026, 11, 10, 18, 0))
    state, sent = {}, _Sent()
    notify.todos(state, sent, st, datetime(2026, 11, 10, 18, 1))
    (title, body, data), = sent
    assert data["why"] == "draft" and data["category"] == "TODO_TIME" and "22:30" in body and "行吗" in body
    notify.todos(state, sent, st, datetime(2026, 11, 10, 18, 2))
    assert len(sent) == 1                                               # 只问一次
    notify.todos(state, sent, st, datetime(2026, 11, 10, 22, 21))
    assert sent[-1][2]["why"] == "pre"                                  # 不回也按拟的时间提醒


def test_agent_controls_how_a_card_reminds(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "a", "board": "sleep", "date": D.isoformat(), "when": "22:00", "title": "洗澡", "kind": "done",
            "remind": {"lead_min": 30, "extra": ["22:20"], "nudge": False}}, D)
    st.add({"id": "b", "board": "sleep", "date": D.isoformat(), "when": "22:00", "title": "吃药", "kind": "done",
            "remind": {"off": True}}, D)
    state, sent = {}, _Sent()
    for hm in ("21:30", "22:00", "22:20", "22:15", "22:40"):
        notify.todos(state, sent, st, datetime(2026, 11, 10, int(hm[:2]), int(hm[3:])))
    assert [(d["todo"], d["why"]) for _, _, d in sent] == [("a", "pre"), ("a", "due"), ("a", "extra2220")]
    with pytest.raises(TodoError):
        st.add({"board": "sleep", "date": D.isoformat(), "when": "22:00", "title": "x", "kind": "done",
                "remind": {"lead": 5}}, D)


def test_failed_push_is_retried_then_given_up(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "k", "board": "sport", "date": D.isoformat(), "when": "21:00", "title": "练膝盖", "kind": "done",
            "remind": {"lead_min": 0, "nudge": False}}, D)
    state, bad = {}, _Sent(ok=False)
    for m in range(4):
        notify.todos(state, bad, st, datetime(2026, 11, 10, 21, m))
    assert len(bad) == 3 and "due:k:2026-11-10:21:00" in state["failed"]
    state2, good = {}, _Sent()
    notify.todos(state2, good, st, datetime(2026, 11, 10, 21, 14))      # 服务停了 14 分钟：到点那条还补
    notify.todos(state2, good, st, datetime(2026, 11, 10, 21, 16))
    assert len(good) == 1


def test_audit_finds_missed_reminders(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "s", "board": "sleep", "date": D.isoformat(), "when": "21:30", "title": "床外拉伸", "kind": "done",
            "created_at": "2026-11-10T08:00:00"}, D)
    missed = notify.audit({}, st, datetime(2026, 11, 10, 22, 0), 15, "America/Los_Angeles")
    assert {m["what"] for m in missed} == {"pre", "due"}
    state = {"sent": {"pre:s:2026-11-10:21:30": "x", "due:s:2026-11-10:21:30": "x"}}
    assert notify.audit(state, st, datetime(2026, 11, 10, 22, 0), 15, "America/Los_Angeles") == []


def test_standalone_reminder(tmp_path):
    cfg = _cfg(tmp_path)
    r = notify.add_reminder(cfg, D.isoformat(), "22:30", "收手机", "放客厅充电", "sleep")
    state, sent = {}, _Sent()
    notify.reminders(state, sent, cfg, datetime(2026, 11, 10, 22, 29))
    notify.reminders(state, sent, cfg, datetime(2026, 11, 10, 22, 31))
    notify.reminders(state, sent, cfg, datetime(2026, 11, 10, 22, 33))
    assert [(t, d["why"]) for t, _, d in sent] == [("收手机", "reminder")] and r["id"]
    with pytest.raises(ValueError):
        notify.add_reminder(cfg, D.isoformat(), "9:30", "x")


def test_audit_skips_cards_done_before_their_time(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "e", "board": "sport", "date": D.isoformat(), "when": "20:30", "title": "腰背放松", "kind": "done",
            "created_at": "2026-11-09T08:00:00"}, D)
    st.user_submit("e", "done", {}, None, None, datetime(2026, 11, 10, 0, 25))
    assert notify.audit({}, st, datetime(2026, 11, 10, 22, 0), 15, "America/Los_Angeles") == []
