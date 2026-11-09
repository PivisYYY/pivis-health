"""场景标签（build 49）：从 events.sqlite3 的定位、蓝牙、摘手环算出每天的标签。

每天一条：在家（home）、外出（out）、外宿（away_night：那一夜不在常住地）、开车分钟（drive_min）、
摘手环分钟和时段（watch_off_min / watch_off）。常住地由服务器从夜间定位自己算。

隐私：坐标、蓝牙设备名只在这台机器上用。scene_daily.json 里只有标签；常住地坐标单独存 scene_home.json（0600），
两个文件都在数据目录，不进仓库，也不发给模型。洞察一期只攒，不出洞察。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DAILY = "scene_daily.json"
HOME = "scene_home.json"
HOME_KM = 1.0            # 离常住地 1 km 内算在家
AWAY_KM = 30.0           # 夜里离常住地 30 km 以上算外宿（出差）
DRIVE_KMH = 25.0         # 两个相邻定位之间平均速度 ≥ 25 km/h 算在开车
DRIVE_GAP_MIN = 30       # 两个定位隔得太久就不算（中间去了哪不知道）
CAR_WORDS = ("carplay", "car", "auto", "车", "tesla", "bmw", "benz", "audi", "byd", "nio", "xpeng", "li auto")


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _rows(db: Path, types: tuple[str, ...]) -> list[tuple[str, float, dict]]:
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        q = f"select type, occurred_ts, payload_json from raw_events where type in ({','.join('?' * len(types))}) order by occurred_ts"
        out = []
        for typ, ts, pj in con.execute(q, types):
            try:
                out.append((typ, float(ts), json.loads(pj)))
            except ValueError:
                continue
        return out
    finally:
        con.close()


def _write(path: Path, obj) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def home_of(points: list[tuple[datetime, float, float]]) -> tuple[float, float] | None:
    """常住地：夜里（00:00–06:00）定位最多的那一格（约 1 km），取格子里的平均坐标。夜里的定位少于 3 个就不算。"""
    night = [(lat, lon) for t, lat, lon in points if t.hour < 6]
    if len(night) < 3:
        return None
    cells = Counter((round(lat, 2), round(lon, 2)) for lat, lon in night)
    cell, _n = cells.most_common(1)[0]
    pts = [(lat, lon) for lat, lon in night if (round(lat, 2), round(lon, 2)) == cell]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def compute(events_db: Path, tz_name: str, home: tuple[float, float] | None = None) -> tuple[dict, tuple | None]:
    """→（{日期: 标签}，常住地）。纯函数，测试直接喂一个临时库。"""
    tz = ZoneInfo(tz_name)
    rows = _rows(events_db, ("location", "wearable_removed", "wearable_restored", "bluetooth_connected"))
    points: list[tuple[datetime, float, float]] = []
    for typ, ts, p in rows:
        if typ == "location" and isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float)):
            if float(p.get("accuracy_m") or 0) > 1000:          # 精度太差的点不要
                continue
            points.append((datetime.fromtimestamp(ts, tz), float(p["lat"]), float(p["lon"])))
    home = home or home_of(points)
    days: dict[str, dict] = {}

    def day(d: date) -> dict:
        return days.setdefault(d.isoformat(), {"home": False, "out": False, "away_night": False, "drive_min": 0,
                                               "watch_off_min": 0, "watch_off": [], "points": 0})

    for t, lat, lon in points:
        e = day(t.date())
        e["points"] += 1
        if home is None:
            continue
        dist = _km(home, (lat, lon))
        if dist <= HOME_KM:
            e["home"] = True
        else:
            e["out"] = True
        if t.hour < 6 and dist >= AWAY_KM:
            # 凌晨还在外地 = 前一天晚上外宿：标在前一天（「在外过夜后 3 天」从第二天算）
            day(t.date() - timedelta(days=1))["away_night"] = True
    # 开车：相邻两个定位的平均速度；车载蓝牙连上也算（只看名字像不像车，名字不存）
    for (t1, la1, lo1), (t2, la2, lo2) in zip(points, points[1:]):
        gap = (t2 - t1).total_seconds() / 60
        if 0 < gap <= DRIVE_GAP_MIN and _km((la1, lo1), (la2, lo2)) / (gap / 60) >= DRIVE_KMH:
            day(t1.date())["drive_min"] += int(round(gap))
    for typ, ts, p in rows:
        if typ == "bluetooth_connected" and any(w in str(p.get("device_name") or "").lower() for w in CAR_WORDS):
            day(datetime.fromtimestamp(ts, tz).date())["car_bt"] = True
    # 摘手环：removed → restored 配对；过了 12 小时还没戴回来的就截到 12 小时
    off_at: datetime | None = None
    for typ, ts, _p in rows:
        t = datetime.fromtimestamp(ts, tz)
        if typ == "wearable_removed":
            off_at = off_at or t
        elif typ == "wearable_restored" and off_at is not None:
            end = min(t, off_at + timedelta(hours=12))
            e = day(off_at.date())
            e["watch_off_min"] += int(round((end - off_at).total_seconds() / 60))
            e["watch_off"].append([off_at.strftime("%H:%M"), end.strftime("%H:%M")])
            off_at = None
    for e in days.values():
        if e.get("car_bt") and not e["drive_min"]:
            e["drive_min"] = None          # 连过车载蓝牙，但开了多久不知道
        e.pop("car_bt", None)
    return dict(sorted(days.items())), home


def update(cfg) -> dict:
    """重算并存下（每次全量重算，数据很少）。常住地算过一次就固定，避免偶尔出差几晚把它挪走。"""
    data_dir = Path(cfg.data_dir)
    saved = None
    try:
        h = json.loads((data_dir / HOME).read_text(encoding="utf-8"))
        saved = (float(h["lat"]), float(h["lon"]))
    except Exception:  # noqa: BLE001
        pass
    days, home = compute(data_dir / "events.sqlite3", cfg.timezone, saved)
    if home and not saved:
        _write(data_dir / HOME, {"lat": home[0], "lon": home[1], "at": datetime.now().isoformat(timespec="seconds")})
    _write(data_dir / DAILY, days)
    return {"days": len(days), "home_known": home is not None,
            "away_nights": sum(1 for e in days.values() if e["away_night"])}


def load(cfg) -> dict:
    try:
        return json.loads((Path(cfg.data_dir) / DAILY).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
