"""每天三次的场景推荐：按钟点分档，每档每天只发一次，发到主对话。"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

from pivis_health import dsh_chat, v3
from pivis_health.config import Config


def test_slot_by_hour():
    assert v3.slot_for(datetime(2026, 11, 6, 8, 0)) == "morning"
    assert v3.slot_for(datetime(2026, 11, 6, 13, 0)) == "noon"
    assert v3.slot_for(datetime(2026, 11, 6, 18, 0)) == "evening"


def test_each_slot_once_a_day_to_main_chat(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(dsh_chat, "send_message", lambda msg, ctx: sent.append((msg, ctx)))
    now = {"t": datetime(2026, 11, 6, 13, 0)}
    tools = SimpleNamespace(cfg=replace(Config(), data_dir=tmp_path), _now=lambda: now["t"])
    assert v3.daily_review(tools)["status"] == "sent"
    assert v3.daily_review(tools)["status"] == "already"
    msg, ctx = sent[0]
    assert ctx == "" and msg.startswith("【每日推荐】2026-11-06 13:00｜午后") and "daily-recommend" in msg
    now["t"] = datetime(2026, 11, 6, 18, 0)
    assert v3.daily_review(tools)["slot"] == "evening" and len(sent) == 2
    assert v3.daily_review(tools, force=True, slot="noon")["status"] == "sent"
