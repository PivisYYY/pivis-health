"""主卡图表（v3 hero.viz）：P-Health 决定画什么、怎么画；内核只填数。

P-Health 在主卡里写一份描述：
    {"metric": "hrv", "kind": "trend", "days": 14, "show": ["band", "warn"]}
- metric：画哪项数据（METRICS 里的键）
- kind：画法，不写就用这项数据的默认画法（METRICS[*]["kinds"] 第一个）
    trend    折线 + 个人常态带 + 警戒线          任何有每日序列的指标都能画
    gauge    0–100 半圆仪表                       恢复
    need     睡了 vs 需要 的缺口条 + 近 N 晚够不够  睡眠时长
    stack    每晚欠下的睡眠一块块叠起来            睡眠债
    range    区间刻度：今天落在常态/警戒哪一段      静息心率等
    progress 按此刻应走到的进度比                  步数
    route    朝目标的计划路线 vs 实际              体重
- days：看几天（DAYS[kind] 里选）
- show：显示哪些参照（MARKS 的子集），不写就全显示
数字全部由这里算：常态区间 = 个人 30 天均值 ± 1 个标准差；警戒线 = 均值 ∓ 1.5 个标准差（方向看指标）。
Psir 用 pref.viz.<metric> 定过的数（warn、goal、target、start、start_date、rate_kg_week）以他定的为准。
不用医学阈值，不诊断。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from .clock import day_of

METRICS: dict[str, dict[str, Any]] = {
    "hrv": {"label": "HRV", "unit": "ms", "series": "whoop_hrv_rmssd", "dir": "low_bad", "nd": 1,
            "board": "stress", "kinds": ("trend", "range")},
    "resp_rate": {"label": "呼吸频率", "unit": "次/分", "series": "respiratory_rate", "dir": "high_bad", "nd": 1,
                  "board": "stress", "kinds": ("trend", "range")},
    "resting_hr": {"label": "静息心率", "unit": "次/分", "series": "resting_heart_rate", "dir": "high_bad", "nd": 0,
                   "board": "stress", "kinds": ("range", "trend")},
    "recovery": {"label": "恢复", "unit": "%", "series": "whoop_recovery", "dir": "low_bad", "nd": 0,
                 "board": "sport", "kinds": ("gauge", "trend")},
    "sleep": {"label": "昨晚睡了", "unit": "小时", "series": None, "dir": "low_bad", "nd": 1,
              "board": "sleep", "kinds": ("need", "trend")},
    "sleep_debt": {"label": "睡眠债", "unit": "小时", "series": None, "dir": "high_bad", "nd": 1,
                   "board": "sleep", "kinds": ("stack",)},
    # 睡眠效率（睡着 ÷ 在床，WHOOP 算）：CBT-I 唯一用来调窗口的数，带子 = ≥90 加窗口，虚线 = <85 减窗口
    "sleep_efficiency": {"label": "睡眠效率", "unit": "%", "series": None, "dir": "low_bad", "nd": 0,
                         "board": "sleep", "kinds": ("trend",)},
    "steps": {"label": "今天步数", "unit": "步", "series": "steps", "dir": "low_bad", "nd": 0,
              "board": "sport", "kinds": ("progress", "trend")},
    "weight": {"label": "体重", "unit": "kg", "series": "weight", "dir": "high_bad", "nd": 1,
               "board": "sport", "kinds": ("route", "trend")},
}
KINDS = ("trend", "gauge", "need", "stack", "range", "progress", "route")
DAYS = {"trend": (7, 14, 30, 90), "range": (7, 14), "need": (7, 14), "stack": (5, 7)}
DEFAULT_DAYS = {"trend": 14, "range": 7, "need": 7, "stack": 5}
MARKS = ("band", "warn", "need", "pace", "goal", "target", "plan")
GAUGE_WARN, GAUGE_MID = 33, 66          # 恢复：WHOOP 红 / 黄 / 绿分界
NIGHT_SHORT_ACT, NIGHT_SHORT_WATCH = 2.0, 1.0
DEBT_WARN_H = 10.0                      # 近 5 晚累计缺觉的警戒
STEPS_GOAL = 8000
WAKE_END = "22:30"                      # 步数节奏按 起床目标→22:30 线性算


class VizUnavailable(ValueError):
    pass


# ---------------------------------------------------------------- helpers
def _r(v: float | None, nd: int):
    if v is None:
        return None
    return int(round(v)) if nd == 0 else round(float(v), nd)


def _text(v: float | None, nd: int) -> str:
    if v is None:
        return ""
    return str(int(round(v))) if nd == 0 else f"{float(v):.{nd}f}"


def prefs_for(cfg) -> dict[str, dict]:
    """Psir 用 pref.viz.<metric> 定过的数和画法。"""
    from .prefs import active_prefs
    out: dict[str, dict] = {}
    for e in active_prefs(cfg):
        scope = str(e.get("scope", ""))
        if scope.startswith("pref.viz."):
            out[scope[len("pref.viz."):]] = dict(e.get("payload") or {})
    return out


def _num(p: dict, key: str) -> float | None:
    try:
        return float(p[key]) if p.get(key) not in (None, "") else None
    except (TypeError, ValueError):
        return None


def sleep_debt(nights: list[dict], days: int = 5) -> tuple[float, list[dict]]:
    """睡眠债的唯一算法（主卡、facts、结论都用它）：最近 days 个「知道需要睡多久」的晚上，每晚缺的相加。"""
    known = [n for n in nights if n.get("need") is not None and n.get("actual") is not None][-days:]
    blocks = [{"night_of": n["date"], "short": _r(max(0.0, n["need"] - n["actual"]), 1)} for n in known]
    return _r(sum(b["short"] for b in blocks), 1), blocks


def _sleep_nights(tools, day: date) -> list[dict]:
    from .pages import V2Pages
    sp = V2Pages(tools).sleep(day)
    yday = (day - timedelta(days=1)).isoformat()
    return [n for n in sp.get("chart14") or [] if n.get("date") <= yday and n.get("actual") is not None]


def _series(tools, metric: str, day: date, days: int) -> list[tuple[str, float]]:
    m = METRICS[metric]
    if metric == "sleep":
        return [(n["date"], float(n["actual"])) for n in _sleep_nights(tools, day)][-days:]
    if metric == "sleep_efficiency":
        from .coach import sleep_week
        return [(r["night_of"], float(r["efficiency_pct"])) for r in sleep_week(tools, days, day)["nights"]
                if r.get("efficiency_pct") is not None]
    if not m["series"]:
        return []
    daily = tools.daily_series(m["series"], day, max(days, 1) + 40)
    vals = [(d.isoformat(), float(v)) for d, v in sorted(daily.items()) if d <= day and v is not None]
    return vals[-days:]


def _band(tools, metric: str, asof: str, pref: dict) -> tuple[list[float] | None, float | None]:
    m = METRICS[metric]
    band, warn = None, None
    if metric == "sleep":
        vals = [float(n["actual"]) for n in _sleep_nights(tools, date.fromisoformat(asof) + timedelta(days=1))][-30:]
        if len(vals) >= 5:
            c = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - c) ** 2 for v in vals) / (len(vals) - 1))
            if sd:
                band = [_r(c - sd, 1), _r(c + sd, 1)]
                warn = _r(c - 1.5 * sd, 1)
    elif m["series"]:
        b = (tools.baseline(m["series"], date.fromisoformat(asof)) or {}).get("baseline") or {}
        c, s = b.get("center"), b.get("spread")
        if c is not None and s:
            nd = m["nd"]
            band = [_r(c - s, nd), _r(c + s, nd)]
            warn = _r(c - 1.5 * s if m["dir"] == "low_bad" else c + 1.5 * s, nd)
    if _num(pref, "warn") is not None:
        warn = _num(pref, "warn")
    return band, warn


def _zone(direction: str, value: float, band: list[float] | None, warn: float | None) -> str | None:
    if warn is None and band is None:
        return None
    if direction == "low_bad":
        if warn is not None and value <= warn:
            return "act"
        if band is not None and value < band[0]:
            return "watch"
    else:
        if warn is not None and value >= warn:
            return "act"
        if band is not None and value > band[1]:
            return "watch"
    return "steady"


def _delta(vals: list[float]) -> dict | None:
    if len(vals) < 5:
        return None
    a = sum(vals[-3:]) / 3
    prev = vals[:-3]
    b = sum(prev) / len(prev)
    if not b:
        return None
    pct = round((a - b) / b * 100)
    arrow = "↘" if pct <= -3 else ("↗" if pct >= 3 else "→")
    return {"pct": pct, "text": f"{arrow} {abs(pct)}%" if arrow != "→" else "→ 持平", "span": "近 3 天"}


# ---------------------------------------------------------------- build
def normalize(spec: Any) -> dict:
    """校验并补全 P-Health 写的描述（不碰数据）。"""
    if isinstance(spec, str):
        spec = {"metric": spec}
    if not isinstance(spec, dict):
        raise ValueError("hero.viz 要写成 {\"metric\": \"...\"}")
    metric = spec.get("metric")
    if metric not in METRICS:
        raise ValueError(f"hero.viz.metric 只能是 {list(METRICS)}")
    kinds = METRICS[metric]["kinds"]
    kind = spec.get("kind") or kinds[0]
    if kind not in kinds:
        raise ValueError(f"{metric} 能用的画法是 {list(kinds)}")
    out: dict[str, Any] = {"metric": metric, "kind": kind}
    if kind in DAYS:
        days = spec.get("days") or DEFAULT_DAYS[kind]
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ValueError("hero.viz.days 要是数字")
        if days not in DAYS[kind]:
            raise ValueError(f"{kind} 的 days 只能是 {list(DAYS[kind])}")
        out["days"] = days
    show = spec.get("show")
    if show is not None:
        if not isinstance(show, list) or any(s not in MARKS for s in show):
            raise ValueError(f"hero.viz.show 只能从 {list(MARKS)} 里选")
        out["show"] = [str(s) for s in show]
    return out


def build(tools, spec: Any, day: date | None = None, now: datetime | None = None) -> dict:
    """按描述算出图表要的全部数字。没有数据时抛 VizUnavailable。"""
    s = normalize(spec)
    now = now or tools._now()
    day = day or day_of(now)
    metric, kind = s["metric"], s["kind"]
    m = METRICS[metric]
    pref = prefs_for(tools.cfg).get(metric, {})
    base = {"metric": metric, "kind": kind, "label": m["label"], "unit": m["unit"], "direction": m["dir"],
            "nd": m["nd"], "show": s.get("show") or list(MARKS)}
    fn = {"trend": _trend, "gauge": _gauge, "need": _need, "stack": _stack, "range": _range,
          "progress": _progress, "route": _route}[kind]
    try:
        out = fn(tools, metric, day, now, s, pref)
    except VizUnavailable as exc:
        # 睡眠：WHOOP 断更时最近几晚只有 Apple 健康的时长、没有「需要睡多久」，need 画不了 → 退回折线，
        # 并标明是退回来的，免得 Agent 以为页面画的是它选的那种
        if metric != "sleep" or kind != "need":
            raise
        out = _trend(tools, metric, day, now, {**s, "days": s.get("days", 7)}, pref)
        base = {**base, "kind": "trend", "fallback_from": kind, "fallback_reason": str(exc)}
    out = {**base, **out}
    out["value_text"] = _text(out.get("value"), m["nd"])
    return out


def _trend(tools, metric, day, now, s, pref) -> dict:
    m = METRICS[metric]
    days = s.get("days", 14)
    vals = _series(tools, metric, day, days)
    if len(vals) < 3:
        raise VizUnavailable(f"{m['label']}最近没有足够的数据")
    asof, value = vals[-1]
    out: dict[str, Any] = {"value": _r(value, m["nd"]), "asof": asof, "days": days,
                           "series": [{"date": d, "value": _r(v, m["nd"])} for d, v in vals]}
    if metric == "sleep_efficiency":
        # 固定的两条线（CBT-I 的调窗口规则），不按个人常态算；在做 CBT-I 时带子和虚线上直接写规则
        from . import cbti
        in_cbti = cbti.state(tools, day, now) is not None
        out["band"], out["warn"] = [cbti.EFF_ADD, 100], cbti.EFF_CUT
        out["band_label"] = "≥90 加窗口" if in_cbti else "≥90"
        out["warn_label"] = "<85 减窗口" if in_cbti else "85"
        out["zone"] = "act" if value < cbti.EFF_CUT else ("watch" if value < cbti.EFF_ADD else "steady")
        out["aside"] = None
        return out
    if metric == "sleep" and _last_need(tools, day) is not None:
        need = _last_need(tools, day)
        out["need"] = _r(need, 1)
        out["band"], out["warn"] = None, None
        out["zone"] = _night_zone(need - value)
    else:
        # 没有「需要睡多久」的晚上（WHOOP 断更，只有 Apple 健康时长）：跟其他指标一样和自己近 30 天比
        band, warn = _band(tools, metric, asof, pref)
        out["band"], out["warn"] = band, warn
        out["zone"] = _zone(m["dir"], value, band, warn)
    d = _delta([v for _, v in vals])
    out["aside"] = {"text": d["text"], "sub": d["span"]} if d else None
    return out


def _gauge(tools, metric, day, now, s, pref) -> dict:
    vals = _series(tools, metric, day, 14)
    if not vals:
        raise VizUnavailable("恢复最近没有数据")
    asof, value = vals[-1]
    warn = _num(pref, "warn") or GAUGE_WARN
    prev = vals[-2][1] if len(vals) > 1 else None
    zone = "act" if value <= warn else ("watch" if value <= GAUGE_MID else "steady")
    return {"value": _r(value, 0), "asof": asof, "warn": _r(warn, 0), "mid": GAUGE_MID, "zone": zone,
            "prev": _r(prev, 0), "aside": {"text": f"前一天 {_text(prev, 0)}"} if prev is not None else None}


def _last_need(tools, day: date) -> float | None:
    nights = _sleep_nights(tools, day)
    return nights[-1].get("need") if nights else None


def _night_zone(short: float) -> str:
    return "act" if short >= NIGHT_SHORT_ACT else ("watch" if short >= NIGHT_SHORT_WATCH else "steady")


def _need(tools, metric, day, now, s, pref) -> dict:
    days = s.get("days", 7)
    nights = _sleep_nights(tools, day)[-days:]
    if not nights:
        raise VizUnavailable("最近没有睡眠记录")
    if nights[-1].get("need") is None:
        raise VizUnavailable("最近一晚只有时长、没有「需要睡多久」（WHOOP 没同步）")
    last = nights[-1]
    slept, need = float(last["actual"]), float(last["need"])
    marks = [{"night_of": n["date"], "slept": _r(n["actual"], 1), "need": _r(n.get("need"), 1),
              "ok": bool(n.get("need") is None or n["actual"] >= n["need"] - 0.5)} for n in nights]
    short = max(0.0, need - slept)
    n_short = sum(1 for x in marks if not x["ok"])
    return {"value": _r(slept, 1), "asof": last["date"], "need": _r(need, 1), "short": _r(short, 1),
            "nights": marks, "short_nights": n_short, "zone": _night_zone(short),
            "aside": {"text": f"需要 {_text(need, 1)}"}}


def _stack(tools, metric, day, now, s, pref) -> dict:
    days = s.get("days", 5)
    total, blocks = sleep_debt(_sleep_nights(tools, day), days)
    if not blocks:
        raise VizUnavailable("最近没有睡眠记录")
    nights = [{"date": b["night_of"]} for b in blocks]
    warn = _num(pref, "warn") or DEBT_WARN_H
    zone = "act" if total >= warn else ("watch" if total >= warn / 2 else "steady")
    return {"value": _r(total, 1), "asof": nights[-1]["date"], "blocks": blocks, "warn": _r(warn, 1),
            "zone": zone, "aside": {"text": f"近 {len(blocks)} 晚"}}


def _range(tools, metric, day, now, s, pref) -> dict:
    m = METRICS[metric]
    days = s.get("days", 7)
    vals = _series(tools, metric, day, days)
    if not vals:
        raise VizUnavailable(f"{m['label']}最近没有数据")
    asof, value = vals[-1]
    band, warn = _band(tools, metric, asof, pref)
    pts = [v for _, v in vals] + (band or []) + ([warn] if warn is not None else [])
    lo, hi = min(pts), max(pts)
    pad = max((hi - lo) * 0.18, 1.0)
    first = vals[0][1]
    span = "一周前" if days == 7 else f"{days} 天前"
    return {"value": _r(value, m["nd"]), "asof": asof, "days": days, "band": band, "warn": warn,
            "scale": [_r(lo - pad, m["nd"]), _r(hi + pad, m["nd"])],
            "trail": [{"date": d, "value": _r(v, m["nd"])} for d, v in vals],
            "zone": _zone(m["dir"], value, band, warn),
            "aside": {"text": f"{span} {_text(first, m['nd'])}"} if len(vals) > 1 else None}


def _progress(tools, metric, day, now, s, pref) -> dict:
    daily = tools.daily_series("steps", day, 3)
    value = daily.get(day)
    if value is None:
        # 早上还没走、手机还没传今天的数：前两天有数说明手机在正常上传，今天就是「还没走」= 0，别让整张卡空着
        if not any(daily.get(day - timedelta(days=k)) for k in (1, 2)):
            raise VizUnavailable("步数最近没有数据（手机没传上来）")
        value = 0.0
    goal = _num(pref, "goal") or STEPS_GOAL
    try:
        from .params import Params
        wake = str(Params(tools.subj).get("wake_target") or "08:20")
    except Exception:
        wake = "08:20"
    t0 = datetime.combine(day, datetime.strptime(wake, "%H:%M").time(), tzinfo=now.tzinfo)
    t1 = datetime.combine(day, datetime.strptime(WAKE_END, "%H:%M").time(), tzinfo=now.tzinfo)
    frac = min(1.0, max(0.0, (now - t0).total_seconds() / max(1.0, (t1 - t0).total_seconds())))
    pace = int(round(goal * frac, -2))
    if value >= goal:
        zone = "steady"
    elif pace <= 0:
        zone = "steady"
    else:
        ratio = value / pace
        zone = "act" if ratio < 0.4 else ("watch" if ratio < 0.8 else "steady")
    return {"value": int(round(value)), "asof": day.isoformat(), "goal": int(goal), "pace": pace,
            "pace_time": now.strftime("%H:%M"), "zone": zone, "aside": {"text": f"目标 {int(goal):,}"}}


def _route(tools, metric, day, now, s, pref) -> dict:
    target = _num(pref, "target")
    if target is None:
        raise VizUnavailable("还没定目标体重（pref.viz.weight 里写 target）")
    daily = tools.daily_series("weight", day, 240)
    vals = [(d, float(v)) for d, v in sorted(daily.items()) if d <= day]
    if not vals:
        raise VizUnavailable("最近没有体重数据")
    start_date = date.fromisoformat(pref["start_date"]) if pref.get("start_date") else vals[0][0]
    vals = [(d, v) for d, v in vals if d >= start_date] or vals[-1:]
    start = _num(pref, "start") or vals[0][1]
    rate = _num(pref, "rate_kg_week") or 0.5
    weeks_total = max(1, math.ceil(abs(start - target) / rate))
    week_now = (day - start_date).days / 7
    sign = -1 if target < start else 1
    plan_now = start + sign * min(abs(start - target), rate * week_now)
    value = vals[-1][1]
    over = (value - plan_now) * (-sign)      # 正数 = 比计划落后
    zone = "act" if over >= 3 else ("watch" if over >= 1 else "steady")
    return {"value": _r(value, 1), "asof": vals[-1][0].isoformat(), "start": _r(start, 1), "target": _r(target, 1),
            "start_date": start_date.isoformat(), "weeks_total": weeks_total, "week_now": round(week_now, 2),
            "plan_now": _r(plan_now, 1), "behind": _r(over, 1),
            "points": [{"week": round((d - start_date).days / 7, 2), "value": _r(v, 1)} for d, v in vals],
            "zone": zone, "aside": {"text": f"计划该到 {_text(plan_now, 1)}"}}


def available(tools, day: date | None = None) -> dict:
    """每项指标用默认画法能不能画、画出来是什么数（给 P-Health 挑主卡用）。"""
    out: dict[str, Any] = {}
    for metric, m in METRICS.items():
        try:
            v = build(tools, {"metric": metric}, day)
        except Exception as exc:
            out[metric] = {"ok": False, "reason": str(exc), "kinds": list(m["kinds"]), "board": m["board"]}
            continue
        out[metric] = {"ok": True, "board": m["board"], "kinds": list(m["kinds"]), "label": v["label"],
                       "value": v.get("value"), "value_text": v["value_text"], "unit": v["unit"],
                       "asof": v.get("asof"), "zone": v.get("zone"),
                       **{k: v[k] for k in ("band", "warn", "need", "short", "goal", "pace", "target", "plan_now")
                          if v.get(k) is not None}}
    return out
