"""CBT-I 进行中的状态（build 56）：阶段、处方、睡眠效率、守窗口、昨晚在床、每周记录、复盘建议、档位。

全部是内核现算的数（设备的入睡 / 起床 / 在床 / 效率 + 日记 + sleep.cbti 记下的处方）。
页面编排和对话里的卡片都从这里取数：facts.cbti、零件的 bind（cbti.*、cbti.lastnight、cbti.weeks、sleep_efficiency 图）。
做 CBT-I 时主卡不用睡眠债：前两周少睡是方案本身，债一定涨，显示它只会催人补觉、早上床、赖床。
"""
from __future__ import annotations

import math
import re
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from .clock import day_of

EFF_ADD, EFF_CUT = 90, 85           # 7 晚中位 ≥90 加 15 分钟；<85 减 15 分钟（protocol.md 第 3 节）
MIN_WINDOW_H = 5.5
RISE_GRACE_MIN = 15                 # 起床晚不过 15 分钟算守住
BED_GRACE_MIN = 10                  # 上床早不过 10 分钟算守住（设备记的入睡时间有误差）
LONG_LATENCY = ("30–60", "1 小时+")

# 零件 value / stat 能绑的数：cbti.<名字> → (显示的字段, 单位, 默认小标题)
SCALARS = ("efficiency", "efficiency_last", "kept", "window", "week", "review_in", "suggest", "early", "late",
           "rise_dev", "diary", "breaks", "in_bed", "asleep", "awake", "to_bed", "ge90")


def _m(hm: str | None) -> int | None:
    """"HH:MM" → 分钟（0–1439）"""
    if not hm or not re.match(r"^\d{1,2}:\d{2}$", str(hm)):
        return None
    h, mm = str(hm).split(":")
    return int(h) * 60 + int(mm)


def _night_m(hm: str | None) -> int | None:
    """上床这类跨午夜的时刻：从中午 12 点起算的分钟，23:40 < 00:10"""
    v = _m(hm)
    return None if v is None else (v - 720) % 1440


def _hm(minutes: int) -> str:
    minutes %= 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _project(store, day: date) -> dict | None:
    for p in store.projects(active_only=True):
        if not str(p.get("id", "")).startswith("cbti") or p.get("board") != "sleep":
            continue
        start = date.fromisoformat(p["start"])
        if start <= day < start + timedelta(days=int(p.get("days") or 42)):
            return p
    return None


def _rx(cfg, p: dict) -> dict:
    """处方：sleep.cbti 记下的为准；没记就从项目模板里读（起床在 rules，最早上床在「上床」那项的时间）"""
    from .agent_context import AgentContextStore
    entries = AgentContextStore(cfg).snapshot()["entries"]
    pid = p["id"]
    for scope in (f"sleep.{pid}", "sleep.cbti"):
        e = next((e for e in reversed(entries) if e.get("scope") == scope), None)
        pl = (e or {}).get("payload") or {}
        if pl.get("wake") and pl.get("earliest_bed"):
            return {"wake": pl["wake"], "earliest_bed": pl["earliest_bed"], "window_h": pl.get("window_h"),
                    "history": [h for h in pl.get("history") or [] if isinstance(h, dict)]}
    wake = next((m.group(1) for r in p.get("rules") or [] for m in [re.search(r"(\d{1,2}:\d{2}) ?起床", str(r))] if m), None)
    bed = next((d.get("when") for d in p.get("daily") or [] if d.get("key") == "bed" or d.get("auto") == "bedtime"), None)
    if not (wake and bed):
        return {}
    return {"wake": wake, "earliest_bed": bed, "window_h": None, "history": []}


def _window_h(rx: dict) -> float | None:
    if rx.get("window_h"):
        return round(float(rx["window_h"]), 2)
    w, b = _m(rx.get("wake")), _m(rx.get("earliest_bed"))
    if w is None or b is None:
        return None
    return round(((w - b) % 1440) / 60, 2)


def _diaries(store, p: dict, day: date, nights: int) -> dict[str, dict]:
    """近 N 天的日记（按日记那天 = 头一晚的第二天）：{日期: values}"""
    out = {}
    for i in range(nights):
        d = day - timedelta(days=i)
        for t in store.for_date(d, "sleep"):
            if t.get("project") == p["id"] and str(t["id"]).endswith("-diary") and t.get("status") == "done":
                out[d.isoformat()] = ((t.get("record") or {}).get("values") or {})
    return out


def _median(xs: list[float]) -> int | None:
    return int(round(statistics.median(xs))) if xs else None


def _decision(n: int, ge90: int, lt85: int, long_lat: int, diary: int, breaks: int, window_h: float | None) -> tuple[str, str]:
    """周复盘调窗口（protocol.md 第 3 节的表，按顺序判断）"""
    if n < 5:
        return "不变", f"有数据的只有 {n} 晚"
    if diary < 5 or breaks >= 3:
        return "不变", "先把执行做到"
    if long_lat >= 3:
        return "不变", f"日记里入睡慢的有 {long_lat} 晚"
    if ge90 * 2 > n:
        return "+15", f"≥90% 的有 {ge90} 晚"
    if lt85 * 2 > n:
        if window_h is not None and window_h <= MIN_WINDOW_H:
            return "不变", "窗口已经最短"
        return "-15", f"<85% 的有 {lt85} 晚"
    return "不变", "效率在 85–89%"


def state(tools, day: date | None = None, now: datetime | None = None) -> dict | None:
    """进行中的 CBT-I 的全部现算状态；没在做就是 None。"""
    from .coach import sleep_week
    from .todos import TodoStore
    now = now or tools._now()
    day = day or day_of(now)
    store = TodoStore(tools.cfg)
    p = _project(store, day)
    if not p:
        return None
    rx = _rx(tools.cfg, p)
    start = date.fromisoformat(p["start"])
    days_total = int(p.get("days") or 42)
    day_n = (day - start).days + 1
    week = (day_n - 1) // 7 + 1
    weeks = math.ceil(days_total / 7)
    window_h = _window_h(rx)
    out: dict[str, Any] = {
        "project": {"id": p["id"], "name": p.get("name") or "CBT-I", "day": day_n, "days": days_total,
                    "week": week, "weeks": weeks},
        "rx": {"wake": rx.get("wake"), "earliest_bed": rx.get("earliest_bed"), "window_h": window_h},
    }
    eb = _m(rx.get("earliest_bed"))
    if eb is not None:
        out["rx"]["caffeine_cutoff"] = _hm(eb - 8 * 60)
        out["rx"]["winddown"] = _hm(eb - 60)

    span = max(7, min(day_n - 1, 42))
    rows = sleep_week(tools, span, day)["nights"]
    last7 = rows[-7:]
    diaries = _diaries(store, p, day, 8)
    wake_m, bed_m = _m(rx.get("wake")), _night_m(rx.get("earliest_bed"))
    nights, eff7, early, late, devs = [], [], 0, 0, []
    for r in last7:
        e = r.get("efficiency_pct")
        bed, rise = r.get("start"), r.get("end")
        kept_bed = kept_rise = None
        if bed and bed_m is not None:
            kept_bed = _night_m(bed) >= bed_m - BED_GRACE_MIN
            early += 0 if kept_bed else 1
        if rise and wake_m is not None:
            dv = _m(rise) - wake_m
            kept_rise = dv <= RISE_GRACE_MIN
            late += 0 if kept_rise else 1
            devs.append(abs(dv))
        if e is not None:
            eff7.append(float(e))
        nights.append({"night_of": r["night_of"], "bed": bed, "rise": rise,
                       "efficiency": int(round(float(e))) if e is not None else None,
                       "kept": None if kept_bed is None and kept_rise is None else bool(kept_bed is not False and kept_rise is not False)})
    have = [n for n in nights if n["kept"] is not None]
    kept = sum(1 for n in have if n["kept"])
    missed_out = sum(1 for v in diaries.values() if v.get("out") == "没下床")
    long_lat = sum(1 for v in diaries.values() if v.get("latency") in LONG_LATENCY)
    diary_n = sum(1 for i in range(7) if (day - timedelta(days=i)).isoformat() in diaries)
    breaks = early + late + missed_out
    bands = {"ge90": sum(1 for e in eff7 if e >= EFF_ADD), "85_89": sum(1 for e in eff7 if EFF_CUT <= e < EFF_ADD),
             "lt85": sum(1 for e in eff7 if e < EFF_CUT), "no_data": 7 - len(eff7)}
    prev7 = [float(r["efficiency_pct"]) for r in rows[-14:-7] if r.get("efficiency_pct") is not None]
    out["nights"] = nights
    out["efficiency"] = {"median_7n": _median(eff7), "median_prev_7n": _median(prev7),
                         "last": nights[-1]["efficiency"] if nights else None,
                         "last_night_of": nights[-1]["night_of"] if nights else None,
                         "nights_with_data": len(eff7), "bands": bands}
    out["adherence"] = {"kept": kept, "nights": len(have), "early_bed": early, "late_rise": late,
                        "rise_dev_min": int(round(sum(devs) / len(devs))) if devs else None,
                        "missed_out_of_bed": missed_out, "diary": diary_n, "breaks": breaks}
    lr = last7[-1] if last7 else {}
    if lr.get("in_bed_h") and lr.get("asleep_h"):
        awake = max(0.0, float(lr["in_bed_h"]) - float(lr["asleep_h"]))
        out["last_night"] = {"night_of": lr["night_of"], "bed": lr.get("start"), "rise": lr.get("end"),
                             "in_bed_h": round(float(lr["in_bed_h"]), 1), "asleep_h": round(float(lr["asleep_h"]), 1),
                             "awake_in_bed_min": int(round(awake * 60)),
                             "efficiency": nights[-1]["efficiency"] if nights else None}
    suggest, reason = _decision(len(eff7), bands["ge90"], bands["lt85"], long_lat, diary_n, breaks, window_h)
    reviews = sorted(r["date"] for r in p.get("reviews") or [] if r.get("date", "") >= day.isoformat())
    nxt = date.fromisoformat(reviews[0]) if reviews else day + timedelta(days=(6 - day.weekday()) % 7)
    out["review"] = {"next": nxt.isoformat(), "in_days": (nxt - day).days, "today": nxt == day,
                     "suggest": suggest, "reason": reason}
    # 每周一行：窗口、那周效率中位、那周的决定（sleep.cbti.history 里记的）
    hist = {int(h["week"]): h for h in rx.get("history") or [] if str(h.get("week", "")).isdigit()}
    weeks_rows = []
    # 新一周的第一天还没有数据：表只列到刚过完的那周（周日复盘看的就是它）
    last_week = week - 1 if week > 1 and (day - start).days % 7 == 0 else week
    for k in range(1, last_week + 1):
        ws, we = start + timedelta(days=7 * (k - 1)), start + timedelta(days=7 * k - 1)
        effs = [float(r["efficiency_pct"]) for r in rows
                if r.get("efficiency_pct") is not None and ws <= date.fromisoformat(r["night_of"]) <= we]
        h = hist.get(k) or {}
        # 记下了决定的周用当时的窗口；还没记的（这周、刚过完等复盘的那周）窗口就是现在的处方
        weeks_rows.append({"week": k, "window_h": h.get("window_h") or window_h,
                           "median": _median(effs), "decision": h.get("decision")})
    out["weeks"] = weeks_rows
    stable = len(rx.get("history") or []) >= 2 and all(str(h.get("decision")) in ("不变", "0", "+0")
                                                         for h in (rx.get("history") or [])[-2:])
    out["phase"] = ("适应期" if week <= 2 else "收尾" if day_n > days_total - 7
                    else "维持期" if stable and week >= 4 else "调整期")
    # 今晚：离最早上床还有多久（中午以后到上床前才有）
    if eb is not None and now.hour >= 12:
        mins = (eb - (now.hour * 60 + now.minute)) % 1440
        if mins <= 12 * 60:
            out["tonight"] = {"minutes_to_bed": mins, "to_bed_text": f"{mins // 60}:{mins % 60:02d}"}
    med, prev = out["efficiency"]["median_7n"], out["efficiency"]["median_prev_7n"]
    if (med is not None and med < EFF_CUT and (prev is None or prev < EFF_CUT)) or breaks >= 3:
        level = "act"
    elif (med is not None and med < EFF_ADD) or breaks >= 1:
        level = "watch"
    else:
        level = "steady"
    out["level"] = level
    return out


def scalar(st: dict, field: str) -> dict:
    """零件 bind cbti.<field> 的显示值：{text, unit, label}"""
    eff, adh, ln, rv = st.get("efficiency") or {}, st.get("adherence") or {}, st.get("last_night") or {}, st.get("review") or {}

    def need(v, what):
        if v is None:
            raise ValueError(f"CBT-I 的{what}现在没有数")
        return v
    if field == "efficiency":
        return {"text": str(need(eff.get("median_7n"), "效率")), "unit": "%", "label": "近 7 晚效率中位"}
    if field == "efficiency_last":
        return {"text": str(need(eff.get("last"), "昨晚效率")), "unit": "%", "label": "昨晚效率"}
    if field == "ge90":
        return {"text": str(eff.get("bands", {}).get("ge90", 0)), "unit": f"/ {eff.get('nights_with_data') or 7}",
                "label": "≥90% 的晚"}
    if field == "kept":
        return {"text": str(adh.get("kept", 0)), "unit": f"/ {need(adh.get('nights') or None, '守窗口')} 晚", "label": "守住窗口"}
    if field == "window":
        w = need((st.get("rx") or {}).get("window_h"), "窗口")
        return {"text": f"{w:g}", "unit": "小时", "label": "窗口"}
    if field == "week":
        pr = st["project"]
        return {"text": f"第 {pr['week']} 周", "unit": f"/ {pr['weeks']} 周", "label": "CBT-I"}
    if field == "review_in":
        return ({"text": "今天", "unit": "", "label": "复盘"} if rv.get("today")
                else {"text": str(rv.get("in_days")), "unit": "天后", "label": "复盘"})
    if field == "suggest":
        s = rv.get("suggest") or "不变"
        return {"text": s.replace("-", "−"), "unit": "" if s == "不变" else "分", "label": "复盘建议"}
    if field == "early":
        return {"text": str(adh.get("early_bed", 0)), "unit": "晚", "label": "早上床"}
    if field == "late":
        return {"text": str(adh.get("late_rise", 0)), "unit": "晚", "label": "起晚"}
    if field == "rise_dev":
        return {"text": f"±{need(adh.get('rise_dev_min'), '起床偏差')}", "unit": "分", "label": "起床偏差"}
    if field == "diary":
        return {"text": str(adh.get("diary", 0)), "unit": "/ 7", "label": "日记"}
    if field == "breaks":
        return {"text": str(adh.get("breaks", 0)), "unit": "次", "label": "这周破例"}
    if field == "in_bed":
        return {"text": f"{need(ln.get('in_bed_h'), '在床时间'):.1f}", "unit": "小时", "label": "在床"}
    if field == "asleep":
        return {"text": f"{need(ln.get('asleep_h'), '睡着时间'):.1f}", "unit": "小时", "label": "睡着"}
    if field == "awake":
        return {"text": str(need(ln.get("awake_in_bed_min"), "床上醒着")), "unit": "分", "label": "床上醒着"}
    if field == "to_bed":
        t = need(st.get("tonight"), "离上床时间")
        return {"text": t["to_bed_text"], "unit": "", "label": "离最早上床"}
    raise ValueError(f"cbti.{field} 不认识")


def lastnight_items(st: dict) -> tuple[list[dict], str]:
    """stack 零件 bind cbti.lastnight：昨晚在床拆成 睡着 / 醒着"""
    ln = st.get("last_night")
    if not ln:
        raise ValueError("昨晚的在床时间还没出来")
    awake_h = ln["awake_in_bed_min"] / 60
    return ([{"label": "睡着", "value": ln["asleep_h"]}, {"label": "醒着", "value": round(awake_h, 2)}],
            f"在床 {ln['in_bed_h']:.1f} 小时")


def weeks_table(st: dict) -> dict:
    """table 零件 bind cbti.weeks：每周 窗口 / 效率中位 / 调整"""
    rows = []
    rv = st.get("review") or {}
    weeks = st.get("weeks") or []
    for i, w in enumerate(weeks):
        win = f"{w['window_h']:g}h" if w.get("window_h") else "—"
        med = f"{w['median']}%" if w.get("median") is not None else "—"
        if w.get("decision"):
            dec = "不变" if str(w["decision"]) in ("不变", "0", "+0") else f"{str(w['decision']).replace('-', '−')}分"
        elif i == len(weeks) - 1:          # 最后一行：等复盘的那周
            dec = "今天" if rv.get("today") else f"{rv.get('in_days')}天后"
        else:
            dec = "—"
        rows.append([f"第 {w['week']} 周", win, med, dec])
    if not rows:
        raise ValueError("CBT-I 还没有满一周")
    return {"columns": ["", "窗口", "效率", "调整"], "rows": rows[-5:]}
