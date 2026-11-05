"""生成式 UI 组件渲染器（§11 子集）+ 校验降级。

agent 不写自由页面代码，只从目录选组件填字段；本模块是目录的服务端实现。
校验纪律：字段缺失/样本不足 → 组件降级为文字卡并注明原因（绝不画误导图）。
视觉：深色 B 风（§12）——页面 #0F1217、卡片 #181C23、强调 #9DB4FF、
数据主色 #5B8DEF、唯一警示 #D9772E、达标 #2E9E7C（不与橙同图）。
"""
from __future__ import annotations

from html import escape
from typing import Any

WARN = "#D9772E"
GOOD = "#2E9E7C"
DATA = "#5B8DEF"
ACCENT = "#9DB4FF"
MUT = "#9AA3AE"


def _e(s: Any) -> str:
    return escape(str(s), quote=True)


def degrade(cid: str, reason: str) -> str:
    return (f'<div class="cmp cmp-degrade" data-cid="{cid}">'
            f'<span class="muted">{_e(reason)}</span></div>')


def comp(cid: str, builder, data: Any, ready: bool = True, reason: str = "数据不足") -> str:
    """统一入口：ready=False 或数据为空时降级。"""
    if not ready or data is None or data == {} or data == []:
        return degrade(cid, reason)
    return builder(data)


# ---------- 文字与数字 ----------
def c01_headline(d: dict) -> str:
    goal = f'<div class="c01-goal">{_e(d["goal"])}</div>' if d.get("goal") else ""
    return (f'<div class="cmp c01" data-cid="C01">'
            f'<div class="c01-row"><span class="c01-ava">健</span>'
            f'<span class="c01-text">{_e(d["text"])}</span></div>{goal}</div>')


def c02_hero(d: dict) -> str:
    dev = d.get("deviation") or {}
    state = dev.get("state")
    val = d.get("value")
    if val is None:
        num = '<span class="c02-big c02-nodata">数据不足</span>'
        sub = "数据没到就不编数"
    else:
        cls = "c02-low" if state == "below" else ""
        num = f'<span class="c02-big {cls}">{val:.0f}<small>{_e(d.get("unit",""))}</small></span>'
        sub = _e(dev.get("note", ""))
    rng = (d.get("range") or {}).get("label", "")
    return (f'<div class="cmp c02" data-cid="C02"><div class="c02-label">{_e(d.get("label",""))}</div>'
            f'{num}<div class="c02-sub">{sub}</div><div class="c02-range muted">{_e(rng)}</div></div>')


def c05_stat(d: dict) -> str:
    emphasis = f' style="color:{WARN}"' if d.get("emphasis") else ""
    compare = f'<div class="c05-cmp muted">{_e(d["compare"])}</div>' if d.get("compare") else ""
    note = f'<div class="c05-note muted">{_e(d["note"])}</div>' if d.get("note") else ""
    return (f'<div class="cmp c05" data-cid="C05"><div class="c05-label muted">{_e(d["label"])}</div>'
            f'<div class="c05-val"{emphasis}>{_e(d["value"])}<small>{_e(d.get("unit",""))}</small></div>'
            f'{compare}{note}</div>')


# ---------- 图表（纯 SVG） ----------
def _svg_open(w: int, h: int) -> str:
    return f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img">'


def c04_spark(d: dict) -> str:
    pts = [p["value"] for p in d["series"] if p.get("value") is not None]
    if len(pts) < 2:
        return degrade("C04", "样本不足")
    w, h, pad = 300, 44, 4
    lo, hi = min(pts), max(pts) or 1
    hi = hi if hi > lo else lo + 1
    step = (w - 2 * pad) / (len(pts) - 1)
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{pad + i * step:.1f},{h - pad - (v - lo) / (hi - lo) * (h - 2 * pad):.1f}"
        for i, v in enumerate(pts))
    last_c = WARN if d.get("highlight_last_bad") else DATA
    return (f'{_svg_open(w, h)}<path d="{path}" fill="none" stroke="{last_c}" stroke-width="2"/></svg>')


def c07_col_vs_target(d: dict) -> str:
    rows = [r for r in d["series"] if r.get("actual") is not None or r.get("need") is not None]
    if not rows:
        return degrade("C07", "睡眠数据未到")
    w, h, pad, base = 300, 120, 6, 96
    need_vals = [r["need"] for r in rows if r.get("need") is not None]
    act_vals = [r["actual"] for r in rows if r.get("actual") is not None]
    hi = max(need_vals + act_vals + [8.0]) * 1.1
    step = (w - 2 * pad) / max(1, len(rows))
    out = []
    for i, r in enumerate(rows):
        x = pad + i * step + step * 0.15
        if r.get("need") is not None:
            nh = (r["need"] / hi) * (base - pad)
            out.append(f'<line x1="{x + step*0.3:.0f}" y1="{base - nh:.1f}" x2="{x + step*0.3:.0f}" '
                       f'y2="{base}" stroke="#4A515C" stroke-width="3"/>')
        if r.get("actual") is not None:
            ah = (r["actual"] / hi) * (base - pad)
            color = WARN if r.get("short") else DATA
            out.append(f'<rect x="{x:.0f}" y="{base - ah:.1f}" width="{max(3, step*0.45):.0f}" '
                       f'height="{ah:.1f}" rx="1.5" fill="{color}"/>')
        if r.get("hq") is True:
            out.append(f'<circle cx="{x + step*0.22:.0f}" cy="{base + 8}" r="2.5" fill="{GOOD}"/>')
        elif r.get("hq") is False:
            out.append(f'<circle cx="{x + step*0.22:.0f}" cy="{base + 8}" r="2.5" fill="{WARN}"/>')
    return (f'{_svg_open(w, h)}{"".join(out)}<line x1="{pad}" y1="{base}" x2="{w-pad}" y2="{base}" '
            f'stroke="#262B33"/></svg>')


def c08_band(d: dict) -> str:
    pts = [p["value"] for p in d["series"] if p.get("value") is not None]
    if len(pts) < 2:
        return degrade("C08", "样本不足")
    w, h, pad, base = 300, 110, 6, 92
    rng = d.get("range") or {}
    extra = [rng["low"], rng["high"]] if rng.get("ready") else []
    lo = min(pts + extra)
    hi = max(pts + extra) or 1
    hi = hi if hi > lo else lo + 1
    step = (w - 2 * pad) / (len(d["series"]) - 1)

    def y(v: float) -> float:
        return base - (v - lo) / (hi - lo) * (base - pad)

    out = []
    if rng.get("ready"):
        out.append(f'<rect x="{pad}" y="{y(rng["high"]):.1f}" width="{w-2*pad}" '
                   f'height="{max(2.0, y(rng["low"]) - y(rng["high"])):.1f}" fill="#232934"/>')
    for m in d.get("markers") or []:
        try:
            from datetime import date as _date
            md = _date.fromisoformat(m["date"])
        except Exception:
            continue
        idx = next((i for i, p in enumerate(d["series"]) if p["date"] == m["date"]), None)
        if idx is None:
            continue
        mx = pad + idx * step
        color = WARN if m.get("heavy") else ACCENT
        out.append(f'<line x1="{mx:.0f}" y1="{pad}" x2="{mx:.0f}" y2="{base}" '
                   f'stroke="{color}" stroke-width="1.5" opacity="0.7"/>'
                   f'<circle cx="{mx:.0f}" cy="{pad + 6}" r="3" fill="{color}"/>')
    path = ""
    started = False
    for i, p in enumerate(d["series"]):
        if p.get("value") is None:
            started = False
            continue
        x = pad + i * step
        yy = y(p["value"])
        path += f"{'M' if not started else 'L'}{x:.1f},{yy:.1f} "
        started = True
    out.append(f'<path d="{path}" fill="none" stroke="{DATA}" stroke-width="2"/>')
    for p in d["series"]:
        if p.get("value") is None or not rng.get("ready"):
            continue
        if p["value"] < rng["low"]:
            try:
                from datetime import date as _date
                idx = next(i for i, q in enumerate(d["series"]) if q["date"] == p["date"])
                out.append(f'<circle cx="{pad + idx * step:.0f}" cy="{y(p["value"]):.1f}" r="3" fill="{WARN}"/>')
            except StopIteration:
                pass
    return f'{_svg_open(w, h)}{"".join(out)}<line x1="{pad}" y1="{base}" x2="{w-pad}" y2="{base}" stroke="#262B33"/></svg>'


# ---------- 行动与决策 ----------
_NEED_ACTION_JS = "needAction('{type}','{action}')"


def c06_need_card(d: dict) -> str:
    ev = f'<div class="c06-ev muted">{_e(d["evidence"])}</div>' if d.get("evidence") else ""
    top = " c06-top" if d.get("top") else ""
    return (f'<div class="cmp c06{top}" data-cid="C06" data-type="{_e(d["need_type"])}">'
            f'<div class="c06-title">{_e(d["title"])}</div>'
            f'<div class="c06-act">{_e(d["action"])}</div>{ev}'
            f'<div class="c06-btns">'
            f'<button onclick="{_NEED_ACTION_JS.format(type=_e(d["need_type"]), action="做了")}">做了</button>'
            f'<button class="ghost" onclick="{_NEED_ACTION_JS.format(type=_e(d["need_type"]), action="换一个")}">换一个</button>'
            f'<button class="ghost" onclick="{_NEED_ACTION_JS.format(type=_e(d["need_type"]), action="今天算了")}">今天算了</button>'
            f'</div></div>')


def c13_quota(d: dict) -> str:
    done, quota = int(d.get("done", 0)), int(d.get("quota", 0))
    blocks = "".join(
        f'<span class="qblk{" on" if i < done else ""}"></span>' for i in range(max(quota, 1)))
    return (f'<div class="cmp c05" data-cid="C13"><div class="c05-label muted">{_e(d.get("label","额度"))}</div>'
            f'<div class="c05-val">{done}<small>/{quota}</small></div>'
            f'<div class="c13-blocks">{blocks}</div></div>')


def c14_decision(d: dict) -> str:
    verdict = d.get("verdict", "—")
    color = WARN if verdict in ("不宜", "可以但轻一点") else GOOD
    checks = "".join(
        f'<div class="c14-check"><span class="c14-mark" style="color:{GOOD if c["pass"] else (MUT if c["pass"] is None else WARN)}">'
        f'{"✓" if c["pass"] else ("—" if c["pass"] is None else "✗")}</span>'
        f'<span>{_e(c["name"])} · {_e(c["value"])}</span></div>'
        for c in d.get("checks", []))
    return (f'<div class="cmp c14" data-cid="C14"><div class="c14-verdict" style="color:{color}">{_e(verdict)}</div>'
            f'{checks}<div class="muted c14-note">每个条件点开可见字段与来源</div></div>')


def c18_rating(d: dict) -> str:
    chips = "".join(
        f'<button class="rchip" onclick="rating(\'{d["kind"]}\',{i})">{i}</button>'
        for i in range(1, 6))
    anchors = f'<div class="muted c18-anchors">{_e(d.get("anchor_low","1 很难"))} ～ {_e(d.get("anchor_high","5 很好"))}</div>'
    return (f'<div class="cmp c18" data-cid="C18" data-kind="{_e(d["kind"])}">'
            f'<div class="c18-q">{_e(d["question"])}</div>'
            f'<div class="c18-chips">{chips}</div>{anchors}</div>')


def c19_confirm(d: dict) -> str:
    return (f'<div class="cmp c19" data-cid="C19"><div class="c18-q">{_e(d["claim"])}</div>'
            f'<div class="c06-btns">'
            f'<button onclick="confirmWhoop(true)">对</button>'
            f'<button class="ghost" onclick="confirmWhoop(false)">不对，另有原因</button></div>'
            f'<input id="c19-reason" class="c19-in" placeholder="不对的话：原因（可选）">'
            f'</div>')


def c24_hq_grid(d: dict) -> str:
    nights = d.get("nights") or []
    if not nights:
        return degrade("C24", "高质量判定数据未到")
    head = "".join(f'<div class="gq-h">{_e(r["date"][5:])}</div>' for r in nights)
    body = ""
    for qid in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        body += f'<div class="gq-h gq-q">{qid}</div>'
        for r in nights:
            st = r.get("checks", {}).get(qid)
            cls = "pass" if st is True else ("fail" if st is False else "na")
            body += f'<div class="gq-c {cls}"></div>'
    return f'<div class="cmp c24" data-cid="C24"><div class="gq">{head}{body}</div><div class="muted">灰=不计（数据缺/范围学习中）</div></div>'


def c12_plan(d: dict) -> str:
    steps = d.get("steps") or []
    if not steps:
        return degrade("C12", "今晚还没定计划（21:30 前可在放松页共创）")
    rows = "".join(
        f'<div class="c12-step"><span class="c12-t">{_e(s.get("time",""))}</span>'
        f'<span class="c12-n">{_e(s.get("name",""))} {_e(s.get("minutes",""))}分</span>'
        f'<button class="ghost small" onclick="swapStep({i})">换一步</button></div>'
        for i, s in enumerate(steps))
    return (f'<div class="cmp c12" data-cid="C12">{rows}'
            f'<div class="c12-bed muted">目标上床 {_e(d.get("bed_time","—"))}</div>'
            f'<button onclick="location.href=\'/v2/relax\'">开始执行</button></div>')
