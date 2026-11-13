"""测试夹具：合成客观库（真实 schema）+ 合成 WHOOP 快照 + 临时主观库。

隐私纪律：不复制任何真实数据；场景为手工构造（含历史事故复刻）。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# 测试绝不碰真实 DSH 工作区：后台重排关掉，默认工作区指到临时目录（dsh_chat 在 import 时读这两个变量）
import tempfile as _tempfile
os.environ["PIVIS_NO_REPUBLISH"] = "1"
os.environ.setdefault("PIVIS_DSH_CWD", _tempfile.mkdtemp(prefix="pivis-test-ws-"))

CN = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
BASE = date(2026, 10, 28)  # "今天"，周三
HISTORY_DAYS = 40

SCHEMA = """
CREATE TABLE batches (batch_id TEXT PRIMARY KEY, batch_digest TEXT NOT NULL,
                      acknowledgement_json TEXT NOT NULL);
CREATE TABLE evidence_outbox (batch_id TEXT PRIMARY KEY REFERENCES batches(batch_id),
                              acknowledgement_json TEXT NOT NULL, evidence_timestamp TEXT);
CREATE TABLE projection_outbox (local_date TEXT PRIMARY KEY, generation INTEGER NOT NULL);
CREATE TABLE tombstones (device_id TEXT NOT NULL, sample_id TEXT NOT NULL,
                         batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                         PRIMARY KEY (device_id, sample_id));
CREATE TABLE samples (device_id TEXT NOT NULL, sample_id TEXT NOT NULL,
                      batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                      type TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL,
                      unit TEXT NOT NULL, numeric_value REAL, category_value TEXT,
                      PRIMARY KEY (device_id, sample_id));
"""


def utc_iso(local: datetime) -> str:
    return local.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@pytest.fixture(scope="session")
def objective_db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("obj") / "health.sqlite3"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("INSERT INTO batches VALUES('b1','d','{}')")

    def ins(sample_id: str, typ: str, start: datetime, end: datetime | None, unit: str,
            value: float | None = None, category: str | None = None):
        con.execute(
            "INSERT INTO samples VALUES('dev',?,?,?,?,?,?,?,?)",
            (sample_id, "b1", typ, utc_iso(start), utc_iso(end or start), unit, value, category),
        )

    def add_night(d: date, start_h=23, start_m=30, hours=7.5, dual_track=False, with_unspec=True):
        start = datetime.combine(d, time(start_h, start_m), tzinfo=CN)
        end = start + timedelta(hours=hours)
        plan = [("asleep_core", 0.45), ("asleep_deep", 0.20), ("asleep_rem", 0.25), ("awake", 0.10)]
        tracks = [(0, 0)] if not dual_track else [(0, 0), (5, 5)]  # 第二轨整体平移 5 分钟
        for ti, (off_s, off_e) in enumerate(tracks):
            cur = start + timedelta(minutes=off_s)
            span = (end + timedelta(minutes=off_e)) - cur
            for si, (cat, frac) in enumerate(plan):
                seg = span * (frac / 2)  # 每阶段拆 2 段
                for half in range(2):
                    s, e = cur, cur + seg
                    ins(f"sl-{d}-{ti}-{si}-{half}", "sleep_analysis", s, e, "category",
                        category=cat)
                    cur = e
        if with_unspec:
            ins(f"sl-{d}-unspec", "sleep_analysis", start, end, "category",
                category="asleep_unspecified")

    def add_nap(d: date, hour=13, hours=0.5):
        s = datetime.combine(d, time(hour, 0), tzinfo=CN)
        ins(f"nap-{d}", "sleep_analysis", s, s + timedelta(hours=hours), "category",
            category="asleep_core")

    rng = 7
    for back in range(HISTORY_DAYS, -1, -1):
        d = BASE - timedelta(days=back)
        wave = math.sin(back / 3.7) * 4
        hrv = 60 + wave  # 基线 ~60ms
        if back <= 2:
            hrv = 40  # 最近 3 天骤降 → z ≈ -4
        ins(f"hrv-am-{d}", "heart_rate_variability_sdnn",
            datetime.combine(d, time(2, 10), tzinfo=CN), None, "ms", hrv)
        ins(f"hrv-pm-{d}", "heart_rate_variability_sdnn",
            datetime.combine(d, time(14, 10), tzinfo=CN), None, "ms", hrv + 2)
        ins(f"rhr-{d}", "resting_heart_rate",
            datetime.combine(d, time(8, 10), tzinfo=CN), None, "count/min", 60 + math.sin(back) * 2)
        ins(f"resp-{d}", "respiratory_rate",
            datetime.combine(d, time(8, 11), tzinfo=CN), None, "count/min", 16 + math.sin(back / 2) * 0.4)
        ins(f"spo2-{d}", "oxygen_saturation",
            datetime.combine(d, time(8, 12), tzinfo=CN), None, "%", 96.5)
        ins(f"steps-{d}", "step_count", datetime.combine(d, time(9), tzinfo=CN), None,
            "count", 8000 + int(math.sin(back) * 3000))
        ins(f"en-{d}", "active_energy_burned", datetime.combine(d, time(9), tzinfo=CN), None,
            "kcal", 600)
        if back % 7 == 0:
            ins(f"wt-{d}", "body_mass", datetime.combine(d, time(7, 30), tzinfo=CN), None,
                "kg", 90.0 - (HISTORY_DAYS - back) * 0.015)
        if back <= 20 and back != 5:  # 5 那天故意无睡眠（race 场景）
            add_night(d)
        if back == 3:
            add_nap(d)

    # 一晚平行双轨（09-28 事故复刻）；选在常规范围外的日子避免主键冲突
    add_night(BASE - timedelta(days=30), dual_track=True)

    # 运动后心率恢复样本
    wstart = datetime.combine(BASE - timedelta(days=2), time(18, 0), tzinfo=CN)
    wend = wstart + timedelta(hours=1)
    ins("wk-1", "workout", wstart, wend, "workout")
    cur = wstart
    while cur <= wend + timedelta(minutes=10):
        bpm = 150 if cur <= wend else max(70, 150 - (cur - wend).total_seconds() / 60 * 30)
        ins(f"hr-wk-{cur.strftime('%H%M%S')}", "heart_rate", cur, None, "count/min", round(bpm))
        cur += timedelta(seconds=30)

    con.commit()
    con.close()
    return path


@pytest.fixture(scope="session")
def whoop_snapshot(tmp_path_factory) -> Path:
    snap = {"schema_version": 1, "source": "whoop", "pagination_complete": True,
            "coverage_warning": "API分页完整不等于每天有数据",
            "collections": {"recovery": [], "sleep": [], "workout": [], "cycle": []}}
    sleep_ids: dict[date, str] = {}
    for back in range(10, -1, -1):
        d = BASE - timedelta(days=back)
        sid = f"sleep-{d}"
        sleep_ids[d] = sid
        start = datetime.combine(d, time(23, 20), tzinfo=CN)
        end = start + timedelta(hours=7)
        rec_score = 66 if back > 3 else 25  # 最近 3 晚红区（<33）
        snap["collections"]["sleep"].append({
            "id": sid, "cycle_id": back, "start": utc_iso(start), "end": utc_iso(end),
            "timezone_offset": "+08:00", "nap": False, "score_state": "SCORED",
            "score": {
                "stage_summary": {
                    "total_in_bed_time_milli": int(7.6 * 3.6e6),
                    "total_awake_time_milli": int(0.5 * 3.6e6),
                    "total_light_sleep_time_milli": int(3.2 * 3.6e6),
                    "total_slow_wave_sleep_time_milli": int(1.4 * 3.6e6),
                    "total_rem_sleep_time_milli": int(1.8 * 3.6e6),
                    "sleep_cycle_count": 5, "disturbance_count": 2,
                },
                "sleep_needed": {
                    "baseline_milli": int(7.5 * 3.6e6),
                    "need_from_sleep_debt_milli": int(0.5 * 3.6e6),
                    "need_from_recent_strain_milli": int(0.3 * 3.6e6),
                    "need_from_recent_nap_milli": 0,
                },
                "respiratory_rate": 15.8,
                "sleep_performance_percentage": 85.0,
                "sleep_consistency_percentage": 60.0,
                "sleep_efficiency_percentage": 93.0,
            },
        })
        snap["collections"]["recovery"].append({
            "cycle_id": back, "sleep_id": sid, "created_at": utc_iso(end + timedelta(minutes=30)),
            "updated_at": utc_iso(end + timedelta(minutes=30)), "score_state": "SCORED",
            "score": {
                "user_calibrating": False, "recovery_score": float(rec_score),
                "resting_heart_rate": 58.0, "hrv_rmssd_milli": 45.0,
                "spo2_percentage": 96.0, "skin_temp_celsius": 33.4,
            },
        })
        snap["collections"]["cycle"].append({
            "id": back, "start": utc_iso(datetime.combine(d, time(16), tzinfo=CN)),
            "end": utc_iso(datetime.combine(d + timedelta(days=1), time(4), tzinfo=CN)),
            "timezone_offset": "+08:00", "score_state": "SCORED",
            "score": {"strain": 10.0 + (5 if back <= 6 else 0), "kilojoule": 9000.0,
                      "average_heart_rate": 80, "max_heart_rate": 170},
            "step_count": 9000,
        })
    path = tmp_path_factory.mktemp("whoop") / "whoop-snapshot.json"
    path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def tools_env(tmp_path, monkeypatch, objective_db, whoop_snapshot):
    data_dir = tmp_path / "runtime"
    monkeypatch.setenv("PIVIS_HEALTH_VAULT_DB", str(objective_db))
    monkeypatch.setenv("PIVIS_HEALTH_WHOOP_SNAPSHOT", str(whoop_snapshot))
    monkeypatch.setenv("PIVIS_HEALTH_DATA_DIR", str(data_dir))
    monkeypatch.delenv("PIVIS_HEALTH_CONFIG", raising=False)
    from pivis_health.config import load_config
    from pivis_health.tools import HealthTools
    return HealthTools(load_config())



@pytest.fixture(autouse=True)
def _no_real_workspace(tmp_path_factory, monkeypatch):
    """测试绝不碰真实 DSH 工作区：工作区目录换成临时目录（偏好段、全盘简报都写在工作区里）。"""
    from pivis_health import dsh_chat
    ws = tmp_path_factory.mktemp("dsh-ws")
    (ws / "AGENTS.md").write_text("# 测试工作区\n", encoding="utf-8")
    monkeypatch.setattr(dsh_chat, "DSH_CWD", str(ws))
    monkeypatch.setattr(dsh_chat, "SESSIONS_DIR", ws / "sessions")     # 也不读真实的对话记录
