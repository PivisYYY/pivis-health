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


def recovery_by_day(snapshot: dict[str, Any], tz_name: str = "Asia/Shanghai") -> dict[date, dict]:
    """恢复分数按「醒来那天」归档：和 WHOOP App 一样，今早醒来测出的恢复 / HRV / 静息心率就是「今天的」。
    （睡眠时长仍按夜归档：sleep_by_night。）"""
    return {night + timedelta(days=1): v for night, v in recovery_by_night(snapshot, tz_name).items()}


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
        out[_night_of(start) + timedelta(days=1)] = {   # 周期从入睡开始：算到醒来那天（23:30 睡也不会盖掉当天）
            "strain": score.get("strain"),
            "kilojoule": score.get("kilojoule"),
            "avg_hr": score.get("average_heart_rate"),
            "max_hr": score.get("max_heart_rate"),
            "step_count": c.get("step_count"),
        }
    return out


SPORT_NAMES = {
    "tennis": "网球", "running": "跑步", "cycling": "骑行", "walking": "步行", "hiking": "徒步",
    "swimming": "游泳", "yoga": "瑜伽", "pilates": "普拉提", "weightlifting": "力量训练",
    "powerlifting": "力量训练", "functional-fitness": "功能训练", "hiit": "HIIT", "stretching": "拉伸",
    "basketball": "篮球", "soccer": "足球", "badminton": "羽毛球", "table-tennis": "乒乓球",
    "golf": "高尔夫", "boxing": "拳击", "elliptical": "椭圆机", "rowing": "划船", "spin": "动感单车",
    "activity": "运动", "other": "运动",
}


def workouts(snapshot: dict[str, Any], tz_name: str = "Asia/Shanghai") -> list[dict]:
    """WHOOP 记到的训练（已评分的），按开始时间排：日期、项目、分钟、strain、平均心率。"""
    tz = ZoneInfo(tz_name)
    out = []
    for w in snapshot.get("workout", []):
        if w.get("score_state") not in (None, "SCORED"):
            continue
        try:
            start, end = _to_local(str(w["start"]), tz), _to_local(str(w["end"]), tz)
        except Exception:
            continue
        score = w.get("score") or {}
        name = str(w.get("sport_name") or "activity").strip().lower().replace(" ", "-").replace("_", "-")
        out.append({"date": start.date().isoformat(), "start": start.strftime("%H:%M"),
                    "sport": SPORT_NAMES.get(name, name),
                    "min": int(round((end - start).total_seconds() / 60)),
                    "strain": round(float(score["strain"]), 1) if score.get("strain") is not None else None,
                    "avg_hr": int(round(float(score["average_heart_rate"]))) if score.get("average_heart_rate") else None})
    return sorted(out, key=lambda x: (x["date"], x["start"]))


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
