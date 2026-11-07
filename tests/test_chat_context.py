"""App 带着习惯 / 待办发消息：正文前一行【习惯 id · 名字】或【待办 id · 标题】；读历史时拆成 context，正文不带标记。"""
from __future__ import annotations

import json

import pytest

from pivis_health import dsh_chat


def test_split_context():
    assert dsh_chat.split_context("【习惯 strength · 力量训练】\n周四改周五吧") == (
        "周四改周五吧", {"kind": "habit", "id": "strength", "name": "力量训练"})
    assert dsh_chat.split_context("【待办 cbti-2026-11-19-flow · 睡前拉伸】今晚改 23:00") == (
        "今晚改 23:00", {"kind": "todo", "id": "cbti-2026-11-19-flow", "name": "睡前拉伸"})
    assert dsh_chat.split_context("今天睡得怎么样") == ("今天睡得怎么样", None)
    assert dsh_chat.split_context("我说【习惯 x · y】不在开头")[1] is None


def test_history_carries_context(tmp_path, monkeypatch):
    zstandard = pytest.importorskip("zstandard")
    sdir = tmp_path / "phealth-sport"
    sdir.mkdir()
    lines = [
        {"type": "user/message", "time": 1794000000000,
         "data": {"content": [{"type": "text", "text": "【习惯 strength · 力量训练】\n周四改周五吧"}]}},
        {"type": "assistant/message", "time": 1794000005000,
         "data": {"message": {"content": [{"type": "text", "text": "行，B 挪到周五。"}]}}},
    ]
    raw = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines).encode()
    (sdir / "session.v4.jsonl.zstd").write_bytes(zstandard.ZstdCompressor().compress(raw))
    monkeypatch.setattr(dsh_chat, "_session_dir", lambda context="": sdir)
    msgs = dsh_chat.read_messages(10)
    assert msgs[0]["text"] == "周四改周五吧"
    assert msgs[0]["context"] == {"kind": "habit", "id": "strength", "name": "力量训练"}
    assert "context" not in msgs[1]
