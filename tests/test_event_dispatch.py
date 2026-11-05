"""事件分发：按到达顺序、成功才标记、部分失败继续、重启不丢。"""
from __future__ import annotations

from pivis_health.config import Config
from pivis_health.event_dispatch import EventDelivery
from pivis_health.event_ingest import EventStore


def _append(cfg, event_id, minutes=0, state="connected"):
    with EventStore(cfg.data_dir / "events.sqlite3") as store:
        store.append({"event_id": event_id, "type": "bluetooth_connected",
                      "occurred_at": f"2026-11-04T08:{30 + minutes:02d}:00Z",
                      "source": "test", "payload": {"state": state}})


def test_empty_store_has_no_pending_and_dispatch_is_noop(tmp_path):
    delivery = EventDelivery(Config(data_dir=tmp_path))
    assert delivery.pending() == []
    assert delivery.dispatch(lambda event: True) == {"dispatched": 0, "failed": [], "pending": 0}


def test_dispatch_success_marks_and_repeated_dispatch_skips(tmp_path):
    cfg = Config(data_dir=tmp_path)
    _append(cfg, "e-1")
    _append(cfg, "e-2", minutes=1)
    delivery = EventDelivery(cfg)
    sent = []
    result = delivery.dispatch(lambda event: sent.append(event["event_id"]) or True)
    assert result["dispatched"] == 2 and result["failed"] == [] and result["pending"] == 0
    assert sent == ["e-1", "e-2"]
    assert EventDelivery(cfg).pending() == []
    again = EventDelivery(cfg).dispatch(lambda event: True)
    assert again["dispatched"] == 0


def test_failed_send_is_not_marked_and_later_event_can_continue(tmp_path):
    cfg = Config(data_dir=tmp_path)
    _append(cfg, "bad", state="connected")
    _append(cfg, "good", minutes=1, state="disconnected")
    delivery = EventDelivery(cfg)
    calls = []

    def send(event):
        calls.append(event["event_id"])
        return event["event_id"] != "bad"

    result = delivery.dispatch(send)
    assert result["dispatched"] == 1
    assert [f["event_id"] for f in result["failed"]] == ["bad"]
    assert result["pending"] == 1
    assert calls == ["bad", "good"]

    retry = EventDelivery(cfg).dispatch(lambda event: True)
    assert retry["dispatched"] == 1 and retry["pending"] == 0


def test_send_exception_does_not_stop_following_events(tmp_path):
    cfg = Config(data_dir=tmp_path)
    _append(cfg, "boom")
    _append(cfg, "after", minutes=1)
    delivery = EventDelivery(cfg)

    def send(event):
        if event["event_id"] == "boom":
            raise RuntimeError("network down")
        return True

    result = delivery.dispatch(send)
    assert result["dispatched"] == 1
    assert result["failed"][0]["event_id"] == "boom"
    assert "network down" in result["failed"][0]["error"]
    assert result["pending"] == 1  # boom 未标记，after 成功；剩余项留待重试


def test_delivery_state_survives_restart(tmp_path):
    cfg = Config(data_dir=tmp_path)
    _append(cfg, "e-1")
    assert EventDelivery(cfg).dispatch(lambda event: True)["dispatched"] == 1
    reloaded = EventDelivery(Config(data_dir=tmp_path))
    assert reloaded.pending() == []
    _append(cfg, "e-2", minutes=1)
    assert [e["event_id"] for e in reloaded.pending()] == ["e-2"]


def test_limit_only_dispatches_oldest_received_events(tmp_path):
    cfg = Config(data_dir=tmp_path)
    _append(cfg, "e-1")
    _append(cfg, "e-2", minutes=1)
    _append(cfg, "e-3", minutes=2)
    sent = []
    result = EventDelivery(cfg).dispatch(lambda event: sent.append(event["event_id"]) or True,
                                         limit=2)
    assert sent == ["e-1", "e-2"]
    assert result["pending"] == 1
