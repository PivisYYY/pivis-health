"""睡眠重建算法 —— 从 hermes pivis_health_apple.py 完整移植（生产验收版）。

两起双计事故的固化防线，逻辑保持逐行等价，不得"优化"：
1. 2026-09-18：Apple Watch 同时写 asleep_unspecified 汇总段与分阶段明细，
   旧逻辑直接累加 → 多算 1.8h。修法：分阶段为准，unspecified 只补缺口。
2. 2026-09-28：手表写入两套完整平行分期轨（跨类互叠 21h）。
   修法：partition_tracks 分轨重建，取累计睡眠最长的轨道为 canon，其余整轨忽略。
3. 可信度门禁 validate_sleep_plausibility：渲染时长超过原始段并集的物理上界
   （±15% 容差）即抛错拒绝输出——错误数据比缺数据更伤信任。

夜间/午睡口径（用户作息）：主段起点在 [21:00, 12:00) 为夜间；[12:00, 21:00) 为午睡。
链式延伸：夜间链间隔 <3h 连续；晨起后回笼/上午小睡归 nap。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

STAGED = {"asleep_core", "asleep_deep", "asleep_rem", "awake"}


class SleepPlausibilityError(RuntimeError):
    """渲染时长超物理上界 —— 拒绝输出而不是给出错误数字。"""


def _to_local(text: str, tz: ZoneInfo) -> datetime:
    from .readonly import parse_ts

    return parse_ts(text).astimezone(tz)


def _classify(segs: list[tuple[datetime, datetime, str]]) -> tuple[list, list]:
    """夜间主链 / 午睡拆分。链断开后的段（回笼、上午小睡）归 nap，
    否则上午 10 点的小睡会因 hour<12 被误并入夜间（09-18 事故另一半根因）。"""
    ordered = sorted(segs, key=lambda x: x[0])
    night: list[tuple[datetime, datetime, str]] = []
    nap: list[tuple[datetime, datetime, str]] = []
    chain_open = False
    last_end: datetime | None = None
    for s, e, cat in ordered:
        in_night_window = 21 <= s.hour or s.hour < 12
        morning_wakeoff = (
            chain_open
            and last_end is not None
            and s.hour >= 6
            and s.hour < 12
            and s.hour != last_end.hour
            and (s - last_end).total_seconds() > 0
            and last_end.hour >= 6
        )
        if not chain_open:
            if in_night_window and (21 <= s.hour or s.hour < 3):
                night.append((s, e, cat))
                chain_open = True
                last_end = e
            else:
                nap.append((s, e, cat))
        elif (
            in_night_window
            and (s - last_end).total_seconds() / 3600 < 3
            and not (s.hour >= 6 and last_end.hour >= 6 and (s - last_end).total_seconds() >= 1800)
        ):
            night.append((s, e, cat))
            last_end = max(last_end, e)
        else:
            nap.append((s, e, cat))
            chain_open = False
    return night, nap


def _partition_tracks(segs: list[tuple[datetime, datetime, str]], tol_min: float = 2.0) -> list[list]:
    """互相重叠的分期段按区间图染色拆成平行轨道；同轨内任意两段互不重叠（容 2min 毛边）。"""
    tracks: list[list[tuple[datetime, datetime, str]]] = []
    for s, e, cat in sorted(segs, key=lambda x: (x[0], x[1])):
        placed = False
        for tr in tracks:
            if all(
                not (s < te - timedelta(minutes=tol_min) and ts < e - timedelta(minutes=tol_min))
                for ts, te, _ in tr
            ):
                tr.append((s, e, cat))
                placed = True
                break
        if not placed:
            tracks.append([(s, e, cat)])
    return tracks


def _merge_intervals(ivs: Iterable[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for s, e in sorted(ivs):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _fill_unspec_gaps(
    canon_ivs: list[tuple[datetime, datetime]],
    totals: list[tuple[datetime, datetime]],
) -> float:
    """unspecified（任意大小）只补 canon 轨未覆盖的时间，绝不叠加。"""
    merged = _merge_intervals(canon_ivs)
    fills = _merge_intervals(totals)
    extra = 0.0
    for ts, te in fills:
        cur = ts
        for cs, ce in merged:
            if ce <= cur:
                continue
            if cs > cur:
                extra += (min(cs, te) - cur).total_seconds() / 3600
            cur = max(cur, ce)
            if cur >= te:
                break
        if cur < te:
            extra += (te - cur).total_seconds() / 3600
    return extra


def _bucket_result(
    segs: list[tuple[datetime, datetime, str]],
    totals: list[tuple[datetime, datetime]],
    notes: list[str],
    day: date,
) -> dict[str, Any]:
    stages = {"core": 0.0, "deep": 0.0, "rem": 0.0, "awake": 0.0, "unspecified": 0.0}
    staged = [(s, e, c) for s, e, c in segs if c in STAGED]
    tracks = _partition_tracks(staged)
    canon_ivs: list[tuple[datetime, datetime]] = []
    if tracks:
        def sleep_h(tr: list[tuple[datetime, datetime, str]]) -> float:
            return sum((e - s).total_seconds() / 3600 for s, e, c in tr if c != "awake")

        canon = max(tracks, key=lambda tr: (sleep_h(tr), len(tr)))
        if len(tracks) > 1:
            notes.append(
                f"sleep {day}: {len(tracks)} 条平行分期轨，取累计睡眠最长轨 {sleep_h(canon):.1f}h 为准，其余整轨忽略"
            )
        for s, e, cat in canon:
            st = "awake" if cat == "awake" else cat[len("asleep_"):]
            stages[st] += (e - s).total_seconds() / 3600
        canon_ivs = [(s, e) for s, e, _ in canon]
    fills = list(totals) + [(s, e) for s, e, c in segs if c == "asleep_unspecified"]
    stages["unspecified"] += _fill_unspec_gaps(canon_ivs, fills)
    total = sum(v for k, v in stages.items() if k != "awake")
    return {"hours": round(total, 1), "stages": {k: round(v, 2) for k, v in stages.items()}}


def validate_sleep_plausibility(
    sleep: dict[str, Any],
    day: date,
    detail_by_bucket: dict[str, list],
    total_by_bucket: dict[str, list],
    tolerance: float = 0.15,
) -> None:
    """总时长不得超过 (明细 ∪ 汇总段) 去重后的物理上界；超界即抛错。"""
    for bucket in ("night", "nap"):
        got = float((sleep.get(bucket) or {}).get("hours") or 0)
        segs = detail_by_bucket.get(bucket) or []
        if got <= 0:
            continue
        ivs = [(s, e) for s, e, _ in segs] + list(total_by_bucket.get(bucket) or [])
        if not ivs:
            continue
        merged = _merge_intervals(ivs)
        phys = sum((e - s).total_seconds() / 3600 for s, e in merged)
        if got > phys * (1 + tolerance) + 0.05:
            raise SleepPlausibilityError(
                f"sleep plausibility failed {day.isoformat()} [{bucket}]: "
                f"rendered {got:.2f}h exceeds physical coverage {phys:.2f}h "
                f"({len(merged)} merged) beyond {tolerance:.0%} — likely double counting"
            )


def validate_sleep_consistency(source_count: int, sleep: dict[str, Any], day: date) -> None:
    """有睡眠输入却算出 0 小时时中止，避免把处理错误误报成数据缺失。"""
    night_h = float((sleep.get("night") or {}).get("hours") or 0)
    nap_h = float((sleep.get("nap") or {}).get("hours") or 0)
    if source_count > 0 and night_h <= 0 and nap_h <= 0:
        raise SleepPlausibilityError(
            f"sleep consistency failed {day.isoformat()}: "
            f"source has {source_count} rows but rendered sleep is 0 hours"
        )


def sleep_from_rows(rows: Iterable[dict[str, Any]], day: date, tz_name: str = "Asia/Shanghai") -> dict[str, Any]:
    """报告日 d 的睡眠：拆夜间/午睡，输出 {night, nap, notes}。

    rows 用 store.projection_rows(d) 的结果（睡眠窗 d 12:00 → d+1 12:00 已由投影层处理）。
    """
    tz = ZoneInfo(tz_name)
    detail_segs: list[tuple[datetime, datetime, str]] = []
    total_segs: list[tuple[datetime, datetime]] = []
    source_count = 0
    for r in rows:
        if r.get("type") != "sleep_analysis":
            continue
        source_count += 1
        cat = str(r.get("category_value") or "")
        try:
            s = _to_local(str(r["start_at"]), tz)
            e = _to_local(str(r["end_at"]), tz)
        except Exception:
            continue
        h = (e - s).total_seconds() / 3600
        if h <= 0:
            continue
        if cat == "asleep_unspecified" and h > 3:
            total_segs.append((s, e))  # Apple 整段汇总
        else:
            detail_segs.append((s, e, cat))

    notes: list[str] = []
    night, nap = _classify(detail_segs)
    night_totals = [t for t in total_segs if 21 <= t[0].hour or t[0].hour < 12]
    nap_totals = [t for t in total_segs if 12 <= t[0].hour < 21]
    result = {
        "night": _bucket_result(night, night_totals, notes, day),
        "nap": _bucket_result(nap, nap_totals, notes, day),
        "notes": notes,
        "source_count": source_count,
    }
    validate_sleep_consistency(source_count, result, day)
    validate_sleep_plausibility(
        result, day, {"night": night, "nap": nap}, {"night": night_totals, "nap": nap_totals}
    )
    return result


def asleep_minute_sets(
    rows_by_day: dict[date, list[dict[str, Any]]], tz_name: str = "Asia/Shanghai"
) -> dict[date, set[int]]:
    """SRI/睡眠债用的逐分钟入睡集合（本地日 → 分钟集合）。awake/in_bed 不算入睡。"""
    tz = ZoneInfo(tz_name)
    out: dict[date, set[int]] = {}
    for day, rows in rows_by_day.items():
        lo = datetime.combine(day, datetime.min.time(), tzinfo=tz)
        hi = lo + timedelta(days=1)
        mins: set[int] = set()
        for r in rows:
            if r.get("type") != "sleep_analysis":
                continue
            cat = str(r.get("category_value") or "")
            if cat in ("awake", "in_bed"):
                continue
            try:
                s = _to_local(str(r["start_at"]), tz)
                e = _to_local(str(r["end_at"]), tz)
            except Exception:
                continue
            if e <= lo or s >= hi:
                continue
            m0 = int((max(s, lo) - lo).total_seconds() // 60)
            m1 = int((min(e, hi) - lo).total_seconds() // 60)
            mins.update(range(m0, m1))
        out[day] = mins
    return out


def night_durations(sleep_results: dict[date, dict[str, Any]]) -> dict[date, float]:
    """按本地夜归档的夜间睡眠时长（key = 投影日）。

    纪律：缺数据的夜（无来源或 0 小时）不计入——缺数据 ≠ 睡了 0 小时，
    否则睡眠债会被无数据的日期虚增。
    """
    return {
        d: float(v["night"]["hours"])
        for d, v in sleep_results.items()
        if v.get("night") and (v.get("source_count") or 0) > 0 and float(v["night"]["hours"]) > 0
    }
