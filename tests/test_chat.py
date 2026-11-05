"""聊天通道：身份映射、消息解析、未授权错误、镜像存储。"""
from __future__ import annotations

import json

from pivis_health import chat as chat_mod
from pivis_health.subjective import SubjectiveStore


def _fake_cli(monkeypatch, responses):
    calls = []

    def fake_run(args, timeout=25):
        calls.append(args)
        for key, out in responses.items():
            if key in " ".join(args):
                return out
        return {"ok": False, "error": {"message": "no stub"}}

    monkeypatch.setattr(chat_mod, "_run_cli", fake_run)
    return calls


def test_sender_role_mapping():
    assert chat_mod._sender_role({"id_type": "app_id", "id": "cli_x"}, "ou_me") == "xiaojian"
    assert chat_mod._sender_role({"id_type": "open_id", "id": "ou_me"}, "ou_me") == "me"
    assert chat_mod._sender_role({"id_type": "open_id", "id": "ou_other"}, "ou_me") == "other"
    assert chat_mod._sender_role(None, "ou_me") == "other"


def test_fetch_and_order(monkeypatch):
    raw = {"ok": True, "data": {"messages": [
        {"message_id": "b", "content": "回复", "create_time": "10:00", "deleted": False,
         "message_position": "782", "sender": {"id_type": "app_id", "id": "cli_test_app_0001"}},
        {"message_id": "a", "content": "问题", "create_time": "09:59", "deleted": False,
         "message_position": "781", "sender": {"id_type": "open_id", "id": chat_mod.DEFAULT_USER_OPEN_ID}},
        {"message_id": "x", "content": "已删除", "create_time": "09:58", "deleted": True,
         "message_position": "780", "sender": {"id_type": "app_id", "id": "cli_test_app_0001"}},
    ]}}
    _fake_cli(monkeypatch, {"chat-messages-list": raw})
    msgs = chat_mod.fetch_group_messages("oc_test_group", 10)
    assert [m.message_id for m in msgs] == ["a", "b"]
    assert [m.role for m in msgs] == ["me", "xiaojian"]
    hist = chat_mod.chat_history("oc_test_group", 10)
    assert hist["latest_position"] == 782


def test_incremental_poll_filter(monkeypatch):
    raw = {"ok": True, "data": {"messages": [
        {"message_id": "a", "content": "1", "create_time": "t", "deleted": False,
         "message_position": "781", "sender": {"id_type": "open_id", "id": chat_mod.DEFAULT_USER_OPEN_ID}},
        {"message_id": "b", "content": "2", "create_time": "t", "deleted": False,
         "message_position": "782", "sender": {"id_type": "app_id", "id": "cli_test_app_0001"}},
    ]}}
    _fake_cli(monkeypatch, {"chat-messages-list": raw})
    hist = chat_mod.chat_history("oc_test_group", 10, after_position=781)
    assert [m["message_id"] for m in hist["messages"]] == ["b"]


def test_send_need_auth(monkeypatch):
    _fake_cli(monkeypatch, {"messages-send": {
        "ok": False, "error": {"type": "authentication", "subtype": "token_missing",
                               "message": "need_user_authorization"}}})
    try:
        chat_mod.send_as_user("oc_test_group", "hi")
        raise AssertionError("应当抛 ChatError")
    except chat_mod.ChatError as exc:
        assert exc.kind == "need_auth"
        assert "授权" in str(exc)


def test_send_empty_rejected():
    try:
        chat_mod.send_as_user("oc_test_group", "  ")
        raise AssertionError("空消息应当被拒绝")
    except chat_mod.ChatError:
        pass


def test_mirror_roundtrip(tmp_path):
    s = SubjectiveStore(tmp_path / "c.sqlite3")
    s.chat_mirror_upsert([
        {"message_id": "a", "role": "me", "text": "1", "create_time": "t", "position": 781},
        {"message_id": "b", "role": "xiaojian", "text": "2", "create_time": "t", "position": 782},
        {"message_id": "a", "role": "me", "text": "1", "create_time": "t", "position": 781},
    ])
    hist = s.chat_mirror_history()
    assert [m["message_id"] for m in hist] == ["a", "b"]  # 去重 + 按 position 升序
