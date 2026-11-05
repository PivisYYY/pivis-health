"""WHOOP 快照只读解析（integrations/whoop/runtime/whoop-snapshot.json）。

口径纪律（P5）：WHOOP 的 HRV 是 RMSSD，Apple 的是 SDNN，两者永不混算。
本模块产出的指标名一律带 whoop_ 前缀。
快照是 14 天滚动缓存 —— 它"有"只代表 API 分页完整，某天缺失不代表正常。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _to_local(text: str, tz: ZoneInfo) -> datetime:
    from .readonly import parse_ts

    return parse_ts(text).astimezone(tz)


def load_snapshot(path: Path | str) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    cols = data.get("collections") or {}
    return {
        "window_start": data.get("window_start_utc"),
        "window_end": data.get("window_end_utc"),
        "coverage_warning": data.get("coverage_warning"),
        "recovery": list(cols.get("recovery") or []),
        "sleep": list(cols.get("sleep") or []),
        "cycle": list(cols.get("cycle") or []),
        "workout": list(cols.get("workout") or []),
    }


def _night_of(start_local: datetime) -> date:
    """入睡时刻 → 夜归属日（12 点前算前一晚）。"""
    return start_local.date() if start_local.hour >= 12 else start_local.date() - timedelta(days=1)


def recovery_by_night(snapshot: dict[str, Any], tz_name: str = "Asia/Shanghai") -> dict[date, dict]:
    """恢复分数按睡眠夜归档；用 recovery.created_at（晨起评分时刻）兜底对齐。"""
    tz = ZoneInfo(tz_name)
    sleep_start: dict[str, datetime] = {}
    for s in snapshot.get("sleep", []):
        try:
            sleep_start[str(s.get("id"))] = _to_local(str(s["start"]), tz)
        except Exception:
            continue
    out: dict[date, dict] = {}
    for rec in snapshot.get("recovery", []):
        score = rec.get("score") or {}
        night: date | None = None
        sid = str(rec.get("sleep_id") or "")
        if sid in sleep_start:
            night = _night_of(sleep_start[sid])
        elif rec.get("created_at"):
            try:
                night = _to_local(str(rec["created_at"]), tz).date() - timedelta(days=1)
            except Exception:
                night = None
        if night is None:
            continue
        out[night] = {
            "recovery_score": score.get("recovery_score"),
            "hrv_rmssd": score.get("hrv_rmssd_milli"),
            "resting_heart_rate": score.get("resting_heart_rate"),
            "spo2": score.get("spo2_percentage"),
            "skin_temp_celsius": score.get("skin_temp_celsius"),
            "user_calibrating": bool(score.get("user_calibrating")),
            "score_state": rec.get("score_state"),
        }
    return out


def sleep_by_night(snapshot: dict[str, Any], tz_name: str = "Asia/Shanghai") -> dict[date, dict]:
    tz = ZoneInfo(tz_name)
    out: dict[date, dict] = {}
    for s in snapshot.get("sleep", []):
        try:
            start = _to_local(str(s["start"]), tz)
            end = _to_local(str(s["end"]), tz)
        except Exception:
            continue
        night = _night_of(start)
        score = s.get("score") or {}
        stage = score.get("stage_summary") or {}
        needed = score.get("sleep_needed") or {}

        def _h(milli) -> float | None:
            return round(milli / 3_600_000, 2) if isinstance(milli, (int, float)) else None

        duration = (end - start).total_seconds() / 3600
        asleep_h = None
        parts = [
            _h(stage.get("total_light_sleep_time_milli")),
            _h(stage.get("total_slow_wave_sleep_time_milli")),
            _h(stage.get("total_rem_sleep_time_milli")),
        ]
        if all(p is not None for p in parts):
            asleep_h = round(sum(parts), 2)
        entry = {
            "start_local": start.isoformat(),
            "end_local": end.isoformat(),
            "duration_h": round(duration, 2),
            "asleep_h": asleep_h,
            "nap": bool(s.get("nap")),
            "score_state": s.get("score_state"),
            "performance_pct": score.get("sleep_performance_percentage"),
            "efficiency_pct": score.get("sleep_efficiency_percentage"),
            "consistency_pct": score.get("sleep_consistency_percentage"),
            "respiratory_rate": score.get("respiratory_rate"),
            "stages_h": {
                "light": _h(stage.get("total_light_sleep_time_milli")),
                "slow_wave": _h(stage.get("total_slow_wave_sleep_time_milli")),
                "rem": _h(stage.get("total_rem_sleep_time_milli")),
                "awake": _h(stage.get("total_awake_time_milli")),
                "in_bed": _h(stage.get("total_in_bed_time_milli")),
            },
            "sleep_needed_h": {
                "baseline": _h(needed.get("baseline_milli")),
                "from_debt": _h(needed.get("need_from_sleep_debt_milli")),
                "from_strain": _h(needed.get("need_from_recent_strain_milli")),
                "from_nap": _h(needed.get("need_from_recent_nap_milli")),
            },
            "disturbance_count": stage.get("disturbance_count"),
        }
        if s.get("nap"):
            continue  # 小憩不占夜槽，避免覆盖主夜
        out[night] = entry
    return out


def strain_by_day(snapshot: dict[str, Any], tz_name: str = "Asia/Shanghai") -> dict[date, dict]:
    tz = ZoneInfo(tz_name)
    out: dict[date, dict] = {}
    for c in snapshot.get("cycle", []):
        try:
            start = _to_local(str(c["start"]), tz)
        except Exception:
            continue
        score = c.get("score") or {}
        out[start.date()] = {
            "strain": score.get("strain"),
            "kilojoule": score.get("kilojoule"),
            "avg_hr": score.get("average_heart_rate"),
            "max_hr": score.get("max_heart_rate"),
            "step_count": c.get("step_count"),
        }
    return out


def latest_timestamps(snapshot: dict[str, Any], tz_name: str = "Asia/Shanghai") -> dict[str, str]:
    tz = ZoneInfo(tz_name)
    latest: datetime | None = None
    for key in ("recovery", "sleep", "cycle", "workout"):
        for item in snapshot.get(key, []):
            for field in ("updated_at", "created_at"):
                try:
                    ts = _to_local(str(item[field]), tz)
                except Exception:
                    continue
                latest = ts if latest is None or ts > latest else latest
    return {"whoop_latest_local": latest.isoformat() if latest else None}
