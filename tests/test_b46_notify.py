"""build 46：推送放宽（回复 / 待办到点前和到点 / 过点没做 / 新问的卡）、对话里不再冒出 DSH 自己插的话、待办都有时间。"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta

from pivis_health import notify
from pivis_health.config import Config
from pivis_health.todos import TodoStore, normalize

D = date(2026, 11, 8)


class _Sent(list):
    def __call__(self, title, body, data):
        self.append((title, body, data))
        return {"ok": True}


def _asst(text):
    return {"type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": text}]}}}


def _turn(*texts):
    return [{"type": "turn/start"}, *[_asst(t) for t in texts], {"type": "turn/end"}]


def test_reply_pushed_once_per_finished_turn():
    sessions = {"": [], "运动": _turn("老的回复")}
    state: dict = {}
    sent = _Sent()
    notify.replies(state, sent, lambda c: sessions.get(c, []))
    assert sent == []                                            # 第一次只记位置，不补推历史
    sessions["运动"] += _turn("我先看看", "好，今晚 22:00 练膝盖 5 分钟\n```phealth-ui\n{\"type\":\"options\",\"title\":\"今晚练吗\"}\n```")
    sessions["运动"] += [{"type": "turn/start"}, _asst("还在说…")]   # 还没说完的这轮不推
    notify.replies(state, sent, lambda c: sessions.get(c, []))
    assert len(sent) == 1
    title, body, data = sent[0]
    assert title == "P-Health · 运动" and body == "好，今晚 22:00 练膝盖 5 分钟"
    assert data["context"] == "运动" and data["page"] == "sport"
    sessions["运动"] += [{"type": "turn/end"}]
    notify.replies(state, sent, lambda c: sessions.get(c, []))
    assert [b for _, b, _ in sent] == ["好，今晚 22:00 练膝盖 5 分钟", "还在说…"]   # 说完了再推，前面那轮不重复


def test_card_only_reply_says_card_title():
    assert notify.summarize("```phealth-ui\n{\"type\":\"options\",\"title\":\"今晚先做哪个\"}\n```") == "发来一张卡：今晚先做哪个"
    assert notify.summarize("**今晚** 早点睡 " * 30).endswith("…")


def _store(tmp_path) -> TodoStore:
    return TodoStore(replace(Config(), data_dir=tmp_path))


def test_todo_pre_due_and_nudge(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "knee", "board": "sport", "date": D.isoformat(), "when": "22:00", "title": "练膝盖", "kind": "done"}, D)
    st.add({"id": "auto", "board": "sleep", "date": D.isoformat(), "when": "22:00", "title": "上床", "kind": "done",
            "auto": "bedtime"}, D)
    state, sent = {}, _Sent()
    for hm, want in (("21:49", 0), ("21:50", 1), ("21:55", 1), ("22:00", 2), ("22:14", 2), ("22:15", 3), ("22:30", 3)):
        h, m = map(int, hm.split(":"))
        notify.todos(state, sent, st, datetime(2026, 11, 8, h, m))
        assert len(sent) == want, hm
    assert [d["why"] for _, _, d in sent] == ["pre", "due", "nudge"]
    assert sent[0][0] == "练膝盖" and sent[0][1].startswith("10 分钟后 · 22:00")
    assert all(d["todo"] == "knee" and d["page"] == "sport" for _, _, d in sent)      # 自动记的不响


def test_after_midnight_card_and_done_cards(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "late", "board": "sleep", "date": D.isoformat(), "when": "00:30", "title": "关灯上床", "kind": "done"}, D)
    st.add({"id": "did", "board": "life", "date": D.isoformat(), "when": "21:00", "title": "喝水", "kind": "done"}, D)
    st.user_submit("did", "done", {}, None, None, datetime(2026, 11, 8, 20, 0))
    state, sent = {}, _Sent()
    notify.todos(state, sent, st, datetime(2026, 11, 9, 0, 21))        # 第二天凌晨：昨天那张 00:30 的到点前
    notify.todos(state, sent, st, datetime(2026, 11, 8, 20, 55))
    assert [(d["todo"], d["why"]) for _, _, d in sent] == [("late", "pre")]          # 做完的不再提醒


def test_restart_does_not_flood(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "old", "board": "life", "date": D.isoformat(), "when": "09:00", "title": "称体重", "kind": "done"}, D)
    sent = _Sent()
    notify.todos({}, sent, st, datetime(2026, 11, 8, 15, 0))              # 早过了：不补推
    assert sent == []


def test_new_ask_card_pushed_once(tmp_path):
    st = _store(tmp_path)
    st.add({"id": "q", "board": "life", "date": D.isoformat(), "title": "昨天没拍，是为什么", "kind": "options",
            "inputs": [{"id": "x", "type": "options", "options": ["忘了", "没吃"]}]}, D)
    state, sent = {}, _Sent()
    notify.todos(state, sent, st, datetime(2026, 11, 8, 19, 0))
    notify.todos(state, sent, st, datetime(2026, 11, 8, 19, 1))
    assert [(t, b, d["why"]) for t, b, d in sent] == [("P-Health 问你", "昨天没拍，是为什么", "ask")]


def test_tick_first_run_only_records(tmp_path, monkeypatch):
    class T:
        cfg = replace(Config(), data_dir=tmp_path)

        def _now(self):
            return datetime(2026, 11, 8, 21, 55)
    st = TodoStore(T.cfg)
    st.add({"id": "k", "board": "sport", "date": D.isoformat(), "when": "22:00", "title": "练膝盖", "kind": "done"}, D)
    sent = _Sent()
    first = notify.tick(T(), send=sent, events_of=lambda c: [])
    assert first["first"] and sent == []
    second = notify.tick(T(), send=sent, events_of=lambda c: [], now=datetime(2026, 11, 8, 22, 0))
    assert not second["first"] and [d["why"] for _, _, d in sent] == ["due"]          # 第一次记过「到点前」，不补推
    assert json.loads((tmp_path / notify.STATE_FILE).read_text())["sent"]


def test_injected_messages_not_shown_as_mine(monkeypatch):
    from pivis_health import dsh_chat
    ev = [{"type": "user/message", "data": {"source": {"kind": "user"}, "content": [{"type": "text", "text": "发我个视频"}]}},
          {"type": "user/message", "data": {"source": {"kind": "repeat-tool-reminder", "form": "notice"},
                                            "content": [{"type": "text", "text": "You are repeating the exact same tool call"}]}},
          {"type": "user/message", "data": {"content": [{"type": "text", "text": "老格式没有 source"}]}}]
    monkeypatch.setattr(dsh_chat, "_load_events", lambda context="": ev)
    assert [m["text"] for m in dsh_chat.read_messages(context="运动")] == ["发我个视频", "老格式没有 source"]


def test_time_taken_from_title():
    base = {"board": "sleep", "date": D.isoformat(), "kind": "done"}
    assert normalize({**base, "title": "23:15 前洗完澡"})["when"] == "23:15"
    assert normalize({**base, "title": "9:05 吃药"})["when"] == "09:05"
    assert normalize({**base, "title": "喝 2 杯水"})["when"] == ""
    assert normalize({**base, "title": "22:00 练膝盖", "when": "21:45"})["when"] == "21:45"   # 给了 when 就不动


def test_disabled_in_sim(tmp_path):
    assert not notify.enabled(replace(Config(), data_dir=tmp_path, sim_mode=True, apns={"key_path": "x"}))
    assert not notify.enabled(replace(Config(), data_dir=tmp_path, apns={}))


def test_last_reply_time_for_unread_dot(tmp_path, monkeypatch):
    """状态接口里每个对话 P-Health 最后一次回话的时刻：App 拿它亮「没看过的回复」那个点。"""
    from pivis_health import dsh_chat, v3
    (tmp_path / "session.v4.jsonl.zstd").write_bytes(b"x")
    ev = [{"type": "assistant/message", "time": 1794139800000,
           "data": {"message": {"content": [{"type": "text", "text": "好的"}]}}},
          {"type": "assistant/message", "time": 1794139900000, "data": {"message": {"content": [{"type": "tool_use"}]}}}]
    monkeypatch.setattr(dsh_chat, "_session_dir", lambda context="": tmp_path)
    monkeypatch.setattr(dsh_chat, "read_session_events", lambda context="": ev)
    v3._REPLY_CACHE.clear()
    assert v3._last_reply("运动") == "2026-11-08T20:10:00+08:00"      # 只有工具调用的那条不算回话
