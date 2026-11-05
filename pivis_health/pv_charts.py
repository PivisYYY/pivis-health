"""图表 SVG 生成器 —— 按需求文档设计稿（附录 14.5–14.8）几何复刻。

坐标与配色严格对照设计稿：柱图圆角顶+蓝刻度线、范围带折线+橙点/绿点行、
D1 迷你 spark 122×46、主图 330×150、E4 122 高带底纹。
"""
from __future__ import annotations

from html import escape
from typing import Any

MU = "#6B7380"   # 线主色（设计稿折线用 muted-2）
DATA = "#5B8DEF"
ATTN = "#D9772E"
GOOD = "#2E9E7C"
MUT = "#4A515C"
BAND = "#232934"
GRID = "#262B33"
T2 = "#9AA3AE"
TXT = "#ECEEF1"
CARD = "#181C23"
SHADE = "rgba(217,119,46,0.18)"


def _e(s: Any) -> str:
    return escape(str(s), quote=True)


def spark_band(values: list[float | None], band: tuple[float, float] | None,
               w: int = 122, h: int = 46, pad: float = 2.0) -> str:
    """D1 主数字旁 spark：范围带 + 折线 + 末点（低于范围橙）。"""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return ""
    lo_extra = [band[0], band[1]] if band else []
    lo = min([v for _, v in pts] + lo_extra)
    hi = max([v for _, v in pts] + lo_extra)
    if hi <= lo:
        hi = lo + 1
    inner_w = w - 2 * pad
    n = len(values) - 1 or 1
    step = inner_w / n

    def X(i: int) -> float:
        return pad + i * step

    def Y(v: float) -> float:
        return 7.6 + (v - lo) / (hi - lo) * (h - 15.2) if band else pad + (1 - (v - lo) / (hi - lo)) * (h - 2 * pad - 4)

    if band:
        y_top, y_bot = Y(band[1]), Y(band[0])
    else:
        lo_all = min(v for _, v in pts)
        hi_all = max(v for _, v in pts) or 1
        hi_all = hi_all if hi_all > lo_all else lo_all + 1
        y_top = pad + 0 + (hi_all - hi) / (hi - lo) * (h - 2 * pad)
        y_bot = y_top + (hi - lo) / (hi_all - lo_all) * (h - 2 * pad) if hi_all > lo_all else h - pad
    path = " ".join(
        f"{'M' if k == 0 else 'L'}{X(i):.1f} {Y(v):.1f}" for k, (i, v) in enumerate(pts))
    last_i, last_v = pts[-1]
    last_attn = bool(band and last_v < band[0])
    dot = (f'<circle cx="{X(last_i):.1f}" cy="{Y(last_v):.1f}" r="4" fill="{ATTN}" stroke="{CARD}" stroke-width="2"/>'
           if last_attn else
           f'<circle cx="{X(last_i):.1f}" cy="{Y(last_v):.1f}" r="4" fill="{MU}" stroke="{CARD}" stroke-width="2"/>')
    band_rect = (f'<rect x="0" y="{y_top:.1f}" width="{w}" height="{max(0.0, y_bot - y_top):.1f}" fill="{BAND}"/>'
                 if band else "")
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="趋势">'
            f'{band_rect}<path d="{path}" fill="none" stroke="{MU}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>{dot}</svg>')


def need_mini_bars(actuals: list[float | None], need: float | None,
                    w: int = 86, h: int = 42) -> str:
    """需求卡迷你图：7 柱 + 需要刻度线；最后一柱低于需要 1h+ 标橙。"""
    vals = actuals[-7:]
    if not any(v is not None for v in vals):
        return ""
    hi = max([v for v in vals if v is not None] + ([need] if need else []) + [1.0]) * 1.12
    n = len(vals)
    bw = 8
    gap = (w - n * bw) / max(1, n)
    parts = []
    if need:
        y = 4.4 + (1 - need / hi) * (h - 4.4)
        parts.append(f'<path d="M0 {y:.1f} H{w}" stroke="{DATA}" stroke-width="1"/>')
    for i, v in enumerate(vals):
        if v is None:
            continue
        x = i * (bw + gap) + gap / 2
        bh = max(2.0, v / hi * (h - 6))
        color = ATTN if (need and v < need - 1.0) else MUT
        parts.append(f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{bw}" height="{bh:.1f}" rx="2" fill="{color}"/>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">{"".join(parts)}</svg>'


def need_mini_band(values: list[float | None], band: tuple[float, float] | None,
                   w: int = 86, h: int = 42) -> str:
    """需求卡迷你范围带折线。"""
    return spark_band(values, band, w=w, h=h)


def bars_need(nights: list[dict], w: int = 330, h: int = 150) -> str:
    """D2 主图：14 晚柱（圆角顶）vs 当晚需要刻度；少睡>1h 橙柱。

    nights: [{date, actual, need, short, hq}]，hq: True/False/None
    """
    rows = [r for r in nights if r.get("actual") is not None or r.get("need") is not None]
    if not rows:
        return ""
    left, top, bottom = 28, 4, 128
    vals = [r["actual"] for r in rows if r.get("actual") is not None]
    needs = [r["need"] for r in rows if r.get("need") is not None]
    hi = max(vals + needs + [8.0]) * 1.08

    def Y(v: float) -> float:
        return bottom - v / hi * (bottom - top)

    n = len(rows)
    slot = (w - left - 2) / n
    bw = min(12.0, slot * 0.55)
    grid, labels, bars_grey, bars_attn, ticks, dots = [], [], [], [], [], []
    for gv in (0.0, 4.0, 8.0):
        y = Y(gv)
        grid.append(f'<path d="M{left} {y:.1f} H{w}"/>')
        labels.append(f'<text x="22" y="{y + 3:.0f}">{int(gv)}{"h" if gv else ""}</text>')
    for i, r in enumerate(rows):
        cx = left + slot * (i + 0.5)
        if r.get("actual") is not None:
            a = r["actual"]
            y, bh = Y(a), bottom - Y(a)
            target = bars_attn if r.get("short") else bars_grey
            target.append(
                f'M{cx - bw/2:.1f} {bottom:.1f} V{y + 3:.1f} Q{cx - bw/2:.1f} {y:.1f} '
                f'{cx - bw/2 + 3:.1f} {y:.1f} H{cx + bw/2 - 3:.1f} Q{cx + bw/2:.1f} {y:.1f} '
                f'{cx + bw/2:.1f} {y + 3:.1f} V{bottom:.1f} Z')
        if r.get("need") is not None:
            ny = Y(r["need"])
            ticks.append(f'M{cx - 8:.1f} {ny:.1f} H{cx + 8:.1f}')
        if r.get("hq") is True:
            dots.append(f'<circle cx="{cx:.1f}" cy="{bottom + 9}" r="2.5" fill="{GOOD}"/>')
        elif r.get("hq") is False:
            dots.append(f'<circle cx="{cx:.1f}" cy="{bottom + 9}" r="2.5" fill="{ATTN}"/>')
    last = rows[-1]
    tail = ""
    if last.get("actual") is not None:
        cx = left + slot * (n - 0.5)
        tail = (f'<text x="{cx:.1f}" y="{Y(last["actual"]) - 6:.0f}" fill="{TXT}" font-size="11.5" '
                f'font-weight="700" text-anchor="middle">{last["actual"]:.1f}</text>')
    xlab = (f'<text x="{left + slot * 0.5:.1f}" y="{h - 5}">{_e(rows[0]["date"][5:])}</text>'
            if n else "")
    xlab += f'<text x="{w - 8}" y="{h - 5}" text-anchor="end">昨晚</text>'
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            f'<g stroke="{GRID}" stroke-width="1">{"".join(grid)}</g>'
            f'<g fill="{T2}" font-size="11" text-anchor="end">{"".join(labels)}</g>'
            f'<path fill="{MUT}" d="{" ".join(bars_grey)}"/>'
            f'<path fill="{ATTN}" d="{" ".join(bars_attn)}"/>'
            f'<path fill="none" stroke="{DATA}" stroke-width="2" stroke-linecap="round" d="{" ".join(ticks)}"/>'
            f'{"".join(dots)}{tail}'
            f'<g fill="{T2}" font-size="11" text-anchor="middle">{xlab}</g></svg>')


def band_dots(values: list[dict], band: tuple[float, float] | None,
              events: list[dict] | None = None, shading: list[dict] | None = None,
              w: int = 330, h: int = 150, y_ticks: list[float] | None = None,
              event_row: bool = False) -> str:
    """E3/E4 主图：范围带 + 折线 + 橙点（跌出）+（可选）绿点事件行 + 会议底纹。

    values: [{date, value}]; events: [{date, heavy}]; shading: [{date}]（整列底纹）
    """
    pts = [(i, p["value"]) for i, p in enumerate(values) if p.get("value") is not None]
    if len(pts) < 2:
        return ""
    left, top, bottom = 28, 8, 118
    lo_extra = list(band) if band else []
    lo = min([v for _, v in pts] + lo_extra)
    hi = max([v for _, v in pts] + lo_extra) or 1
    if hi <= lo:
        hi = lo + 1
    lo, hi = lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06
    n = len(values) - 1 or 1
    slot = (w - left - 8) / n

    def X(i: int) -> float:
        return left + slot * i

    def Y(v: float) -> float:
        return bottom - (v - lo) / (hi - lo) * (bottom - top)

    out = []
    for s in shading or []:
        try:
            idx = next(i for i, p in enumerate(values) if p["date"] == s["date"])
        except StopIteration:
            continue
        out.append(f'<rect x="{X(idx) - slot * 0.34:.1f}" y="{top}" width="{slot * 0.68:.1f}" '
                   f'height="{bottom - top}" fill="{SHADE}"/>')
    if band:
        out.append(f'<rect x="{left}" y="{Y(band[1]):.1f}" width="{w - left - 2}" '
                   f'height="{max(1.0, Y(band[0]) - Y(band[1])):.1f}" fill="{BAND}"/>')
    ticks = y_ticks if y_ticks is not None else ([band[0], band[1]] if band else [lo, hi])
    grid, labels = [], []
    for gv in ticks:
        y = max(top, min(bottom, Y(gv)))
        grid.append(f'<path d="M{left} {y:.1f} H{w}"/>')
        labels.append(f'<text x="22" y="{y + 3:.0f}">{gv:g}</text>')
    path = " ".join(f"{'M' if k == 0 else 'L'}{X(i):.1f} {Y(v):.1f}" for k, (i, v) in enumerate(pts))
    out.append(f'<g stroke="{GRID}" stroke-width="1">{"".join(grid)}</g>')
    out.append(f'<g fill="{T2}" font-size="11" text-anchor="end">{"".join(labels)}</g>')
    out.append(f'<path d="{path}" fill="none" stroke="{MU}" stroke-width="2" '
               f'stroke-linejoin="round" stroke-linecap="round"/>')
    for i, v in pts:
        if band and v < band[0]:
            r = 5 if i == pts[-1][0] else 4.5
            out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{r}" fill="{ATTN}" stroke="{CARD}" stroke-width="2"/>')
    li, lv = pts[-1]
    below = bool(band and lv < band[0])
    if below:
        out.append(f'<text x="{w - 8}" y="{Y(lv) + 20:.0f}" fill="{TXT}" font-size="11.5" font-weight="700" text-anchor="end">今天 {lv:g}</text>')
    else:
        out.append(f'<circle cx="{X(li):.1f}" cy="{Y(lv):.1f}" r="5" fill="{MU}" stroke="{CARD}" stroke-width="2"/>')
    if event_row:
        for ev in events or []:
            try:
                idx = next(i for i, p in enumerate(values) if p["date"] == ev["date"])
            except StopIteration:
                continue
            color = ATTN if ev.get("heavy") else GOOD
            out.append(f'<circle cx="{X(idx):.1f}" cy="{bottom + 10}" r="5" fill="{color}" stroke="{CARD}" stroke-width="2"/>')
    xlab = f'<text x="{left + 4}" y="{h - 5}">{_e(values[0]["date"][5:])}</text>'
    xlab += f'<text x="{w - 8}" y="{h - 5}" text-anchor="end">今天</text>'
    out.append(f'<g fill="{T2}" font-size="11" text-anchor="middle">{xlab}</g>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">{"".join(out)}</svg>'
