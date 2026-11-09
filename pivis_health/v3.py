"""v3 页面：主卡（Agent 发布）+ 生成式待办（实时）+ 依据 + 注脚。

页面文档 = Agent 发布的 headline/hero/details/notices + 待办仓库里当天的待办。
数字只来自 facts（内核确定性计算）；Agent 不能编造。
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from . import content
from .agent_context import AgentContextStore
from .todos import BOARD_LABEL, BOARDS, PENDING, TodoError, TodoStore
from .todos import _sort_when as _sort_when_key

PAGES = ("now", "sleep", "sport", "stress")
LEVELS = ("act", "watch", "steady")   # 「数据不足」不再做主卡：断更就换一个有数的指标
LEVEL_LABEL = {"act": "需要处理", "watch": "留意", "steady": "平稳", "nodata": "数据不足"}
DETAIL_KINDS = ("bars", "line", "list", "text")
CONTEXT_OF_BOARD = {"sleep": "休息", "sport": "运动", "stress": "压力"}   # life（日常）走主对话
PAGE_BOARDS = ("sleep", "sport", "stress")   # 能当主卡、能单独成页的板块


# ---------------------------------------------------------------- facts
def _round(v: Any, n: int = 1):
    if v is None:
        return None
    return int(round(float(v))) if n == 0 else round(float(v), n)


def facts(tools, day: date) -> dict:
    """主卡与结论可引用的全部数字（内核确定性计算）。"""
    from .pages import V2Pages
    v2 = V2Pages(tools)
    out: dict[str, Any] = {"date": day.isoformat(), "weekday": "一二三四五六日"[day.weekday()]}
    try:
        sp = v2.sleep(day)
        # 睡眠记录按“入睡那晚”记日期：D 的条目是 D 晚到 D+1 早。今天能看到的“昨晚”是 D-1。
        yday = (day - timedelta(days=1)).isoformat()
        nights = [n for n in sp.get("chart14") or [] if n.get("date") <= yday]
        out["sleep_nights"] = [{"night_of": n["date"], "slept_h": _round(n.get("actual")),
                                "need_h": _round(n.get("need")),
                                "short_h": _round((n.get("need") or 0) - (n.get("actual") or 0))}
                               for n in nights[-7:]]
        last5 = [n for n in nights[-5:] if n.get("actual") is not None]
        from .viz import sleep_debt
        debt, blocks = sleep_debt(nights, 5)          # 和主卡的「睡眠债」同一个算法
        if last5 and nights and nights[-1]["date"] == yday:
            if blocks:
                out["sleep_debt_5n_h"] = debt
            out["sleep_avg_5n_h"] = _round(sum(n["actual"] for n in last5) / len(last5))
            out["last_night"] = out["sleep_nights"][-1]
        else:
            out["last_night"] = None
            # 数据断了几天：仍给出最近的缺觉合计，并标明是哪天的数据，免得 Agent 自己去算
            if blocks:
                out["sleep_debt_latest"] = {"h": debt, "nights": len(blocks), "asof": blocks[-1]["night_of"],
                                            "avg_slept_h": _round(sum(n["actual"] for n in last5) / len(last5)) if last5 else None}
        tiles = sp.get("tiles") or {}
        if (tiles.get("latency") or {}).get("mean") is not None:
            out["sleep_latency_difficulty"] = {"mean": tiles["latency"]["mean"], "target": tiles["latency"].get("target"),
                                               "n": tiles["latency"].get("n")}
    except Exception as exc:  # 缺数据不编
        out["sleep_error"] = str(exc)
    for metric, key, nd in (("whoop_recovery", "recovery_pct", 0), ("whoop_hrv_rmssd", "hrv_ms", 1),
                            ("whoop_strain", "strain", 1), ("steps", "steps", 0)):
        try:
            ser = tools.series(metric, 7, day)
            vals = [{"date": v["date"], "value": _round(v["value"], nd)} for v in ser.get("values") or []
                    if v["date"] <= day.isoformat()]
            out[key] = {"today": next((v["value"] for v in vals if v["date"] == day.isoformat()), None),
                        "recent": vals[-7:]}
        except Exception:
            out[key] = {"today": None, "recent": []}
    # 运动页用：WHOOP 记到的训练（近 7 天，含今天）。没有训练也要明说 0 次，别让运动页只剩步数
    try:
        from . import whoop as whoop_mod
        start = (day - timedelta(days=6)).isoformat()
        ws = [w for w in whoop_mod.workouts(tools._whoop or {}, tools.cfg.timezone) if start <= w["date"] <= day.isoformat()]
        if tools._whoop:
            out["workouts"] = {"last_7d": ws, "count_7d": len(ws), "min_7d": sum(w["min"] for w in ws),
                               "today": [w for w in ws if w["date"] == day.isoformat()], "source": "WHOOP"}
    except Exception:
        pass
    # 压力页用：静息心率、呼吸频率（带数据日期）和 HRV 近 3 天对比之前（个人范围没学满时自己和自己比）
    for metric, key, nd in (("resting_heart_rate", "resting_hr", 0), ("respiratory_rate", "resp_rate", 1)):
        try:
            ser = tools.series(metric, 14, day)
            vals = [(v["date"], float(v["value"])) for v in ser.get("values") or [] if v["date"] <= day.isoformat()]
            if vals:
                prev = [v for _, v in vals[:-1]][-7:]
                out[key] = {"latest": _round(vals[-1][1], nd), "latest_date": vals[-1][0],
                            "avg_prev7": _round(sum(prev) / len(prev), nd) if prev else None,
                            "recent": [{"date": d, "value": _round(v, nd)} for d, v in vals[-7:]],
                            # 数从哪个设备来（WHOOP 是睡眠中测的；和 Apple 手表的口径不同，不要混着比）
                            "source": {"whoop": "WHOOP（睡眠中测）", "apple": "Apple 健康"}[
                                tools.series_source(metric, day, 14)] if hasattr(tools, "series_source") else None}
        except Exception:
            pass
    try:
        ser = tools.series("whoop_hrv_rmssd", 14, day)
        hv = [float(v["value"]) for v in ser.get("values") or [] if v["date"] <= day.isoformat()]
        if len(hv) >= 6:
            a, b = sum(hv[-3:]) / 3, sum(hv[:-3][-7:]) / len(hv[:-3][-7:])
            out["hrv_trend"] = {"last3_avg": _round(a), "prev_avg": _round(b),
                                "change_pct": _round((a - b) / b * 100, 0), "days": len(hv)}
    except Exception:
        pass
    rec = (out.get("recovery_pct") or {}).get("today")
    if rec is not None:
        out["recovery_zone"] = "red" if rec < 34 else ("yellow" if rec < 67 else "green")
    try:
        st = v2.stress(day)
        band = st.get("band") or {}
        rng = band.get("range") or {}
        out["hrv_range"] = {"ready": bool(rng.get("ready")), "learning_days": rng.get("learning_days"),
                            "need_days": 14}
    except Exception:
        out["hrv_range"] = {"ready": False}
    try:
        from .params import Params
        p = Params(tools.subj).all()
        out["params"] = {k: p.get(k) for k in ("wake_target", "sport_name", "weekly_quota") if k in p}
    except Exception:
        pass
    try:
        w = tools.daily_series("weight", day, 60)   # 只看到今天为止
        if w:
            last = max(w)
            out["weight_latest"] = {"date": last.isoformat(), "kg": round(w[last], 1)}
    except Exception:
        pass
    return out


def media_library(tools=None) -> list[dict]:
    from .media import is_follow_video, kind_of as kind
    lib = [{"id": it["id"], "title": it["title"], "duration_min": it["duration_min"], "url": it["url"],
            "kind": kind(it["url"])} for it in content.LIBRARY]
    if tools is not None:
        from .coach import user_media
        lib += [{**m, "source": "老大的素材库"} for m in user_media(tools)]
    # 能不能排成练习卡：只有 follow 出的片可以；其余只能在对话里发媒体卡（白噪音、雨声这类）
    return [{**m, "plannable": is_follow_video(str(m.get("url", "")))} for m in lib]


# ---------------------------------------------------------------- 发布存储
class V3PageStore:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.path = cfg.data_dir / "pages_v3.json"

    def all(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, page: str) -> dict | None:
        return self.all().get(page)

    def save(self, page: str, doc: dict) -> dict:
        import fcntl
        import os
        with open(self.path.with_suffix(".lock"), "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            data = self.all()
            _note_discovery(self.cfg, page, (data.get(page) or {}).get("hero"), doc.get("hero"))
            data[page] = doc
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        return doc


def _note_discovery(cfg, page: str, old: dict | None, new: dict | None) -> None:
    """主卡档位变成「需要处理 / 留意」（或换了一个需要处理的指标）= P-Health 发现了一个问题：记进行动日志，
    洞察引擎拿它看「发现了之后有没有给建议」。"""
    new = new or {}
    if new.get("level") not in ("act", "watch"):
        return
    old = old or {}
    topic = str(new.get("metric") or new.get("label") or "")
    if old.get("level") == new.get("level") and str(old.get("metric") or old.get("label") or "") == topic:
        return
    from . import journal
    journal.action(cfg, "discover", board=new.get("board") or page, topic=topic,
                   detail=f"{new.get('level')} · {new.get('label') or ''}", ref=page)


# ---------------------------------------------------------------- 校验
# 日期、钟点、编号不是「数」：不进来源池，也不当成要核对的数（以前日期里的每个数字都进了池，1–31 随便写都能过）
_NOT_A_NUMBER = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"   # 2026-11-07、ISO 时间
    r"|\b\d{1,2}:\d{2}\b"                                                                 # 01:00、22:40
    r"|\b\d{1,2}/\d{1,2}\b"                                                               # 11/7
    r"|\d{1,2}月\d{1,2}日?"                                                               # 11月7日
    r"|[A-Za-z_]+[-_]?\d[\w-]*"                                                           # id、ssid、key 里的数字
)
# 「近 7 晚」「第 2 天」「连续 3 次」这类计数 / 窗口不是健康数据
_COUNT_PHRASE = re.compile(r"(?:近|第|最近|连续|这|前|过去|每)\s*\d+\s*(?:天|晚|周|次|件|个|顿|组)")


def _strip_non_numbers(text: str) -> str:
    return _COUNT_PHRASE.sub(" ", _NOT_A_NUMBER.sub(" ", text))


def _numbers(obj: Any) -> list[float]:
    """来源池：facts 里的数值字段，加上文字字段里真正的数（去掉日期、钟点、编号）。"""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out += [float(x) for x in re.findall(r"\d+(?:\.\d+)?", _NOT_A_NUMBER.sub(" ", obj))]
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _numbers(v)
    return out


def _has_number(pool: list[float], value: float) -> bool:
    return any(abs(p - value) <= max(0.051, abs(p) * 0.005) for p in pool)


def _check_numbers(pool: list[float], text: str, where: str) -> None:
    for num in re.findall(r"\d+(?:\.\d+)?", _strip_non_numbers(text)):
        if not _has_number(pool, float(num)):
            raise ValueError(f"{where} 里的 {num} 在 facts 里找不到：数字只能抄 facts 里的值"
                             "（钟点、日期、「近 7 晚」这类计数不算）")


def validate_page(page: str, doc: Any, evidence: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("输出必须是 JSON 对象")
    pool = _numbers(evidence)
    pool += [abs(p) for p in pool if p < 0]
    head = doc.get("headline") or {}
    if not isinstance(head, dict) or not str(head.get("text") or "").strip():
        raise ValueError("headline.text 必填")
    headline = str(head["text"]).strip()
    _check_numbers(pool, headline, "headline")
    hero = doc.get("hero") or {}
    if hero.get("level") == "nodata":
        raise ValueError("不要用 nodata（数据不足）做主卡：换一个 facts 里有数的指标，断更的在 note 里写数据日期")
    if hero.get("level") not in LEVELS:
        raise ValueError(f"hero.level 只能是 {LEVELS}")
    if hero.get("board") not in PAGE_BOARDS:
        raise ValueError(f"hero.board 只能是 {PAGE_BOARDS}")
    if page != "now" and hero["board"] != page:
        raise ValueError(f"{page} 页的主卡 board 必须是 {page}")
    if not str(hero.get("label") or "").strip():
        raise ValueError("hero.label 必填")
    value = str(hero.get("value") or "")
    _check_numbers(pool, value, "hero.value")
    fields = hero.get("fields") or []
    if not isinstance(fields, list) or len(fields) > 3:
        raise ValueError("hero.fields 最多 3 个")
    out_fields = []
    for f in fields:
        if not isinstance(f, dict) or not str(f.get("label") or "").strip():
            raise ValueError("hero.fields 每项要有 label 和 value")
        _check_numbers(pool, str(f.get("value") or ""), "hero.fields")
        out_fields.append({"label": str(f["label"]), "value": str(f.get("value") or ""), "unit": str(f.get("unit") or "")})
    table = hero.get("table") or None
    out_table = None
    if table:
        cols = table.get("columns") if isinstance(table, dict) else None
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(cols, list) or not isinstance(rows, list) or not rows:
            raise ValueError("hero.table 要有 columns 和 rows")
        if len(cols) > 4 or len(rows) > 5:
            raise ValueError("hero.table 最多 4 列 5 行")
        for r in rows:
            if not isinstance(r, list) or len(r) != len(cols):
                raise ValueError("hero.table 每行的格数要和 columns 一样")
            for cell in r[1:]:          # 第一列是日期或名目，不校验
                _check_numbers(pool, str(cell), "hero.table")
        out_table = {"columns": [str(c) for c in cols], "rows": [[str(c) for c in r] for r in rows]}
    if out_fields and out_table:
        raise ValueError("hero.fields 和 hero.table 二选一，不要两样都放")
    out_viz = None
    unit = str(hero.get("unit") or "")
    if hero.get("viz"):
        from . import viz as vizmod
        out_viz = vizmod.normalize(hero["viz"])
        m = out_viz["metric"]
        vz = evidence.get("viz") if isinstance(evidence.get("viz"), dict) else (evidence.get("facts") or {}).get("viz")
        avail = (vz or {}).get(m) or {}
        if not avail.get("ok"):
            raise ValueError(f"hero.viz 选的 {m} 现在画不了（{avail.get('reason') or '没有数据'}），换一个 facts.viz 里 ok 的")
        if vizmod.METRICS[m]["board"] != hero["board"]:
            raise ValueError(f"{m} 属于 {vizmod.METRICS[m]['board']} 板块，hero.board 要一致")
        if out_fields or out_table:
            raise ValueError("用了 hero.viz 就不要再放 fields/table：图里已经有支撑的数")
        if avail.get("zone") == "act" and hero["level"] == "steady":
            raise ValueError(f"{m} 已经过了警戒线（facts.viz.{m}.zone=act），level 不能写 steady")
        value = str(avail.get("value_text") or value)     # 主卡数字以内核为准
        unit = str(avail.get("unit") or unit)
    out_layout = None
    if hero.get("layout"):
        # 开放画布：主卡标题行（label + 档位）由 App 画，下面整块由 P-Health 用零件拼
        from . import canvas
        if out_viz or out_fields or out_table:
            raise ValueError("用了 hero.layout 就不要再放 viz / fields / table：图、字段都放进 layout 里")
        try:
            out_layout = canvas.validate(hero["layout"], "hero", pool, _has_number)
        except canvas.CanvasError as exc:
            raise ValueError(f"hero.layout：{exc}") from exc
        # 「主卡别放 timeline」「结论别重复主卡的数」是写法建议（见 SCHEMA），不再硬拦：
        # 老大明确要过的布局（pref.page）里有 timeline 时，以前三次都被拦，页面一直发不出去
    _check_numbers(pool, str(hero.get("note") or ""), "hero.note")
    notices = doc.get("notices") or []
    if len(notices) > 2:
        raise ValueError("notices 最多 2 个")
    for n in notices:
        _check_numbers(pool, str(n.get("text") if isinstance(n, dict) else n), "notices")
    return {
        "headline": {"text": headline},
        "hero": {"level": hero["level"], "board": hero["board"], "label": str(hero["label"]),
                 "value": "" if out_layout else value, "unit": "" if out_layout else unit,
                 "note": str(hero.get("note") or ""),
                 "fields": out_fields, "table": out_table, "viz": out_viz, "layout": out_layout, "others": []},
        "details": [],   # 依据折叠区已去掉；旧客户端读到空数组
        "notices": [{"text": str(n.get("text") if isinstance(n, dict) else n)} for n in notices],
    }


_LAYOUT_SHELL = ("v", "h", "text", "spacer", "rule")


def _layout_sig(node: Any) -> list[tuple]:
    """零件树里「画什么数据」的部分：零件类型 + bind / metric / days / kind，按顺序。文字、间距不算。"""
    if not isinstance(node, dict):
        return []
    out = []
    if node.get("t") not in _LAYOUT_SHELL:
        out.append(tuple(str(node.get(k) or "") for k in ("t", "bind", "metric", "days", "kind")))
    for k in node.get("children") or []:
        out += _layout_sig(k)
    return out


def page_pref(cfg, page: str) -> dict | None:
    """老大在对话里确认过的这一页主卡（pref.page.<page> 里带 layout 的那条）。"""
    from . import prefs
    for e in prefs.active_prefs(cfg):
        p = e.get("payload") or {}
        if e.get("scope") == f"pref.page.{page}" and isinstance(p.get("layout"), (dict, list)):
            return p
    return None


def _evidence_pool(facts_: dict) -> list[float]:
    pool = _numbers(facts_)
    return pool + [abs(p) for p in pool if p < 0]


def enforce_page_pref(page: str, doc: dict, pref: dict | None, facts_: dict, final: bool) -> dict:
    """老大确认过的主卡样子必须照做：零件和 bind 一样才算（文字可以微调）。
    不一样：还能重排就退回（ValueError，原因发回编排）；最后一次直接换成确认过的零件树。"""
    if not pref:
        return doc
    from . import canvas
    try:
        want = canvas.validate(pref["layout"], "hero", _evidence_pool(facts_), _has_number)
    except canvas.CanvasError:
        return doc          # 偏好里的零件树本身过不了（比如手写的数现在对不上了）：没法强制，照编排的来
    hero = doc.get("hero") or {}
    if hero.get("layout") and _layout_sig(hero["layout"]) == _layout_sig(want):
        return doc
    if not final:
        raise ValueError("老大确认过这一页主卡的样子（上面给的零件树），hero.layout 必须照它排：零件、bind、metric、days 都别改，"
                         "只能微调文字；label 和结论也要讲这张图说的事")
    from . import viz as vizmod
    metric = next((s[2] or s[1] for s in _layout_sig(want) if s[1] or s[2]), "")
    label = str(pref.get("label") or (vizmod.METRICS.get(metric) or {}).get("label") or hero.get("label") or "")
    hero = {**hero, "layout": want, "value": "", "unit": "", "viz": None, "fields": [], "table": None, "label": label}
    if page in BOARDS:
        hero["board"] = page
    return {**doc, "hero": hero, "pref_forced": True}


def _layout_bound_numbers(node: dict) -> list[str]:
    """layout 里手写的数字（用来检查结论有没有重复主卡的数）。"""
    out: list[str] = []
    if node.get("t") in ("value", "stat") and node.get("value"):
        out += re.findall(r"\d+(?:\.\d+)?", str(node["value"]))
    for k in node.get("children") or []:
        out += _layout_bound_numbers(k)
    return out


SCHEMA = """只输出一个 JSON 对象，不要 Markdown、不要解释：
{"headline": {"text": "一句判断 + 接下来该做什么，口语化，≤30字；不重复主卡里的数字"},
 "hero": {"level": "act|watch|steady", "board": "sleep|sport|stress",
          "label": "指标名", "value": "数字（只能抄 facts）", "unit": "单位",
          "note": "可选，≤20字；断更的指标写数据日期，没必要就留空",
          "fields": [{"label": "需要", "value": "9.9", "unit": "小时"}],
          "table": {"columns": ["", "睡了", "需要"], "rows": [["10-29", "6.2", "9.8"]]},
          "viz": {"metric": "hrv", "kind": "trend", "days": 14, "show": ["band", "warn"]}},
 "notices": [{"text": "授权缺失、数据断更超过 2 天才写，≤25字"}]}
规则：
- 一页只表达最主要的一个问题。主卡 = 这个问题的值 + 档位；支撑它的数放 fields（最多 3 个）或 table（最多 4 列 5 行，第一列写日期或名目），二选一，也可以都不放。
- 主卡首选画图 hero.viz：你决定画哪项（metric）、怎么画（kind）、看几天（days）、显示哪些参照（show）；数字由内核按描述填，你不用写进去。
  · metric 只能选 facts.viz 里 ok=true 的，且要属于本页板块（facts.viz.*.board）。用了 viz 就不放 fields/table。
  · kind 不写就用默认画法：hrv/resp_rate=trend（折线+常态带+警戒线），resting_hr=range（区间刻度），recovery=gauge（半圆仪表），sleep=need（睡了 vs 需要的缺口条），sleep_debt=stack（每晚欠的叠起来），steps=progress（按此刻该走到的进度），weight=route（朝目标的计划路线）。每项能换的画法在 facts.viz.*.kinds；老大说喜欢折线就用 trend。
  · days：trend 7/14/30，range 7/14，need 7/14，stack 5/7。show 从 band、warn、need、pace、goal、target、plan 里挑，不写就全显示。
  · hero.value 写 facts.viz.<metric>.value_text；常态区间和警戒线是按老大自己 30 天的数算的（或他自己定的），不是医学标准，不要说成诊断。
    结论和 note 里说「比你平时高 / 低」「出了你自己的常态」，**不要写「正常范围」「超标」「异常」**（老大会以为是医学上的不正常）。
  · facts.viz.<metric>.zone 是内核按常态和警戒线算的位置：act=过了警戒线，watch=出了常态，steady=常态里。level 由你判断，但 zone=act 时不能写 steady。
- **主卡也可以自己排（hero.layout，开放画布）**：主卡标题行（label + 档位）App 会画，标题行下面整块（宽 354、高最多 400）由你用零件拼，替代 value/viz/fields/table（用了 layout 就别再放这三样）。样式没法写，只能选零件和档位：
  · hero.layout 的零件和写法见 canvas-cards skill，或跑 `./pivis-health parts`；写完用 `./pivis-health canvas --slot hero --json '<零件树>'` 预览，过了再输出。
  · 数字优先用 bind（内核现算，永远是最新的）；手写的数字也只能抄 facts。
  · 页面主卡下面已经列了「接下来」的待办和「坚持习惯」那一行：layout 里别放 timeline、别重复项目名，除非老大的偏好里明确要。
  · 什么时候用 layout：一个数 + 一张图就够时用 viz；要把两三样拼在一起讲一件事（睡了多久 + 一排每晚点 + 坚持习惯进度；恢复圆环 + HRV/静息心率两个字段；步数进度条 + 今天还差多少 + 接下来去走的那件事）时用 layout。
- level：act=需要处理；watch=留意；steady=平稳/没问题。客户端按 level 给动效：act 最强、watch 缓慢、steady 静止。
- headline 说判断和接下来该做什么；数字只放主卡，不要在结论里重复主卡的 value。
- 此刻页（now）从三个板块里挑当前最需要关注的一项；专项页只挑本板块（hero.board 必须等于页面）。
- 所有数字只能来自 facts，禁止自己加减乘除推算新数字；fields 和 table 里的每个数也一样。
- 正在进行的项目由客户端显示在主卡下，不写进 hero；有进行中的项目时结论要体现计划，早上写成对昨晚执行的总结。
- 压力页（stress）：从 hrv_trend（近 3 天对比之前）、hrv_ms、resting_hr（对比 avg_prev7）、resp_rate、recovery_pct 里挑最能说明当前生理压力信号的一个。HRV 个人范围没学满时就用这些自己和自己比。都在正常波动内就 level=steady，结论写「压力这块没问题」这类，主卡放最能说明没问题的那个数。不诊断、不推测情绪、不说「因为…所以压力大」。
- 运动页（sport）：从 recovery_pct（今早醒来测的恢复，决定今天能练多大强度）、workouts（近 7 天练了什么、几次、多久、strain）、strain（每天的负荷）、steps 里挑。早上 recovery_pct.today 有数时，优先用它讲「今天适合怎么练」，可以配上这周练了几次；12 点前今天的步数还没攒起来，不拿今天的步数（steps.today / bind 今天步数）做主卡。
- 不用「数据不足」做主卡：某个指标断更就换一个有数的指标，note 里写数据日期（如「10-31 的数据」）。
- sleep_nights 里的 short_h 是「每晚缺觉」，不是睡眠债（睡眠债是 sleep_debt_5n_h 一个数）。
- 老大对某项图表定过的偏好（pref.viz.<metric>：画法、天数、警戒线、目标）和页面偏好（pref.page.<page>）优先于上面的默认值。
- shared_context 里是老大定下的偏好，必须遵守。pref.* 是展示和对比偏好（例如图表用折线、跟上一周比）；facts 里有 compare 时，说「比…高/低」一律用 compare 里按老大指定基线算好的数（recent.avg、baseline.avg、change、change_pct），不要再拿别的时间段比。"""


def evidence_for(tools, page: str) -> dict:
    now = tools._now()
    store = TodoStore(tools.cfg)
    day = now.date()
    projects = []
    for p in store.projects(active_only=True):
        start = date.fromisoformat(p["start"])
        if start <= day < start + timedelta(days=p["days"]):
            projects.append({"name": p["name"], "board": p["board"], "day": (day - start).days + 1,
                             "days": p["days"], "rules": p.get("rules")})
    todos = [{"title": t["title"], "when": t["when"], "board": t["board"], "status": t["status"],
              "summary": t.get("summary")} for t in store.for_date(day)]
    yesterday = [{"title": t["title"], "board": t["board"], "status": t["status"], "summary": t.get("summary")}
                 for t in store.for_date(day - timedelta(days=1))]
    fx = facts(tools, day)
    # 老大指定了对比基线（pref.baseline）：按它把几个主要指标算好，页面只许用这里的对比
    from . import prefs
    bp = prefs.baseline_pref(tools.cfg)
    if bp:
        cmp = {}
        for m in ("sleep", "hrv", "recovery", "resting_hr", "strain"):
            try:
                c = prefs.compare(tools, m, day, 7, bp)
                if c.get("ok"):
                    cmp[m] = c
            except Exception:
                pass
        fx["compare"] = {"baseline": bp, "metrics": cmp}
        # 只留老大指定的这一种对比，别的对比口径（近 3 天对之前、对近 7 天均值）拿掉，免得页面混用
        fx.pop("hrv_trend", None)
        for k in ("resting_hr", "resp_rate"):
            if isinstance(fx.get(k), dict):
                fx[k].pop("avg_prev7", None)
    from . import viz as vizmod
    try:
        fx["viz"] = vizmod.available(tools, day)
    except Exception as exc:
        fx["viz"] = {"error": str(exc)}
    return {"page": page, "now": now.isoformat(timespec="minutes"), "facts": fx,
            "projects": projects, "todos_today": todos, "todos_yesterday": yesterday,
            "shared_context": AgentContextStore(tools.cfg).snapshot()}


def publish(tools, page: str, timeout: int = 420) -> dict:
    from . import dsh_chat
    from .publications import _ensure_composer, _new_assistant_text, _parse_json
    if page not in PAGES:
        raise ValueError(f"unknown page {page}")
    evidence = evidence_for(tools, page)
    run_id = f"v3{int(time.time() * 1000)}"
    context = f"组件编排:{page}:{run_id}"
    session = _ensure_composer(page, run_id)
    from . import prefs
    active = prefs.active_prefs(tools.cfg)
    rules = [str((e.get("payload") or {}).get("rule") or "") for e in active]
    pref_text = ("\n老大定下的偏好（必须遵守）：\n" + "\n".join(f"- {r}" for r in rules if r)) if any(rules) else ""
    # 老大在对话里确认过的主卡样子：照这个零件树排（bind 的数会现算成最新的）；发布前代码还会再核对一遍
    confirmed = page_pref(tools.cfg, page)
    if confirmed:
        pref_text += ("\n老大确认过这一页主卡的样子，hero.layout 照这个排（可以微调文字，零件和 bind 别改）：\n"
                      + json.dumps(confirmed["layout"], ensure_ascii=False))
    prompt = ("你是 P-Health 的页面编排，不是聊天。根据真实证据为「" + {"now": "此刻", "sleep": "休息", "sport": "运动",
              "stress": "压力"}[page] + "」页写主卡和结论。\n" + SCHEMA + pref_text + "\n证据：\n"
              + json.dumps(evidence, ensure_ascii=False, default=str))
    before = len(dsh_chat.read_session_events(context))
    dsh_chat.send_message(prompt, context)
    deadline = time.time() + timeout
    tries = 0
    while time.time() < deadline:
        time.sleep(2)
        events = dsh_chat.read_session_events(context)
        new = events[before:]
        ended = [d for d in new if d.get("type") == "turn/end"]
        if not ended:
            continue
        try:
            doc = validate_page(page, _parse_json(_new_assistant_text(new)), evidence["facts"])
            doc = enforce_page_pref(page, doc, confirmed, evidence["facts"], final=tries >= 2)
            if not confirmed and tries < 2:
                _check_live_hero(tools, page, doc)
            doc.update({"published_at": tools._now().isoformat(timespec="seconds"), "session": session,
                        "producer": "P-Health Agent"})
            return V3PageStore(tools.cfg).save(page, doc)
        except ValueError as exc:
            if tries >= 2:
                raise
            tries += 1
            before = len(events)
            dsh_chat.send_message(f"上一次输出没通过校验：{exc}。请按同样格式重新输出完整 JSON。", context)
    raise TimeoutError(f"v3 publish timeout {page}")


def _check_live_hero(tools, page: str, doc: dict) -> None:
    """主卡发出去之前现算一遍：绑的数现在全都算不出来（比如早上 8 点拿「今天步数」做主卡），
    App 上就只剩一行「算不出来」。退回去让 P-Health 换一个今天有数的指标。"""
    from . import canvas
    from . import viz as vizmod
    hero = doc.get("hero") or {}
    day, now = tools._now().date(), tools._now()
    if hero.get("viz"):
        try:
            vizmod.build(tools, hero["viz"], day, now)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"主卡的图现在画不出来（{str(exc)[:40]}）：换一个 facts 里今天有数的指标") from exc
    if hero.get("layout"):
        try:
            resolved = canvas.resolve(tools, hero["layout"], day, now, hero.get("board"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"主卡现在画不出来（{str(exc)[:40]}）：换一个 facts 里今天有数的指标") from exc
        bound, gaps = canvas.live_gaps(hero["layout"], resolved)
        if bound and len(gaps) >= bound:
            raise ValueError(f"主卡绑的数现在全都算不出来（{gaps[0][:40]}）：换一个 facts 里今天有数的指标")


# ---------------------------------------------------------------- 页面文档
def _auto_bedtime(tools, store: TodoStore, day: date) -> None:
    """auto=bedtime 的待办：设备识别到入睡就自动打勾（可纠正）。"""
    for t in store.for_date(day):
        if t.get("auto") != "bedtime" or t["status"] not in ("scheduled", "proposed", "expired"):
            continue
        try:
            rows = tools._rows(day)
        except Exception:
            continue
        starts = []
        for r in rows:
            if r.get("type") != "sleep_analysis" or str(r.get("category_value")) in ("awake", "in_bed"):
                continue
            try:
                s = datetime.fromisoformat(str(r["start_at"]).replace("Z", "+00:00")).astimezone(tools.tz)
            except Exception:
                continue
            if datetime.combine(day, datetime.min.time(), tools.tz) + timedelta(hours=19) <= s <= \
                    datetime.combine(day + timedelta(days=1), datetime.min.time(), tools.tz) + timedelta(hours=6):
                starts.append(s)
        if starts and tools._now() >= min(starts):
            hhmm = min(starts).strftime("%H:%M")
            store.auto_complete(t["id"], f"{hhmm} 入睡（WHOOP / Apple 健康）", {"bedtime": hhmm})


def _expire(store: TodoStore, day: date, now: datetime | None = None) -> None:
    """昨天没做、已经过点的收起；设了 until 的，过了 until 也收起（例如没回的午睡提议）。
    00:00–05:59 的卡算当晚（第二天凌晨才到点）：到点后再留 2 小时，不在零点一过就收起。"""
    from .todos import due_at
    nowl = now.replace(tzinfo=None) if now is not None else None
    stale = []
    for t in store.for_date(day - timedelta(days=1)):
        if t["status"] not in ("scheduled", "proposed", "in_progress") or t.get("auto"):
            continue
        due = due_at(t["date"], t["when"]) if t.get("when") else None
        if nowl is not None and due is not None and due.date() >= day and nowl < due + timedelta(hours=2):
            continue
        stale.append(t)
    if nowl is not None:
        for t in store.for_date(day - timedelta(days=1)) + store.for_date(day):
            if t.get("until") and t["status"] in ("scheduled", "proposed") and t not in stale:
                until = due_at(t["date"], t["until"])
                if until is not None and nowl > until:
                    stale.append(t)
    for t in stale:
        try:
            store.update(t["id"], {"status": "expired"}, by="system")
        except TodoError:
            pass


REPUBLISH_THROTTLE_S = 60          # 页面过期时，客户端每次轮询都会来一次：一分钟内只拉起一次
BACKOFF_FIRST_S, BACKOFF_MAX_S = 600, 7200


def _republish_lock_busy(cfg) -> bool:
    """有没有一个重排进程正持着锁（flock：进程退出锁就没了，不会卡死）。"""
    import fcntl
    try:
        with open(cfg.data_dir / "republish.lock", "a") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def _republish_state(cfg) -> dict:
    try:
        return json.loads((cfg.data_dir / "republish.state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_republish_state(cfg, st: dict) -> None:
    import os
    path = cfg.data_dir / "republish.state.json"
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def republish_async(cfg) -> bool:
    """后台跑一次 publish-v3 all（真正的单实例锁和退避在 publish_all 里）。
    正在跑：记一个「再跑一遍」，跑完接着跑，不丢改动。一分钟内只拉起一次。返回是否新拉起了进程。"""
    import os
    import subprocess
    import sys
    try:
        if _republish_lock_busy(cfg):
            (cfg.data_dir / "republish.again").write_text(str(time.time()))
            return False
        st = _republish_state(cfg)
        if time.time() - float(st.get("spawned_at") or 0) < REPUBLISH_THROTTLE_S:
            return False
        st["spawned_at"] = time.time()
        _save_republish_state(cfg, st)
        log = open(cfg.data_dir / "republish.log", "a")
        subprocess.Popen([sys.executable, "-m", "pivis_health.cli", "publish-v3", "all"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, start_new_session=True, env={**os.environ})
        return True
    except Exception:  # noqa: BLE001
        return False


def publish_all(tools, pages: list[str], timeout: int = 420, force: bool = False) -> dict:
    """重排几页，同一时间只有一个进程在跑（定时任务和客户端触发都走这里）。
    某页失败（DSH 不通、三次校验不过）：这一页按 10 分钟、20 分钟……最长 2 小时退避，不再整夜反复重来。"""
    import fcntl
    cfg = tools.cfg
    lockf = open(cfg.data_dir / "republish.lock", "a")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        (cfg.data_dir / "republish.again").write_text(str(time.time()))
        lockf.close()
        return {"busy": True}
    out: dict[str, Any] = {}
    prog = cfg.data_dir / "republish.progress.json"
    again = cfg.data_dir / "republish.again"
    try:
        for _round in range(3):
            again.unlink(missing_ok=True)
            st = _republish_state(cfg)
            todo = [pg for pg in pages
                    if force or time.time() >= float((st.get("pages") or {}).get(pg, {}).get("next_try") or 0)]
            for i, pg in enumerate(todo):
                prog.write_text(json.dumps({"current": pg, "left": todo[i + 1:], "at": time.time()}))
                t0 = time.time()
                try:
                    out[pg] = {"ok": True, "published_at": publish(tools, pg, timeout).get("published_at")}
                    fails = 0
                except Exception as exc:  # noqa: BLE001
                    out[pg] = {"error": str(exc)[:300]}
                    fails = int((st.get("pages") or {}).get(pg, {}).get("fails") or 0) + 1
                st = _republish_state(cfg)
                pst = st.setdefault("pages", {})
                pst[pg] = {"fails": fails, "at": time.time(),
                           "next_try": time.time() + min(BACKOFF_FIRST_S * 2 ** (fails - 1), BACKOFF_MAX_S) if fails else 0}
                _save_republish_state(cfg, st)
                _log_agent_error(cfg, "publish", pg, out[pg].get("error"), secs=round(time.time() - t0))
            for skipped in set(pages) - set(todo):
                out.setdefault(skipped, {"skipped": "backoff"})
            if not again.exists():
                break
    finally:
        prog.unlink(missing_ok=True)
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()
    return out


def _log_agent_error(cfg, kind: str, where: str, error: str | None, **extra) -> None:
    """P-Health 后台工作的结果都记一行（成功也记，方便看失败率）：runtime/agent_runs.jsonl，超过 2000 行截断。"""
    path = cfg.data_dir / "agent_runs.jsonl"
    try:
        row = {"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, "where": where,
               "ok": not error, "error": error, **extra}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if path.stat().st_size > 600_000:
            lines = path.read_text(encoding="utf-8").splitlines()[-2000:]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def _with_poster(cfg, t: dict) -> dict:
    """follow 出的片有封面就带上 media.poster（App 不再按视频路径猜封面）。"""
    from .media import poster_for
    if t.get("kind") != "follow":
        return t
    steps = []
    for st in t.get("steps") or []:
        m = st.get("media") or {}
        poster = poster_for(cfg, str(m.get("url") or "")) if m else None
        steps.append({**st, "media": {**m, "poster": poster}} if poster else st)
    out = {**t, "steps": steps}
    if t.get("media"):
        poster = poster_for(cfg, str(t["media"].get("url") or ""))
        if poster:
            out["media"] = {**t["media"], "poster": poster}
    return out


def page_doc(tools, page: str) -> dict:
    if page not in PAGES:
        raise ValueError(f"unknown page {page}")
    now = tools._now()
    day = now.date()
    store = TodoStore(tools.cfg)
    store.materialize(day, now)
    _auto_bedtime(tools, store, day - timedelta(days=1))
    _auto_bedtime(tools, store, day)
    _expire(store, day, now)
    pub = V3PageStore(tools.cfg).get(page)
    # 主卡是昨天（或更早）编排的：标记过期，后台重新编排；客户端显示「正在更新」
    stale = (not pub) or str(pub.get("published_at", ""))[:10] < day.isoformat()
    if stale:
        republish_async(tools.cfg)
    todos = store.for_date(day, None if page == "now" else page)
    # 昨晚的“上床”这类跨午夜待办，今天早上在已完成里显示
    carry = [t for t in store.for_date(day - timedelta(days=1), None if page == "now" else page)
             if t.get("auto") == "bedtime" and t["status"] == "done"]
    pending = [t for t in todos if t["status"] in PENDING]
    # 项目里的卡带上「上次」：跟做卡显示上次的评价，数值卡先填上次的数；练习视频带上封面地址
    pending = [_with_poster(tools.cfg, {**t, "last": store.last_record(t)} if t.get("project") else t) for t in pending]
    done = [t for t in todos if t["status"] in ("done", "skipped")] + carry
    more: list[dict] = []
    if page == "now" and len(pending) > 3:
        # 先排再截：等拍板的和最早到点的在前（日常卡没有自己的页，截错了就哪儿都看不到）。
        # 截下来的放 more，App 显示「另有 N 件」点开，提醒也照排
        from .todos import sort_key
        keep = sorted((t for t in pending if t["status"] == "processing"), key=sort_key)
        rest = sorted((t for t in pending if t["status"] != "processing"), key=sort_key)
        n = max(3, len(keep))
        head, more = (keep + rest)[:n], (keep + rest)[n:]
        pending = sorted(head, key=sort_key)
    hidden = len(more)
    hero = (pub or {}).get("hero") or {"level": "nodata", "board": page if page in BOARDS else "sleep",
                                       "label": "还没有判断", "value": "", "unit": "",
                                       "note": "P-Health 下一次更新时生成", "others": []}
    if hero.get("viz"):
        from . import viz as vizmod
        try:
            live = vizmod.build(tools, hero["viz"], day, now)
            hero = {**hero, "viz": live, "value": live["value_text"], "unit": live["unit"]}
        except Exception:
            # 数据断了：不拿发布时的旧数字冒充现在的数，留空并说明
            hero = {**hero, "viz": None, "value": "", "unit": "",
                    "note": "数据暂时读不到，P-Health 会自动恢复"}
    if hero.get("layout"):
        from . import canvas
        try:
            hero = {**hero, "layout": canvas.resolve(tools, hero["layout"], day, now,
                                                     hero.get("board") or (page if page in BOARDS else None))}
        except Exception:  # noqa: BLE001
            # 整张图都算不出来：别静默丢掉（App 上会只剩标题），换成一行说明
            hero = {**hero, "layout": {"t": "v", "gap": 12, "align": "leading", "children": [
                {"t": "text", "text": "数据暂时读不到，P-Health 会自动恢复；先按昨天的安排来", "role": "body", "tone": 2}]}}
    board = hero.get("board") or (page if page in BOARDS else None)
    return {
        "page": page, "now": now.isoformat(timespec="minutes"), "date": day.isoformat(),
        "headline": (pub or {}).get("headline") or {"text": ""},
        "hero": {**hero, "level_label": LEVEL_LABEL.get(hero.get("level"), ""), "board_label": BOARD_LABEL.get(board, "")},
        # 主卡下面每个习惯一行（此刻页 = 所有板块）：点进去是这个板块的对话，顶部是习惯卡（GET /api/v3/habit/<id>）
        "habits": habit_rows(store, page, day),
        "todos": pending, "more": more, "done": done, "hidden": hidden,
        "details": (pub or {}).get("details") or [],
        "notices": (pub or {}).get("notices") or [],
        "projects": [{"id": p["id"], "name": p["name"], "board": p["board"], "rules": p.get("rules"),
                      "start": p["start"], "days": p["days"], "reviews": p.get("reviews")}
                     for p in store.projects(active_only=True) if page == "now" or p["board"] == page],
        "publication": {k: v for k, v in (pub or {}).items() if k in ("published_at", "producer")},
        "stale": stale,
    }


# ---------------------------------------------------------------- 坚持习惯（项目）
WD_CN = "一二三四五六日"


from .canvas_parts import _clean_name   # 项目名去掉「· 56 天 / · 8 周」：习惯行和主卡同一个写法


def _tpl_on(tpl: dict, d: date) -> bool:
    wd = tpl.get("weekdays")
    return not wd or d.isoweekday() in wd


def _tpl_video(tpl: dict, cfg) -> dict | None:
    """模板里的练习视频（follow 出的片）：url、标题、时长，有封面就带上。"""
    media = tpl.get("media") or next((s.get("media") for s in tpl.get("steps") or [] if s.get("media")), None)
    if not media or media.get("kind") != "video" or not str(media.get("url", "")).startswith("/media/follow/"):
        return None
    out = {"url": media["url"], "title": media.get("title") or tpl.get("title") or "",
           "duration_min": media.get("duration_min") or tpl.get("duration_min")}
    from .follow import media_path
    poster = media["url"].rsplit("/", 1)[0] + "/poster.jpg"
    if media_path(cfg, poster) is not None:
        out["poster"] = poster
    return out


def _short_label(title: str) -> str:
    """周视图圆点里的一两个字：「全身力量 B」→ B；否则取第一个字。"""
    last = (title or "").split()[-1] if (title or "").split() else ""
    return last if 0 < len(last) <= 2 and last.isascii() else (title or "")[:1]


def _when_text(d: date, today: date, when: str) -> str:
    if d == today:
        head = "今天"
    elif d == today + timedelta(days=1):
        head = "明天"
    else:
        mon = today - timedelta(days=today.isoweekday() - 1)
        head = ("周" if d < mon + timedelta(days=7) else "下周") + WD_CN[d.isoweekday() - 1]
    return f"{head} {when}".strip()


def _project_state(p: dict, day: date) -> tuple[str, int]:
    start = date.fromisoformat(p["start"])
    n = (day - start).days + 1
    if day < start:
        return "not_started", n
    if n > int(p.get("days") or 0):
        return "ended", n
    return "active", n


def _next_text(p: dict, day: date) -> str:
    """明天起最近一次要做的：「明天 10:00」「周六 20:00」"""
    start = date.fromisoformat(p["start"])
    end = start + timedelta(days=int(p.get("days") or 0))
    for k in range(1, 15):
        d = day + timedelta(days=k)
        if not (start <= d < end):
            continue
        whens = sorted((t.get("when") or "" for t in p.get("daily") or [] if _tpl_on(t, d)), key=_sort_when_key)
        if whens:
            return _when_text(d, day, whens[0])
    return ""


def habit_rows(store: TodoStore, page: str, day: date) -> list[dict]:
    """主卡下面的「坚持习惯」行：本板块进行中、还没结束的项目（此刻页 = 所有板块），按开始日排。"""
    rows = []
    todos = store.for_date(day, None)
    for p in sorted(store.projects(active_only=True), key=lambda p: (p["start"], p["id"])):
        if page != "now" and p["board"] != page:
            continue
        state, n = _project_state(p, day)
        if state == "ended":
            continue
        name = _clean_name(p["name"])
        mine = sorted((t for t in todos if t.get("project") == p["id"]), key=lambda t: _sort_when_key(t["when"]))
        if state == "not_started":
            right = f"{date.fromisoformat(p['start']).strftime('%m-%d')} 开始"
        elif any(t["status"] in PENDING for t in mine):
            nxt = next(t for t in mine if t["status"] in PENDING)
            right = f"今天 {nxt['when']}" if nxt["when"] else "今天待做"
        elif mine and all(t["status"] == "done" for t in mine):
            right = "今天做完了"
        else:
            # 今天没有要做的（休息日），或今天的都过点了：写下一次
            right = _next_text(p, day) or "今天休息"
        label = f"{name} · 第 {n} 天 / {p['days']}" if state == "active" else name
        rows.append({"id": p["id"], "name": name, "board": p["board"], "board_label": BOARD_LABEL.get(p["board"], ""),
                     "day": n if state == "active" else 0, "days": p["days"], "state": state,
                     "label": label, "today": right})
    return rows


def habit_doc(tools, project_id: str) -> dict | None:
    """习惯卡（对话顶部）：名字、第几天、本周 7 天、每套训练（标题、哪几天、下次、时长、视频）。只读。"""
    now = tools._now()
    day = now.date()
    store = TodoStore(tools.cfg)
    store.materialize(day, now)
    p = next((x for x in store.projects() if x["id"] == project_id), None)
    if not p:
        return None
    start = date.fromisoformat(p["start"])
    end = start + timedelta(days=int(p["days"]))          # 不含
    state, n = _project_state(p, day)
    tpls = list(p.get("daily") or [])
    practice_titles = {t.get("title") for t in tpls if t.get("kind") == "follow"}
    multi = len(practice_titles) > 1

    def day_label(d: date) -> str:
        if not multi:
            return ""
        t = next((t for t in tpls if t.get("kind") == "follow" and _tpl_on(t, d)), None)
        return _short_label(t["title"]) if t else ""

    mon = day - timedelta(days=day.isoweekday() - 1)
    week = []
    for i in range(7):
        d = mon + timedelta(days=i)
        on = start <= d < end and any(_tpl_on(t, d) for t in tpls)
        mine = [t for t in store.for_date(d, None) if t.get("project") == p["id"]] if d <= day else []
        done = [t for t in mine if t["status"] == "done"]
        if not on:
            st = "rest"
        elif d < day:
            st = "done" if mine and len(done) == len(mine) else ("part" if done else "missed")
        elif d == day:
            st = "done" if mine and len(done) == len(mine) else "today"
        else:
            st = "plan"
        week.append({"date": d.isoformat(), "wd": WD_CN[i], "state": st, "label": day_label(d) if on else "",
                     "today": d == day})

    sessions = []
    for tpl in tpls:
        nxt = None
        for k in range(0, 15):
            d = day + timedelta(days=k)
            if not (start <= d < end) or not _tpl_on(tpl, d):
                continue
            if d == day:
                inst = store.get(f"{p['id']}-{d.isoformat()}-{tpl['key']}")
                if inst and inst["status"] not in PENDING:
                    continue
            nxt = d
            break
        video = _tpl_video(tpl, tools.cfg)
        dur = tpl.get("duration_min") or (video or {}).get("duration_min")
        next_text = _when_text(nxt, day, tpl.get("when") or "") if nxt else ""
        meta = " · ".join(x for x in (next_text, f"{dur:g} 分钟" if dur else "") if x)
        sessions.append({"key": tpl["key"], "title": tpl.get("title") or "", "kind": tpl.get("kind") or "done",
                         "weekdays": tpl.get("weekdays"), "when": tpl.get("when") or "",
                         "next": next_text, "today": nxt == day, "duration_min": dur, "meta": meta, "video": video,
                         "_d": nxt})
    by_next = lambda s: (s["_d"] or date.max, _sort_when_key(s["when"]))  # noqa: E731
    first = min((s for s in sessions if s["_d"]), key=by_next, default=None)
    # 练习（有视频的）排前面，各自按下次时间
    sessions.sort(key=lambda s: (s["video"] is None, *by_next(s)))
    for x in sessions:
        x.pop("_d")
    name = _clean_name(p["name"])
    if state == "not_started":
        summary = f"{start.strftime('%m-%d')} 开始"
    elif state == "ended":
        summary = f"{p['days']} 天已结束"
    else:
        summary = f"第 {n} 天" + (f" · 下次 {first['next']} {first['title']}" if first else "")
    return {"id": p["id"], "name": name, "board": p["board"], "board_label": BOARD_LABEL.get(p["board"], ""),
            "state": state, "day": n if state == "active" else 0, "days": p["days"], "start": p["start"],
            "status": p.get("status"), "week": week, "sessions": sessions, "summary": summary,
            "label": f"{name} · 第 {n} 天 / {p['days']}" if state == "active" else name}


# ---------------------------------------------------------------- 用户提交
def _agent_message(t: dict, values: dict, text: str) -> str:
    parts = []
    for inp in t.get("inputs") or []:
        if inp["id"] in values:
            v = values[inp["id"]]
            if inp["type"] in ("options", "multi"):
                labels = {o["id"]: o["label"] for o in inp.get("options") or []}
                v = "、".join(labels.get(x, x) for x in (v if isinstance(v, list) else [v]))
            if inp["type"] == "photo":
                v = f"照片 {v}（用 read_image 看这张图）"
            parts.append(f"{inp['label']}：{v}" if inp.get("label") else str(v))
    if text:
        parts.append(f"文字：{text}")
    return (f"【待办提交】id={t['id']}｜{t['title']}（{BOARD_LABEL[t['board']]}，{t['date']} {t['when'] or ''}）\n"
            f"用户在待办卡里提交：{'；'.join(parts) or '（无内容）'}\n"
            "请理解用户意图后直接更新数据，不要只在对话里回复：\n"
            f"- 改这条：./pivis-health todo-update --id {t['id']} --json '<改动 JSON>'（时间、标题、素材、inputs、状态都能改）\n"
            "- 需要新增待办：todo-add；属于项目的长期改动（比如以后都换这一套）：project-set 更新模板\n"
            f"- 必须追问用户才能做时：todo-update --id {t['id']} --json '{{\"escalate\":\"chat\"}}'，然后在本对话里用 phealth-ui question 卡追问\n"
            "处理完后用一句话说清楚改了什么、什么时候生效。")


def _store_photo(tools, stem: str, data: bytes) -> dict:
    if not data or len(data) > 12 * 1024 * 1024:
        raise ValueError("照片为空或超过 12 MB")
    if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        raise ValueError("只收 JPEG / PNG")
    folder = tools.cfg.data_dir / "photos"
    folder.mkdir(parents=True, exist_ok=True)
    ext = "png" if data[:4] == b"\x89PNG" else "jpg"
    path = folder / f"{re.sub(r'[^A-Za-z0-9_-]', '-', stem)}-{int(time.time() * 1000)}.{ext}"
    path.write_bytes(data)
    return {"photo": str(path), "name": path.name}


def save_photo(tools, todo_id: str, data: bytes) -> dict:
    """待办卡上拍的照片：存到运行目录 photos/，返回给 P-Health 读图用的绝对路径。"""
    if TodoStore(tools.cfg).get(todo_id) is None:
        raise KeyError(todo_id)
    return _store_photo(tools, todo_id, data)


def save_chat_photo(tools, data: bytes) -> dict:
    """对话里直接拍的照片：同样存 photos/，客户端把路径写进消息发给 P-Health。"""
    return _store_photo(tools, "chat", data)


PHOTO_NAME = re.compile(r"^[A-Za-z0-9_-]+\.(?:jpg|png)$")


def photo_file(tools, name: str) -> Path | None:
    """对话里显示缩略图用：只认 photos/ 下的文件名，不接受路径。"""
    if not PHOTO_NAME.match(name):
        return None
    f = tools.cfg.data_dir / "photos" / name
    return f if f.is_file() else None


# ---------------------------------------------------------------- 客户端同步状态
_TURN_CACHE: dict[str, tuple[int, dict]] = {}
CHAT_CONTEXTS = ("", "休息", "运动", "压力", "事件处理")


def _turn(context: str) -> dict | None:
    """会话回合状态，按会话文件 mtime 缓存（客户端会几秒轮询一次）。"""
    from . import dsh_chat
    f = dsh_chat._session_dir(context) / "session.v4.jsonl.zstd"
    try:
        m = f.stat().st_mtime_ns
    except OSError:
        return None
    hit = _TURN_CACHE.get(context)
    if hit and hit[0] == m:
        return hit[1]
    st = dsh_chat.turn_status(context)
    _TURN_CACHE[context] = (m, st)
    return st


def sync_health(tools, now: datetime | None = None) -> dict:
    """老大在 App 里下拉刷新：马上拉一次 WHOOP（App 同时把 Apple 健康的数据传上来）。
    - 60 秒内重复下拉不重复拉，直接说刚同步过；
    - 模拟回放 / 演示环境不连 WHOOP。"""
    cfg = tools.cfg
    if getattr(cfg, "sim_mode", False):
        return {"ok": True, "whoop": "skipped", "message": "模拟环境不连 WHOOP"}
    from . import whoop_sync
    mark = cfg.data_dir / "whoop_manual_sync.json"
    t = time.time()
    try:
        last = json.loads(mark.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        last = {}
    if t - float(last.get("at") or 0) < 60 and last.get("ok"):
        return {"ok": True, "whoop": "recent", "message": "刚同步过", "latest": last.get("latest")}
    try:
        r = whoop_sync.sync(cfg, force=True)
        out = {"ok": True, "whoop": "synced", "latest": r.get("latest_recovery_night"),
               "message": "WHOOP 已同步"}
    except whoop_sync.WhoopError as exc:
        out = {"ok": False, "whoop": "failed", "message": f"WHOOP 同步失败：{str(exc)[:60]}"}
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "whoop": "failed", "message": f"WHOOP 同步失败：{type(exc).__name__}"}
    try:
        mark.write_text(json.dumps({"at": t, "ok": out["ok"], "latest": out.get("latest")}), encoding="utf-8")
    except OSError:
        pass
    return out


def sync_status(tools) -> dict:
    """客户端用来决定什么时候刷新、哪里显示「正在改」：
    rev     页面、待办、偏好、健康数据任一变了就变 → 客户端重新拉页面；
    agent   P-Health 正在某个对话里处理（可能马上改页面/待办）；
    updating 后台正在重排的页面（主卡和结论会换）。"""
    import hashlib
    cfg = tools.cfg
    d = cfg.data_dir
    files = [d / "pages_v3.json", d / "todos_v3.json", d / "agent_context.json",
             Path(cfg.vault_db), Path(str(cfg.vault_db) + "-wal"), Path(cfg.whoop_snapshot)]
    sig = "|".join(str(f.stat().st_mtime_ns) if f.exists() else "-" for f in files)
    lock, again, prog = d / "republish.lock", d / "republish.again", d / "republish.progress.json"
    updating: list[str] = []
    running = _republish_lock_busy(cfg)
    if running:
        try:
            pr = json.loads(prog.read_text(encoding="utf-8"))
            updating = [x for x in [pr.get("current"), *(pr.get("left") or [])] if x in PAGES]
        except Exception:  # noqa: BLE001
            updating = list(PAGES)
        if again.exists():
            updating = list(PAGES)
    agent: dict[str, Any] = {"busy": False}
    for ctx in CHAT_CONTEXTS:
        st = _turn(ctx)
        if st and st.get("busy"):
            agent = {"busy": True, "context": ctx, "tool": st.get("last_tool"),
                     "args": (st.get("last_args") or "")[:600]}
            break
    # 每个对话 P-Health 最后一次回话的时刻：App 拿它和「上次看到哪」比，有新回复就在入口亮个点
    replies = {(ctx or "main"): t for ctx in REPLY_CONTEXTS if (t := _last_reply(ctx))}
    out = {"rev": hashlib.sha1(sig.encode()).hexdigest()[:12], "agent": agent, "updating": updating,
           "replies": replies, "now": tools._now().isoformat(timespec="seconds")}
    # 洞察：有待发的一期时带上（App 在主对话输入框上方浮一条、中间圆钮亮点）
    from . import insight
    pending = insight.pending_status(cfg)
    if pending:
        out["insight"] = pending
    return out


REPLY_CONTEXTS = ("", "休息", "运动", "压力")
_REPLY_CACHE: dict[str, tuple[int, str | None]] = {}


def _last_reply(context: str) -> str | None:
    """这个对话里 P-Health 最后一段话的时刻（ISO，北京时间）。按会话文件 mtime 缓存，轮询不费事。"""
    from . import dsh_chat
    f = dsh_chat._session_dir(context) / "session.v4.jsonl.zstd"
    try:
        m = f.stat().st_mtime_ns
    except OSError:
        return None
    hit = _REPLY_CACHE.get(context)
    if hit and hit[0] == m:
        return hit[1]
    out = None
    try:
        for d in reversed(dsh_chat.read_session_events(context)):
            if d.get("type") != "assistant/message" or not d.get("time"):
                continue
            msg = (d.get("data") or {}).get("message", d.get("data") or {})
            if any(isinstance(c, dict) and c.get("type") == "text" and str(c.get("text", "")).strip()
                   for c in msg.get("content", [])):
                out = datetime.fromtimestamp(int(d["time"]) / 1000, tz=ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
                break
    except Exception:  # noqa: BLE001
        out = None
    _REPLY_CACHE[context] = (m, out)
    return out


BOARD_LABELS = {"sleep": "休息", "sport": "运动", "stress": "压力", "life": "日常"}


def _abs_time(day_iso: str, hhmm: str, tz) -> str | None:
    """待办的绝对时间：00:00–05:59 的算当晚（第二天凌晨）。小组件按它排时间线。"""
    if not hhmm:
        return None
    from .todos import due_at
    try:
        at = due_at(day_iso, hhmm)
    except ValueError:
        return None
    return at.replace(tzinfo=tz).isoformat(timespec="minutes") if at else None


def widget_doc(tools) -> dict:
    """小组件用的一小份数据：此刻主卡、今天还没做的待办（带绝对时间）、上床时间、近 7 晚。"""
    from . import viz as vizmod
    from .todos import sort_key
    now = tools._now()
    day = now.date()
    tz = now.tzinfo
    page = page_doc(tools, "now")
    hero = page.get("hero") or {}
    store = TodoStore(tools.cfg)
    today = store.for_date(day, None)
    pending = sorted((t for t in today if t["status"] in PENDING), key=sort_key)
    todos = [{
        "id": t["id"], "when": t["when"], "at": _abs_time(t["date"], t["when"], tz),
        "title": t["title"], "note": t.get("note") or "", "board": t["board"],
        "board_label": BOARD_LABELS.get(t["board"], ""), "kind": t["kind"], "status": t["status"],
        "auto": bool(t.get("auto")),        # 设备自动记的（上床）：小组件上写「自动记」，不让手点
        "duration_min": t.get("duration_min"),
        # 练习（follow 出的片）：小组件、到点提醒点开直接全屏播
        "play": t["kind"] == "follow" and any(str((st.get("media") or {}).get("url", "")).startswith("/media/follow/")
                                              for st in t.get("steps") or []),
        # 小组件上能直接打勾的：只要知道做没做的（跟做、填写、计时这些要进 App）
        # 打勾卡（包括「上床」这种设备也会自动记的）：小组件上直接点 ✓（老大 11-08：上床也应该是对勾）
        "check": t["kind"] == "done" and t["status"] != "processing",
    } for t in pending]
    bed = next((t for t in today if t.get("auto") == "bedtime"), None)
    nights = []
    try:
        nights = vizmod._sleep_nights(tools, day)[-7:]
    except Exception:  # noqa: BLE001
        nights = []
    sleep = {"nights": [{"date": n["date"], "hours": round(float(n["actual"]), 1),
                         "need": round(float(n["need"]), 1) if n.get("need") is not None else None}
                        for n in nights]}
    if nights:
        last = nights[-1]
        sleep["last"] = round(float(last["actual"]), 1)
        if last.get("need") is not None:
            sleep["need"] = round(float(last["need"]), 1)
            sleep["short"] = round(max(0.0, float(last["need"]) - float(last["actual"])), 1)
    return {
        "now": now.isoformat(timespec="minutes"), "date": day.isoformat(),
        "hero": {"label": hero.get("label") or "", "value": str(hero.get("value") or ""),
                 "unit": hero.get("unit") or "", "level": hero.get("level") or "",
                 "board_label": BOARD_LABELS.get(hero.get("board") or "", ""),
                 "note": (page.get("headline") or {}).get("text") or hero.get("note") or ""},
        "todos": todos[:8], "count": len(todos),
        "bed": {"title": bed["title"], "when": bed["when"], "at": _abs_time(bed["date"], bed["when"], tz)} if bed and bed["when"] else None,
        "sleep": sleep,
    }


def _client_now(server_now: datetime, client_at) -> datetime:
    """老大点下去的那一刻（App 断网时先记在本地，连上再发）。只认最近 36 小时内、不超前 5 分钟的时间，
    否则（包括模拟回放的假时钟）用服务器时间。"""
    if not client_at:
        return server_now
    try:
        t = datetime.fromisoformat(str(client_at).replace("Z", "+00:00"))
    except ValueError:
        return server_now
    if t.tzinfo is None or server_now.tzinfo is None:
        return server_now
    t = t.astimezone(server_now.tzinfo)
    if timedelta(minutes=-5) <= server_now - t <= timedelta(hours=36):
        return t
    return server_now


def submit(tools, todo_id: str, body: dict) -> dict:
    from . import dsh_chat
    store = TodoStore(tools.cfg)
    action = body.get("action") or "done"
    values = body.get("values") or {}
    text = (body.get("text") or "").strip()
    now = _client_now(tools._now(), body.get("client_at"))
    photos = (tools.cfg.data_dir / "photos").resolve()
    cur = store.get(todo_id) or {}
    for inp in cur.get("inputs") or []:
        if inp["type"] == "photo" and inp["id"] in values:
            p = Path(str(values[inp["id"]])).resolve()
            if photos not in p.parents or not p.is_file():
                raise ValueError("照片路径无效")
    t = store.user_submit(todo_id, action, values, text, body.get("summary"), now, op_id=body.get("op_id"))
    if action == "agent":
        msg = _agent_message(t, values, text)
        context = CONTEXT_OF_BOARD.get(t["board"], "")

        def _send():
            try:
                before = len(dsh_chat.read_session_events(context))
                dsh_chat.send_message(msg, context)
                # 兜底：P-Health 这一轮结束了，卡片却还停在「处理中」（它说了要退回却没改），
                # 就把卡片放回原来的状态，并打开对话让老大看到它说了什么
                deadline = time.time() + 300
                while time.time() < deadline:
                    time.sleep(3)
                    if any(e.get("type") == "turn/end" for e in dsh_chat.read_session_events(context)[before:]):
                        break
                time.sleep(2)
                cur = store.get(todo_id)
                if cur and cur["status"] == "processing":
                    store.update(todo_id, {"status": (t.get("request") or {}).get("previous_status") or "scheduled",
                                           "escalate": "chat"}, by="system")
            except Exception as exc:
                try:
                    store.update(todo_id, {"status": t["request"].get("previous_status") or "scheduled",
                                           "escalate": "error"}, by="system")
                except Exception:
                    pass
                print("agent submit failed", exc)

        threading.Thread(target=_send, daemon=True).start()
    if action in ("done", "skip") and t.get("project"):
        # 主观记录同时进入主观库，供后续计算
        try:
            tools.log_subjective("todo_record", {"todo": todo_id, "title": t["title"], "action": action,
                                                 "values": values, "text": text})
        except Exception:
            pass
    return t


# ---- 每日整理：每天早上让各板块的 P-Health 看一眼数据和项目，决定要不要加 0–2 件待办 ----
REVIEW_PREFIX = "【每日整理】"      # 已不再单独发送（早上那次【每日推荐】带上整理）；留给旧聊天记录的显示


RECOMMEND_PREFIX = "【每日推荐】"
SLOTS = {"morning": ("早上", "起床"), "noon": ("午后", "午休结束"), "evening": ("傍晚", "下班回家")}


def slot_for(now: datetime) -> str:
    """按钟点判断现在是哪一档：11 点前早上，16 点前午后，其余傍晚。"""
    return "morning" if now.hour < 11 else ("noon" if now.hour < 16 else "evening")


def _recommend_message(slot: str, now: datetime) -> str:
    name, scene = SLOTS[slot]
    return (f"{RECOMMEND_PREFIX}{now.date().isoformat()} {now.strftime('%H:%M')}｜{name}\n"
            f"系统的定时推荐，老大看不到这条。现在是{name}（老大{scene}的时候）。"
            f"按 daily-recommend skill 里「{name}」那一节做：看数据和今天已有的待办，主动给老大推荐 1–2 件现在最合适的事，"
            "用待办卡写进对应板块（要占时间或改计划的用 proposal，几分钟的小事直接给打勾卡）；不要和项目里已有的重复。"
            "练习只推荐 follow 出过片的（follow session list 能查）；没有就请老大发一个博主视频，今天已经问过就别再问。"
            "做完只回一句话，例如「早上推荐了：晨光散步、网球前臂离心」。")


DAILY_REVIEW_NOTE = ("\n这是早上那次【每日推荐】，顺带做每日整理：看昨天的待办做得怎么样（漏了的问原因，连续漏两次的按 habit-coach 处理）、"
                     "昨天用过的素材该打分的出打分卡、今天训练该不该降强度（training-coach）、还没做的入门问卷（phealth-role）。")


def _today_counts(tools, day: date) -> str:
    """今天已经排了几张带时间的卡、锁屏推了几条：P-Health 据此守住「到点提醒一天最多 3 张」，不用自己记。"""
    timed = [t for t in TodoStore(tools.cfg).for_date(day) if t.get("when") and t["status"] in PENDING]
    try:
        pushed = tools.subj.push_count(day.isoformat())
    except Exception:  # noqa: BLE001
        pushed = 0
    return f"\n今天的计数：还没做的带时间待办 {len(timed)} 张；锁屏推送已发 {pushed} 条（上限 {tools.cfg.daily_push_limit}）。"


def daily_review(tools, boards: list[str] | None = None, force: bool = False, slot: str | None = None) -> dict:
    """每天三次（早上 8 点起床、午后 1 点午休结束、傍晚 6 点下班回家）的场景推荐：
    发给主对话里的 P-Health，由它通盘看三个板块，在合适的板块加 1–2 张卡。每档每天只发一次。
    周日早上那次顺带做每个进行中项目的周复盘。boards 参数保留给旧调用，已不分板块。"""
    from . import dsh_chat
    from .coach import weekly_review_note
    now = tools._now()
    slot = slot or slot_for(now)
    if slot not in SLOTS:
        raise ValueError(f"slot 只能是 {tuple(SLOTS)}")
    state_path = tools.cfg.data_dir / "daily_review.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    key = f"main:{now.date().isoformat()}:{slot}"
    if state.get(key) and not force:
        return {"slot": slot, "status": "already"}
    msg = _recommend_message(slot, now)
    from .coach import projects_truth
    msg += _today_counts(tools, now.date())
    msg += projects_truth(tools, now.date())
    if slot == "morning":
        msg += DAILY_REVIEW_NOTE
        msg += weekly_review_note(tools, now.date())
    try:
        dsh_chat.send_message(msg, "")
        state[key] = now.isoformat(timespec="minutes")
        out = {"slot": slot, "status": "sent"}
    except Exception as exc:  # noqa: BLE001
        out = {"slot": slot, "status": f"error: {exc}"}
    _log_agent_error(tools.cfg, "daily_recommend", slot, None if out["status"] == "sent" else out["status"])
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(state_path)
    return out
