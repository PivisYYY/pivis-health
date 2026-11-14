"""b61：事件分类不带整份记忆、不预设开车；事件会话按天换新的。"""
from __future__ import annotations

from datetime import datetime

from pivis_health import dsh_chat, event_dispatch
from pivis_health.agent_context import AgentContextStore


def test_event_context_is_short_and_active_only(tools_env):
    st = AgentContextStore(tools_env.cfg)
    st.record("pref.x", {"rule": "旧的"}, source_session="t", reason="t")
    st.record("pref.x", {"rule": "新的"}, source_session="t", reason="t")
    st.record("profile.home_place", {"rule": "住址"}, source_session="t", reason="t")
    ctx = event_dispatch._brief_context(tools_env.cfg)
    rules = [c["rule"] for c in ctx]
    assert "新的" in rules and "旧的" not in rules and "住址" not in rules


def test_event_prompt_has_no_driving_assumption(tools_env, monkeypatch):
    sent = []
    monkeypatch.setattr(dsh_chat, "ensure_session", lambda c: "x")
    monkeypatch.setattr(dsh_chat, "send_message", lambda text, c: sent.append(text) or {"ok": True})
    event_dispatch.send_event_to_agent(tools_env.cfg, {"type": "location"})
    assert "可能驾驶时" not in sent[0] and "不从位置变化" in sent[0]


def test_events_session_rotates_daily():
    sid = dsh_chat._session_id("事件处理")
    assert sid.endswith(datetime.now().strftime("%Y%m%d"))
    assert dsh_chat._session_id("") == dsh_chat.SESSION_MAIN
