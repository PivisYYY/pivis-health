"""Build a fully synthetic P-Health demo environment (no real data anywhere).

Writes into <root>:
  demo-vault.sqlite3     Apple Health-style samples for 40 days (one device "iphone-demo")
  demo-whoop.json        WHOOP-style snapshot for the last 14 nights
  config.demo.json       points the kernel at the two files above, its own runtime folder, sim clock
  pivis-health           CLI wrapper for this workspace (own DSH session prefix)
  pivis-runtime/sim_clock.json

Story: someone who has slept a bit short this week, HRV drifting down, plays tennis twice a week,
walks ~8-9k steps, and is slowly heading for a target weight.
用法：python3 examples/make_demo.py <演示目录> [仓库目录，默认本仓库]
然后：<演示目录>/pivis-health viz、page-v3 now、publish-v3 all（要 DSH 上的 P-Health）、serve --port 8944 …
DSH 地址用环境变量 PIVIS_DSH_WEB（默认 http://127.0.0.1:8960）。
"""
import json
import math
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(sys.argv[1]).expanduser().resolve()
REPO = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent
CN = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
TODAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 21, 10, tzinfo=CN)

SCHEMA = """
CREATE TABLE batches (batch_id TEXT PRIMARY KEY, batch_digest TEXT NOT NULL, acknowledgement_json TEXT NOT NULL);
CREATE TABLE evidence_outbox (batch_id TEXT PRIMARY KEY REFERENCES batches(batch_id), acknowledgement_json TEXT NOT NULL, evidence_timestamp TEXT);
CREATE TABLE projection_outbox (local_date TEXT PRIMARY KEY, generation INTEGER NOT NULL);
CREATE TABLE tombstones (device_id TEXT NOT NULL, sample_id TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(batch_id), PRIMARY KEY (device_id, sample_id));
CREATE TABLE samples (device_id TEXT NOT NULL, sample_id TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(batch_id),
  type TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL, unit TEXT NOT NULL, numeric_value REAL, category_value TEXT,
  PRIMARY KEY (device_id, sample_id));
"""


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sleep_hours(back: int) -> float:
    """Nightly sleep: ~7.3 h baseline, the last week a bit short."""
    base = 7.3 + 0.35 * math.sin(back / 2.3)
    if back <= 6:
        base -= 0.6 + 0.15 * (6 - back) / 6
    return round(base, 2)


def bedtime(back: int) -> datetime:
    d = TODAY - timedelta(days=back)
    minutes = 23 * 60 + 35 + int(25 * math.sin(back / 1.7)) + (20 if back <= 6 else 0)
    return datetime.combine(d, time(0, 0), tzinfo=CN) + timedelta(minutes=minutes)


def build_vault(path: Path) -> None:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("INSERT INTO batches VALUES('demo-1','sha1:demo','{\"source\":\"demo\"}')")

    def ins(sid, typ, start, end, unit, value=None, cat=None):
        con.execute("INSERT INTO samples VALUES('iphone-demo',?,?,?,?,?,?,?,?)",
                    (sid, "demo-1", typ, iso(start), iso(end), unit, value, cat))

    for back in range(40, -1, -1):
        d = TODAY - timedelta(days=back)
        day0 = datetime.combine(d, time(0, 0), tzinfo=CN)
        # daily aggregates (like the app's HealthKit daily stats)
        steps = 8400 + 1900 * math.sin(back / 1.9) + (2600 if d.weekday() in (1, 5) else 0)
        if back == 0:
            steps = 6240          # today, still evening
        ins(f"hkagg-step_count-{d:%Y%m%d}", "step_count", day0, day0 + timedelta(days=1), "count", round(steps))
        ins(f"hkagg-active_energy_burned-{d:%Y%m%d}", "active_energy_burned", day0, day0 + timedelta(days=1), "kcal",
            round(520 + 140 * math.sin(back / 2.1) + (260 if d.weekday() in (1, 5) else 0)))
        if back % 3 == 0:
            ins(f"hkagg-body_mass-{d:%Y%m%d}", "body_mass", day0 + timedelta(hours=7.5), day0 + timedelta(hours=7.5),
                "kg", round(79.2 - (40 - back) * 0.04 + 0.15 * math.sin(back), 1))
        if back == 0:
            continue
        # night that starts on d-? : the night of (d - 1) -> sleep starting evening of d-1
        n = back
        start = bedtime(n)
        hours = sleep_hours(n)
        plan = [("asleep_core", 0.50), ("asleep_deep", 0.18), ("asleep_rem", 0.24), ("awake", 0.08)]
        cur = start
        total = timedelta(hours=hours / (1 - 0.08))
        for i, (cat, frac) in enumerate(plan):
            for half in range(2):
                seg = total * frac / 2
                ins(f"hkslp-{start:%Y%m%d}-{i}-{half}", "sleep_analysis", cur, cur + seg, "category", cat=cat)
                cur += seg
    con.commit()
    con.close()


def build_whoop(path: Path) -> None:
    snap = {"schema_version": 1, "source": "whoop", "pagination_complete": True,
            "coverage_warning": "API分页完整不等于每天有数据；缺失不代表正常或没有运动。",
            "window_start_utc": iso(NOW - timedelta(days=14)), "window_end_utc": iso(NOW - timedelta(minutes=20)),
            "collections": {"recovery": [], "sleep": [], "cycle": [], "workout": []}}
    for back in range(14, 0, -1):
        start = bedtime(back)
        hours = sleep_hours(back)
        awake = 0.35
        end = start + timedelta(hours=hours + awake)
        sid = f"demo-sleep-{back}"
        ms = lambda h: int(h * 3.6e6)
        debt = max(0.0, 0.25 * (7 - back)) if back <= 6 else 0.1
        snap["collections"]["sleep"].append({
            "id": sid, "cycle_id": 1000 + back, "start": iso(start), "end": iso(end), "timezone_offset": "+08:00",
            "nap": False, "score_state": "SCORED",
            "score": {
                "stage_summary": {"total_in_bed_time_milli": ms(hours + awake), "total_awake_time_milli": ms(awake),
                                  "total_light_sleep_time_milli": ms(hours * 0.52), "total_slow_wave_sleep_time_milli": ms(hours * 0.22),
                                  "total_rem_sleep_time_milli": ms(hours * 0.26), "sleep_cycle_count": 5,
                                  "disturbance_count": 2 if back > 6 else 4},
                "sleep_needed": {"baseline_milli": ms(7.6), "need_from_sleep_debt_milli": ms(debt),
                                 "need_from_recent_strain_milli": ms(0.3), "need_from_recent_nap_milli": 0},
                "respiratory_rate": 15.2 + 0.1 * back if back <= 2 else round(15.4 + 0.5 * math.sin(back * 1.3), 1),
                "sleep_performance_percentage": round(min(100, hours / (7.9 + debt) * 100)),
                "sleep_consistency_percentage": 72 if back > 6 else 58, "sleep_efficiency_percentage": 92 if back > 6 else 88},
        })
        hrv = 52 + 4 * math.sin(back / 1.8) - (7 - back) * 1.6 if back <= 6 else 52 + 4 * math.sin(back / 1.8)
        rhr = 56 + 1.6 * math.sin(back * 1.1) + (1 if back <= 3 else 0)
        if back <= 2:                      # 最近两晚静息心率、呼吸都在常态里：这个故事里只有睡眠和 HRV 出问题
            rhr = 55 + back
        rec = max(20, min(95, 64 + 12 * math.sin(back / 1.6) - (18 if back <= 2 else 0)))
        snap["collections"]["recovery"].append({
            "cycle_id": 1000 + back, "sleep_id": sid, "created_at": iso(end + timedelta(minutes=25)),
            "updated_at": iso(end + timedelta(minutes=25)), "score_state": "SCORED",
            "score": {"user_calibrating": False, "recovery_score": round(rec), "resting_heart_rate": round(rhr),
                      "hrv_rmssd_milli": round(hrv, 1), "spo2_percentage": 96.4, "skin_temp_celsius": 33.6}})
        cd = (TODAY - timedelta(days=back))
        tennis = cd.weekday() in (1, 5)
        snap["collections"]["cycle"].append({
            "id": 1000 + back, "start": iso(datetime.combine(cd, time(7, 30), tzinfo=CN)),
            "end": iso(datetime.combine(cd + timedelta(days=1), time(7, 30), tzinfo=CN)), "timezone_offset": "+08:00",
            "score_state": "SCORED",
            "score": {"strain": round(13.8 if tennis else 8.5 + 2 * math.sin(back), 1), "kilojoule": 9800 if tennis else 8100,
                      "average_heart_rate": 74, "max_heart_rate": 172 if tennis else 141}})
        if tennis:
            ws = datetime.combine(cd, time(19, 0), tzinfo=CN)
            snap["collections"]["workout"].append({
                "id": f"demo-wk-{back}", "start": iso(ws), "end": iso(ws + timedelta(minutes=90)), "timezone_offset": "+08:00",
                "sport_name": "tennis", "score_state": "SCORED",
                "score": {"strain": 12.6, "average_heart_rate": 138, "max_heart_rate": 172, "kilojoule": 2900}})
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "pivis-runtime").mkdir(exist_ok=True)
    build_vault(ROOT / "demo-vault.sqlite3")
    build_whoop(ROOT / "demo-whoop.json")
    cfg = {"vault_db": str(ROOT / "demo-vault.sqlite3"), "whoop_snapshot": str(ROOT / "demo-whoop.json"),
           "data_dir": str(ROOT / "pivis-runtime"), "timezone": "Asia/Shanghai", "sim_mode": True,
           "whoop_auth_dir": str(ROOT / "whoop-auth")}
    import os
    cfg["dsh_web"] = os.environ.get("PIVIS_DSH_WEB", "http://127.0.0.1:8960")
    (ROOT / "config.demo.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    (ROOT / "pivis-runtime" / "sim_clock.json").write_text(json.dumps({"now": NOW.isoformat(timespec="seconds")}))
    wrapper = f"""#!/bin/sh
# 演示工作区：全部是编出来的数据（截图、录屏用），和真实数据、模拟回放都隔离
export PYTHONPATH="{REPO}${{PYTHONPATH:+:$PYTHONPATH}}"
export PIVIS_HEALTH_CONFIG="{ROOT / 'config.demo.json'}"
export PIVIS_DSH_CWD="{ROOT}"
export PIVIS_DSH_PREFIX="phealth-demo-"
exec /usr/bin/python3 -m pivis_health.cli "$@"
"""
    w = ROOT / "pivis-health"
    w.write_text(wrapper)
    w.chmod(0o755)
    print("demo ready at", ROOT)


if __name__ == "__main__":
    main()
