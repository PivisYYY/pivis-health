"""App 的待办发送队列：断网时先在本地生效、连上再发，重发的同一个动作只算一次；按点下去的时间记。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from pivis_health.config import Config
from pivis_health.todos import TodoStore
from pivis_health.v3 import _client_now

D = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 10, 0)
TZ = timezone(timedelta(hours=8))


def _st(tmp_path):
    return TodoStore(replace(Config(), data_dir=tmp_path))


def test_same_op_id_counts_once(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "life", "date": D.isoformat(), "title": "喝水", "kind": "counter", "target": 3, "unit": "杯"}, D)
    for _ in range(3):      # 同一次点击因为断网重发了三次
        t = st.user_submit(t["id"], "inc", {}, None, None, NOW, op_id="op-1")
    assert t["record"]["count"] == 1
    t = st.user_submit(t["id"], "inc", {}, None, None, NOW, op_id="op-2")
    assert t["record"]["count"] == 2


def test_timer_restart_is_ignored_for_same_op(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "sleep", "date": D.isoformat(), "when": "13:30", "title": "午睡", "kind": "timer",
                "duration_min": 20, "alarm": "13:50"}, D)
    t = st.user_submit(t["id"], "start", {}, None, None, NOW, op_id="start-1")
    later = st.user_submit(t["id"], "start", {}, None, None, NOW + timedelta(minutes=5), op_id="start-1")
    assert later["record"]["started_at"] == t["record"]["started_at"]


def test_ops_list_is_bounded(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "life", "date": D.isoformat(), "title": "喝水", "kind": "counter", "target": 20, "unit": "杯"}, D)
    for i in range(40):
        t = st.user_submit(t["id"], "inc", {"n": 0}, None, None, NOW, op_id=f"op-{i}")
    assert len(t["ops"]) == 30 and t["ops"][-1] == "op-39"


def test_no_op_id_still_works(tmp_path):
    st = _st(tmp_path)
    t = st.add({"board": "life", "date": D.isoformat(), "title": "喝水", "kind": "counter", "target": 3, "unit": "杯"}, D)
    t = st.user_submit(t["id"], "inc", {}, None, None, NOW)
    t = st.user_submit(t["id"], "inc", {}, None, None, NOW)
    assert t["record"]["count"] == 2 and t["ops"] == []


def test_ops_survive_agent_update_so_retries_stay_deduped(tmp_path):
    """b44：P-Health 改过这张卡之后，App 断网重发的同一个 +1 也不会算两次（以前 update 会丢掉 ops）"""
    st = _st(tmp_path)
    t = st.add({"board": "life", "date": D.isoformat(), "title": "喝水", "kind": "counter", "target": 5, "unit": "杯"}, D)
    st.user_submit(t["id"], "inc", {}, None, None, NOW, op_id="inc-1")
    st.update(t["id"], {"note": "多喝点"})
    t = st.user_submit(t["id"], "inc", {}, None, None, NOW, op_id="inc-1")
    assert t["record"]["count"] == 1


def test_client_time_used_when_recent():
    server = datetime(2026, 11, 6, 17, 30, tzinfo=TZ)
    tapped = "2026-11-06T09:00:00Z"            # 17:00 北京：断网时点的，半小时后才发到
    assert _client_now(server, tapped) == datetime(2026, 11, 6, 17, 0, tzinfo=TZ)


def test_client_time_rejected_when_far_or_future_or_bad():
    server = datetime(2026, 11, 1, 12, 10, tzinfo=TZ)     # 模拟回放的假时钟
    assert _client_now(server, "2026-11-06T09:00:00Z") == server   # 超前好几天
    assert _client_now(server, "2026-10-29T12:00:00+08:00") == server   # 太久以前
    assert _client_now(server, "not a time") == server
    assert _client_now(server, None) == server
    assert _client_now(server, "2026-11-01T12:00:00") == server    # 没有时区
