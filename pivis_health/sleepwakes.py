"""夜里醒（build 54，Psir 11-11：说到健康的事先对照实际数据——「我每天某个点固定醒」到底是不是）。

从 Apple 健康的睡眠分段里取「醒着」的段（WHOOP / 手表写进健康的），按晚归组（中午 12 点为界），
去重、相隔 2 分钟以内的合并，只留 ≥ N 分钟的；最后起床那一段（WHOOP 记的起床时间之后）不算夜里醒。
只读库，不联网。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

MERGE_GAP_MIN = 2
EARLY = (5 * 60, 8 * 60 + 30)       # 清晨 05:00–08:30


def _parse(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _segments(cfg, since: datetime, until: datetime) -> list[tuple[datetime, datetime]]:
    db = Path(cfg.vault_db)
    if not db.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute("SELECT DISTINCT start_at, end_at FROM samples WHERE type='sleep_analysis' AND category_value='awake'"
                               " AND end_at >= ? AND start_at <= ?",
                               (since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                                until.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    out = sorted({(a, b) for a, b in ((_parse(s), _parse(e)) for s, e in rows) if a and b and b > a})
    merged: list[list[datetime]] = []
    for a, b in out:
        if merged and (a - merged[-1][1]).total_seconds() <= MERGE_GAP_MIN * 60:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def nights(tools, days: int = 14, min_minutes: int = 5, today: date | None = None) -> dict:
    cfg = tools.cfg
    tz = ZoneInfo(cfg.timezone)
    today = today or tools._today()
    start = datetime.combine(today - timedelta(days=days), datetime.min.time(), tz) + timedelta(hours=12)
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tz) + timedelta(hours=12)
    segs = _segments(cfg, start, end)
    wake_end: dict[str, str] = {}
    try:
        from .coach import sleep_week
        for r in sleep_week(tools, days, today + timedelta(days=1)).get("nights") or []:
            if r.get("end"):
                wake_end[r["night_of"]] = r["end"]
    except Exception:  # noqa: BLE001
        pass
    by_night: dict[str, list[dict]] = {}
    for a, b in segs:
        la, lb = a.astimezone(tz), b.astimezone(tz)
        night = (la - timedelta(hours=12)).date().isoformat()
        mins = round((b - a).total_seconds() / 60)
        end_hm = wake_end.get(night)
        if end_hm:                      # 起床时间之后（或起床前 5 分钟内开始）的醒：是起床，不算夜里醒
            h, m = int(end_hm[:2]), int(end_hm[3:5])
            wake_dt = datetime.combine(date.fromisoformat(night) + timedelta(days=1 if h < 12 else 0), datetime.min.time(), tz) \
                + timedelta(hours=h, minutes=m)
            if la >= wake_dt - timedelta(minutes=5):
                continue
        if mins < min_minutes:
            continue
        by_night.setdefault(night, []).append({"at": la.strftime("%H:%M"), "min": mins,
                                               "_m": la.hour * 60 + la.minute})
    rows = []
    early_times = []
    for i in range(days, 0, -1):
        d = (today - timedelta(days=i - 1) - timedelta(days=1)).isoformat()
        w = by_night.get(d, [])
        early = [x for x in w if EARLY[0] <= x["_m"] <= EARLY[1]]
        early_times += [x["_m"] for x in early]
        rows.append({"night_of": d, "wakes": [{k: v for k, v in x.items() if k != "_m"} for x in w],
                     "awake_min": sum(x["min"] for x in w), "early": [x["at"] for x in early], "woke_up": wake_end.get(d)})
    have = [r for r in rows if r["wakes"] or r["woke_up"]]
    summary = {"nights_with_data": len(have), "nights_with_wakes": sum(1 for r in rows if r["wakes"]),
               "nights_with_early": sum(1 for r in rows if r["early"]), "min_minutes": min_minutes}
    if early_times:
        med = int(median(early_times))
        summary["early_typical"] = f"{med // 60:02d}:{med % 60:02d}"
        summary["early_spread_min"] = max(early_times) - min(early_times)
    return {"nights": rows, "summary": summary,
            "note": "Apple 健康睡眠分段里的「醒着」段（≥ %d 分钟，相隔 2 分钟内合并）；起床后的不算。手环对很短的醒会漏记或多记，单晚看个大概，几晚一起看规律" % min_minutes}


def brief_line(tools, today: date) -> list[str]:
    try:
        d = nights(tools, 7, 5, today)
    except Exception:  # noqa: BLE001
        return []
    s = d["summary"]
    if not s["nights_with_data"]:
        return []
    line = f"夜里醒（≥5 分钟，Apple 健康）：近 7 晚 {s['nights_with_wakes']} 晚有"
    if s.get("early_typical"):
        line += f"，清晨 5–8:30 醒 {s['nights_with_early']} 晚、多在 {s['early_typical']} 前后"
    longest = max((w for r in d["nights"] for w in r["wakes"]), key=lambda w: w["min"], default=None)
    if longest:
        line += f"，最长一次 {longest['min']} 分钟"
    return [line + "（sleep-wakes 看每晚）"]
