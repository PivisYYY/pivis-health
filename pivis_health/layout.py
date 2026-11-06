"""页面组件目录派生：iOS 原生渲染器的唯一数据源（一期 SP-01）。

设计约束：
- 把 V2Pages 的字段层文档**确定性地**翻译成组件数组；iOS 只渲染 components，
  不再自己拼装页面。数值格式化也在这一层完成（客户端不再做字段换算）。
- 结构边界写死在本模块：tiles ≤ 3、needs ≤ 3、组件顺序即渲染顺序。
  「3 张卡变 6 张」在协议层不可能——数组里根本没有多余的格子；
  将来 P-Health 通过对话调整时，校验器也只认这里产出的形状。
- 降级纪律沿用组件目录：数据不足就**不产出该组件**（客户端跳过），不产出假数据。

组件类型（v1 目录，客户端 switch 实现）：
  headline      板块头部（kicker + 结论句，点击进 session）
  hero_status   此刻页大状态卡（大数字）
  hero_risk     专项页主风险卡（大数值 + 内嵌 viz）
  quiet_note    安静说明（无异常时）
  tiles         数据位组（items ≤ TILES_MAX，每个 stat_tile）
  need_section  「你需要做」执行卡组（needs ≤ NEEDS_MAX）
  relax_entry   放松流程入口（休息页， tonight.planSetToday 时才产出）
  whoop_confirm WHOOP 判定校准卡
  evidence      折叠依据（内嵌 chart：night_bars / strain_bars / hrv_line）
"""
from __future__ import annotations

from typing import Any

# 与 iOS 端 sessionForSpecialty 同一映射
SESSION_OF_SPECIALTY = {"睡眠": "休息", "运动": "运动", "压力": "压力", "身体": "压力"}

TILES_MAX = 3
NEEDS_MAX = 3


def _fmt_num(v: float) -> str:
    """与 iOS 旧版 heroValue 同一规则：整数且 <1000 取整，否则一位小数。"""
    n = int(v) if float(v) == int(v) and v < 1000 else round(float(v), 1)
    return str(n)


def _hero_status(state: str | None) -> str:
    return {"below": "低于个人范围", "high": "偏高"}.get(state or "", "需要关注")


def _need_payload(n: dict) -> dict:
    return {"need_type": n.get("need_type", ""), "title": n.get("title"),
            "specialty": n.get("specialty"), "evidence": n.get("evidence"),
            "action": n.get("action"), "window": n.get("window"), "top": n.get("top")}


def _stat_tile(label: str, value: str, note: str = "", warning: bool = False,
               tone: str | None = None) -> dict:
    return {"label": label, "value": value, "note": note, "warning": bool(warning), "tone": tone}


def _tiles(items: list[dict]) -> dict:
    # 容量写死：调用方传多了也只保留前 TILES_MAX 个（对应 UI 骨架的数据位行）
    return {"type": "tiles", "items": items[:TILES_MAX]}


def _evidence(title: str, chart: dict) -> dict:
    return {"type": "evidence", "title": title, "chart": chart}


# ---------- D1 现在 ----------

def today_components(doc: dict) -> list[dict]:
    out: list[dict] = []
    needs = doc.get("needs") or []
    top = next((n for n in needs if n.get("top")), needs[0] if needs else None)
    session = SESSION_OF_SPECIALTY.get((top or {}).get("specialty"), "")
    out.append({"type": "headline", "kicker": "P-Health · 当前判断",
                "text": doc.get("headline") or "今天照常就好", "session": session})

    hero = doc.get("hero") or {}
    if hero.get("value") is not None:
        v = float(hero["value"])
        rng_label = (hero.get("range") or {}).get("label") or ""
        out.append({"type": "hero_status", "kicker": "当前最异常",
                    "label": hero.get("label") or (top or {}).get("title") or "当前状态",
                    "value": _fmt_num(v) + (hero.get("unit") or ""),
                    "note": (top or {}).get("evidence") or rng_label,
                    "status": _hero_status((hero.get("deviation") or {}).get("state")),
                    "warning": True, "tone": "amber"})
    elif top:
        out.append({"type": "hero_status", "kicker": "当前最异常",
                    "label": top.get("title") or "当前状态", "value": "需要行动",
                    "note": top.get("evidence") or "", "status": "需要关注", "warning": True,
                    "tone": "amber"})
    else:
        out.append({"type": "quiet_note", "text": "今天照常就好。没有需要你处理的变化。"})

    if needs:
        out.append({"type": "need_section",
                    "needs": [_need_payload(n) for n in needs[:NEEDS_MAX]]})
    return out


# ---------- D2 休息 ----------

def sleep_components(doc: dict) -> list[dict]:
    out: list[dict] = [{
        "type": "headline", "kicker": "休息专项 · 恢复与入睡管理",
        "text": doc.get("headline") or "今晚的睡眠安排", "session": "休息",
    }]
    tiles = doc.get("tiles") or {}

    debt = tiles.get("debt")
    if debt and debt.get("debt_h") is not None:
        dh = float(debt["debt_h"])
        out.append({"type": "hero_risk", "kicker": "睡眠债 · 主风险",
                    "value": f"{dh:.1f}", "unit": "h",
                    "status": "显著偏高" if dh > 3 else "稳定", "warning": dh > 3,
                    "tone": "risk" if dh > 3 else "good",
                    "note": f"近 {debt.get('n_nights') or 7} 晚累计 · 橙色段为每晚缺口",
                    "viz": {"type": "gap_bar",
                            "avg": debt.get("avg_h") or 0, "need": debt.get("target_h") or 0}})

    items: list[dict] = []
    if doc.get("recovery") is not None:
        r = float(doc["recovery"])
        items.append(_stat_tile("Recovery", f"{int(round(r))}%", "共享恢复结论", r < 50,
                                "risk" if r < 50 else "good"))
    lat = tiles.get("latency")
    if lat:
        if lat.get("mean") is not None:
            mean = float(lat["mean"])
            tgt = lat.get("target") or 2
            items.append(_stat_tile("入睡难度", f"{mean:.1f}", f"目标 ≤{tgt}", mean > tgt,
                                    "amber" if mean > tgt else None))
        else:
            items.append(_stat_tile("入睡难度", "—", "样本积累中"))
    hq = tiles.get("hq")
    if hq and hq.get("score") is not None:
        s = int(hq["score"])
        items.append(_stat_tile("高质量睡眠难度", f"{s}",
                                f"近 {hq.get('n_nights') or 0} 晚 {hq.get('nights_pass') or 0} 晚达标",
                                s >= 4, "risk" if s >= 4 else None))
    if items:
        out.append(_tiles(items))

    needs = doc.get("needs") or []
    if needs:
        out.append({"type": "need_section",
                    "needs": [_need_payload(n) for n in needs[:NEEDS_MAX]]})
    if (doc.get("tonight") or {}).get("planSetToday"):
        out.append({"type": "relax_entry"})
    wc = doc.get("whoopConfirm") or {}
    if wc.get("pending") and wc.get("claim"):
        out.append({"type": "whoop_confirm", "claim": wc["claim"]})
    chart = doc.get("chart14") or []
    if chart:
        out.append(_evidence("近 14 晚依据", {"type": "night_bars", "nights": chart}))
    return out


# ---------- E3 运动 ----------

def sport_components(doc: dict) -> list[dict]:
    play = doc.get("play") or {}
    verdict = play.get("verdict") or "—"
    checks = play.get("checks") or []
    goal = doc.get("goal") or ""
    key = next((c for c in checks if c.get("pass") is False), checks[0] if checks else None)
    note = (f"{key.get('name', '')} · {key.get('value', '')}" if key else "")
    need_down = "不宜" in verdict or "数据不足" in verdict

    out: list[dict] = [{
        "type": "headline",
        "kicker": f"运动专项 · {goal}" if goal else "运动专项",
        "text": f"{verdict}，再决定现在怎么动。", "session": "运动",
    }, {
        "type": "hero_risk", "kicker": "运动判断", "value": verdict,
        "status": "需要降级" if need_down else "可以动", "warning": need_down,
        "tone": "risk" if need_down else "good",
        "note": note, "viz": {"type": "verdict_dial", "verdict": verdict},
    }]

    tiles = doc.get("tiles") or {}
    band = doc.get("band") or {}
    items: list[dict] = []
    series = band.get("series") or []
    rec_latest = next((p.get("value") for p in reversed(series) if p.get("value") is not None), None)
    if rec_latest is not None:
        r = float(rec_latest)
        items.append(_stat_tile("Recovery", f"{int(round(r))}%", "共享恢复结论", r < 50,
                                "risk" if r < 50 else "good"))
    load_t = tiles.get("load") or {}
    if load_t.get("used") is not None:
        budget = load_t.get("budget")
        note_l = f"预算 {budget:.0f}" if isinstance(budget, (int, float)) else ""
        items.append(_stat_tile("本周负荷", f"{float(load_t['used']):.1f}", note_l))
    sess = tiles.get("sessions") or {}
    if sess:
        items.append(_stat_tile("本周场次", f"{int(sess.get('done') or 0)}/{int(sess.get('quota') or 0)}",
                                "节奏参考"))
    if items:
        out.append(_tiles(items))

    needs = doc.get("needs") or []
    if needs:
        out.append({"type": "need_section",
                    "needs": [_need_payload(n) for n in needs[:NEEDS_MAX]]})
    s14 = play.get("strain14") or []
    if s14:
        out.append(_evidence(f"近 {len(s14)} 天负荷", {"type": "strain_bars", "points": s14}))
    return out


# ---------- E4 压力与恢复 ----------

def stress_components(doc: dict) -> list[dict]:
    ws = doc.get("work_signals") or {}
    ws_avail = ws.get("available") is True
    out: list[dict] = [{
        "type": "headline", "kicker": "压力专项 · 信号与主观感受",
        "text": "结合授权背景与身体信号，只处理有依据的变化。" if ws_avail
                else "工作信号未接入，先只看身体数据与主观感受。",
        "session": "压力",
    }]

    band = doc.get("band") or {}
    series = band.get("series") or []
    values = [p["value"] for p in series if p.get("value") is not None]
    rng = band.get("range") or {}
    range_ready = rng.get("ready") is True
    latest = values[-1] if values else None

    if latest is not None:
        v = float(latest)
        below = range_ready and rng.get("low") is not None and v < float(rng["low"])
        status = "低于个人范围" if below else ("个人范围内" if range_ready else "范围学习中")
        mean = sum(values) / len(values) if values else None
        mean_note = (f"近 {len(values)} 天 · 均值 {mean:.0f} ms" if mean is not None
                     else "只与个人趋势比较")
        out.append({"type": "hero_risk", "kicker": "HRV · 主风险",
                    "value": f"{v:.0f}", "unit": "ms", "status": status, "warning": below,
                    "tone": "risk" if below else ("good" if range_ready else "accent"),
                    "note": mean_note,
                    "viz": {"type": "mini_bars", "values": values}})

    tiles = doc.get("tiles") or {}
    items: list[dict] = []
    if doc.get("recovery") is not None:
        r = float(doc["recovery"])
        items.append(_stat_tile("Recovery", f"{int(round(r))}%", "共享恢复结论", r < 50,
                                "risk" if r < 50 else "good"))
    learning = rng.get("learning_days") or 0
    if range_ready:
        range_note = f"常见范围 {float(rng.get('low') or 0):.0f}–{float(rng.get('high') or 0):.0f}"
        items.append(_stat_tile("个人范围", "已建立", range_note, tone="good"))
    else:
        items.append(_stat_tile("个人范围", "学习中", f"第 {learning} 天 / 满 14 天建立", tone="accent"))
    items.append(_stat_tile("工作信号", "已接入" if ws_avail else "未接入",
                            "会议与晚间在线" if ws_avail else "不根据日历单独归因",
                            tone="good" if ws_avail else None))
    out.append(_tiles(items))

    needs = doc.get("needs") or []
    if needs:
        out.append({"type": "need_section",
                    "needs": [_need_payload(n) for n in needs[:NEEDS_MAX]]})
    if series:
        out.append(_evidence(f"HRV · 近 {len(series)} 天",
                             {"type": "hrv_line", "points": series}))
    return out


COMPONENTS_FOR = {
    "today": today_components,
    "sleep": sleep_components,
    "sport": sport_components,
    "stress": stress_components,
}


def _series_values(doc: dict) -> list[float]:
    rows = doc.get("chart14") or (doc.get("play") or {}).get("strain14") or (doc.get("band") or {}).get("series") or []
    key = "actual" if rows and "actual" in rows[0] else "value"
    return [float(r[key]) for r in rows if isinstance(r, dict) and isinstance(r.get(key), (int, float))]


def _hero_source(page: str, source: str, doc: dict, current: dict) -> dict:
    out = dict(current)
    tiles = doc.get("tiles") or {}
    if page == "sleep":
        debt = tiles.get("debt") or {}
        latency = tiles.get("latency") or {}
        hq = tiles.get("hq") or {}
        if source == "recovery":
            value = doc.get("recovery")
            status = "数据未到" if value is None else ("个人范围内" if value >= 50 else "需要关注")
            tone = "accent" if value is None else ("good" if value >= 50 else "risk")
            out.update(kicker="Recovery · 当前恢复", value=str(int(round(value))) if value is not None else "—",
                       unit="%", status=status, warning=value is not None and value < 50, tone=tone,
                       note="共享 WHOOP 恢复结论", viz={"type": "mini_bars", "values": _series_values(doc)})
        elif source == "latency":
            value = latency.get("mean")
            target = latency.get("target") or 2
            status = "样本积累中" if value is None else ("高于目标" if value > target else "目标内")
            out.update(kicker="入睡难度 · 主观反馈", value=f"{float(value):.1f}" if value is not None else "—",
                       unit="", status=status, warning=value is not None and value > target,
                       tone="accent" if value is None else None, note=f"近 7 晚均值 · 目标 ≤{target}", viz=None)
        elif source == "hq":
            value = hq.get("score")
            status = "样本积累中" if value is None else ("需要关注" if value >= 4 else "稳定")
            out.update(kicker="高质量睡眠难度", value=str(value) if value is not None else "—", unit="",
                       status=status, warning=value is not None and value >= 4,
                       tone="accent" if value is None else None,
                       note=f"近 {hq.get('n_nights') or 0} 晚 {hq.get('nights_pass') or 0} 晚达标", viz=None)
        elif source == "avg_sleep":
            value = debt.get("avg_h")
            out.update(kicker="近期实际睡眠", value=f"{float(value):.1f}" if value is not None else "—",
                       unit="h", status="与个人需求比较" if value is not None else "数据未到",
                       warning=False, tone="accent",
                       note=f"近 {debt.get('n_nights') or 7} 晚平均", viz={"type": "mini_bars", "values": _series_values(doc)})
        elif source == "bedtime":
            value = ((doc.get("tonight") or {}).get("target") or {}).get("bedtime")
            out.update(kicker="今晚目标上床", value=value or "—", unit="",
                       status="按计划收尾" if value else "数据未到", warning=False, tone="accent",
                       note="由固定起床与睡眠需求推导", viz=None)
    elif page == "sport":
        if source == "recovery":
            rows = (doc.get("band") or {}).get("series") or []
            value = next((r.get("value") for r in reversed(rows) if r.get("value") is not None), None)
            status = "数据未到" if value is None else ("需要降级" if value < 50 else "可以动")
            out.update(kicker="Recovery · 当前恢复", value=str(int(round(value))) if value is not None else "—",
                       unit="%", status=status, warning=value is not None and value < 50,
                       tone="accent" if value is None else None, note="共享恢复结论",
                       viz={"type": "mini_bars", "values": _series_values(doc)})
        elif source == "load":
            load = tiles.get("load") or {}
            value = load.get("used")
            out.update(kicker="本周负荷", value=f"{float(value):.1f}" if value is not None else "—",
                       unit="", status="负荷预算内" if value is not None else "数据未到", warning=False, tone="accent",
                       note=f"预算 {load.get('budget') or '—'}", viz={"type": "mini_bars", "values": _series_values(doc)})
    elif page == "stress" and source == "recovery":
        value = doc.get("recovery")
        status = "数据未到" if value is None else ("需要关注" if value < 50 else "个人范围内")
        out.update(kicker="Recovery · 身体恢复", value=str(int(round(value))) if value is not None else "—",
                   unit="%", status=status, warning=value is not None and value < 50,
                   tone="accent" if value is None else None, note="不据此推断情绪或疾病",
                   viz={"type": "mini_bars", "values": _series_values(doc)})
    return out


def _tile_source(page: str, source: str, doc: dict, existing: list[dict]) -> dict | None:
    default_sources = {"sleep": ["recovery", "latency", "hq"], "sport": ["recovery", "load", "sessions"],
                       "stress": ["recovery", "range", "work"]}
    if source in default_sources.get(page, []):
        idx = default_sources[page].index(source)
        if idx < len(existing):
            return dict(existing[idx])
    tiles = doc.get("tiles") or {}
    if page == "sleep":
        debt = tiles.get("debt") or {}
        if source == "debt" and debt.get("debt_h") is not None:
            value = float(debt["debt_h"])
            return _stat_tile("睡眠债", f"{value:.1f}h", f"近 {debt.get('n_nights') or 7} 晚累计",
                              value > 3, "risk" if value > 3 else None)
        if source == "avg_sleep" and debt.get("avg_h") is not None:
            return _stat_tile("平均睡眠", f"{float(debt['avg_h']):.1f}h", "与需求分开看", tone="accent")
        if source == "bedtime":
            value = ((doc.get("tonight") or {}).get("target") or {}).get("bedtime")
            return _stat_tile("目标上床", value or "—", "今晚执行锚点", tone="accent")
    return None


def _apply_experience(page: str, doc: dict, components: list[dict], overrides: dict) -> list[dict]:
    out = []
    for original in components:
        c = dict(original)
        typ = c.get("type") or ""
        ov = overrides.get(typ) or {}
        if ov.get("source") and typ == "hero_risk":
            c = _hero_source(page, ov["source"], doc, c)
        if ov.get("sources") and typ == "tiles":
            selected = [_tile_source(page, source, doc, c.get("items") or []) for source in ov["sources"]]
            c["items"] = [item for item in selected if item is not None][:TILES_MAX]
        for key, value in (ov.get("fields") or {}).items():
            c[key] = value
        if ov.get("style"):
            c["style"] = ov["style"]
        for index, item_ov in (ov.get("items") or {}).items():
            key = "items" if typ == "tiles" else "needs"
            rows = c.get(key) or []
            i = int(index)
            if i >= len(rows):
                continue
            row = dict(rows[i])
            row.update(item_ov.get("fields") or {})
            if item_ov.get("style"):
                row["style"] = item_ov["style"]
            rows[i] = row
            c[key] = rows
        if ov.get("viz_type") and typ == "hero_risk":
            viz_type = ov["viz_type"]
            if viz_type == "none":
                c["viz"] = None
            elif viz_type == "mini_bars":
                c["viz"] = {"type": "mini_bars", "values": _series_values(doc)}
            elif viz_type == "gap_bar" and page == "sleep":
                debt = (doc.get("tiles") or {}).get("debt") or {}
                c["viz"] = {"type": "gap_bar", "avg": debt.get("avg_h") or 0,
                            "need": debt.get("target_h") or 0}
            elif viz_type == "verdict_dial" and page == "sport":
                c["viz"] = {"type": "verdict_dial", "verdict": (doc.get("play") or {}).get("verdict") or "—"}
        if ov.get("chart_type") and typ == "evidence" and c.get("chart"):
            chart = dict(c["chart"])
            target = ov["chart_type"]
            if target in ("strain_bars", "hrv_line") and not chart.get("points"):
                chart["points"] = [{"date": r.get("date"), "value": r.get("actual")}
                                   for r in chart.get("nights") or []]
            elif target == "night_bars" and not chart.get("nights"):
                chart["nights"] = [{"date": r.get("date"), "actual": r.get("value")}
                                   for r in chart.get("points") or []]
            chart["type"] = target
            c["chart"] = chart
        out.append(c)
    return out


def components_for(page: str, doc: dict, cfg=None) -> list[dict]:
    page_key = "now" if page == "today" else page
    fn = COMPONENTS_FOR.get("today" if page_key == "now" else page_key)
    if not fn:
        return []
    components = fn(doc)
    if cfg is not None:
        from .experience import Experience
        components = _apply_experience(page_key, doc, components, Experience(cfg).ui(page_key))
    return components


def apply_component_experience(page: str, doc: dict, components: list[dict], cfg) -> list[dict]:
    """把 Agent 在对话中保存的表现偏好应用到 Agent 已发布组件。"""
    from .experience import Experience
    page_key = "now" if page == "today" else page
    return _apply_experience(page_key, doc, components, Experience(cfg).ui(page_key))
