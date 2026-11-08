"""开放画布的新零件（占比 / 时间 / 趋势 / 进度四组）：校验规范化、估算高度、内核现算。

公开入口仍在 canvas.py（validate / estimate / resolve / PARTS）；这里只放每个零件的三件事：
  NORMALIZERS[t](node, ck) -> dict   校验 + 规范化（ck = 手写数字检查，主卡里数字要能在证据里找到）
  ESTIMATES[t](n) -> int             估算高度（px，按 312 宽）
  RESOLVERS[t](ctx, n) -> dict       绑定数据现算成显示值（缺数据抛 VizUnavailable / KeyError，整格换成一行说明）
所有颜色由 App 定，这里只给语义（on / state / level / peak …）。日期写 M/D，时间 HH:MM，分钟 32′。
"""
from __future__ import annotations

import math
import re
import statistics
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import viz as vizmod
from .canvas import CanvasError, _check_bind

TITLE, LABEL, CAPTION, ITEM = 18, 14, 40, 20        # 标题类 / 标签 / 说明 / 列表项最多几个字
SERIES_METRICS = ("hrv", "resp_rate", "resting_hr", "recovery", "sleep", "steps", "weight")
COMPARE_METRICS = ("sleep", "steps", "hrv", "resting_hr", "recovery")
SHORT = {"hrv": "HRV", "resp_rate": "呼吸", "resting_hr": "静息心率", "recovery": "恢复", "sleep": "睡眠",
         "steps": "步数", "weight": "体重"}
AXIS = {"hrv": "HRV", "resp_rate": "呼吸频率", "resting_hr": "静息心率", "recovery": "恢复", "sleep": "睡了几小时",
        "steps": "步数", "weight": "体重"}
WEEKDAY = "一二三四五六日"
MINUS = "−"
STAGE_LABELS = ("深睡", "快速眼动", "浅睡", "清醒")
ZONE_KEYS = ("zone_zero_milli", "zone_one_milli", "zone_two_milli", "zone_three_milli", "zone_four_milli",
             "zone_five_milli")
ZONE_ROWS = ("Z1 很轻松", "Z2 轻松", "Z3 中等", "Z4 吃力", "Z5 极限")
SPORT_CN = {"tennis": "网球", "running": "跑步", "run": "跑步", "cycling": "骑行", "walking": "走路", "hiking": "徒步",
            "swimming": "游泳", "yoga": "瑜伽", "basketball": "篮球", "badminton": "羽毛球", "soccer": "足球",
            "weightlifting": "力量", "functional-fitness": "力量", "strength-trainer": "力量", "pilates": "普拉提",
            "table-tennis": "乒乓球", "rowing": "划船", "elliptical": "椭圆机", "activity": "运动"}
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
BOARDS = ("now", "sleep", "sport", "stress", "life")


# ---------------------------------------------------------------- 小工具
def _s(node: dict, key: str, limit: int, where: str, ck=None, required: bool = False) -> str:
    v = node.get(key)
    if v is None or str(v).strip() == "":
        if required:
            raise CanvasError(f"{where} 要有 {key}")
        return ""
    s = str(v).strip()
    if len(s) > limit:
        raise CanvasError(f"{where} 的 {key} 最多 {limit} 个字（现在 {len(s)} 个）：缩短一点，长内容放到对话里说")
    if ck:
        ck(s, where)
    return s


def _w(s: str) -> float:
    """格子里的字数：中文算 1 个，英文、数字、符号算半个（tag / stepper / kv / table 这类窄格子用）。"""
    return sum(1 if unicodedata.east_asian_width(c) in ("W", "F") else 0.5 for c in s)


def _cell(v: Any, limit: int, where: str, ck=None, required: bool = True) -> str:
    s = str(v if v is not None else "").strip()
    if required and not s:
        raise CanvasError(f"{where} 不能是空的")
    if _w(s) > limit:
        raise CanvasError(f"{where} 每格最多 {limit} 个字（英文、数字算半个；「{s[:12]}」太长）")
    if ck and s:
        ck(s, where)
    return s


def _short(s: str, n: int) -> str:
    """长句截短：先在逗号处断，断不开再加省略号。"""
    s = str(s or "").strip()
    if len(s) <= n:
        return s
    cut = max(s.rfind(p, 0, n) for p in "，、；。,")
    return s[:cut] if cut > 4 else s[:n - 1] + "…"


def _todo_text(t: dict) -> str:
    """待办显示成「HH:MM 标题」；标题本身以时间开头（「01:30 后再上床」）就不再重复。"""
    when, title = t.get("when") or "", t["title"]
    return title if not when or title.startswith(when) else f"{when} {title}"


def _int(node: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(node.get(key, default) if node.get(key) is not None else default)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _hhmm(v: Any, where: str) -> str:
    m = HHMM.match(str(v or "").strip())
    if not m:
        raise CanvasError(f"{where} 要写成 HH:MM（例如 01:30）")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _number(v: Any, where: str, ck=None) -> float:
    if isinstance(v, bool):
        raise CanvasError(f"{where} 要是数字")
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        raise CanvasError(f"{where} 要是数字") from None
    if ck:
        ck(str(v), where)
    return f


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _hod(dt: datetime) -> float:
    """一天里的第几小时（0–24）。"""
    return round(dt.hour + dt.minute / 60 + dt.second / 3600, 2)


def _nh(dt: datetime) -> float:
    """按「从中午算起」的小时：00:30 记成 24.5，方便跨午夜画作息。"""
    h = dt.hour + dt.minute / 60
    return h + 24 if dt.hour < 12 else h


def _hm_to_h(hm: str) -> float:
    h, m = hm.split(":")
    return round(int(h) + int(m) / 60, 2)


def _fmt(metric: str, v: float | None) -> str:
    if v is None:
        return "—"
    if metric == "steps":
        return f"{int(round(v)):,}"
    return vizmod._text(v, vizmod.METRICS[metric]["nd"])


def _rnd(metric: str, v: float | None):
    return vizmod._r(v, vizmod.METRICS[metric]["nd"]) if v is not None else None


def _signed(v: float, nd: int, comma: bool = False) -> str:
    body = f"{abs(v):,.{nd}f}" if comma else f"{abs(v):.{nd}f}"
    if round(v, nd) == 0:
        return body
    return ("+" if v > 0 else MINUS) + body


def _dur_text(minutes: float) -> str:
    if minutes < 60:
        return f"{int(round(minutes))} 分钟"
    h = minutes / 60
    return f"{h:.0f} 小时" if abs(h - round(h)) < 0.05 else f"{h:.1f} 小时"


def _pcts(values: list[float]) -> list[int]:
    """百分比取整后加起来正好 100（最大余数法）。"""
    total = sum(values)
    if total <= 0:
        return [0 for _ in values]
    raw = [v / total * 100 for v in values]
    out = [int(math.floor(r)) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)[:100 - sum(out)]:
        out[i] += 1
    return out


def _nice_step(x: float) -> float:
    if x <= 0:
        return 1.0
    k = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * k >= x - 1e-9:
            return m * k
    return 10 * k


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1
    step = _nice_step(v / 4)
    return round(math.ceil(v / step - 1e-9) * step, 2)


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _clean_name(name: str) -> str:
    return re.sub(r"\s*[·・]\s*\d+\s*[天周]$", "", str(name or "")).strip()


def _pid(b: str) -> str:
    return b.split(":", 1)[1]


def _items_num(node: dict, ck, where: str, lo: int, hi: int) -> list[dict]:
    items = node.get("items")
    if not isinstance(items, list) or not lo <= len(items) <= hi:
        raise CanvasError(f"{where} 要么写 bind，要么手写 items（{lo}–{hi} 项，每项 {{\"label\":…,\"value\":数字}}）")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise CanvasError(f"{where} 的 items 每项要是 {{\"label\":…,\"value\":数字}}")
        label = _s(it, "label", LABEL, where, ck, required=True)
        val = _number(it.get("value"), f"{where} 的 value", ck)
        if val < 0:
            raise CanvasError(f"{where} 的 value 不能是负数")
        out.append({"label": label, "value": val, "text": str(it.get("value")).strip()})
    return out


# ---------------------------------------------------------------- 取数（每张卡一份缓存）
class Ctx:
    def __init__(self, tools, day: date, now: datetime, board: str | None, vz: Callable) -> None:
        self.tools, self.day, self.now, self.board, self.vz = tools, day, now, board, vz
        self._memo: dict[str, Any] = {}

    def memo(self, key: str, fn: Callable):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tools.cfg.timezone)

    @property
    def yday(self) -> date:
        return self.day - timedelta(days=1)


def _whoop_sleep(ctx: Ctx) -> dict[date, dict]:
    def f():
        from .whoop import sleep_by_night
        snap = ctx.tools._whoop
        return sleep_by_night(snap, ctx.tools.cfg.timezone) if snap else {}
    return ctx.memo("wsleep", f)


def _need_of(w: dict | None) -> float | None:
    from .quality import night_need
    return night_need(w)


def _nights(ctx: Ctx, days: int) -> list[dict]:
    """近 N 晚（入睡那晚 ≤ 昨晚）：slept / need / ok。WHOOP 优先；断了用 Apple 健康的时长（没有 need，不编）。
    ok 和 dots / columns 一样：睡了 ≥ 需要 − 0.5 小时算睡够；没有 need 的晚上 ok=None（不知道）。"""
    def f():
        from .pages import V2Pages
        raw = V2Pages(ctx.tools)._nights(ctx.day, days + 1)
        out = []
        for nd in sorted(raw):
            n = raw[nd]
            if nd > ctx.yday or nd <= ctx.day - timedelta(days=days + 1) or n.get("asleep_h") is None:
                continue
            need = _need_of(n) if n.get("source") != "apple_health" else None
            slept = float(n["asleep_h"])
            out.append({"date": nd, "slept": slept, "need": need, "ok": (slept >= need - 0.5) if need else None})
        return out
    return ctx.memo(f"nights{days}", f)


def _apple_night(ctx: Ctx, nd: date) -> list[tuple[datetime, datetime, str]]:
    """Apple Watch 这一晚的分期片段（和睡眠重建同一套：只取夜间主链、平行轨取最长的那条）。"""
    def f():
        from .readonly import parse_ts
        from .sleep import STAGED, _classify, _partition_tracks
        try:
            rows = ctx.tools._rows(nd)
        except Exception:  # noqa: BLE001 —— 这一晚读不出来就当没有
            return []
        segs = []
        for r in rows:
            cat = str(r.get("category_value") or "")
            if r.get("type") != "sleep_analysis" or cat not in STAGED:
                continue
            try:
                s = parse_ts(str(r["start_at"])).astimezone(ctx.tz)
                e = parse_ts(str(r["end_at"])).astimezone(ctx.tz)
            except Exception:  # noqa: BLE001
                continue
            if e > s:
                segs.append((s, e, cat))
        night, _ = _classify(segs)
        tracks = _partition_tracks(night)
        if not tracks:
            return []
        canon = max(tracks, key=lambda tr: (sum((e - s).total_seconds() for s, e, c in tr if c != "awake"), len(tr)))
        return sorted(canon)
    return ctx.memo(f"apple{nd}", f)


def _apple_stage_hours(segs) -> dict[str, float]:
    out = {"deep": 0.0, "rem": 0.0, "core": 0.0, "awake": 0.0}
    for s, e, c in segs:
        k = "awake" if c == "awake" else c[len("asleep_"):]
        out[k] = out.get(k, 0.0) + (e - s).total_seconds() / 3600
    return out


def _night_times(ctx: Ctx, nd: date, onset: bool = False) -> tuple[datetime, datetime] | None:
    """这一晚几点入睡 / 起床：WHOOP 的 start / end；没有就用 Apple Watch 片段（onset=True 时从第一段睡着算）。"""
    w = _whoop_sleep(ctx).get(nd)
    if w and w.get("start_local") and w.get("end_local"):
        return datetime.fromisoformat(w["start_local"]), datetime.fromisoformat(w["end_local"])
    segs = _apple_night(ctx, nd)
    if not segs:
        return None
    asleep = [x for x in segs if x[2] != "awake"] or segs
    start = asleep[0][0] if onset else segs[0][0]
    return start, max(e for _, e, _ in segs)


def _shift(ctx: Ctx, metric: str) -> int:
    """WHOOP 的晨间指标按「睡的那晚」记日期（11/4 那条是 11/5 早上测的），换成发生的日子要 +1。"""
    if metric in ("hrv", "recovery"):
        return 1
    if metric in ("resting_hr", "resp_rate"):
        series = vizmod.METRICS[metric]["series"]
        try:
            return 1 if ctx.tools.series_source(series, ctx.day, 30) == "whoop" else 0
        except Exception:  # noqa: BLE001
            return 0
    return 0


def _series(ctx: Ctx, metric: str, days: int, complete: bool = True) -> list[tuple[date, float]]:
    """某项每天一个数，取到最新那天为止的 N 天窗口。步数默认不含今天（今天还没走完）。"""
    def f():
        if metric == "sleep":
            vals = [(n["date"], n["slept"]) for n in _nights(ctx, days + 10)]
        else:
            m = vizmod.METRICS[metric]
            end = ctx.yday if (complete and metric == "steps") else ctx.day
            daily = ctx.tools.daily_series(m["series"], ctx.day, days + 10)
            vals = sorted((d, float(v)) for d, v in daily.items() if v is not None and d <= end)
        if not vals:
            return []
        last = vals[-1][0]
        return [(d, v) for d, v in vals if d > last - timedelta(days=days)]
    return ctx.memo(f"series{metric}{days}{complete}", f)


def _by_date(ctx: Ctx, metric: str, start: date, end: date) -> dict[date, float]:
    if metric == "sleep":
        span = (ctx.day - start).days + 1
        return {n["date"]: n["slept"] for n in _nights(ctx, span) if start <= n["date"] <= end}
    daily = ctx.tools.daily_series(vizmod.METRICS[metric]["series"], end, (end - start).days + 1)
    return {d: float(v) for d, v in daily.items() if v is not None and start <= d <= end and d <= ctx.day}


def _steps_goal(ctx: Ctx) -> int:
    try:
        pref = vizmod.prefs_for(ctx.tools.cfg).get("steps", {})
        return int(vizmod._num(pref, "goal") or vizmod.STEPS_GOAL)
    except Exception:  # noqa: BLE001
        return vizmod.STEPS_GOAL


def _store(ctx: Ctx):
    from .todos import TodoStore
    return ctx.memo("store", lambda: TodoStore(ctx.tools.cfg))


def _projects(ctx: Ctx, active_only: bool = False) -> list[dict]:
    ps = ctx.memo("projects", lambda: _store(ctx).projects())
    return [p for p in ps if p.get("status") == "active"] if active_only else ps


def _todos_on(ctx: Ctx, d: date, board: str | None = None) -> list[dict]:
    """同 TodoStore.for_date，但一张卡只读一次待办文件。"""
    from .todos import sort_key
    allt = ctx.memo("todos", lambda: list(_store(ctx).snapshot()["todos"].values()))
    return sorted((t for t in allt if t["date"] == d.isoformat() and (board is None or t["board"] == board)), key=sort_key)


def _project(ctx: Ctx, pid: str) -> dict:
    p = next((p for p in _projects(ctx) if p["id"] == pid), None)
    if not p:
        raise KeyError(f"没有项目 {pid}")
    return p


def _proj_todos(ctx: Ctx, p: dict, d: date) -> list[dict]:
    return [t for t in _todos_on(ctx, d, p["board"]) if t.get("project") == p["id"]]


def _cbti(ctx: Ctx, pid: str = "cbti") -> dict:
    from .agent_context import AgentContextStore
    entries = AgentContextStore(ctx.tools.cfg).snapshot()["entries"]
    for scope in (f"sleep.{pid}",) + (("sleep.cbti",) if "cbti" in pid else ()):
        e = next((e for e in reversed(entries) if e.get("scope") == scope), None)
        p = (e or {}).get("payload") or {}
        if p.get("wake") and p.get("earliest_bed"):
            return p
    raise KeyError("还没有 CBT-I 窗口（sleep.cbti）")


def _workouts(ctx: Ctx) -> list[dict]:
    def f():
        from .readonly import parse_ts
        out = []
        for w in (ctx.tools._whoop or {}).get("workout") or []:
            try:
                s = parse_ts(str(w["start"])).astimezone(ctx.tz)
                e = parse_ts(str(w["end"])).astimezone(ctx.tz)
            except Exception:  # noqa: BLE001
                continue
            zd = (w.get("score") or {}).get("zone_durations") or {}
            zones = [float(zd.get(k) or 0) / 60000 for k in ZONE_KEYS] if any(zd.get(k) for k in ZONE_KEYS) else None
            name = str(w.get("sport_name") or "").lower()
            out.append({"start": s, "end": e, "sport": SPORT_CN.get(name, name or "训练"), "zones": zones,
                        "minutes": (e - s).total_seconds() / 60})
        return sorted(out, key=lambda x: x["start"])
    return ctx.memo("workouts", f)


def _day_word(ctx: Ctx, d: date) -> str:
    if d == ctx.day:
        return "今天"
    if d == ctx.yday:
        return "昨天"
    if ctx.day - d < timedelta(days=7):
        return "周" + WEEKDAY[d.weekday()]
    return _md(d)


# ---------------------------------------------------------------- 占比与构成
def _composition(ctx: Ctx, b: str) -> tuple[list[dict], str, str]:
    """sleep.stages / training.zones → (items[{label,value}], 单位 h|min, 一句说明)。"""
    if b == "sleep.stages":
        for nd in (ctx.yday, ctx.yday - timedelta(days=1), ctx.yday - timedelta(days=2)):
            w = _whoop_sleep(ctx).get(nd) or {}
            st = w.get("stages_h") or {}
            vals = [st.get("slow_wave"), st.get("rem"), st.get("light"), st.get("awake")]
            if all(v is not None for v in vals):
                break
            segs = _apple_night(ctx, nd)
            if segs:
                h = _apple_stage_hours(segs)
                vals = [h["deep"], h["rem"], h["core"], h["awake"]]
                break
        else:
            raise vizmod.VizUnavailable("最近 3 晚没有睡眠分期")
        items = [{"label": lab, "value": round(float(v), 2)} for lab, v in zip(STAGE_LABELS, vals)]
        asleep = sum(i["value"] for i in items[:3])
        when = "昨晚" if nd == ctx.yday else f"{_md(nd)} 那晚"
        return items, "h", f"{when} {asleep:.1f} 小时"
    if b == "training.zones":
        ws = [w for w in _workouts(ctx) if w["zones"] and ctx.day - timedelta(days=6) <= w["start"].date() <= ctx.day]
        if not ws:
            raise vizmod.VizUnavailable("近 7 天的训练没有心率区间")
        z = [sum(w["zones"][i] for w in ws) for i in range(6)]
        items = [{"label": "轻松", "value": round(z[0] + z[1] + z[2])}, {"label": "中等", "value": round(z[3])},
                 {"label": "高强度", "value": round(z[4] + z[5])}]
        return items, "min", f"近 7 天 {len(ws)} 次训练 · {_dur_text(sum(w['minutes'] for w in ws))}"
    raise KeyError(b)


def n_pie(node, ck, t):
    out: dict[str, Any] = {"t": t}
    if node.get("bind"):
        out["bind"] = _check_bind(str(node["bind"]), ("stages",))
    else:
        out["items"] = _items_num(node, ck, t, 2, 5)
    center = _s(node, "center", LABEL, t, ck)
    if center:
        out["center"] = center
    return out


def r_pie(ctx, n):
    if "bind" in n:
        items, unit, caption = _composition(ctx, n["bind"])
        for i in items:
            i["text"] = f"{i['value']:.1f} 小时" if unit == "h" else _dur_text(i["value"])
    else:
        items, caption = [dict(i) for i in n["items"]], None
    if sum(i["value"] for i in items) <= 0:
        raise vizmod.VizUnavailable("全是 0，画不了占比")
    for i, p in zip(items, _pcts([i["value"] for i in items])):
        i["pct"] = p
    center_text = center_sub = None
    if n["t"] == "donut" or n.get("center"):
        pick = next((i for i in items if i["label"] == n.get("center")), None) or max(items, key=lambda i: i["value"])
        center_text, center_sub = f"{pick['pct']}%", pick["label"]
    return {"items": items, "center_text": center_text, "center_sub": center_sub, "caption": caption}


def n_stack(node, ck, t):
    out = n_pie(node, ck, t)
    out.pop("center", None)
    title = _s(node, "title", TITLE, t, ck)
    if title:
        out["title"] = title
    return out


def r_stack(ctx, n):
    if "bind" in n:
        items, unit, title = _composition(ctx, n["bind"])
        for i in items:
            i["text"] = f"{i['value']:.1f}" if unit == "h" else f"{int(round(i['value']))}′"
    else:
        items, title = [dict(i) for i in n["items"]], None
    total = sum(i["value"] for i in items)
    if total <= 0:
        raise vizmod.VizUnavailable("全是 0，画不了构成")
    for i in items:
        i["frac"] = round(i["value"] / total, 3)
    return {"title": n.get("title") or title, "items": items}


def n_stack_columns(node, ck, t):
    b = str(node.get("bind") or "sleep.stages").strip()
    if b != "sleep.stages":
        raise CanvasError("stack_columns 的 bind 只能是 sleep.stages（每晚一根柱，里面是深睡 / 快速眼动 / 浅睡）")
    return {"t": t, "bind": b, "days": _int(node, "days", 7, 3, 14),
            "height": node.get("height") if node.get("height") in ("s", "m") else "s"}


def r_stack_columns(ctx, n):
    cols = []
    for i in range(n["days"], 0, -1):
        nd = ctx.day - timedelta(days=i)
        w = _whoop_sleep(ctx).get(nd) or {}
        st = w.get("stages_h") or {}
        parts = [st.get("slow_wave"), st.get("rem"), st.get("light")]
        ref = _need_of(w) if w else None
        if any(p is None for p in parts):
            segs = _apple_night(ctx, nd)
            if not segs:
                continue
            h = _apple_stage_hours(segs)
            parts, ref = [h["deep"], h["rem"], h["core"]], None
        cols.append({"label": _md(nd), "parts": [round(float(p), 2) for p in parts],
                     "ref": round(ref, 1) if ref else None, "now": nd == ctx.yday})
    if not cols:
        raise vizmod.VizUnavailable("最近没有睡眠分期")
    top = max(max(sum(c["parts"]), c["ref"] or 0) for c in cols)
    caption = "短横线 = 当晚需要" if any(c["ref"] for c in cols) else "深睡在最下面"
    return {"height": n["height"], "keys": list(STAGE_LABELS[:3]), "columns": cols, "max": round(top, 1),
            "caption": caption}


def _daily_ok(ctx: Ctx, b: str, days: int) -> tuple[list[tuple[date, bool]], dict]:
    """每天（每晚）做到没：只返回已经能判断的天（今天还没做到的、没数据的晚上、项目休息日都不算）。"""
    info: dict[str, Any] = {}
    out: list[tuple[date, bool]] = []
    if b == "sleep.nights":
        info.update(unit="晚", label="连续睡够", what="睡够")
        out = [(n["date"], bool(n["ok"])) for n in _nights(ctx, days) if n["ok"] is not None]
    elif b == "steps.week":
        goal = _steps_goal(ctx)
        series = ctx.tools.daily_series("steps", ctx.day, days)
        info.update(unit="天", label=f"连续走够 {goal:,} 步", what=f"走够 {goal:,} 步", goal=goal)
        for i in range(days - 1, -1, -1):
            d = ctx.day - timedelta(days=i)
            v = series.get(d)
            ok = v is not None and v >= goal
            if d == ctx.day and not ok:
                continue
            out.append((d, ok))
    elif b.startswith("project:"):
        p = _project(ctx, _pid(b))
        start = date.fromisoformat(p["start"])
        info.update(unit="天", label=f"{_clean_name(p['name'])[:8]} 连续做到", what="做到", name=_clean_name(p["name"]))
        for i in range(days - 1, -1, -1):
            d = ctx.day - timedelta(days=i)
            if d < start:
                continue
            ts = _proj_todos(ctx, p, d)
            if not ts:
                continue
            ok = all(t["status"] == "done" for t in ts)
            if d == ctx.day and not ok:
                continue
            out.append((d, ok))
    elif b.startswith("wake:"):
        hm = b.split(":", 1)[1]
        limit = _hm_to_h(hm) + 0.25
        info.update(unit="天", label=f"连续 {hm} 起床", what=f"{hm} 起床")
        for i in range(days - 1, -1, -1):
            d = ctx.day - timedelta(days=i)
            tm = _night_times(ctx, d - timedelta(days=1))
            if not tm or tm[1].date() != d or (d == ctx.day and ctx.now < tm[1]):
                continue
            out.append((d, _hod(tm[1]) <= limit))
    else:
        raise KeyError(b)
    return out, info


def n_waffle(node, ck, t):
    return {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("dots",)), "days": _int(node, "days", 30, 7, 60)}


def r_waffle(ctx, n):
    rows, info = _daily_ok(ctx, n["bind"], n["days"])
    if not rows:
        raise vizmod.VizUnavailable("这段时间还没有能判断的天")
    hit = sum(1 for _, ok in rows if ok)
    unit = info["unit"]
    head = f"{info['name']} · " if info.get("name") else ""
    return {"items": [ok for _, ok in rows], "caption": f"{head}近 {len(rows)} {unit}，{hit} {unit}{info['what']}"}


def n_zones(node, ck, t):
    b = str(node.get("bind") or "workout.last").strip()
    if b not in ("workout.last", "workout.week"):
        raise CanvasError("zones 的 bind 只能是 workout.last（最近一次训练）或 workout.week（近 7 天合计）")
    return {"t": t, "bind": b}


def r_zones(ctx, n):
    ws = [w for w in _workouts(ctx) if w["zones"] and w["start"].date() <= ctx.day]
    if n["bind"] == "workout.week":
        ws = [w for w in ws if w["start"].date() >= ctx.day - timedelta(days=6)]
        if not ws:
            raise vizmod.VizUnavailable("近 7 天没有带心率区间的训练")
        title = f"近 7 天 {len(ws)} 次训练 · {int(round(sum(w['minutes'] for w in ws)))} 分钟"
    else:
        if not ws:
            raise vizmod.VizUnavailable("最近的训练没有心率区间")
        ws = ws[-1:]
        w = ws[0]
        title = f"{_day_word(ctx, w['start'].date())} {w['sport']} · {int(round(w['minutes']))} 分钟"
    z = [sum(w["zones"][i] for w in ws) for i in range(6)]
    mins = [z[0] + z[1], z[2], z[3], z[4], z[5]]
    rows = [{"label": lab, "minutes": int(round(m)), "text": f"{int(round(m))}′"} for lab, m in zip(ZONE_ROWS, mins)]
    return {"title": title, "rows": rows, "max": max(1, max(r["minutes"] for r in rows))}


def n_radar(node, ck, t):
    return {"t": t}


# 雷达五维（0–100，本周 = 近 7 天，上周 = 再往前 7 天）：
#   睡眠 = 平均(每晚睡了 / 当晚需要) ×100，每晚封顶 100（只算有「需要」的晚上）
#   恢复 = WHOOP 恢复分数的平均
#   运动 = 平均(每天步数 / 步数目标) ×100，每天封顶 100（不算今天，今天还没走完）
#   压力 = 100 − clamp((个人基线 HRV − 这 7 天平均 HRV) / 基线 × 200, 0, 100)；基线 = WHOOP HRV 近 30 天均值
#   习惯 = 进行中项目的执行率（project-stats 的做到 / 应做，跨项目合计）
#   哪一维没有数就给 null（App 画虚点），不拿别的数顶。
RADAR_AXES = ("睡眠", "恢复", "运动", "压力", "习惯")


def _radar_week(ctx: Ctx, end: date, hrv_base: float | None) -> list[int | None]:
    start = end - timedelta(days=6)
    nights = [n for n in _nights(ctx, (ctx.day - start).days + 2) if start - timedelta(days=1) <= n["date"] <= end -
              timedelta(days=1) and n["need"]]
    sleep = _mean([min(100.0, n["slept"] / n["need"] * 100) for n in nights])
    rec = _by_date(ctx, "recovery", start, end)        # 恢复 / HRV 按醒来那天记，今早的算今天
    recovery = _mean(list(rec.values()))
    goal = _steps_goal(ctx)
    steps = ctx.tools.daily_series("steps", end, (ctx.day - start).days + 2)
    sv = [min(100.0, v / goal * 100) for d, v in steps.items()
          if v is not None and start - timedelta(days=1) <= d <= end - timedelta(days=1)]
    move = _mean(sv)
    hv = _by_date(ctx, "hrv", start, end)
    stress = None
    if hv and hrv_base:
        drop = (hrv_base - _mean(list(hv.values()))) / hrv_base * 200
        stress = 100 - max(0.0, min(100.0, drop))
    done = total = 0
    from .coach import project_stats
    for p in _projects(ctx, active_only=True):
        try:
            st = project_stats(ctx.tools, p["id"], 7, end)
        except ValueError:
            continue
        done += sum(i["done"] for i in st["items"])
        total += sum(i["total"] for i in st["items"])
    habit = done / total * 100 if total else None
    return [None if v is None else int(round(v)) for v in (sleep, recovery, move, stress, habit)]


def r_radar(ctx, n):
    try:
        b = (ctx.tools.baseline("whoop_hrv_rmssd", ctx.day) or {}).get("baseline") or {}
        base = b.get("center")
    except Exception:  # noqa: BLE001
        base = None
    now = _radar_week(ctx, ctx.day, base)
    prev = _radar_week(ctx, ctx.day - timedelta(days=7), base)
    if all(v is None for v in now):
        raise vizmod.VizUnavailable("这周五项都没有数")
    return {"axes": list(RADAR_AXES), "now": now, "prev": prev, "caption": "实线 = 近 7 天 · 虚线 = 再往前 7 天"}


# ---------------------------------------------------------------- 时间与作息
def r_hypnogram(ctx, n):
    segs = _apple_night(ctx, ctx.yday)
    if not segs:
        raise vizmod.VizUnavailable("只有 Apple Watch 的晚上能画")
    start, end = segs[0][0], max(e for _, e, _ in segs)
    name = {"awake": "wake", "asleep_rem": "rem", "asleep_core": "light", "asleep_deep": "deep"}
    out: list[dict] = []
    for s, e, c in segs:
        a = int(round((s - start).total_seconds() / 60))
        b = int(round((e - start).total_seconds() / 60))
        if b <= a:
            continue
        st = name[c]
        if out and out[-1]["stage"] == st and out[-1]["to"] >= a:
            out[-1]["to"] = max(out[-1]["to"], b)
        else:
            out.append({"stage": st, "from": a, "to": b})
    return {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
            "total_min": int(round((end - start).total_seconds() / 60)), "segments": out}


def n_sleep_window(node, ck, t):
    out = {"t": t, "days": _int(node, "days", 7, 3, 14)}
    band = str(node.get("band") or "").strip()
    if band:
        if not band.startswith("project:"):
            raise CanvasError("sleep_window 的 band 只能写 project:<项目 id>（取 sleep.cbti 记下的窗口），不写就自动找 CBT-I")
        out["band"] = band
    return out


def _auto_cbti(ctx: Ctx, band: str | None) -> dict | None:
    try:
        if band:
            return _cbti(ctx, _pid(band))
        if any("cbti" in p["id"] for p in _projects(ctx, active_only=True)):
            return _cbti(ctx)
    except KeyError:
        return None
    return None


def r_sleep_window(ctx, n):
    rows = []
    for i in range(n["days"], 0, -1):
        nd = ctx.day - timedelta(days=i)
        tm = _night_times(ctx, nd)
        if tm:
            rows.append((nd, tm[0], tm[1]))
    if not rows:
        raise vizmod.VizUnavailable("最近没有入睡和起床时间")
    c = _auto_cbti(ctx, n.get("band"))
    hs = [_nh(s) for _, s, _ in rows] + [_nh(e) for _, _, e in rows]
    if c:
        bed, wake = _hm_to_h(c["earliest_bed"]), _hm_to_h(c["wake"])
        hs += [bed + (24 if bed < 12 else 0), wake + (24 if wake < 12 else 0)]
    lo = min(22, math.floor(min(hs)))
    hi = max(34, math.ceil(max(hs)))
    span = hi - lo
    step = 4 if span <= 14 else 6
    out = {"axis_start": lo % 24, "axis_hours": span,
           "rows": [{"label": _md(nd), "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M"),
                     "from": round(_nh(s) - lo, 2), "to": round(_nh(e) - lo, 2), "now": nd == ctx.yday}
                    for nd, s, e in rows],
           "band": None,
           "ticks": [{"at": a, "label": f"{(lo + a) % 24:02d}:00"} for a in range(0, span + 1, step)]}
    if c:
        out["band"] = {"from": round(bed + (24 if bed < 12 else 0) - lo, 2),
                       "to": round(wake + (24 if wake < 12 else 0) - lo, 2),
                       "label": f"CBT-I 窗口 {c['earliest_bed']}–{c['wake']}"}
    return out


def r_clock24(ctx, n):
    arcs: list[dict] = []
    tm = _night_times(ctx, ctx.yday)
    if tm and tm[1].date() == ctx.day:
        arcs.append({"kind": "sleep", "from": _hod(tm[0]), "to": _hod(tm[1]),
                     "label": f"睡眠 {tm[0]:%H:%M}–{tm[1]:%H:%M}"})
    for w in _workouts(ctx):
        if w["start"].date() == ctx.day:
            arcs.append({"kind": "workout", "from": _hod(w["start"]), "to": _hod(w["end"]),
                         "label": f"{w['sport']} {w['start']:%H:%M}–{w['end']:%H:%M}"})
    from .todos import _sort_when
    ts = [t for t in _todos_on(ctx, ctx.day, None if ctx.board in (None, "now") else ctx.board)
          if t.get("when") and t["status"] != "expired"]
    ts.sort(key=lambda t: _sort_when(t["when"]))
    dots = [{"at": _hm_to_h(t["when"]), "label": _todo_text(t)[:14], "done": t["status"] == "done"} for t in ts[:6]]
    if not arcs and not dots:
        raise vizmod.VizUnavailable("今天还没有睡眠、训练和待办")
    return {"arcs": arcs, "dots": dots, "now": _hod(ctx.now)}


def n_calendar(node, ck, t):
    month = str(node.get("month") or "current").strip()
    if month not in ("current", "prev") and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", month):
        raise CanvasError("calendar 的 month 只能是 current / prev / YYYY-MM")
    return {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("dots",)), "month": month}


def r_calendar(ctx, n):
    if n["month"] == "current":
        first = ctx.day.replace(day=1)
    elif n["month"] == "prev":
        first = (ctx.day.replace(day=1) - timedelta(days=1)).replace(day=1)
    else:
        first = date.fromisoformat(n["month"] + "-01")
    nxt = (first + timedelta(days=32)).replace(day=1)
    b = n["bind"]
    level: Callable[[date], int | None]
    if b == "sleep.nights":
        span = max(1, (ctx.day - first).days + 1)
        nights = {x["date"]: x for x in _nights(ctx, span)}

        def level(d):
            x = nights.get(d)
            if not x or not x["need"]:
                return None
            short = x["need"] - x["slept"]
            return 3 if short <= 0.5 else (2 if short < 1 else (1 if short < 2 else 0))
        title, legend = f"{first.month} 月 · 每晚睡够没", ["够了", "差 1 小时内", "差 1–2", "差 2+"]
    elif b == "steps.week":
        goal = _steps_goal(ctx)
        series = ctx.tools.daily_series("steps", min(ctx.day, nxt - timedelta(days=1)), 32)

        def level(d):
            v = series.get(d)
            if v is None or (d == ctx.day and v < goal):
                return None
            f = v / goal
            return 3 if f >= 1 else (2 if f >= 0.75 else (1 if f >= 0.5 else 0))
        title, legend = f"{first.month} 月 · 每天走够没", ["走够了", "差 1/4 内", "差一半内", "不到一半"]
    elif b.startswith("project:"):
        p = _project(ctx, _pid(b))
        start = date.fromisoformat(p["start"])

        def level(d):
            if d < start:
                return None
            ts = _proj_todos(ctx, p, d)
            if not ts:
                return None
            done = sum(1 for t in ts if t["status"] == "done")
            if done == len(ts):
                return 3
            if d == ctx.day:
                return None
            if done:
                return 2
            return 1 if any(t["status"] == "skipped" for t in ts) else 0
        title, legend = f"{first.month} 月 · {_clean_name(p['name'])[:10]}", ["都做了", "做了一部分", "跳过", "没做"]
    else:
        raise KeyError(b)
    days = []
    d = first
    while d < nxt:
        lv = level(d) if (d < ctx.day or (d == ctx.day and b != "sleep.nights")) else None
        days.append({"d": d.day, "level": lv, "today": d == ctx.day})
        d += timedelta(days=1)
    if all(x["level"] is None for x in days):
        raise vizmod.VizUnavailable("这个月还没有数")
    return {"title": title, "first_weekday": first.isoweekday(), "days": days, "legend": legend}


def n_weekgrid(node, ck, t):
    return {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("weekgrid",))}


def r_weekgrid(ctx, n):
    b = n["bind"]
    monday = ctx.day - timedelta(days=ctx.day.weekday())
    cells = []
    if b == "steps":
        goal = _steps_goal(ctx)
        series = ctx.tools.daily_series("steps", ctx.day, 8)
    elif b == "sleep":
        nights = {x["date"]: x for x in _nights(ctx, 8)}
    else:
        p = _project(ctx, _pid(b))
        start = date.fromisoformat(p["start"])
        end = start + timedelta(days=int(p.get("days") or 30) - 1)
    for i in range(7):
        d = monday + timedelta(days=i)
        text, state = "", "future"
        if b == "steps":
            v = series.get(d)
            text = f"{v / 1000:.0f}k" if v is not None and d <= ctx.day else ""
            if d < ctx.day:
                state = "rest" if v is None else ("done" if v >= goal else "missed")
                text = text or "—"
            elif d == ctx.day:
                state = "done" if v is not None and v >= goal else "today"
        elif b == "sleep":
            x = nights.get(d)
            if d < ctx.day:
                if not x:
                    state, text = "rest", "—"
                else:
                    text = f"{x['slept']:.1f}"
                    state = "done" if x["ok"] else ("missed" if x["ok"] is False else "rest")
            elif d == ctx.day:
                state = "today"
        else:
            if d < start or d > end:
                state, text = "rest", ""
            elif d > ctx.day:
                tpl = [x for x in p.get("daily") or [] if not x.get("weekdays") or d.isoweekday() in x["weekdays"]]
                state, text = ("future", tpl[0]["title"][:2] if len(tpl) == 1 else f"{len(tpl)}件") if tpl else ("rest", "休")
            else:
                ts = _proj_todos(ctx, p, d)
                if not ts:
                    state, text = ("today", "") if d == ctx.day else ("rest", "休")
                else:
                    done = sum(1 for t in ts if t["status"] == "done")
                    skipped = sum(1 for t in ts if t["status"] == "skipped")
                    text = ts[0]["title"][:2] if len(ts) == 1 else f"{done}/{len(ts)}"
                    if done == len(ts):
                        state = "done"
                    elif d == ctx.day:
                        state = "today"
                    elif skipped and done + skipped == len(ts):
                        state, text = "skipped", ("跳过" if len(ts) == 1 else text)
                    else:
                        state = "missed"
        cells.append({"label": WEEKDAY[i], "text": text, "state": state})
    return {"days": cells}


def n_streak(node, ck, t):
    b = str(node.get("bind") or "").strip()
    if b.startswith("wake:"):
        return {"t": t, "bind": "wake:" + _hhmm(b[5:], "streak 的 wake")}
    return {"t": t, "bind": _check_bind(b, ("streak",))}


def r_streak(ctx, n):
    rows, info = _daily_ok(ctx, n["bind"], 60)
    if not rows:
        raise vizmod.VizUnavailable("还没有能判断的天")
    count = 0
    for _, ok in reversed(rows):
        if not ok:
            break
        count += 1
    best = run = 0
    for _, ok in rows:
        run = run + 1 if ok else 0
        best = max(best, run)
    unit = info["unit"]
    broke = next((d for d, ok in reversed(rows) if not ok), None)
    if broke is None:
        head = f"近 {len(rows)} {unit}都做到了"
    else:
        k = (ctx.day - broke).days
        head = "今天断了" if k == 0 else ("昨天断了" if k == 1 else f"{k} 天前断过一次")
    return {"count": count, "unit": unit, "label": info["label"], "marks": [ok for _, ok in rows[-14:]],
            "best": best, "caption": f"{head} · 最长 {best} {unit}"}


def n_countdown(node, ck, t):
    to = str(node.get("to") or "").strip()
    if to.startswith("project:"):
        parts = to.split(":")
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise CanvasError("countdown 的 to 写 HH:MM，或 project:<项目 id>:<待办 key>（取那条待办的时间）")
    else:
        to = _hhmm(to, "countdown 的 to")
        if ck:
            ck(to, "countdown")
    out = {"t": t, "to": to, "label": _s(node, "label", LABEL, t, ck) or "还有"}
    sub = _s(node, "sub", CAPTION, t, ck)
    if sub:
        out["sub"] = sub
    return out


def _wake_anchor(ctx: Ctx) -> str:
    try:
        from .params import Params
        w = str(Params(ctx.tools.subj).get("wake_target") or "07:00")
        return _hhmm(w, "wake")
    except Exception:  # noqa: BLE001
        return "07:00"


def r_countdown(ctx, n):
    to, what = n["to"], None
    if to.startswith("project:"):
        _, pid, key = to.split(":")
        p = _project(ctx, pid)
        tpl = next((x for x in p.get("daily") or [] if x.get("key") == key), None)
        if not tpl or not tpl.get("when"):
            raise KeyError(f"{pid} 里没有带时间的 {key}")
        to, what = tpl["when"], tpl["title"]
    now = ctx.now
    hh, mm = (int(x) for x in to.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    from .todos import NIGHT_END_HOUR
    if hh < NIGHT_END_HOUR and now.hour >= NIGHT_END_HOUR:      # 凌晨的点算今晚
        target += timedelta(days=1)
    wh, wm = (int(x) for x in _wake_anchor(ctx).split(":"))
    anchor = now.replace(hour=wh, minute=wm, second=0, microsecond=0)
    if anchor > now:
        anchor -= timedelta(days=1)
    sub = n.get("sub") or ((what if to in what else f"{to} · {what}") if what else f"到 {to}")
    if target <= now:
        return {"label": n["label"], "text": "0:00", "sub": f"已经过了 {to}", "fraction": 1.0, "to": to}
    left = int((target - now).total_seconds() // 60)
    frac = (now - anchor).total_seconds() / max(60.0, (target - anchor).total_seconds())
    return {"label": n["label"], "text": f"{left // 60}:{left % 60:02d}", "sub": sub,
            "fraction": round(max(0.0, min(1.0, frac)), 3), "to": to}


def n_time_range(node, ck, t):
    if node.get("bind"):
        return {"t": t, "bind": _check_bind(str(node["bind"]), ("project",))}
    a = _hhmm(node.get("from"), "time_range 的 from")
    b = _hhmm(node.get("to"), "time_range 的 to")
    if ck:
        ck(f"{a} {b}", "time_range")
    out = {"t": t, "from": a, "to": b, "label": _s(node, "label", LABEL, t, ck) or "时间段"}
    note = _s(node, "note", CAPTION, t, ck)
    if note:
        out["note"] = note
    return out


def r_time_range(ctx, n):
    if "bind" in n:
        c = _cbti(ctx, _pid(n["bind"]))
        a, b = c["earliest_bed"], c["wake"]
        week = c.get("week")
        label = f"睡眠窗口 · 第 {week} 周" if week else "睡眠窗口"
        note = None
    else:
        a, b, label, note = n["from"], n["to"], n["label"], n.get("note")
    fa, fb = _hm_to_h(a), _hm_to_h(b)
    minutes = round(((fb - fa) % 24) * 60)
    sub = _dur_text(minutes) + (f" · {note}" if note else "")
    return {"label": label, "text": f"{a} — {b}", "sub": sub, "from": fa, "to": fb}


def n_milestones(node, ck, t):
    if node.get("bind"):
        return {"t": t, "bind": _check_bind(str(node["bind"]), ("project",))}
    items = node.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 5:
        raise CanvasError("milestones 要么 bind project:<id>，要么手写 items（1–5 项，每项 {\"title\":…,\"sub\":…}）")
    out_items = []
    for it in items:
        if not isinstance(it, dict):
            raise CanvasError("milestones 的 items 每项要是 {\"title\":…,\"sub\":…}")
        out_items.append({"title": _s(it, "title", ITEM, "milestones", ck, required=True),
                          "sub": _s(it, "sub", ITEM, "milestones", ck)})
    out = {"t": t, "items": out_items, "current": _int(node, "current", 0, 0, len(out_items) - 1)}
    title = _s(node, "title", TITLE, t, ck)
    if title:
        out["title"] = title
    return out


def r_milestones(ctx, n):
    if "items" in n:
        cur = n["current"]
        items = [{**it, "state": "done" if i < cur else ("now" if i == cur else "next")}
                 for i, it in enumerate(n["items"])]
        return {"title": n.get("title"), "items": items}
    p = _project(ctx, _pid(n["bind"]))
    start = date.fromisoformat(p["start"])
    days = int(p.get("days") or 30)
    end = start + timedelta(days=days - 1)
    first = next((x for x in (p.get("rules") or [])[:1] + [p.get("goal") or ""] if x and len(x) <= ITEM), None)
    marks = [(start, f"{_md(start)} · 开始", first or _short(p.get("goal") or "", ITEM))]
    for r in sorted(p.get("reviews") or [], key=lambda r: str(r.get("date"))):
        try:
            d = date.fromisoformat(str(r["date"]))
        except (KeyError, ValueError):
            continue
        head, _, tail = str(r.get("title") or "复盘").partition("：")
        marks.append((d, f"{_md(d)} · {head}"[:ITEM], tail[:ITEM]))
    marks.append((end, f"{_md(end)} · 结束", f"共 {days} 天"))
    cur = max([i for i, (d, _, _) in enumerate(marks) if d <= ctx.day] or [-1])
    if len(marks) > 5:
        lo = max(0, min(cur - 1, len(marks) - 5))
        pick = list(range(lo, lo + 5))
        if len(marks) - 1 not in pick:
            pick[-1] = len(marks) - 1
    else:
        pick = list(range(len(marks)))
    items = [{"title": marks[i][1], "sub": marks[i][2],
              "state": "done" if i < cur else ("now" if i == cur else "next")} for i in pick]
    unit = f"{days // 7} 周" if days % 7 == 0 else f"{days} 天"
    return {"title": f"{_clean_name(p['name'])[:12]} · {unit}", "items": items}


# ---------------------------------------------------------------- 趋势与对比
def _metric_label(node: dict, metric: str, ck, t: str) -> str:
    return _s(node, "label", LABEL, t, ck) or SHORT[metric]


def n_sparkline(node, ck, t):
    b = _check_bind(str(node.get("bind") or ""), ("series",))
    out = {"t": t, "bind": b, "days": _int(node, "days", 14, 7, 30)}
    label = _s(node, "label", LABEL, t, ck)
    if label:
        out["label"] = label
    return out


def _direction(vals: list[float]) -> str:
    if len(vals) < 5:
        return "flat"
    a, b = _mean(vals[-3:]), _mean(vals[:-3])
    if not b:
        return "flat"
    pct = (a - b) / b * 100
    return "down" if pct <= -3 else ("up" if pct >= 3 else "flat")


def r_sparkline(ctx, n):
    m = n["bind"]
    vals = _series(ctx, m, n["days"])
    if len(vals) < 3:
        raise vizmod.VizUnavailable(f"{SHORT[m]}最近没有足够的数据")
    vs = [v for _, v in vals]
    return {"label": n.get("label") or SHORT[m], "text": _fmt(m, vs[-1]), "unit": vizmod.METRICS[m]["unit"],
            "points": [_rnd(m, v) for v in vs], "direction": _direction(vs), "asof": _md(vals[-1][0])}


def n_stat_spark(node, ck, t):
    b = _check_bind(str(node.get("bind") or ""), ("series",))
    return {"t": t, "bind": b, "label": _metric_label(node, b, ck, t)}


def r_stat_spark(ctx, n):
    m = n["bind"]
    vals = _series(ctx, m, 14)
    if len(vals) < 3:
        raise vizmod.VizUnavailable(f"{SHORT[m]}最近没有足够的数据")
    vs = [v for _, v in vals]
    moved = False
    if len(vs) >= 6:
        a, b = _mean(vs[-3:]), _mean(vs[-6:-3])
        moved = bool(b) and abs(a - b) / b * 100 > 3
    return {"label": n["label"], "text": _fmt(m, vs[-1]), "unit": vizmod.METRICS[m]["unit"],
            "points": [_rnd(m, v) for v in vs], "moved": moved, "asof": _md(vals[-1][0])}


def n_delta(node, ck, t):
    b = _check_bind(str(node.get("bind") or ""), ("series",))
    base = str(node.get("baseline") or "prev3")
    if base not in ("prev3", "prev_week", "personal"):
        raise CanvasError("delta 的 baseline 只能是 prev3（前 3 天）/ prev_week（上一周）/ personal（你 30 天的平均）")
    return {"t": t, "bind": b, "baseline": base}


def r_delta(ctx, n):
    m, base = n["bind"], n["baseline"]
    meta = vizmod.METRICS[m]
    day_word = "晚" if m == "sleep" else "天"
    if base == "prev3":
        vs = [v for _, v in _series(ctx, m, 10)][-6:]
        if len(vs) < 6:
            raise vizmod.VizUnavailable(f"{SHORT[m]}不够 6 {day_word}")
        a, b = _mean(vs[-3:]), _mean(vs[:3])
        label = f"{SHORT[m]} · 近 3 {day_word}和前 3 {day_word}比"
    elif base == "prev_week":
        vals = _series(ctx, m, 14)
        if not vals:
            raise vizmod.VizUnavailable(f"{SHORT[m]}最近没有数")
        last = vals[-1][0]
        cur = [v for d, v in vals if d > last - timedelta(days=7)]
        prev = [v for d, v in vals if d <= last - timedelta(days=7)]
        if len(cur) < 3 or len(prev) < 3:
            raise vizmod.VizUnavailable("两周里有一周不够 3 天")
        a, b = _mean(cur), _mean(prev)
        label = f"{SHORT[m]} · 近 7 {day_word}和上一周比"
    else:
        vs = [v for _, v in _series(ctx, m, 33)]
        if len(vs) < 10:
            raise vizmod.VizUnavailable(f"{SHORT[m]}还不够算 30 天的平均")
        a, b = _mean(vs[-3:]), _mean(vs[:-3])
        label = f"{SHORT[m]} · 近 3 {day_word}和你 30 天的平均比"
    if not b:
        raise vizmod.VizUnavailable("比较的那段是 0")
    pct = round((a - b) / b * 100)
    direction = "down" if pct <= -3 else ("up" if pct >= 3 else "flat")
    text = "→ 持平" if direction == "flat" else f"{'↓' if direction == 'down' else '↑'} {abs(pct)}%"
    good = True if direction == "flat" else ((direction == "up") == (meta["dir"] == "low_bad"))
    return {"label": label, "text": text, "from": _fmt(m, b), "to": _fmt(m, a), "unit": meta["unit"],
            "direction": direction, "good": good}


COMPARE_TITLE = {"sleep": "每晚睡了多久", "steps": "每天步数", "hrv": "HRV", "resting_hr": "静息心率", "recovery": "恢复"}


def n_compare(node, ck, t):
    b = str(node.get("bind") or node.get("metric") or "").strip()
    if b not in COMPARE_METRICS:
        raise CanvasError(f"compare 的 bind 只能是 {' / '.join(COMPARE_METRICS)}")
    return {"t": t, "bind": b}


def r_compare(ctx, n):
    m = n["bind"]
    monday = ctx.day - timedelta(days=ctx.day.weekday())
    vals = _by_date(ctx, m, monday - timedelta(days=7), monday + timedelta(days=6))
    if not vals:
        raise vizmod.VizUnavailable(f"这两周没有{SHORT[m]}的数")
    pairs = []
    for i in range(7):
        d, pd = monday + timedelta(days=i), monday - timedelta(days=7 - i)
        pairs.append({"label": WEEKDAY[i], "now": _rnd(m, vals.get(d)) if d <= ctx.day else None,
                      "prev": _rnd(m, vals.get(pd)), "today": d == ctx.day})
    top = max(v for p in pairs for v in (p["now"], p["prev"]) if v is not None)
    return {"title": f"{COMPARE_TITLE[m]}：这周 vs 上周", "pairs": pairs, "max": _nice_max(top),
            "unit": vizmod.METRICS[m]["unit"]}


def n_dual_line(node, ck, t):
    a = str(node.get("a") or "").strip()
    b = str(node.get("b") or "").strip()
    for k, v in (("a", a), ("b", b)):
        if v not in SERIES_METRICS:
            raise CanvasError(f"dual_line 的 {k} 只能是 {' / '.join(SERIES_METRICS)}")
    if a == b:
        raise CanvasError("dual_line 的 a 和 b 要是两项不同的指标")
    return {"t": t, "a": a, "b": b, "days": _int(node, "days", 14, 7, 30)}


def _line_text(m: str, vs: list[float]) -> str:
    first, last = vs[0], vs[-1]
    if first and abs(last - first) / abs(first) >= 0.05:
        return f"{_fmt(m, first)} → {_fmt(m, last)}"
    return f"{_fmt(m, min(vs))}–{_fmt(m, max(vs))}"


def r_dual_line(ctx, n):
    sa, sb = dict(_series(ctx, n["a"], n["days"])), dict(_series(ctx, n["b"], n["days"]))
    common = sorted(set(sa) & set(sb))
    if len(common) < 3:
        raise vizmod.VizUnavailable("两项对得上的天太少")
    out = {}
    for k, m, s in (("a", n["a"], sa), ("b", n["b"], sb)):
        vs = [s[d] for d in common]
        out[k] = {"label": SHORT[m], "points": [_rnd(m, v) for v in vs], "text": _line_text(m, vs),
                  "unit": vizmod.METRICS[m]["unit"]}
    return out


def n_diverging(node, ck, t):
    return {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("diverging",)), "days": _int(node, "days", 7, 3, 14)}


def r_diverging(ctx, n):
    items = []
    if n["bind"] == "sleep.need":
        for x in _nights(ctx, n["days"]):
            if x["need"]:
                v = round(x["slept"] - x["need"], 1)
                items.append({"label": _md(x["date"]), "value": v, "text": _signed(v, 1)})
        caption = "横线 = 正好睡够 · 往下 = 少睡"
    else:
        goal = _steps_goal(ctx)
        series = ctx.tools.daily_series("steps", ctx.day, n["days"] + 1)
        for i in range(n["days"], 0, -1):
            d = ctx.day - timedelta(days=i)
            if series.get(d) is not None:
                v = int(round(series[d] - goal))
                items.append({"label": _md(d), "value": v, "text": _signed(v, 0, comma=True)})
        caption = f"横线 = 目标 {goal:,} 步 · 往下 = 没走够"
    if not items:
        raise vizmod.VizUnavailable("这几天没有能比的数")
    return {"items": items, "max_abs": max(abs(i["value"]) for i in items) or 1, "caption": caption}


def n_lollipop(node, ck, t):
    b = _check_bind(str(node.get("bind") or ""), ("lollipop",))
    out = {"t": t, "bind": b, "days": _int(node, "days", 7, 3, 14)}
    if node.get("target") not in (None, ""):
        out["target"] = _number(node["target"], "lollipop 的 target", ck)
    return out


def r_lollipop(ctx, n):
    b, target = n["bind"], n.get("target")
    items = []
    if b.startswith("project:"):
        p = _project(ctx, _pid(b))
        start = date.fromisoformat(p["start"])
        if not any(x.get("duration_min") for x in p.get("daily") or []):
            raise vizmod.VizUnavailable("这个项目的待办没有时长")
        if target is None:
            per = [sum(float(x.get("duration_min") or 0) for x in p.get("daily") or []
                       if not x.get("weekdays") or wd in x["weekdays"]) for wd in range(1, 8)]
            per = [v for v in per if v]
            target = round(sum(per) / len(per)) if per else None
        for i in range(n["days"] - 1, -1, -1):
            d = ctx.day - timedelta(days=i)
            if d < start:
                continue
            ts = [t for t in _proj_todos(ctx, p, d) if t.get("duration_min")]
            if not ts:
                continue
            v = sum(float(t["duration_min"]) for t in ts if t["status"] == "done")
            if d == ctx.day and not v:
                continue
            items.append({"label": _md(d), "value": round(v, 1), "text": f"{v:.0f}′", "done": v > 0})
        if not items:
            raise vizmod.VizUnavailable("这个项目还没有跟做的天")
        tlabel = f"目标 {target:g} 分钟" if target else None
    else:
        m = b
        if target is None and m == "steps":
            target = _steps_goal(ctx)
        for d, v in _series(ctx, m, n["days"]):
            items.append({"label": _md(d), "value": _rnd(m, v), "text": _fmt(m, v),
                          "done": (v >= target) if target is not None else True})
        if not items:
            raise vizmod.VizUnavailable(f"{SHORT[m]}最近没有数")
        unit = vizmod.METRICS[m]["unit"]
        tlabel = f"目标 {_fmt(m, target)} {unit}" if target is not None else None
    top = max([i["value"] for i in items] + [target or 0])
    return {"items": items, "target": target, "target_label": tlabel, "max": top}


def n_scatter(node, ck, t):
    x = str(node.get("x") or "").strip()
    y = str(node.get("y") or "").strip()
    for k, v in (("x", x), ("y", y)):
        if v not in SERIES_METRICS:
            raise CanvasError(f"scatter 的 {k} 只能是 {' / '.join(SERIES_METRICS)}")
    if x == y:
        raise CanvasError("scatter 的 x 和 y 要是两项不同的指标")
    lag = node.get("lag", 1)
    if lag not in (0, 1, "0", "1"):
        raise CanvasError("scatter 的 lag 只能是 0（同一天）或 1（x 当天 / 当晚 vs y 第二天）")
    return {"t": t, "x": x, "y": y, "days": _int(node, "days", 30, 14, 60), "lag": int(lag)}


def _range(vals: list[float], nd: int) -> list[float]:
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.05 or max(abs(hi) * 0.05, 1)
    q = 10 ** nd
    return [math.floor((lo - pad) * q) / q, math.ceil((hi + pad) * q) / q]


def r_scatter(ctx, n):
    x, y, lag = n["x"], n["y"], n["lag"]
    xs = _series(ctx, x, n["days"])
    ys = dict(_series(ctx, y, n["days"] + 3))
    off = timedelta(days=_shift(ctx, x) + lag - _shift(ctx, y))
    pairs = [(xv, ys[d + off], d) for d, xv in xs if d + off in ys]
    if len(pairs) < 14:
        raise vizmod.VizUnavailable(f"样本太少（{len(pairs)} 个，至少 14 个）")
    px, py = [p[0] for p in pairs], [p[1] for p in pairs]
    ndx, ndy = vizmod.METRICS[x]["nd"], vizmod.METRICS[y]["nd"]
    mx, my = _mean(px), _mean(py)
    sxx = sum((v - mx) ** 2 for v in px)
    syy = sum((v - my) ** 2 for v in py)
    sxy = sum((a - mx) * (b - my) for a, b in zip(px, py))
    fit = r = None
    if sxx > 0:
        k = sxy / sxx
        x0, x1 = min(px), max(px)
        fit = [[_rnd(x, x0), _rnd(y, my + k * (x0 - mx))], [_rnd(x, x1), _rnd(y, my + k * (x1 - mx))]]
        if syy > 0:
            r = round(sxy / math.sqrt(sxx * syy), 2)
    last = max(pairs, key=lambda p: p[2])
    unit = "晚" if x == "sleep" else "天"
    return {"points": [[_rnd(x, a), _rnd(y, b)] for a, b, _ in pairs], "x_label": AXIS[x],
            "y_label": f"{'第二天' if lag else '当天'} {AXIS[y]}", "x_range": _range(px, ndx), "y_range": _range(py, ndy),
            "fit": fit, "r": r, "last": [_rnd(x, last[0]), _rnd(y, last[1])],
            "caption": f"{len(pairs)} {unit} · 只说明相关，不代表因果"}


def n_histogram(node, ck, t):
    b = _check_bind(str(node.get("bind") or ""), ("histogram",))
    return {"t": t, "bind": b, "days": _int(node, "days", 30, 7, 60)}


def r_histogram(ctx, n):
    b = n["bind"]
    if b == "bedtime":
        mins = []
        for i in range(n["days"], 0, -1):
            tm = _night_times(ctx, ctx.day - timedelta(days=i), onset=True)
            if tm:
                mins.append(_nh(tm[0]) * 60)
        if len(mins) < 5:
            raise vizmod.VizUnavailable("入睡时间不够 5 晚")
        w = next(w for w in (30, 60, 90, 120, 180, 240) if
                 (math.floor(max(mins) / w) - math.floor(min(mins) / w)) < 8)
        lo = math.floor(min(mins) / w)
        counts = [0] * (math.floor(max(mins) / w) - lo + 1)
        for v in mins:
            counts[math.floor(v / w) - lo] += 1
        labels = [f"{int(((lo + i) * w) // 60) % 24:02d}:{int((lo + i) * w) % 60:02d}" for i in range(len(counts))]
        peak = counts.index(max(counts))
        caption = f"最常在 {labels[peak]} 前后睡着（{counts[peak]} 晚）"
    else:
        m = b
        vs = [v for _, v in _series(ctx, m, n["days"])]
        if len(vs) < 5:
            raise vizmod.VizUnavailable(f"{SHORT[m]}不够 5 天")
        step = _nice_step((max(vs) - min(vs)) / 6 or 1)
        lo = math.floor(min(vs) / step)
        nb = math.floor(max(vs) / step) - lo + 1
        while nb > 8:
            step = _nice_step(step * 1.5)
            lo = math.floor(min(vs) / step)
            nb = math.floor(max(vs) / step) - lo + 1
        counts = [0] * nb
        for v in vs:
            counts[min(nb - 1, math.floor(v / step) - lo)] += 1
        labels = [_fmt(m, (lo + i) * step) for i in range(nb)]
        peak = counts.index(max(counts))
        unit = vizmod.METRICS[m]["unit"]
        caption = (f"最常在 {_fmt(m, (lo + peak) * step)}–{_fmt(m, (lo + peak + 1) * step)} {unit}"
                   f"（{counts[peak]} {'晚' if m == 'sleep' else '天'}）")
    return {"bins": [{"label": lab, "count": c, "peak": i == peak} for i, (lab, c) in enumerate(zip(labels, counts))],
            "caption": caption}


def n_spread(node, ck, t):
    return {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("series",)), "days": _int(node, "days", 30, 7, 60)}


def _asof_word(ctx: Ctx, m: str, d: date) -> str:
    if m == "sleep":
        return "昨晚" if d == ctx.yday else _md(d)
    if m == "steps":
        return "昨天" if d == ctx.yday else _md(d)
    if _shift(ctx, m):
        return "今天" if d == ctx.yday else _md(d)
    return "今天" if d == ctx.day else _md(d)


def r_spread(ctx, n):
    m = n["bind"]
    vals = _series(ctx, m, n["days"])
    if len(vals) < 5:
        raise vizmod.VizUnavailable(f"{SHORT[m]}不够 5 天")
    vs = [v for _, v in vals]
    q1, med, q3 = statistics.quantiles(vs, n=4, method="inclusive")
    d, today = vals[-1]
    unit = "晚" if m == "sleep" else "天"
    name = f" {SHORT[m]} " if SHORT[m].isascii() else SHORT[m]
    return {"label": f"近 {len(vs)} {unit}{name}的范围", "min": _rnd(m, min(vs)), "q1": _rnd(m, q1),
            "median": _rnd(m, med), "q3": _rnd(m, q3), "max": _rnd(m, max(vs)), "today": _rnd(m, today),
            "today_text": f"{_asof_word(ctx, m, d)} {_fmt(m, today)}", "unit": vizmod.METRICS[m]["unit"]}


def n_bullet(node, ck, t):
    out = {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("bullet",))}
    label = _s(node, "label", LABEL, t, ck)
    if label:
        out["label"] = label
    return out


def r_bullet(ctx, n):
    b = n["bind"]
    if b == "sleep.efficiency":
        from .coach import sleep_week
        rows = [r for r in sleep_week(ctx.tools, 7, ctx.day)["nights"] if r.get("efficiency_pct") is not None]
        if not rows:
            raise vizmod.VizUnavailable("最近 7 晚没有睡眠效率")
        r = rows[-1]
        nd = date.fromisoformat(r["night_of"])
        v = int(round(float(r["efficiency_pct"])))
        out = {"label": "昨晚睡眠效率" if nd == ctx.yday else f"{_md(nd)} 睡眠效率", "text": str(v), "unit": "%",
               "value": v, "min": 70 if v >= 70 else v - v % 5 - 5, "max": 100, "bands": [85, 90],
               "target": 90, "direction": "low_bad",
               "caption": "到目标了" if v >= 90 else f"差 {90 - v} 个点到目标"}
    elif b == "recovery":
        v = ctx.vz("recovery")
        val = int(v["value"])
        zone = "红区" if val <= vizmod.GAUGE_WARN else ("黄区" if val <= vizmod.GAUGE_MID else "绿区")
        out = {"label": "恢复", "text": v["value_text"], "unit": "%", "value": val, "min": 0, "max": 100,
               "bands": [vizmod.GAUGE_WARN, vizmod.GAUGE_MID], "target": None, "direction": "low_bad",
               "caption": f"在{zone}（WHOOP 按 33 / 66 分档）"}
    elif b == "steps":
        v = ctx.vz("steps", "progress")
        val, goal = int(v["value"]), int(v["goal"])
        out = {"label": "今天步数", "text": f"{val:,}", "unit": "步", "value": val, "min": 0,
               "max": int(_nice_max(max(goal * 1.25, val))), "bands": [goal // 2, goal * 3 // 4], "target": goal,
               "direction": "low_bad", "caption": "走够了" if val >= goal else f"还差 {goal - val:,} 步到目标"}
    elif b == "sleep":
        v = ctx.vz("sleep", "need")
        val, need = float(v["value"]), float(v["need"])
        out = {"label": "昨晚睡了", "text": v["value_text"], "unit": "小时", "value": round(val, 1),
               "min": math.floor(min(need - 3, val - 0.5)), "max": math.ceil(max(need + 1, val + 0.5)),
               "bands": [round(need - 2, 1), round(need - 1, 1)], "target": round(need, 1), "direction": "low_bad",
               "caption": "睡够了" if val >= need else f"差 {need - val:.1f} 小时到当晚需要"}
    else:
        v = ctx.vz(b, "range", 7)
        band, warn = v.get("band"), v.get("warn")
        if not band or warn is None:
            raise vizmod.VizUnavailable("还没学出你自己的常态范围")
        low_bad = v["direction"] == "low_bad"
        edge = band[0] if low_bad else band[1]
        cap = {"act": "过了你自己的警戒线", "watch": "出了你自己的常态", "steady": "在你自己的常态里"}
        out = {"label": SHORT[b], "text": v["value_text"], "unit": v["unit"], "value": v["value"],
               "min": v["scale"][0], "max": v["scale"][1], "bands": sorted([warn, edge]), "target": None,
               "direction": v["direction"], "caption": cap.get(v.get("zone"), "")}
    if n.get("label"):
        out["label"] = n["label"]
    return out


# ---------------------------------------------------------------- 进度与信息
def n_segments(node, ck, t):
    out = {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("project",))}
    label = _s(node, "label", LABEL, t, ck)
    if label:
        out["label"] = label
    return out


def r_segments(ctx, n):
    p = _project(ctx, _pid(n["bind"]))
    start = date.fromisoformat(p["start"])
    total = max(1, math.ceil(int(p.get("days") or 30) / 7))
    gone = (ctx.day - start).days
    label = n.get("label") or _clean_name(p["name"])[:LABEL]
    if gone < 0:
        return {"text": f"{_md(start)} 开始", "sub": f"/ {total} 周", "label": label, "total": total, "done": 0}
    return {"text": f"第 {min(total, gone // 7 + 1)} 周", "sub": f"/ {total} 周", "label": label, "total": total,
            "done": round(min(float(total), gone / 7), 2)}


def n_stepper(node, ck, t):
    items = node.get("items")
    if not isinstance(items, list) or not 2 <= len(items) <= 5:
        raise CanvasError("stepper 要有 items（2–5 个阶段名）")
    out_items = [_cell(it, 6, "stepper 的阶段名", ck) for it in items]
    subs = node.get("subs") or []
    if not isinstance(subs, list) or (subs and len(subs) != len(out_items)):
        raise CanvasError("stepper 的 subs 要和 items 一样多（每个阶段一句，比如「1–2 周」）")
    out_subs = [_cell(s, 8, "stepper 的 subs", ck, required=False) for s in subs]
    return {"t": t, "items": out_items, "subs": out_subs, "current": _int(node, "current", 0, 0, len(out_items) - 1)}


def n_progress_list(node, ck, t):
    return {"t": t, "bind": _check_bind(str(node.get("bind") or ""), ("progress",)), "days": _int(node, "days", 7, 3, 14)}


def r_progress_list(ctx, n):
    rows = []
    if n["bind"] == "projects":
        for p in _projects(ctx, active_only=True):
            start = date.fromisoformat(p["start"])
            if not start <= ctx.day < start + timedelta(days=int(p.get("days") or 30)):
                continue
            done = total = 0
            for i in range(n["days"] - 1, -1, -1):
                d = ctx.day - timedelta(days=i)
                if d < start:
                    continue
                ts = _proj_todos(ctx, p, d)
                if not ts:
                    continue
                ok = all(t["status"] == "done" for t in ts)
                if d == ctx.day and not ok:
                    continue
                total += 1
                done += ok
            rows.append({"label": _clean_name(p["name"])[:10], "text": f"{done} / {total}" if total else "今天开始",
                         "fraction": round(done / total, 2) if total else 0.0})
        if not rows:
            raise vizmod.VizUnavailable("没有进行中的项目")
    else:
        from .coach import project_stats
        st = project_stats(ctx.tools, _pid(n["bind"]), n["days"], ctx.day)
        for it in st["items"]:
            rows.append({"label": it["title"][:10], "text": f"{it['done']} / {it['total']}",
                         "fraction": round(it["done"] / it["total"], 2) if it["total"] else 0.0})
        if not rows:
            raise vizmod.VizUnavailable("这个项目还没有过去的天可以算")
    return {"rows": rows[:4]}


def n_checklist(node, ck, t):
    board = node.get("board")
    if board is not None and board not in BOARDS:
        raise CanvasError(f"checklist 的 board 只能是 {' / '.join(BOARDS)}")
    out = {"t": t, "n": _int(node, "n", 4, 1, 6)}
    if board:
        out["board"] = board
    return out


def r_checklist(ctx, n):
    from .todos import _sort_when
    board = n.get("board") or ctx.board
    ts = [t for t in _todos_on(ctx, ctx.day, None if board in (None, "now") else board) if t["status"] != "expired"]
    if not ts:
        raise vizmod.VizUnavailable("今天没有待办")
    ts.sort(key=lambda t: (_sort_when(t.get("when") or ""), t.get("created_at") or ""))
    while len(ts) > n["n"] and any(t["status"] in ("done", "skipped") for t in ts):
        ts.remove(next(t for t in ts if t["status"] in ("done", "skipped")))
    items = []
    for t in ts[:n["n"]]:
        text = _todo_text(t)
        state = t["status"] if t["status"] in ("done", "skipped") else "pending"
        items.append({"text": text[:ITEM], "done": t["status"] == "done", "state": state})
    return {"items": items}


def n_kv(node, ck, t):
    if node.get("bind"):
        return {"t": t, "bind": _check_bind(str(node["bind"]), ("project",))}
    items = node.get("items")
    if not isinstance(items, list) or not 2 <= len(items) <= 6:
        raise CanvasError("kv 要么 bind project:<id>，要么手写 items（2–6 行 {\"label\":…,\"value\":…}）")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise CanvasError("kv 的 items 每项要是 {\"label\":…,\"value\":…}")
        out.append({"label": _cell(it.get("label"), 8, "kv 的 label", ck),
                    "value": _cell(it.get("value"), 12, "kv 的 value", ck)})
    return {"t": t, "items": out}


def r_kv(ctx, n):
    if "items" in n:
        return {"items": [dict(i) for i in n["items"]]}
    c = _cbti(ctx, _pid(n["bind"]))
    items = [{"label": "起床", "value": c["wake"]}, {"label": "最早上床", "value": c["earliest_bed"]}]
    if c.get("window_h"):
        items.append({"label": "睡眠窗口", "value": f"{float(c['window_h']):g} 小时"})
    if c.get("week"):
        items.append({"label": "第几周", "value": f"第 {c['week']} 周"})
    return {"items": items}


def n_table(node, ck, t):
    if node.get("bind"):
        b = str(node["bind"]).strip()
        if b != "sleep.week":
            raise CanvasError("table 的 bind 只能是 sleep.week（日期 / 睡了 / 效率 / 入睡），或者手写 columns + rows")
        return {"t": t, "bind": b, "n": _int(node, "n", 4, 1, 6)}
    cols, rows = node.get("columns"), node.get("rows")
    if not isinstance(cols, list) or not 1 <= len(cols) <= 4:
        raise CanvasError("table 要有 columns（1–4 列）")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 6:
        raise CanvasError("table 要有 rows（1–6 行）")
    out_cols = [_cell(c, 6, "table 的列名", required=False) for c in cols]
    out_rows = []
    for r in rows:
        if not isinstance(r, list) or len(r) != len(out_cols):
            raise CanvasError("table 每行的格数要和 columns 一样")
        # 第一列是日期或名目，和 hero.table 一样不查手写数字
        out_rows.append([_cell(c, 6, "table", ck if i > 0 else None, required=False) for i, c in enumerate(r)])
    return {"t": t, "columns": out_cols, "rows": out_rows}


def r_table(ctx, n):
    if "rows" in n:
        return {"columns": list(n["columns"]), "rows": [list(r) for r in n["rows"]]}
    from .coach import sleep_week
    nights = sleep_week(ctx.tools, n["n"], ctx.day)["nights"]
    if all(r.get("asleep_h") is None for r in nights):
        raise vizmod.VizUnavailable("最近几晚没有睡眠数据")
    rows = []
    for r in nights:
        eff = r.get("efficiency_pct")
        rows.append([_md(date.fromisoformat(r["night_of"])),
                     f"{r['asleep_h']:.1f}" if r.get("asleep_h") is not None else "—",
                     f"{float(eff):.0f}%" if eff is not None else "—", r.get("start") or "—"])
    return {"columns": ["日期", "睡了", "效率", "入睡"], "rows": rows}


def n_tag(node, ck, t):
    items = node.get("items")
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list) or not 1 <= len(items) <= 4:
        raise CanvasError("tag 要有 items（1–4 个标签）")
    out = [_cell(it, 10, "tag 的标签", ck) for it in items]
    strong = node.get("strong")
    strong = strong if isinstance(strong, int) and not isinstance(strong, bool) and 0 <= strong < len(out) else None
    return {"t": t, "items": out, "strong": strong}


def n_quote(node, ck, t):
    out = {"t": t, "text": _s(node, "text", 30, t, ck, required=True)}
    src = _s(node, "source", LABEL, t, ck)
    out["source"] = src or None
    return out


def _media_kind(url: str) -> str:
    from .media import kind_of
    return kind_of(url)


def n_media(node, ck, t):
    """跟练入口：只放 follow 出的片（和练习卡同一条规则；以前文档这么写、校验却放过音频和 B 站）。"""
    if node.get("id"):
        return {"t": t, "id": _s(node, "id", 60, t)}
    url = str(node.get("url") or "").strip()
    if not url:
        raise CanvasError("media 要写 url + title（follow 出的片，follow session list 能查）")
    from .media import MediaError, check_url, is_follow_video
    try:
        check_url(url)
    except MediaError as exc:
        raise CanvasError(f"media：{exc}") from exc
    if not is_follow_video(url):
        raise CanvasError("media 只放 follow 出的片（/media/follow/<ssid>/out.mp4），不放音频、不放 B 站链接")
    out = {"t": t, "url": url, "title": _s(node, "title", TITLE, t, ck, required=True)}
    if node.get("duration_min") not in (None, ""):
        out["duration_min"] = _number(node["duration_min"], "media 的 duration_min")
    return out


def r_media(ctx, n):
    if "id" in n:
        from .v3 import media_library
        it = next((m for m in media_library(ctx.tools) if m.get("id") == n["id"]), None)
        if not it:
            raise KeyError(f"素材库里没有 {n['id']}")
        dur = it.get("duration_min")
        kind = it.get("kind") if it.get("kind") in ("audio", "video", "embed") else _media_kind(it["url"])
        return {"title": it["title"], "sub": (f"{float(dur):g} 分钟 · 素材库" if dur else "素材库"),
                "url": it["url"], "kind": kind}
    dur = n.get("duration_min")
    return {"title": n["title"], "sub": f"{dur:g} 分钟" if dur else "", "url": n["url"], "kind": _media_kind(n["url"])}


def n_photo(node, ck, t):
    out: dict[str, Any] = {"t": t}
    if node.get("todo"):
        out["todo"] = _s(node, "todo", 80, t)
    elif node.get("latest"):
        b = str(node["latest"]).strip()
        if b not in BOARDS:
            raise CanvasError(f"photo 的 latest 只能是 {' / '.join(BOARDS)}（该板块今天最近一张）")
        out["latest"] = b
    else:
        raise CanvasError("photo 要写 todo（待办 id）或 latest（板块，取今天最近一张）")
    cap = _s(node, "caption", 30, t, ck)
    if cap:
        out["caption"] = cap
    return out


def _photo_names(t: dict) -> list[tuple[str, str]]:
    """一条待办记录里的照片：[(提交时间, 文件名)]。"""
    rec = t.get("record") or {}
    out = []
    for sub in [rec] + list(rec.get("submitted") or []):
        for v in (sub.get("values") or {}).values():
            if isinstance(v, str) and re.search(r"\.(?:jpg|png)$", v):
                out.append((str(sub.get("at") or ""), v.rsplit("/", 1)[-1]))
    return out


def r_photo(ctx, n):
    from .v3 import photo_file
    if "todo" in n:
        t = _store(ctx).get(n["todo"])
        if not t:
            raise KeyError(f"没有待办 {n['todo']}")
        cands = [(at, name, t) for at, name in _photo_names(t)]
    else:
        board = n["latest"]
        cands = [(at, name, t) for t in _todos_on(ctx, ctx.day, None if board == "now" else board)
                 for at, name in _photo_names(t)]
    cands = [c for c in cands if photo_file(ctx.tools, c[1])]
    if not cands:
        raise vizmod.VizUnavailable("还没有照片")
    at, name, t = max(cands, key=lambda c: c[0])
    cap = n.get("caption") or (str(t.get("summary") or "")[:30] or None)
    return {"url": f"/api/v3/photo/{name}", "caption": cap}


def n_plain(node, ck, t):
    return {"t": t}


def r_same(ctx, n):
    return {k: v for k, v in n.items() if k != "t"}


# ---------------------------------------------------------------- 注册表
def _fixed(h: int) -> Callable[[dict], int]:
    return lambda n: h


NORMALIZERS: dict[str, Callable] = {
    "pie": n_pie, "donut": n_pie, "stack": n_stack, "stack_columns": n_stack_columns, "waffle": n_waffle,
    "zones": n_zones, "radar": n_radar,
    "hypnogram": n_plain, "sleep_window": n_sleep_window, "clock24": n_plain, "calendar": n_calendar,
    "weekgrid": n_weekgrid, "streak": n_streak, "countdown": n_countdown, "time_range": n_time_range,
    "milestones": n_milestones,
    "sparkline": n_sparkline, "stat_spark": n_stat_spark, "delta": n_delta, "compare": n_compare,
    "dual_line": n_dual_line, "diverging": n_diverging, "lollipop": n_lollipop, "scatter": n_scatter,
    "histogram": n_histogram, "spread": n_spread, "bullet": n_bullet,
    "segments": n_segments, "stepper": n_stepper, "progress_list": n_progress_list, "checklist": n_checklist,
    "kv": n_kv, "table": n_table, "tag": n_tag, "quote": n_quote, "media": n_media, "photo": n_photo,
}

ESTIMATES: dict[str, Callable[[dict], int]] = {
    "pie": _fixed(140), "donut": _fixed(140), "stack": _fixed(72),
    "stack_columns": lambda n: 190 if n.get("height") == "m" else 150,
    "waffle": lambda n: math.ceil(n["days"] / 10) * 24 + 24, "zones": _fixed(130), "radar": _fixed(200),
    "hypnogram": _fixed(110), "sleep_window": lambda n: n["days"] * 14 + 40, "clock24": _fixed(160),
    "calendar": _fixed(200), "weekgrid": _fixed(80), "streak": _fixed(130), "countdown": _fixed(120),
    "time_range": _fixed(110), "milestones": lambda n: len(n.get("items") or [0] * 5) * 46 + 24,
    "sparkline": _fixed(56), "stat_spark": _fixed(74), "delta": _fixed(110), "compare": _fixed(140),
    "dual_line": _fixed(140), "diverging": _fixed(120), "lollipop": _fixed(120), "scatter": _fixed(160),
    "histogram": _fixed(130), "spread": _fixed(80), "bullet": _fixed(110),
    "segments": _fixed(90), "stepper": _fixed(76), "progress_list": _fixed(4 * 34),
    "checklist": lambda n: n["n"] * 28, "kv": lambda n: len(n.get("items") or [0] * 4) * 38,
    "table": lambda n: (len(n.get("rows") or [0] * n.get("n", 4)) + 1) * 26, "tag": lambda n: 32 if sum(len(str(x)) + 2 for x in n.get("items") or []) <= 22 else 64,   # 放不下一行就折成两行
    "quote": lambda n: math.ceil(len(n["text"]) / 14) * 34 + 26, "media": _fixed(64), "photo": _fixed(170),
}

RESOLVERS: dict[str, Callable] = {
    "pie": r_pie, "donut": r_pie, "stack": r_stack, "stack_columns": r_stack_columns, "waffle": r_waffle,
    "zones": r_zones, "radar": r_radar,
    "hypnogram": r_hypnogram, "sleep_window": r_sleep_window, "clock24": r_clock24, "calendar": r_calendar,
    "weekgrid": r_weekgrid, "streak": r_streak, "countdown": r_countdown, "time_range": r_time_range,
    "milestones": r_milestones,
    "sparkline": r_sparkline, "stat_spark": r_stat_spark, "delta": r_delta, "compare": r_compare,
    "dual_line": r_dual_line, "diverging": r_diverging, "lollipop": r_lollipop, "scatter": r_scatter,
    "histogram": r_histogram, "spread": r_spread, "bullet": r_bullet,
    "segments": r_segments, "stepper": r_same, "progress_list": r_progress_list, "checklist": r_checklist,
    "kv": r_kv, "table": r_table, "tag": r_same, "quote": r_same, "media": r_media, "photo": r_photo,
}
