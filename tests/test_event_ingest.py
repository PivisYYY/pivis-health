"""event_ingest 回归：幂等去重 / 冲突拒绝 / 乱序按真实时间排序 / 原子持久化 / 空字段校验。"""
from __future__ import annotations

import pytest

from pivis_health.event_ingest import (
    EventConflictError,
    EventStore,
    InvalidEventError,
)


def _event(event_id="e-1", type_="heart_rate", occurred_at="2026-11-04T08:00:00Z",
           source="iphone-native", payload=None):
    return {"event_id": event_id, "type": type_, "occurred_at": occurred_at,
            "source": source,
            "payload": payload if payload is not None else {"value": 62, "unit": "count/min"}}


def test_store_and_get_roundtrip(tmp_path):
    payload = {"value": 58.5, "unit": "count/min", "tags": ["resting", "晨起"],
               "meta": {"device": "watch", "fw": "1.2.0"}}  # 扩展字段任意嵌套
    with EventStore(tmp_path / "events.sqlite3") as store:
        result = store.append(_event(payload=payload))
        assert result == {"status": "stored", "event_id": "e-1"}
        got = store.get("e-1")
        assert got["type"] == "heart_rate"
        assert got["occurred_at"] == "2026-11-04T08:00:00Z"  # 真实发生时间原样保留
        assert got["source"] == "iphone-native"
        assert got["payload"] == payload
        assert got["received_at"].endswith("Z")  # 到达时间仅作审计，不参与幂等
        assert store.get("missing") is None


def test_duplicate_delivery_is_idempotent(tmp_path):
    with EventStore(tmp_path / "events.sqlite3") as store:
        assert store.append(_event())["status"] == "stored"
        # 完全相同的重传（至少一次投递）
        assert store.append(_event())["status"] == "duplicate"
        # payload 键序不同也算同一事件（canonical 比较）
        reordered = _event(payload={"unit": "count/min", "value": 62})
        assert store.append(reordered)["status"] == "duplicate"
        # 同一批内重复
        counts = store.append_batch([_event(), _event()])
        assert counts == {"stored": 0, "duplicates": 2, "received": 2}
        assert len(store) == 1
        assert store.get("e-1")["payload"] == {"value": 62, "unit": "count/min"}


@pytest.mark.parametrize("mutate,field", [
    (lambda e: e.update(payload={"value": 63}) or e, "payload"),
    (lambda e: e.update(occurred_at="2026-11-04T09:00:00Z") or e, "occurred_at"),
    (lambda e: e.update(type="step_count") or e, "type"),
    (lambda e: e.update(source="whoop") or e, "source"),
])
def test_same_id_different_content_conflicts(tmp_path, mutate, field):
    with EventStore(tmp_path / "events.sqlite3") as store:
        store.append(_event())
        with pytest.raises(EventConflictError) as ei:
            store.append(mutate(_event()))
        assert ei.value.event_id == "e-1"
        assert field in ei.value.diff_fields
        # 不静默覆盖：原事件保持原样，也没有第二条
        assert len(store) == 1
        assert store.get("e-1")["occurred_at"] == "2026-11-04T08:00:00Z"
        assert store.get("e-1")["payload"] == {"value": 62, "unit": "count/min"}


def test_out_of_order_delivery_sorted_by_occurred_at(tmp_path):
    events = {
        "e-a": _event("e-a", occurred_at="2026-11-04T08:00:00Z"),
        "e-b": _event("e-b", occurred_at="2026-11-04T09:00:00Z"),
        "e-c": _event("e-c", occurred_at="2026-11-04T10:00:00Z"),
    }
    with EventStore(tmp_path / "events.sqlite3") as store:
        for eid in ("e-c", "e-a", "e-b"):  # 乱序到达
            store.append(events[eid])
        # 默认按真实发生时间排序（处理乱序）
        assert [e["event_id"] for e in store.query()] == ["e-a", "e-b", "e-c"]
        # 到达顺序另查可得，两种顺序互不干扰
        assert [e["event_id"] for e in store.query(order_by="received_at")] == \
            ["e-c", "e-a", "e-b"]
        assert [e["event_id"] for e in store.query(ascending=False)] == ["e-c", "e-b", "e-a"]
        # occurred_at 原样保留（未被重写或归一化覆盖）
        assert {e["event_id"]: e["occurred_at"] for e in store.query()} == {
            "e-a": "2026-11-04T08:00:00Z",
            "e-b": "2026-11-04T09:00:00Z",
            "e-c": "2026-11-04T10:00:00Z",
        }


def test_mixed_timezone_offsets_sort_correctly(tmp_path):
    # 09:00+08:00 == 01:00Z，早于 01:30Z；按字符串排会得到相反顺序
    local = _event("e-local", occurred_at="2026-11-04T09:00:00+08:00")
    utc = _event("e-utc", occurred_at="2026-11-04T01:30:00Z")
    with EventStore(tmp_path / "events.sqlite3") as store:
        store.append(utc)
        store.append(local)
        assert [e["event_id"] for e in store.query()] == ["e-local", "e-utc"]
        assert store.get("e-local")["occurred_at"] == "2026-11-04T09:00:00+08:00"


def test_new_instance_reads_persisted_events(tmp_path):
    db = tmp_path / "events.sqlite3"
    with EventStore(db) as first:
        for eid in ("e-1", "e-2"):
            first.append(_event(eid))
        # 第一个实例仍打开时，第二个实例即可读取
        with EventStore(db) as second:
            assert len(second) == 2
    # 全部关闭后重开：数据仍在，且可继续写入 / 幂等
    with EventStore(db) as reopened:
        assert len(reopened) == 2
        assert reopened.get("e-1")["payload"] == {"value": 62, "unit": "count/min"}
        assert reopened.append(_event("e-1"))["status"] == "duplicate"
        assert reopened.append(_event("e-3"))["status"] == "stored"
        assert len(reopened) == 3


def test_batch_is_atomic(tmp_path):
    with EventStore(tmp_path / "events.sqlite3") as store:
        store.append(_event("e-1"))
        # 非法成员：整批拒绝，不留部分写入
        bad = _event("e-2")
        bad["type"] = ""
        with pytest.raises(InvalidEventError):
            store.append_batch([_event("e-2x"), bad])
        assert len(store) == 1
        assert store.get("e-2x") is None
        # 冲突成员：同样整批拒绝，新事件 e-3 也不落库
        with pytest.raises(EventConflictError):
            store.append_batch([_event("e-3"), _event("e-1", payload={"value": 99})])
        assert len(store) == 1
        assert store.get("e-3") is None
        assert store.get("e-1")["payload"] == {"value": 62, "unit": "count/min"}


@pytest.mark.parametrize("field", ["event_id", "type", "occurred_at", "source"])
@pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "blank", "missing"])
def test_empty_fields_rejected(tmp_path, field, value):
    with EventStore(tmp_path / "events.sqlite3") as store:
        event = _event()
        if value is None:
            event.pop(field)
        else:
            event[field] = value
        with pytest.raises(InvalidEventError):
            store.append(event)
        assert len(store) == 0


@pytest.mark.parametrize("bad_ts", [
    "2026/11/04 08:00",       # 非 ISO-8601
    "2026-13-01T00:00:00Z",   # 月份越界
    "2026-11-04T25:00:00Z",   # 小时越界
    "2026-11-04",             # 只有日期
    1730697600,               # 非字符串
])
def test_bad_timestamp_rejected(tmp_path, bad_ts):
    with EventStore(tmp_path / "events.sqlite3") as store:
        with pytest.raises(InvalidEventError):
            store.append(_event(occurred_at=bad_ts))
        assert len(store) == 0


def test_empty_payload_allowed_and_query_filters(tmp_path):
    with EventStore(tmp_path / "events.sqlite3") as store:
        assert store.append(_event("e-1", payload={}))["status"] == "stored"  # 空 payload 合法
        assert store.get("e-1")["payload"] == {}
        store.append(_event("e-2", type_="sleep_analysis", source="whoop"))
        store.append(_event("e-3", type_="sleep_analysis", source="whoop",
                            occurred_at="2026-11-04T07:00:00Z"))
        assert [e["event_id"] for e in store.query(event_type="sleep_analysis")] == \
            ["e-3", "e-2"]
        assert [e["event_id"] for e in store.query(source="whoop", limit=1)] == ["e-3"]
        assert store.query(event_type="step_count") == []


def test_non_serializable_payload_rejected(tmp_path):
    with EventStore(tmp_path / "events.sqlite3") as store:
        with pytest.raises(InvalidEventError):
            store.append(_event(payload={"cb": object()}))
        assert len(store) == 0


def test_log_observation_routes_to_event_store_and_jsonl(tmp_path):
    from pivis_health.ingest import log_observation

    payload = {"device_uuid": "car-01", "device_name": "合成车辆", "state": "connected",
               "ts": "2026-11-04T08:30:00+08:00"}
    first = log_observation(tmp_path, "bluetooth_connected", payload, source="iphone-test")
    second = log_observation(tmp_path, "bluetooth_connected", payload, source="iphone-test")
    assert first["status"] == "stored"
    assert second["status"] == "duplicate"

    with EventStore(tmp_path / "events.sqlite3") as store:
        assert len(store) == 1
        event = store.query(event_type="bluetooth_connected")[0]
        assert event["occurred_at"] == payload["ts"]
        assert event["source"] == "iphone-test"
        assert event["payload"]["device_uuid"] == "car-01"
    assert '"event_id": "' in (tmp_path / "device" / "observations.jsonl").read_text()


def test_log_observation_conflict_is_visible(tmp_path):
    from pivis_health.ingest import log_observation

    base = {"event_id": "evt-conflict", "type": "bluetooth_connected",
            "occurred_at": "2026-11-04T08:30:00Z", "source": "iphone-test",
            "payload": {"state": "connected"}}
    log_observation(tmp_path, base["type"], base["payload"],
                    source=base["source"], event_id=base["event_id"],
                    occurred_at=base["occurred_at"])
    with pytest.raises(EventConflictError):
        log_observation(tmp_path, base["type"], {"state": "disconnected"},
                        source=base["source"], event_id=base["event_id"],
                        occurred_at=base["occurred_at"])
    with EventStore(tmp_path / "events.sqlite3") as store:
        assert store.get("evt-conflict")["payload"]["state"] == "connected"
