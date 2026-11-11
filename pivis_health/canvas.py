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
  columns    竖柱图（每天一根）    {"t":"columns","metric":"sleep|steps|hrv|resting_hr|resp_rate|recovery|weight","days":7,"height":"s|m"}
  ring       圆环进度             {"t":"ring","bind":"recovery|steps|project:<id>"}
  level      档位点 + 字           {"t":"level","level":"act|watch|steady"}
  rule       细线
  list       清单                 {"t":"list","items":["…"],"style":"dot|number"}
  timeline   接下来的待办          {"t":"timeline","n":2}
  spacer     留白                 {"t":"spacer","size":8|16|24}
另有占比 / 时间 / 趋势 / 进度四组新零件（pie donut stack … photo）：校验、高度、现算在 canvas_parts.py，
说明书在本文件末尾的 PARTS（./pivis-health parts 打印的就是它）。
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from . import viz as vizmod
from .clock import day_of

SLOTS = {"hero": {"w": 354, "h": 400}, "chat": {"w": 312, "h": 520}}
GAPS = (0, 4, 8, 12, 16, 24)
ROLES = {"title": 18, "body": 60, "caption": 40, "label": 14}        # 每种文字最多几个字
ROLE_H = {"title": 22, "body": 21, "caption": 17, "label": 16}
CHARS_PER_LINE = {"title": 16, "body": 21, "caption": 26, "label": 30}
VALUE_H = {"xl": 84, "l": 54, "m": 36}
CHART_H = {"s": 84, "m": 124, "l": 164}
COLUMN_METRICS = ("sleep", "steps", "hrv", "resting_hr", "resp_rate", "recovery", "weight")
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
            return {"t": "dots", "bind": b, "days": max(3, min(MAX_DAYS, days))}
        if t == "bar":
            return {"t": "bar", "bind": _check_bind(str(node.get("bind") or ""), ("bar",))}
        if t == "columns":
            m = str(node.get("metric") or node.get("bind") or "").split(".")[0]
            if m not in COLUMN_METRICS:
                raise CanvasError(f"columns 的 metric 只能是 {' / '.join(COLUMN_METRICS)}")
            days = int(node.get("days") or 7)
            return {"t": "columns", "metric": m, "days": max(3, min(MAX_DAYS, days)),
                    "height": node.get("height") if node.get("height") in ("s", "m") else "s"}
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
        from . import canvas_parts
        if t in canvas_parts.NORMALIZERS:
            return canvas_parts.NORMALIZERS[t](node, check_num, t)
        raise CanvasError(f"不认识的零件 {t!r}：只能用 {' '.join(p['name'] for p in PARTS)}"
                          "（./pivis-health parts 看每个怎么写）")

    root = norm(layout, 1)
    h = estimate(root)
    if h > SLOTS[slot]["h"]:
        raise CanvasError(f"估算高度 {h} 超过画布 {SLOTS[slot]['h']}：少放几样，或者把图改成 height=s")
    return root


BIND_KINDS = {
    "scalar": ("指标数值：" + " / ".join(SCALAR_METRICS) + "，或 <指标>.need / .goal / .target / .short / .pace / .warn / .prev；"
               "做 CBT-I 时还有 cbti.efficiency（7 晚效率中位）/ efficiency_last / ge90 / kept（守住窗口几晚）/ window / week / "
               "review_in / suggest（复盘建议）/ early / late / rise_dev / diary / breaks / in_bed / asleep / awake / to_bed"),
    "dots": "sleep.nights（每晚睡够没）、steps.week（每天走够没）、project:<项目 id>（项目每天做了没）",
    "bar": "sleep（睡了 / 需要）、steps（走了 / 目标）、weight（已减 / 计划）",
    "ring": "recovery（恢复分数）、steps（走了 / 目标）、project:<项目 id>（第几天 / 共几天）",
    # ---- 新零件
    "stages": "sleep.stages（最近一晚分期：WHOOP，没有就 Apple Watch）、training.zones（近 7 天训练心率区间合成 轻松 Z0–2 / 中等 Z3 / 高强度 Z4–5）、cbti.lastnight（做 CBT-I 时：昨晚在床拆成 睡着 / 醒着）",
    "streak": "sleep.nights、steps.week、project:<项目 id>，或 wake:HH:MM（起床不晚于该时间 +15 分钟）",
    "workout": "workout.last（最近一次训练）、workout.week（近 7 天合计），读 WHOOP 训练的心率区间时长",
    "series": "每天一个数的指标：hrv / resp_rate / resting_hr / recovery / sleep / steps / weight（步数不含今天）",
    "diverging": "sleep.need（每晚睡了 − 需要）、steps.goal（每天步数 − 目标）",
    "lollipop": "project:<项目 id>（每天跟做了几分钟，用待办的 duration_min，没做 = 0），或 <指标>",
    "histogram": "bedtime（入睡时间，30 分钟一格），或 <指标>",
    "bullet": "sleep.efficiency（最近一晚睡眠效率，分段 85 / 90，目标 90）、recovery、steps、sleep、hrv、resp_rate、resting_hr",
    "compare": "sleep / steps / hrv / resting_hr / recovery（按星期对齐这周和上周）",
    "weekgrid": "project:<项目 id>、steps、sleep（本周一到周日）",
    "progress": "projects（每个进行中的项目一行：近 N 天做到几天）、project:<项目 id>（项目里每个待办一行）",
    "project": "project:<项目 id>（项目 id 用 ./pivis-health project-list 查；CBT-I 的窗口取 sleep.cbti 记下的）",
    "radar": ("固定五维，近 7 天 vs 再往前 7 天，各 0–100：睡眠 = 平均(睡了/需要) 封顶 100；恢复 = WHOOP 恢复平均；"
              "运动 = 平均(步数/目标) 封顶 100；压力 = 100 − clamp((个人基线 HRV − 这 7 天 HRV)/基线 ×200, 0, 100)；"
              "习惯 = 进行中项目的执行率。缺哪维那维给 null"),
}


def _check_bind(b: str, kinds: tuple[str, ...]) -> str:
    b = b.strip()
    kind = kinds[0]
    if kind == "scalar":
        if re.match(r"^insight:[A-Za-z0-9]+\.[A-Za-z_]+$", b):      # 洞察那段话里的小卡：数取自候选
            return b
        base, _, field = b.partition(".")
        if base in SCALAR_METRICS and (not field or field in EXTRA_FIELDS):
            return b
        from .cbti import SCALARS as CBTI_SCALARS
        if base == "cbti" and field in CBTI_SCALARS:
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
    elif kind in _NEW_BINDS:
        ok, prefixes = _NEW_BINDS[kind]
        if b in ok or any(b.startswith(p) and len(b) > len(p) for p in prefixes):
            return b
    raise CanvasError(f"bind {b!r} 不认识。能用的：{BIND_KINDS[kind]}")


_SERIES = ("hrv", "resp_rate", "resting_hr", "recovery", "sleep", "steps", "weight")
_NEW_BINDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {      # kind → (整串能用的, 能用的前缀)
    "stages": (("sleep.stages", "training.zones", "cbti.lastnight"), ()),
    "streak": (("sleep.nights", "steps.week"), ("project:",)),
    "series": (_SERIES, ()),
    "diverging": (("sleep.need", "steps.goal"), ()),
    "lollipop": (_SERIES, ("project:",)),
    "histogram": (("bedtime",) + _SERIES, ()),
    "bullet": (("sleep.efficiency", "recovery", "steps", "sleep", "hrv", "resp_rate", "resting_hr"), ()),
    "weekgrid": (("steps", "sleep"), ("project:",)),
    "progress": (("projects",), ("project:",)),
    "project": ((), ("project:",)),
}


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
    if t == "columns":
        return CHART_H[n.get("height", "s")] + 36      # 柱子 + 底下的日期 + 上面一行说明
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
    from . import canvas_parts
    if t in canvas_parts.ESTIMATES:
        return canvas_parts.ESTIMATES[t](n)
    return 20


# ---------------------------------------------------------------- 解析（内核现算）
def resolve(tools, layout: dict, day: date | None = None, now: datetime | None = None,
            board: str | None = None) -> dict:
    """把绑定数据的零件换成显示值。某个零件算不出来（数据断了）就换成一行说明，整张卡不挂。"""
    now = now or tools._now()
    day = day or day_of(now)
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
        if base == "cbti":
            from . import cbti
            if "cbti" not in cache:
                cache["cbti"] = cbti.state(tools, day, now)
            if not cache["cbti"]:
                raise vizmod.VizUnavailable("现在没有进行中的 CBT-I")
            s = cbti.scalar(cache["cbti"], field)
            return {**s, "zone": None, "asof": None}
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

    from . import canvas_parts as parts
    ctx = parts.Ctx(tools, day, now, board, vz)

    def one(n: dict) -> dict:
        t = n["t"]
        try:
            if t in ("v", "h"):
                kids, seen = [], set()
                for k in (one(k) for k in n["children"]):
                    if k.get("fallback"):        # 同一个原因算不出来的几格，只留一行说明（以前会重复两遍）
                        if k["text"] in seen:
                            continue
                        seen.add(k["text"])
                    kids.append(k)
                return {**n, "children": kids}
            if t in ("value", "stat"):
                if str(n.get("bind") or "").startswith("insight:"):
                    from . import insight
                    v = insight.bind_value(tools.cfg, n["bind"])
                    out = {k: x for k, x in n.items() if k != "bind"}
                    out.update({"text": str(v), "unit": out.get("unit") or "", "zone": None})
                    if t == "stat" and not out.get("label"):
                        out["label"] = ""
                    return out
                if "bind" in n:
                    s = scalar(n["bind"])
                    out = {**n, "text": s["text"], "unit": s["unit"], "zone": s["zone"]}
                    out.pop("bind")
                    if t == "stat" and (not out.get("label") or str(n["bind"]).startswith("cbti.")):
                        # CBT-I 的数含义固定（起晚 / 早上床 / 起床偏差…），小标题用内核的，免得写成「晚上床」这种反的
                        out["label"] = s.get("label") or n["bind"]
                    return out
                out = {k: v for k, v in n.items() if k != "value"}
                return {**out, "text": n.get("value", ""), "zone": None}
            if t == "chart":
                spec = {k: n[k] for k in ("metric", "kind", "days", "show") if k in n}
                return {"t": "chart", "height": n["height"], "viz": vizmod.build(tools, spec, day, now)}
            if t == "dots":
                return {"t": "dots", **_weekly(_dots(tools, n["bind"], n["days"], day, now, vz), "dots")}
            if t == "bar":
                return {"t": "bar", **_bar(n["bind"], vz)}
            if t == "columns":
                return {"t": "columns", "height": n["height"], **_weekly(_columns(n["metric"], n["days"], day, vz), "columns")}
            if t == "ring":
                return {"t": "ring", **_ring(tools, n["bind"], day, vz)}
            if t == "level":
                return {**n, "text": LEVEL_TEXT[n["level"]]}
            if t == "timeline":
                return {"t": "timeline", "items": _timeline(tools, n["n"], day, now, board)}
            if t in parts.RESOLVERS:
                return {"t": t, **parts.RESOLVERS[t](ctx, n)}
            return dict(n)
        except (vizmod.VizUnavailable, KeyError, ValueError) as exc:
            return {"t": "text", "text": f"这里的数暂时算不出来（{str(exc)[:20]}）", "role": "caption", "tone": 3,
                    "fallback": True}
        except Exception:  # noqa: BLE001  读库失败这类意外：只影响这一格，整张卡照样画
            return {"t": "text", "text": "这里的数据暂时读不到，稍后自动恢复", "role": "caption", "tone": 3,
                    "fallback": True}

    return one(layout)


def live_gaps(source: Any, resolved: Any) -> tuple[int, list[str]]:
    """发布前看看主卡现在能不能画出来：（绑了数据的零件数，算不出来的说明）。"""
    def count(n: Any) -> int:
        if not isinstance(n, dict):
            return 0
        own = 1 if any(k in n for k in ("bind", "metric")) else 0
        return own + sum(count(k) for k in n.get("children") or [])

    def gaps(n: Any) -> list[str]:
        if not isinstance(n, dict):
            return []
        own = [n["text"]] if n.get("fallback") else []
        return own + [g for k in n.get("children") or [] for g in gaps(k)]
    return count(source), gaps(resolved)


MAX_DAYS = 90            # 一排点、竖柱图最多看 90 天；超过 30 天按周汇总（App 一行放不下 30 个以上）
WEEKLY_AFTER = 30


def _weekly(doc: dict, kind: str) -> dict:
    """超过 30 天：每 7 天并成一格（从最早那天起），点 = 那周一半以上的天做到；柱 = 那周的平均。"""
    items = doc.get("items") or []
    if len(items) <= WEEKLY_AFTER:
        return doc
    out = []
    for i in range(0, len(items), 7):
        chunk = items[i:i + 7]
        on = sum(1 for x in chunk if x.get("on")) * 2 >= len(chunk)
        row = {"label": chunk[0].get("label"), "on": on, "week": True}
        if kind == "columns":
            vals = [x["value"] for x in chunk if isinstance(x.get("value"), (int, float))]
            if not vals:
                continue
            avg = sum(vals) / len(vals)
            row.update({"value": round(avg, 2), "text": f"{int(avg):,}" if avg >= 1000 else f"{avg:.1f}".rstrip("0").rstrip(".")})
            if any(x.get("ref") is not None for x in chunk):
                refs = [x["ref"] for x in chunk if isinstance(x.get("ref"), (int, float))]
                row["ref"] = round(sum(refs) / len(refs), 2) if refs else None
        if any(x.get("now") for x in chunk):
            row["now"] = True
        out.append(row)
    return {**doc, "items": out, "weekly": True}


def _dots(tools, b: str, days: int, day: date, now: datetime, vz) -> dict:
    if b == "sleep.nights":
        v = vz("sleep", "need", 14 if days > 7 else 7)
        nights = (v.get("nights") or [])[-days:]
        items = [{"on": bool(n["ok"]), "label": n["night_of"][5:]} for n in nights]
        short = sum(1 for i in items if not i["on"])
        return {"items": items, "caption": f"{short} 晚没睡够" if short else "都睡够了"}
    if b == "steps.week":
        goal = (vz("steps").get("goal")) or vizmod.STEPS_GOAL
        series = tools.daily_series("steps", day, days)
        items = []
        for i in range(days - 1, -1, -1):
            d = day - timedelta(days=i)
            val = series.get(d)
            items.append({"on": bool(val is not None and val >= goal), "now": d == day, "label": f"{d.month}/{d.day}"})
        hit = sum(1 for i in items if i["on"])
        return {"items": items, "caption": f"{hit} 天走够 {int(goal):,} 步"}
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


def _columns(metric: str, days: int, day: date, vz) -> dict:
    """每天（每晚）一根竖柱，从 0 起画（柱高和数成正比，不夸大差别）。
    睡眠：每根柱上标当晚需要多少，够了的柱子实心；步数：画目标线，走够的实心；其他指标：只画柱，最后一根实心。"""
    m = vizmod.METRICS[metric]
    nd = m["nd"]
    items: list[dict] = []
    ref = ref_label = None
    if metric == "sleep" and days <= 14:
        v = vz("sleep", "need", 14 if days > 7 else 7)
        nights = (v.get("nights") or [])[-days:]
        if not nights:
            raise vizmod.VizUnavailable("没有睡眠数据")
        for n in nights:
            d = date.fromisoformat(n["night_of"])
            items.append({"label": f"{d.month}/{d.day}", "value": n["slept"], "text": vizmod._text(n["slept"], 1),
                          "ref": n.get("need"), "on": bool(n["ok"])})
        short = sum(1 for i in items if not i["on"])
        need = nights[-1].get("need")
        ref_label = f"需要 {vizmod._text(need, 1)}" if need else None
        caption = f"{short} 晚没睡够" if short else "都睡够了"          # 「近 N 晚」横轴已经看得出，不再写（老大 11-11：少写字）
    else:
        # 超过 14 晚的睡眠也走走势这条路（「需要多少」只有近 14 晚）；viz 的天数只有 7 / 14 / 30 / 90 几档，取够用的那档再截
        v = vz(metric, "trend", next(x for x in vizmod.DAYS["trend"] if x >= days))
        series = (v.get("series") or [])[-days:]
        if not series:
            raise vizmod.VizUnavailable(f"没有{m['label']}数据")
        goal = None
        if metric == "steps":
            try:
                goal = vz("steps").get("goal") or vizmod.STEPS_GOAL
            except vizmod.VizUnavailable:     # 今天的数出不来也照样画前几天的柱
                goal = vizmod.STEPS_GOAL
        for i, p in enumerate(series):
            d = date.fromisoformat(p["date"])
            val = p["value"]
            text = f"{int(val):,}" if metric == "steps" else vizmod._text(val, nd)
            on = (val >= goal) if goal else (i == len(series) - 1)
            items.append({"label": f"{d.month}/{d.day}", "value": val, "text": text, "on": bool(on),
                          "now": d == day})
        if goal:
            ref, ref_label = goal, f"目标 {int(goal):,}"
            hit = sum(1 for i in items if i["on"])
            last = items[-1]
            if last.get("now") and not last["on"]:      # 今天还没走完，不算没走够
                caption = f"前 {len(items) - 1} 天 {hit} 天走够"
            else:
                caption = f"{hit} 天走够"
        else:
            caption = ""                       # 指标名主卡上方已经写了
    top = max([i["value"] for i in items] + [i.get("ref") or 0 for i in items] + [ref or 0])
    return {"items": items, "ref": ref, "ref_label": ref_label, "unit": m["unit"], "max": top,
            "caption": caption}


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
    from .todos import PENDING, TodoStore, _sort_when, due_at
    nowl = now.replace(tzinfo=None)
    ts = [t for t in TodoStore(tools.cfg).for_date(day, None if board in (None, "now") else board)
          if t["status"] in PENDING]
    # 还没到点的排前面；00:00–05:59 算当晚（22:00 时 00:30 还没到）
    ts.sort(key=lambda t: (bool(t.get("when")) and due_at(t["date"], t["when"]) < nowl, _sort_when(t.get("when") or "")))
    return [{"when": t.get("when") or "", "title": t["title"], "note": t.get("note") or ""} for t in ts[:n]]


def binds_help() -> dict:
    """给 P-Health 看的：现在每种绑定能用哪些（radar 那条是五维的换算规则）。"""
    return {k: v for k, v in BIND_KINDS.items()}


# ---------------------------------------------------------------- 零件说明书（唯一来源：skill 和 ./pivis-health parts 都读这里）
# name / cn 中文名 / group / example 输入示例 / when 什么时候用 / data 数从哪来 / height 估算高度 / binds 用到的绑定 / notes 限制
PART_GROUPS = ("基础", "占比", "时间", "趋势", "进度")
PARTS: list[dict] = [
    # ---- 基础（排版和最早的 15 个）
    {"name": "v", "cn": "竖排", "group": "基础", "example": {"t": "v", "gap": 12, "children": []},
     "when": "从上往下排几样东西；gap 只能 0/4/8/12/16/24", "data": "—", "height": "子零件相加 + gap"},
    {"name": "h", "cn": "横排", "group": "基础",
     "example": {"t": "h", "justify": "between", "align": "baseline", "children": []},
     "when": "左右并排，最多 4 个；两头对齐 justify=between，数字底对齐 align=baseline", "data": "—", "height": "最高的那个"},
    {"name": "text", "cn": "文字", "group": "基础", "example": {"t": "text", "text": "最近几晚都欠觉", "role": "title", "tone": 1},
     "when": "判断、提示、小标题；数字交给 value / stat", "data": "手写（主卡里数字只能抄证据）",
     "notes": "role：title≤18 / body≤60 / caption≤40 / label≤14；tone 1 白 2 灰 3 浅灰", "height": "按字数折行"},
    {"name": "value", "cn": "大数字", "group": "基础", "example": {"t": "value", "bind": "sleep", "size": "xl"},
     "when": "一张卡最重要的那一个数（xl 只放一个）", "data": "bind 内核现算，或手写 value + unit", "binds": ["scalar"],
     "height": "xl 84 / l 54 / m 36（有 label +18）"},
    {"name": "stat", "cn": "小字段", "group": "基础", "example": {"t": "stat", "label": "HRV", "bind": "hrv"},
     "when": "支撑的数，横排 2–3 个", "data": "bind 内核现算，或手写 value", "binds": ["scalar"], "height": "44"},
    {"name": "chart", "cn": "主卡同款图", "group": "基础",
     "example": {"t": "chart", "metric": "hrv", "kind": "trend", "days": 14, "show": ["band", "warn"], "height": "m"},
     "when": "小幅波动 + 常态带 + 警戒线（HRV、静息心率、呼吸）；sleep_efficiency 是每晚睡眠效率（带子 ≥90、虚线 85，做 CBT-I 时写成加 / 减窗口）",
     "data": "./pivis-health viz 同一份数",
     "height": "s 84 / m 124 / l 164（gauge +60）"},
    {"name": "dots", "cn": "一排点", "group": "基础", "example": {"t": "dots", "bind": "sleep.nights", "days": 7},
     "when": "只关心每天达没达标（3–90 天；超过 30 天每 7 天并成一格）", "data": "睡眠（最多近 14 晚）/ 步数 / 项目打卡",
     "binds": ["dots"], "height": "30"},
    {"name": "bar", "cn": "进度条", "group": "基础", "example": {"t": "bar", "bind": "sleep"},
     "when": "一个数离目标多远", "data": "睡了 vs 需要 / 走了 vs 目标 / 已减 vs 计划", "binds": ["bar"], "height": "34"},
    {"name": "columns", "cn": "竖柱图", "group": "基础", "example": {"t": "columns", "metric": "sleep", "days": 7, "height": "s"},
     "when": "每天各多少（每晚睡了多久、每天步数），从 0 起画（3–90 天；超过 30 天每根是一周的平均）",
     "data": "metric：sleep / steps / hrv / resting_hr / resp_rate / recovery / weight", "height": "s 120 / m 160"},
    {"name": "response", "cn": "提醒到动手", "group": "时间", "example": {"t": "response", "bind": "insight:c11101.response"},
     "when": "只在洞察那段话里用：某个提醒每次几点开始做，横轴时间、一条提醒线、每次开始一个点",
     "data": "洞察候选（has_response_card=true 的候选；c11101 换成候选 id）", "height": "96"},
    {"name": "split", "cn": "两组对比", "group": "占比", "example": {"t": "split", "bind": "insight:c11101.split"},
     "when": "只在洞察那段话里用：两组日子（做了 / 没做、外宿后 / 其他）的平均值对比，两根横条",
     "data": "洞察候选（has_split_card=true 的候选）", "height": "80"},
    {"name": "dotstrip", "cn": "每天一点", "group": "时间", "example": {"t": "dotstrip", "bind": "insight:c11101.dotstrip"},
     "when": "只在洞察那段话里用：每天一个点，实心 = 那天做了，下面一道 = 结果好的日子",
     "data": "洞察候选（has_dotstrip_card=true 的候选）", "height": "110"},
    {"name": "ring", "cn": "圆环", "group": "基础", "example": {"t": "ring", "bind": "recovery"},
     "when": "0–100 的分数，或项目第几天 / 共几天", "data": "恢复 / 步数 / 项目", "binds": ["ring"], "height": "96"},
    {"name": "level", "cn": "档位点", "group": "基础", "example": {"t": "level", "level": "watch"},
     "when": "标一下 需要处理 / 留意 / 平稳", "data": "—", "height": "20"},
    {"name": "rule", "cn": "细线", "group": "基础", "example": {"t": "rule"}, "when": "分隔两块，别连用两条", "data": "—", "height": "1"},
    {"name": "list", "cn": "清单", "group": "基础", "example": {"t": "list", "items": ["睡前 1 小时不看工作消息"], "style": "number"},
     "when": "几条规矩、几步做法（1–5 条，每条 ≤30 字）", "data": "手写", "height": "按条数"},
    {"name": "timeline", "cn": "接下来的待办", "group": "基础", "example": {"t": "timeline", "n": 2},
     "when": "对话卡里列接下来 1–3 件待办；主卡里不能放（页面下面已经有）", "data": "今天的待办", "height": "46 × n"},
    {"name": "spacer", "cn": "留白", "group": "基础", "example": {"t": "spacer", "size": 16}, "when": "拉开距离（8/16/24）",
     "data": "—", "height": "size"},
    # ---- 占比与构成
    {"name": "pie", "cn": "饼图", "group": "占比", "example": {"t": "pie", "bind": "sleep.stages"},
     "when": "几样东西各占多少（睡眠分期、训练强度），最多 5 块", "data": "WHOOP / Apple Watch 分期；WHOOP 训练心率区间；或手写 items",
     "binds": ["stages"], "notes": "手写：items 2–5 项 {label≤14, value 数字}", "height": "140"},
    {"name": "donut", "cn": "环形占比", "group": "占比", "example": {"t": "donut", "bind": "training.zones", "center": "轻松"},
     "when": "和饼图一样讲占比，中间放最重要的那一块（center 写 label，不写就放最大的）", "data": "同 pie", "binds": ["stages"],
     "height": "140"},
    {"name": "stack", "cn": "横向堆叠条", "group": "占比", "example": {"t": "stack", "bind": "sleep.stages"},
     "when": "一条讲清一个整体的构成，比饼图省地方，适合放在大数下面", "data": "同 pie（手写可加 title≤18）", "binds": ["stages"],
     "height": "72"},
    {"name": "stack_columns", "cn": "堆叠竖柱", "group": "占比",
     "example": {"t": "stack_columns", "bind": "sleep.stages", "days": 7, "height": "s"},
     "when": "每晚一根柱，再看每根里深睡 / 快速眼动 / 浅睡的构成（3–14 晚）", "data": "WHOOP 分期 + 当晚需要；没有 WHOOP 的晚上用 Apple Watch",
     "height": "s 150 / m 190"},
    {"name": "waffle", "cn": "方格占比", "group": "占比", "example": {"t": "waffle", "bind": "sleep.nights", "days": 30},
     "when": "「几成做到了」（7–60 天，每格一天）", "data": "睡眠 / 步数 / 项目打卡；没数据的晚上和今天还没做完的不算格",
     "binds": ["dots"], "height": "ceil(days/10)×24 + 24"},
    {"name": "zones", "cn": "心率区间", "group": "占比", "example": {"t": "zones", "bind": "workout.last"},
     "when": "一次训练（或近 7 天）在各强度停了多久，看练得太猛还是太轻", "data": "WHOOP 训练 zone_durations（Z0 并进 Z1）",
     "binds": ["workout"], "height": "130"},
    {"name": "radar", "cn": "雷达", "group": "占比", "example": {"t": "radar"},
     "when": "睡眠、恢复、运动、压力、习惯五维一起看强弱，这周 vs 上周", "data": "内核按固定规则换算（见 binds.radar）",
     "binds": ["radar"], "height": "200"},
    # ---- 时间与作息
    {"name": "hypnogram", "cn": "睡眠阶梯", "group": "时间", "example": {"t": "hypnogram"},
     "when": "昨晚在各阶段怎么走，夜醒在什么时候", "data": "Apple Watch 分期片段（只有 WHOOP 的晚上画不了）", "height": "110"},
    {"name": "sleep_window", "cn": "作息条", "group": "时间", "example": {"t": "sleep_window", "days": 7},
     "when": "每晚一条，从上床到起床；CBT-I 一眼看出守没守窗口（3–14 晚）",
     "data": "WHOOP / Apple 健康的入睡起床时间；band 不写时有 CBT-I 项目就自动画 sleep.cbti 的窗口",
     "notes": "可加 \"band\":\"project:<id>\"", "height": "days×14 + 40"},
    {"name": "clock24", "cn": "24 小时环", "group": "时间", "example": {"t": "clock24"},
     "when": "今天睡觉、训练、待办各在哪个钟点", "data": "昨晚睡眠、今天的 WHOOP 训练、今天带时间的待办（最多 6 个）",
     "notes": "弧的 from > to 表示跨过 0 点", "height": "160"},
    {"name": "calendar", "cn": "月历", "group": "时间", "example": {"t": "calendar", "bind": "sleep.nights", "month": "current"},
     "when": "一个月的规律：哪几周差、周末是不是不一样", "data": "睡眠 / 步数 / 项目打卡；month = current / prev / YYYY-MM",
     "binds": ["dots"], "height": "200"},
    {"name": "weekgrid", "cn": "一周七格", "group": "时间", "example": {"t": "weekgrid", "bind": "project:<项目id>"},
     "when": "本周一到周日的计划和完成放一排，每格两个字", "data": "项目待办 / 步数 / 睡眠", "binds": ["weekgrid"], "height": "80"},
    {"name": "streak", "cn": "连续天数", "group": "时间", "example": {"t": "streak", "bind": "wake:08:30"},
     "when": "坚持类目标：连续几天，断掉的那天也看得见", "data": "项目打卡 / 睡眠 / 步数 / 起床时间（近 60 天）",
     "binds": ["streak"], "height": "130"},
    {"name": "countdown", "cn": "倒计时", "group": "时间", "example": {"t": "countdown", "to": "01:30", "label": "离上床还有"},
     "when": "离某个钟点还有多久（上床、下次训练、咖啡截止）", "data": "内核按现在的时间算；to 可写 project:<id>:<待办 key>",
     "notes": "label≤14，sub≤40 可选", "height": "120"},
    {"name": "time_range", "cn": "时间段", "group": "时间", "example": {"t": "time_range", "from": "01:30", "to": "08:30", "label": "睡眠窗口"},
     "when": "一个时间段本身就是重点（睡眠窗口、训练时段、勿扰）", "data": "手写，或 bind project:cbti 取 sleep.cbti 的窗口",
     "binds": ["project"], "notes": "label≤14，note≤40 可选", "height": "110"},
    {"name": "milestones", "cn": "阶段时间线", "group": "时间", "example": {"t": "milestones", "bind": "project:<项目id>"},
     "when": "长期项目的开始、复盘点、结束（阶段多时用；少就用 stepper）", "data": "项目的 start / reviews / 天数；或手写 items + current",
     "binds": ["project"], "notes": "手写 items ≤5，每项 {title≤20, sub≤20}", "height": "条数×46 + 24"},
    # ---- 趋势与对比
    {"name": "sparkline", "cn": "迷你走势", "group": "趋势", "example": {"t": "sparkline", "bind": "hrv", "days": 14},
     "when": "一个数后面跟一条小线，看方向不看细节（7–30 天）", "data": "每天一个数的指标", "binds": ["series"], "height": "56"},
    {"name": "stat_spark", "cn": "字段 + 走势", "group": "趋势", "example": {"t": "stat_spark", "bind": "hrv", "label": "HRV"},
     "when": "stat 加一条 14 天小线，放 h 里横排 2–3 个；近 3 天比前 3 天动了超过 3% 的线是白的", "data": "同 sparkline",
     "binds": ["series"], "height": "74"},
    {"name": "delta", "cn": "变化量", "group": "趋势", "example": {"t": "delta", "bind": "hrv", "baseline": "prev3"},
     "when": "只讲变了多少，比较对象写清楚：prev3 前 3 天 / prev_week 上一周 / personal 30 天平均", "data": "内核现算",
     "binds": ["series"], "height": "110"},
    {"name": "compare", "cn": "两周对比", "group": "趋势", "example": {"t": "compare", "bind": "sleep"},
     "when": "按星期对齐这周和上周，看是不是整体少了一截", "data": "sleep / steps / hrv / resting_hr / recovery", "binds": ["compare"],
     "height": "140"},
    {"name": "dual_line", "cn": "两条线", "group": "趋势", "example": {"t": "dual_line", "a": "hrv", "b": "resting_hr", "days": 14},
     "when": "两项一起动才算数（HRV 降 + 静息心率升），各用各的刻度", "data": "任意两项每天的指标（只取两项都有数的天）",
     "binds": ["series"], "height": "140"},
    {"name": "diverging", "cn": "正负柱", "group": "趋势", "example": {"t": "diverging", "bind": "sleep.need", "days": 7},
     "when": "和一条线比，多了往上、少了往下（欠觉、步数差）", "data": "睡了 − 需要 / 步数 − 目标", "binds": ["diverging"],
     "height": "120"},
    {"name": "lollipop", "cn": "棒棒糖", "group": "趋势", "example": {"t": "lollipop", "bind": "project:<项目id>", "days": 7, "target": 12},
     "when": "每天一个小量（放松、训练分钟），比柱子轻", "data": "项目里做完的待办 duration_min 相加；或某项指标",
     "binds": ["lollipop"], "notes": "target 可省（项目取模板时长，步数取目标）", "height": "120"},
    {"name": "scatter", "cn": "散点", "group": "趋势", "example": {"t": "scatter", "x": "sleep", "y": "hrv", "days": 30, "lag": 1},
     "when": "两件事有没有关系（只说明相关，不代表因果）；样本少于 14 个不画", "data": "任意两项每天的指标；lag=1 是 x 当晚 vs y 第二天",
     "binds": ["series"], "height": "160"},
    {"name": "histogram", "cn": "分布", "group": "趋势", "example": {"t": "histogram", "bind": "bedtime", "days": 30},
     "when": "一个量平时落在哪（入睡时间、步数），最多 8 格", "data": "入睡时间 30 分钟一格，或某项指标", "binds": ["histogram"],
     "height": "130"},
    {"name": "spread", "cn": "范围盒", "group": "趋势", "example": {"t": "spread", "bind": "hrv", "days": 30},
     "when": "今天在自己平时的范围里处在哪（比「正常值」有意义）", "data": "近 N 天的最小 / 四分位 / 中位 / 最大", "binds": ["series"],
     "height": "80"},
    {"name": "bullet", "cn": "子弹图", "group": "趋势", "example": {"t": "bullet", "bind": "sleep.efficiency"},
     "when": "一个值放进 差 / 一般 / 好 三段里，再标目标线", "data": "sleep-week 效率、恢复分档、步数目标、当晚需要、个人常态",
     "binds": ["bullet"], "height": "110"},
    # ---- 进度与信息
    {"name": "segments", "cn": "分段进度", "group": "进度", "example": {"t": "segments", "bind": "project:<项目id>"},
     "when": "按周数的计划进度（第 1 周 / 8 周）", "data": "项目的开始日和天数", "binds": ["project"], "height": "90"},
    {"name": "stepper", "cn": "阶段", "group": "进度",
     "example": {"t": "stepper", "items": ["适应", "加量", "减量", "测试"], "subs": ["1–2 周", "3–4 周", "5 周", "8 周"], "current": 0},
     "when": "横向的几个阶段，阶段少、要省地方时用（多就用 milestones）", "data": "手写",
     "notes": "items 2–5 个、每个 ≤6 字；subs 可省，有就和 items 一样多、每条 ≤8 字", "height": "76"},
    {"name": "progress_list", "cn": "多条进度", "group": "进度", "example": {"t": "progress_list", "bind": "projects", "days": 7},
     "when": "几个项目（或一个项目里几件事）各做到多少，并排比较（最多 4 行）", "data": "项目打卡 / project-stats",
     "binds": ["progress"], "height": "行数×34"},
    {"name": "checklist", "cn": "状态清单", "group": "进度", "example": {"t": "checklist", "board": "sleep", "n": 4},
     "when": "今天的待办做没做（只读，打勾去待办卡）；和 timeline 的区别：这里看做没做", "data": "今天的待办，按时间",
     "notes": "board = now / sleep / sport / stress / life，n 1–6", "height": "条数×28"},
    {"name": "kv", "cn": "键值", "group": "进度", "example": {"t": "kv", "items": [{"label": "起床", "value": "08:30"}, {"label": "最早上床", "value": "01:30"}]},
     "when": "几条设置或事实一行一条，左标签右值", "data": "手写（2–6 行，label≤8、value≤12），或 bind project:cbti 取 sleep.cbti",
     "binds": ["project"], "height": "行数×38"},
    {"name": "table", "cn": "小表", "group": "进度", "example": {"t": "table", "bind": "sleep.week", "n": 4},
     "when": "几晚 / 几天的几样数对齐着看，不画格线",
     "data": "sleep.week（日期 / 睡了 / 效率 / 入睡）、cbti.weeks（CBT-I 每周 窗口 / 效率中位 / 调整），或手写 columns + rows",
     "notes": "手写最多 4 列 × 6 行，每格 ≤6 字；第一列写日期或名目", "height": "(行数+1)×26"},
    {"name": "tag", "cn": "标签", "group": "进度", "example": {"t": "tag", "items": ["CBT-I · 第 1 周", "需要处理"], "strong": 1},
     "when": "给标题或一条信息加个状态，别当按钮用", "data": "手写（1–4 个，每个 ≤10 字；strong = 白框强调的下标）", "height": "32"},
    {"name": "quote", "cn": "强调句", "group": "进度", "example": {"t": "quote", "text": "固定起床，是整个计划里最不能动的一条。", "source": "CBT-I · 规则 1"},
     "when": "把一条规则或结论单独放大，教练式的提醒", "data": "手写（text≤30，source≤14 可省）", "height": "ceil(字数/14)×34 + 26"},
    {"name": "media", "cn": "跟练入口", "group": "进度",
     "example": {"t": "media", "url": "/media/follow/<ssid>/out.mp4", "title": "睡前拉伸", "duration_min": 8},
     "when": "卡片里直接开始一段练习视频", "data": "follow 出的片：url + title + duration_min（follow session list 能查）",
     "notes": "练习只用 follow 出的片（/media/follow/…）；不放音频、不放 B 站链接", "height": "64"},
    {"name": "photo", "cn": "照片", "group": "进度", "example": {"t": "photo", "latest": "life", "caption": "主食偏多，蛋白质够"},
     "when": "老大拍的饭、试纸照片和你的一句点评放一起", "data": "待办上传的照片：todo=<待办 id>，或 latest=<板块>（今天最近一张）",
     "notes": "caption≤30，不写就用那条待办的 summary", "height": "170"},
]


def parts_doc(group: str | None = None, name: str | None = None) -> dict:
    """给 P-Health 查零件：默认每个一行（名字、中文名、什么时候用、输入示例）；--name 给全文。"""
    if name:
        p = next((p for p in PARTS if p["name"] == name), None)
        if not p:
            raise KeyError(f"没有零件 {name}；能用的：{' '.join(x['name'] for x in PARTS)}")
        return {**{k: v for k, v in p.items() if k != "binds"},
                "binds": {k: BIND_KINDS[k] for k in p.get("binds") or []}}
    if group and group not in PART_GROUPS:
        raise KeyError(f"group 只能是 {' / '.join(PART_GROUPS)}")
    rows = [{"name": p["name"], "cn": p["cn"], "when": p["when"], "example": p["example"]}
            for p in PARTS if not group or p["group"] == group]
    return {"parts": rows, "groups": list(PART_GROUPS), "slots": SLOTS,
            "how": "选好零件写成树，先 ./pivis-health canvas --json '<树>'（主卡加 --slot hero）预览；--name <零件> 看全文"}
