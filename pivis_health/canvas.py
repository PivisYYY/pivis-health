"""开放生成式 UI：App 只给画布（宽、最大高）和设计规范，画布里怎么排由 P-Health 决定。

P-Health 写一棵「零件树」（JSON），服务器：
  1. validate —— 只认识规范里的零件和取值（颜色、字号都只能选档位，没法写样式），检查文字长度、
     零件数、估算高度不超画布；页面编排时，手写的数字必须能在证据里找到（和原来的主卡规则一样）；
  2. resolve  —— 把「绑定数据」的零件（bind / chart / dots / ring / timeline …）换成内核现算的显示值。
App 拿到的是已经算好的零件，只管按规范画。

零件（t）：
  v / h      竖排 / 横排          {"t":"v","gap":12,"children":[...]}  h 还可以 "justify":"between"
  text       文字                 {"t":"text","text":"…","role":"title|body|caption|label","tone":1|2|3}
  value      大数字               {"t":"value","bind":"sleep","size":"xl|l|m"}  或 {"t":"value","value":"6.7","unit":"小时"}
  stat       小字段（标签 + 数）   {"t":"stat","label":"HRV","bind":"hrv"}
  chart      主卡同款图           {"t":"chart","metric":"hrv","kind":"trend","days":14,"show":["band","warn"],"height":"s|m|l"}
  dots       一排点（每天 / 每晚） {"t":"dots","bind":"sleep.nights|steps.week|project:<id>","days":7}
  bar        进度条（值 / 参照）   {"t":"bar","bind":"sleep|steps|weight"}
  ring       圆环进度             {"t":"ring","bind":"recovery|steps|project:<id>"}
  level      档位点 + 字           {"t":"level","level":"act|watch|steady"}
  rule       细线
  list       清单                 {"t":"list","items":["…"],"style":"dot|number"}
  timeline   接下来的待办          {"t":"timeline","n":2}
  spacer     留白                 {"t":"spacer","size":8|16|24}
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from . import viz as vizmod

SLOTS = {"hero": {"w": 354, "h": 400}, "chat": {"w": 312, "h": 520}}
GAPS = (0, 4, 8, 12, 16, 24)
ROLES = {"title": 18, "body": 60, "caption": 40, "label": 14}        # 每种文字最多几个字
ROLE_H = {"title": 22, "body": 21, "caption": 17, "label": 16}
CHARS_PER_LINE = {"title": 16, "body": 21, "caption": 26, "label": 30}
VALUE_H = {"xl": 84, "l": 54, "m": 36}
CHART_H = {"s": 84, "m": 124, "l": 164}
MAX_NODES = 40
MAX_DEPTH = 5
SCALAR_METRICS = tuple(vizmod.METRICS)
EXTRA_FIELDS = ("need", "short", "goal", "pace", "target", "warn", "prev", "behind", "plan_now")
LEVEL_TEXT = {"act": "需要处理", "watch": "留意", "steady": "平稳"}


class CanvasError(ValueError):
    pass


# ---------------------------------------------------------------- 规范化 + 校验
def _t(node: Any) -> str:
    if not isinstance(node, dict):
        raise CanvasError("每个零件都要是对象 {\"t\": …}")
    t = node.get("t") or node.get("type")
    if t in ("vstack", "column", "col"):
        t = "v"
    if t in ("hstack", "row"):
        t = "h"
    return str(t or "")


def _numbers_in(text: str) -> list[str]:
    # 时间（22:30）、日期（11-04）里的数也算，但只要求在证据里出现过
    return re.findall(r"\d+(?:\.\d+)?", text)


def validate(layout: Any, slot: str = "hero", pool: list[float] | None = None, has_number=None) -> dict:
    """规范化并校验零件树；不合格抛 CanvasError（页面编排会把原因退回给 P-Health 改）。
    pool：页面编排时证据里的所有数字（手写数字只能抄它们）；对话卡传 None，不查手写数字。"""
    if slot not in SLOTS:
        raise CanvasError(f"slot 只能是 {tuple(SLOTS)}")
    # 整张卡原样传进来也认：{"type":"layout","layout":{…}} / {"type":"layout","children":[…]}
    if isinstance(layout, dict) and str(layout.get("type") or "") == "layout":
        layout = layout.get("layout") or {"t": "v", "children": layout.get("children") or []}
    if isinstance(layout, list):
        layout = {"t": "v", "children": layout}
    count = [0]

    def check_num(text: str, where: str) -> None:
        if pool is None or has_number is None:
            return
        for n in _numbers_in(text):
            if not has_number(pool, float(n)):
                raise CanvasError(f"{where} 里的 {n} 在 facts 里找不到：手写的数字只能抄 facts，要现算的数用 bind")

    def norm(node: Any, depth: int) -> dict:
        count[0] += 1
        if count[0] > MAX_NODES:
            raise CanvasError(f"零件太多（最多 {MAX_NODES} 个）：一张卡只讲一件事")
        if depth > MAX_DEPTH:
            raise CanvasError(f"嵌套太深（最多 {MAX_DEPTH} 层）")
        t = _t(node)
        if t in ("v", "h"):
            kids = node.get("children") or node.get("items") or []
            if not isinstance(kids, list) or not kids:
                raise CanvasError(f"{t} 要有 children")
            if t == "h" and len(kids) > 4:
                raise CanvasError("横排最多 4 个（手机宽度放不下更多）")
            gap = node.get("gap", 12 if t == "v" else 16)
            gap = min(GAPS, key=lambda g: abs(g - (gap if isinstance(gap, (int, float)) else 12)))
            align = node.get("align") if node.get("align") in ("leading", "center", "trailing") else "leading"
            out = {"t": t, "gap": gap, "align": align, "children": [norm(k, depth + 1) for k in kids]}
            if t == "h":
                out["justify"] = "between" if node.get("justify") == "between" else "start"
                out["align"] = node.get("align") if node.get("align") in ("top", "center", "bottom", "baseline") else "center"
            return out
        if t == "text":
            role = node.get("role") if node.get("role") in ROLES else "body"
            text = str(node.get("text") or "").strip()
            if not text:
                raise CanvasError("text 不能为空")
            if len(text) > ROLES[role]:
                raise CanvasError(f"{role} 文字最多 {ROLES[role]} 个字（现在 {len(text)} 个）：长内容放到对话里说")
            check_num(text, "text")
            tone = node.get("tone") if node.get("tone") in (1, 2, 3) else (2 if role in ("caption", "label") else 1)
            return {"t": "text", "text": text, "role": role, "tone": tone}
        if t in ("value", "stat"):
            out: dict[str, Any] = {"t": t}
            if node.get("bind"):
                out["bind"] = _check_bind(str(node["bind"]), ("scalar",))
            else:
                v = str(node.get("value") or "").strip()
                if not v:
                    raise CanvasError(f"{t} 要有 bind（内核现算）或 value")
                check_num(v, t)
                out["value"] = v[:12]
                out["unit"] = str(node.get("unit") or "")[:6]
            if t == "value":
                out["size"] = node.get("size") if node.get("size") in VALUE_H else "l"
            label = str(node.get("label") or "").strip()
            if t == "stat" and not label:
                raise CanvasError("stat 要有 label")
            if label:
                if len(label) > ROLES["label"]:
                    raise CanvasError(f"label 最多 {ROLES['label']} 个字")
                out["label"] = label
            return out
        if t == "chart":
            spec = {k: node[k] for k in ("metric", "kind", "days", "show") if k in node}
            try:
                s = vizmod.normalize(spec)
            except (ValueError, KeyError) as exc:
                raise CanvasError(f"chart：{exc}") from exc
            s["height"] = node.get("height") if node.get("height") in CHART_H else "m"
            return {"t": "chart", **s}
        if t == "dots":
            b = _check_bind(str(node.get("bind") or ""), ("dots",))
            days = int(node.get("days") or 7)
            return {"t": "dots", "bind": b, "days": max(3, min(14, days))}
        if t == "bar":
            return {"t": "bar", "bind": _check_bind(str(node.get("bind") or ""), ("bar",))}
        if t == "ring":
            return {"t": "ring", "bind": _check_bind(str(node.get("bind") or ""), ("ring",))}
        if t == "level":
            lv = node.get("level")
            if lv not in LEVEL_TEXT:
                raise CanvasError("level 只能是 act / watch / steady")
            return {"t": "level", "level": lv}
        if t == "rule":
            return {"t": "rule"}
        if t == "list":
            items = [str(i).strip() for i in (node.get("items") or []) if str(i).strip()]
            if not items or len(items) > 5:
                raise CanvasError("list 要有 1–5 条")
            for i in items:
                if len(i) > 30:
                    raise CanvasError("list 每条最多 30 个字")
                check_num(i, "list")
            return {"t": "list", "items": items, "style": "number" if node.get("style") == "number" else "dot"}
        if t == "timeline":
            return {"t": "timeline", "n": max(1, min(3, int(node.get("n") or 2)))}
        if t == "spacer":
            size = node.get("size", 16)
            return {"t": "spacer", "size": min((8, 16, 24), key=lambda g: abs(g - (size if isinstance(size, (int, float)) else 16)))}
        raise CanvasError(f"不认识的零件 {t!r}：只能用 v h text value stat chart dots bar ring level rule list timeline spacer")

    root = norm(layout, 1)
    h = estimate(root)
    if h > SLOTS[slot]["h"]:
        raise CanvasError(f"估算高度 {h} 超过画布 {SLOTS[slot]['h']}：少放几样，或者把图改成 height=s")
    return root


BIND_KINDS = {
    "scalar": "指标数值：" + " / ".join(SCALAR_METRICS) + "，或 <指标>.need / .goal / .target / .short / .pace / .warn / .prev",
    "dots": "sleep.nights（每晚睡够没）、steps.week（每天走够没）、project:<项目 id>（项目每天做了没）",
    "bar": "sleep（睡了 / 需要）、steps（走了 / 目标）、weight（已减 / 计划）",
    "ring": "recovery（恢复分数）、steps（走了 / 目标）、project:<项目 id>（第几天 / 共几天）",
}


def _check_bind(b: str, kinds: tuple[str, ...]) -> str:
    b = b.strip()
    kind = kinds[0]
    if kind == "scalar":
        base, _, field = b.partition(".")
        if base in SCALAR_METRICS and (not field or field in EXTRA_FIELDS):
            return b
    elif kind == "dots":
        if b in ("sleep.nights", "steps.week") or b.startswith("project:"):
            return b
    elif kind == "bar":
        if b in ("sleep", "steps", "weight"):
            return b
    elif kind == "ring":
        if b in ("recovery", "steps") or b.startswith("project:"):
            return b
    raise CanvasError(f"bind {b!r} 不认识。能用的：{BIND_KINDS[kind]}")


# ---------------------------------------------------------------- 高度估算（和 App 的画法对齐）
def _text_h(role: str, text: str) -> int:
    lines = max(1, math.ceil(len(text) / CHARS_PER_LINE[role]))
    return ROLE_H[role] * lines + (4 * (lines - 1))


def estimate(n: dict) -> int:
    t = n["t"]
    if t == "v":
        kids = [estimate(k) for k in n["children"]]
        return sum(kids) + n["gap"] * (len(kids) - 1)
    if t == "h":
        return max(estimate(k) for k in n["children"])
    if t == "text":
        return _text_h(n["role"], n["text"])
    if t == "value":
        return VALUE_H[n.get("size", "l")] + (18 if n.get("label") else 0)
    if t == "stat":
        return 44
    if t == "chart":
        base = CHART_H[n.get("height", "m")]
        return base + (60 if n.get("kind") == "gauge" else 0)
    if t == "dots":
        return 30
    if t == "bar":
        return 34
    if t == "ring":
        return 96
    if t == "level":
        return 20
    if t == "rule":
        return 1
    if t == "list":
        return sum(_text_h("body", i) for i in n["items"]) + 6 * (len(n["items"]) - 1)
    if t == "timeline":
        return 46 * n["n"]
    if t == "spacer":
        return n["size"]
    return 20


# ---------------------------------------------------------------- 解析（内核现算）
def resolve(tools, layout: dict, day: date | None = None, now: datetime | None = None,
            board: str | None = None) -> dict:
    """把绑定数据的零件换成显示值。某个零件算不出来（数据断了）就换成一行说明，整张卡不挂。"""
    now = now or tools._now()
    day = day or now.date()
    cache: dict[str, Any] = {}

    def vz(metric: str, kind: str | None = None, days: int | None = None) -> dict:
        key = f"{metric}|{kind}|{days}"
        if key not in cache:
            spec: dict[str, Any] = {"metric": metric}
            if kind:
                spec["kind"] = kind
            if days:
                spec["days"] = days
            cache[key] = vizmod.build(tools, spec, day, now)
        return cache[key]

    def scalar(b: str) -> dict:
        base, _, field = b.partition(".")
        v = vz(base)
        m = vizmod.METRICS[base]
        if not field:
            return {"text": v["value_text"], "unit": v["unit"], "zone": v.get("zone"), "asof": v.get("asof"),
                    "label": v.get("label")}
        val = v.get(field)
        if val is None and field == "need":
            val = vz(base, "need").get("need")
        if val is None:
            raise vizmod.VizUnavailable(f"{b} 现在没有数")
        return {"text": vizmod._text(val, m["nd"]), "unit": v["unit"], "zone": None, "asof": v.get("asof")}

    def one(n: dict) -> dict:
        t = n["t"]
        try:
            if t in ("v", "h"):
                return {**n, "children": [one(k) for k in n["children"]]}
            if t in ("value", "stat"):
                if "bind" in n:
                    s = scalar(n["bind"])
                    out = {**n, "text": s["text"], "unit": s["unit"], "zone": s["zone"]}
                    out.pop("bind")
                    if t == "stat" and not out.get("label"):
                        out["label"] = s.get("label") or n["bind"]
                    return out
                out = {k: v for k, v in n.items() if k != "value"}
                return {**out, "text": n.get("value", ""), "zone": None}
            if t == "chart":
                spec = {k: n[k] for k in ("metric", "kind", "days", "show") if k in n}
                return {"t": "chart", "height": n["height"], "viz": vizmod.build(tools, spec, day, now)}
            if t == "dots":
                return {"t": "dots", **_dots(tools, n["bind"], n["days"], day, now, vz)}
            if t == "bar":
                return {"t": "bar", **_bar(n["bind"], vz)}
            if t == "ring":
                return {"t": "ring", **_ring(tools, n["bind"], day, vz)}
            if t == "level":
                return {**n, "text": LEVEL_TEXT[n["level"]]}
            if t == "timeline":
                return {"t": "timeline", "items": _timeline(tools, n["n"], day, now, board)}
            return dict(n)
        except (vizmod.VizUnavailable, KeyError, ValueError) as exc:
            return {"t": "text", "text": f"这里的数暂时算不出来（{str(exc)[:20]}）", "role": "caption", "tone": 3}

    return one(layout)


def _dots(tools, b: str, days: int, day: date, now: datetime, vz) -> dict:
    if b == "sleep.nights":
        v = vz("sleep", "need", 14 if days > 7 else 7)
        nights = (v.get("nights") or [])[-days:]
        items = [{"on": bool(n["ok"]), "label": n["night_of"][5:]} for n in nights]
        short = sum(1 for i in items if not i["on"])
        return {"items": items, "caption": f"近 {len(items)} 晚 · {short} 晚没睡够" if short else f"近 {len(items)} 晚都睡够了"}
    if b == "steps.week":
        goal = (vz("steps").get("goal")) or vizmod.STEPS_GOAL
        series = tools.daily_series("steps", day, days)
        items = []
        for i in range(days - 1, -1, -1):
            d = day - timedelta(days=i)
            val = series.get(d)
            items.append({"on": bool(val is not None and val >= goal), "now": d == day, "label": f"{d.month}/{d.day}"})
        hit = sum(1 for i in items if i["on"])
        return {"items": items, "caption": f"近 {days} 天 {hit} 天走够 {int(goal):,} 步"}
    if b.startswith("project:"):
        from .todos import TodoStore
        store = TodoStore(tools.cfg)
        pid = b.split(":", 1)[1]
        proj = next((p for p in store.projects() if p["id"] == pid), None)
        if not proj:
            raise KeyError(f"没有项目 {pid}")
        start = date.fromisoformat(proj["start"])
        items = []
        for i in range(days - 1, -1, -1):
            d = day - timedelta(days=i)
            if d < start:
                continue
            ts = [t for t in store.for_date(d, proj["board"]) if t.get("project") == pid]
            done = bool(ts) and all(t["status"] in ("done",) for t in ts)
            items.append({"on": done, "now": d == day, "label": f"{d.month}/{d.day}"})
        hit = sum(1 for i in items if i["on"] and not i.get("now"))
        past = sum(1 for i in items if not i.get("now"))
        return {"items": items, "caption": f"{proj['name']} · 近 {past} 天做到 {hit} 天"}
    raise KeyError(b)


def _bar(b: str, vz) -> dict:
    if b == "sleep":
        v = vz("sleep", "need")
        need = v.get("need") or 0
        frac = v["value"] / need if need else 1
        return {"fraction": round(min(1.0, frac), 3), "left": f"睡了 {v['value_text']} 小时",
                "right": f"需要 {vizmod._text(need, 1)}"}
    if b == "steps":
        v = vz("steps", "progress")
        frac = v["value"] / v["goal"] if v.get("goal") else 1
        marker = v["pace"] / v["goal"] if v.get("goal") and v.get("pace") else None
        return {"fraction": round(min(1.0, frac), 3), "marker": round(min(1.0, marker), 3) if marker else None,
                "left": f"{int(v['value']):,} 步", "right": f"目标 {int(v['goal']):,}"}
    if b == "weight":
        v = vz("weight", "route")
        start, target, cur = v.get("start"), v.get("target"), v.get("value")
        if start is None or target is None or start == target:
            raise vizmod.VizUnavailable("体重还没有起点和目标")
        frac = (start - cur) / (start - target)
        return {"fraction": round(max(0.0, min(1.0, frac)), 3), "left": f"已减 {vizmod._text(start - cur, 1)} kg",
                "right": f"目标 {vizmod._text(target, 1)} kg"}
    raise KeyError(b)


def _ring(tools, b: str, day: date, vz) -> dict:
    if b == "recovery":
        v = vz("recovery")
        return {"fraction": round(v["value"] / 100, 3), "text": v["value_text"], "sub": "%", "zone": v.get("zone")}
    if b == "steps":
        v = vz("steps", "progress")
        return {"fraction": round(min(1.0, v["value"] / v["goal"]), 3) if v.get("goal") else 1,
                "text": f"{int(v['value']):,}", "sub": f"/ {int(v['goal']):,}", "zone": v.get("zone")}
    if b.startswith("project:"):
        from .todos import TodoStore
        pid = b.split(":", 1)[1]
        proj = next((p for p in TodoStore(tools.cfg).projects() if p["id"] == pid), None)
        if not proj:
            raise KeyError(f"没有项目 {pid}")
        n = (day - date.fromisoformat(proj["start"])).days + 1
        return {"fraction": round(min(1.0, n / max(1, proj["days"])), 3), "text": str(n), "sub": f"/ {proj['days']} 天",
                "zone": None}
    raise KeyError(b)


def _timeline(tools, n: int, day: date, now: datetime, board: str | None) -> list[dict]:
    from .todos import PENDING, TodoStore
    hm = now.strftime("%H:%M")
    ts = [t for t in TodoStore(tools.cfg).for_date(day, None if board in (None, "now") else board)
          if t["status"] in PENDING]
    ts.sort(key=lambda t: ((t.get("when") or "99:99") < hm, t.get("when") or "99:99"))   # 还没到点的排前面
    return [{"when": t.get("when") or "", "title": t["title"], "note": t.get("note") or ""} for t in ts[:n]]


def binds_help() -> dict:
    """给 P-Health 看的：现在每种绑定能用哪些。"""
    return {k: v for k, v in BIND_KINDS.items()}
