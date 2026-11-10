"""build 53：App 发的是北京时间「+08:00」，服务器以前只收「Z」，从 11-08 起健康数据全被拒。这里用 App 实际发出的格式做契约测试。"""
import sqlite3

from pivis_health import ingest


def _db(tmp_path):
    p = tmp_path / "h.sqlite3"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE batches (batch_id TEXT PRIMARY KEY, batch_digest TEXT, acknowledgement_json TEXT)")
    con.execute("CREATE TABLE samples (device_id TEXT, sample_id TEXT, batch_id TEXT, type TEXT, start_at TEXT,"
                " end_at TEXT, unit TEXT, numeric_value REAL, category_value TEXT, PRIMARY KEY (device_id, sample_id))")
    con.commit()
    con.close()
    return p


def test_utc_ts_formats():
    assert ingest.utc_ts("2026-11-10T00:00:00+08:00") == "2026-11-09T16:00:00Z"   # PTime.iso（App 现在发的）
    assert ingest.utc_ts("2026-11-10T07:30:05.123+08:00") == "2026-11-09T23:30:05.123Z"
    assert ingest.utc_ts("2026-11-10T00:00:00+0800") == "2026-11-09T16:00:00Z"
    assert ingest.utc_ts("2026-10-26T00:10:06.309999942Z") == "2026-10-26T00:10:06.309999942Z"   # 老格式原样
    assert ingest.utc_ts("2026-11-10T00:00:00-05:00") == "2026-11-10T05:00:00Z"
    for bad in ("2026-11-10T00:00:00", "2026-11-10", "", None, 5, "昨天"):
        assert ingest.utc_ts(bad) is None


def test_app_payload_is_accepted_and_stored_as_utc(tmp_path):
    db = _db(tmp_path)
    rows = [
        {"sample_id": "hkagg-step_count-20261110", "type": "step_count", "unit": "count", "numeric_value": 4321,
         "start_at": "2026-11-10T00:00:00+08:00", "end_at": "2026-11-11T00:00:00+08:00"},
        {"sample_id": "hkslp-x", "type": "sleep_analysis", "unit": "category", "category_value": "asleep_core",
         "start_at": "2026-11-10T00:40:00+08:00", "end_at": "2026-11-10T02:10:00+08:00"},
    ]
    r = ingest.ingest_samples(db, rows, "iphone-test")
    assert r["accepted"] == 2 and r["rejected"] == 0
    got = dict(sqlite3.connect(db).execute("select sample_id, start_at from samples").fetchall())
    assert got == {"hkagg-step_count-20261110": "2026-11-09T16:00:00Z", "hkslp-x": "2026-11-09T16:40:00Z"}


def test_note_result_tells_rejects_apart(tmp_path):
    s = ingest.note_result(tmp_path, 3, {"accepted": 0, "rejected": 3, "reject_reasons": [{"reason": "bad_timestamp"}]})
    assert s["last_rejected"] == 3 and s["last_reject_reasons"] == ["bad_timestamp"] and "last_accepted_at" not in s
    s = ingest.note_result(tmp_path, 0, {"accepted": 0, "rejected": 0})          # 锁屏后台上报：没有样本，只有心跳
    assert s["last_sent"] == 3 and s["last_upload_at"]
    s = ingest.note_result(tmp_path, 2, {"accepted": 2, "rejected": 0})
    assert s["last_accepted_at"] and ingest.read_state(tmp_path)["last_accepted"] == 2
