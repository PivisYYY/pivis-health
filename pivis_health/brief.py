"""全盘简报（build 52）：服务器把老大的全部数据算成一页，P-Health 每轮都看得到。

为什么：P-Health 每轮只跑一两条命令（几点了、今天的待办），从没把睡眠、恢复、训练、体重、饮食、
习惯执行、伤病放在一起看，回答就只能就事论事（恢复 39 + 呼吸频率偏高的早上，它推荐「出门走 10 分钟」）。

怎么送到 P-Health：写进工作区的 CLAUDE.local.md。DSH 每轮开始前会检查工作区的指令文件，
变了就把这一份补进每个对话（按文件刷新，约 2 KB）。所以这里限流：数据变了才写，只是待办勾掉了最多一小时写一次。

数字全部由这里算（和自己近 30 天比，不是医学标准）；「交叉信号」是写死的规则，带上触发它的数。
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .clock import day_of

FILE_NAME = "CLAUDE.local.md"      # DSH 默认的本地指令文件名之一（和 AGENTS.local.md 一样按文件刷新）
STATE = "brief_state.json"
MIN_REWRITE_S = 3600               # 只有待办变了：最多一小时重写一次
WD = "一二三四五六日"

# 档案里一个专业导师至少要知道的几项（scope 前缀，任一存在就算有）
PROFILE_FIELDS = [
    ("伤病和限制", ("profile.safety", "profile.injury")),
    ("在用的药", ("profile.meds", "profile.medication")),
    ("工作和通勤时间", ("profile.work", "profile.schedule", "profile.commute")),
    ("饮食习惯", ("profile.diet", "pref.diet")),
    ("身高、年龄、性别（算营养目标用）", ("profile.body",)),
    ("运动经历", ("profile.training", "sport.preference")),
    ("想睡多久", ("profile.sleep_need", "sleep.cbti")),
]


# ---------------------------------------------------------------- 小工具
def _hm(minutes: float) -> str:
    m = int(round(minutes)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _mins(hm: str | None) -> int | None:
    try:
        h, m = (int(x) for x in str(hm).split(":")[:2])
        return h * 60 + m
    except (TypeError, ValueError):
        return None


def _night_min(hm: str | None) -> int | None:
    """入睡 / 上床时间换成「从当晚 18:00 起」的分钟数，跨零点也能比较。"""
    m = _mins(hm)
    return None if m is None else (m + 24 * 60 if m < 18 * 60 else m)


def _baseline(tools, metric: str, day: date, days: int = 30) -> dict | None:
    """近 N 天（不含今天）的均值和标准差；不足 7 天不算。"""
    try:
        ser = tools.daily_series(metric, day - timedelta(days=1), days)
    except Exception:  # noqa: BLE001
        return None
    vals = [float(v) for d, v in sorted(ser.items()) if v is not None]
    if len(vals) < 7:
        return None
    return {"mean": statistics.mean(vals), "sd": statistics.pstdev(vals) or 0.0, "n": len(vals)}


def _latest(tools, metric: str, day: date, days: int = 3) -> tuple[date, float] | None:
    try:
        ser = tools.daily_series(metric, day, days)
    except Exception:  # noqa: BLE001
        return None
    have = [(d, float(v)) for d, v in sorted(ser.items()) if v is not None]
    return have[-1] if have else None


def _vs(value: float, base: dict | None, nd: int = 0, unit: str = "") -> str:
    """「53（常态 49±10）」；偏离 1 个标准差以上标「偏高 / 偏低」。"""
    fmt = (lambda x: f"{x:.{nd}f}") if nd else (lambda x: f"{round(x)}")
    if not base:
        return f"{fmt(value)}{unit}"
    tag = ""
    if base["sd"] and abs(value - base["mean"]) >= base["sd"]:
        tag = "，偏高" if value > base["mean"] else "，偏低"
    return f"{fmt(value)}{unit}（常态 {fmt(base['mean'])}±{fmt(base['sd'])}{tag}）"


# ---------------------------------------------------------------- 各部分
def _today_state(tools, day: date) -> tuple[list[str], dict]:
    parts, raw = [], {}
    for metric, label, nd, unit in (("whoop_recovery", "恢复", 0, ""), ("whoop_hrv_rmssd", "HRV", 0, " ms"),
                                    ("resting_heart_rate", "静息心率", 0, ""), ("respiratory_rate", "呼吸频率", 1, "")):
        got = _latest(tools, metric, day, 2)
        if not got:
            continue
        d, v = got
        base = _baseline(tools, metric, d)
        raw[metric] = {"date": d.isoformat(), "value": v, "base": base}
        txt = f"{label} {_vs(v, base, nd, unit)}"
        if metric == "whoop_recovery":
            txt += "，红区" if v < 34 else ("，黄区" if v < 67 else "，绿区")
        if d != day:
            txt += f"（{d.strftime('%m-%d')}）"
        parts.append(txt)
    return parts, raw


def _sleep(tools, day: date) -> tuple[list[str], dict]:
    from .coach import sleep_week
    lines, raw = [], {}
    try:
        sw = sleep_week(tools, 7, day)
    except Exception:  # noqa: BLE001
        return lines, raw
    nights = [n for n in sw["nights"] if n.get("asleep_h") is not None]
    raw["nights"] = nights
    if not nights:
        return ["睡眠：近 7 晚没有数据"], raw
    last = nights[-1]
    yday = (day - timedelta(days=1)).isoformat()
    if last["night_of"] == yday:
        need = f" / 需要 {last['need_h']:.1f}h" if last.get("need_h") else ""
        eff = f" · 效率 {last['efficiency_pct']:.0f}%" if last.get("efficiency_pct") else ""
        when = f" · {last['start']} 睡 → {last['end']} 起" if last.get("start") and last.get("end") else ""
        lines.append(f"昨晚：睡着 {last['asleep_h']:.1f}h{need}{eff}{when}")
    else:
        lines.append(f"昨晚：还没出来（最近一晚是 {last['night_of'][5:]}，人还没睡或 WHOOP 醒后才算好，不是断了）")
    avg = statistics.mean(n["asleep_h"] for n in nights)
    needs = [n["need_h"] for n in nights if n.get("need_h")]
    avg_need = statistics.mean(needs) if needs else None
    debt = sum(max(0.0, (n.get("need_h") or 0) - n["asleep_h"]) for n in nights[-5:]) if needs else None
    starts = [_night_min(n.get("start")) for n in nights if n.get("start")]
    ends = [_mins(n.get("end")) for n in nights if n.get("end")]
    effs = [n["efficiency_pct"] for n in nights if n.get("efficiency_pct") is not None]
    seg = [f"近 {len(nights)} 晚：平均 {avg:.1f}h" + (f"（需要 {avg_need:.1f}h）" if avg_need else "")]
    if debt is not None:
        seg.append(f"睡眠债（近 5 晚）{debt:.1f}h")
    if starts:
        seg.append(f"入睡 {_hm(min(starts))}–{_hm(max(starts))}")
    if ends:
        seg.append(f"起床 {_hm(min(ends))}–{_hm(max(ends))}")
    if effs:
        seg.append(f"效率 ≥90% 的 {sum(1 for e in effs if e >= 90)}/{len(effs)} 晚")
    lines.append(" · ".join(seg))
    raw.update({"avg": avg, "avg_need": avg_need, "debt5": debt, "starts": starts, "ends": ends, "effs": effs,
                "last_is_yday": last["night_of"] == yday})
    return lines, raw


def _training(tools, day: date) -> tuple[list[str], dict]:
    lines, raw = [], {}
    try:
        from . import whoop as whoop_mod
        start = (day - timedelta(days=6)).isoformat()
        ws = [w for w in whoop_mod.workouts(tools._whoop or {}, tools.cfg.timezone) if start <= w["date"] <= day.isoformat()]
    except Exception:  # noqa: BLE001
        ws = []
    raw["workouts"] = ws
    if ws:
        detail = "、".join(f"{w['date'][5:]} {w['sport']} {w['min']} 分钟" + (f"（strain {w['strain']}）" if w.get("strain") else "")
                          for w in ws[-4:])
        lines.append(f"训练：近 7 天 {len(ws)} 次 {sum(w['min'] for w in ws)} 分钟（{detail}）")
    else:
        lines.append("训练：近 7 天 WHOOP 没记到训练")
    st = _latest(tools, "whoop_strain", day - timedelta(days=1), 1)
    if st:
        raw["strain_yday"] = st[1]
    steps = _latest(tools, "steps", day, 7)
    if steps:
        raw["steps_latest"] = steps[0].isoformat()
        lines.append(f"步数：{steps[0].strftime('%m-%d')} {int(steps[1])} 步")
    return lines, raw


def _weight(tools, day: date, goals: list[dict]) -> tuple[list[str], dict]:
    raw: dict[str, Any] = {}
    try:
        w = tools.daily_series("weight", day, 90)
    except Exception:  # noqa: BLE001
        w = {}
    if not w:
        return ["体重：90 天里没有记录"], raw
    last = max(w)
    raw = {"date": last.isoformat(), "kg": round(w[last], 1), "age_days": (day - last).days}
    target = next((g for g in goals if g.get("metric") == "weight"), None)
    tail = f" · 目标 {target['target']} kg，还差 {round(w[last] - float(target['target']), 1)} kg" if target else ""
    return [f"体重：{w[last]:.1f} kg（{last.strftime('%m-%d')}，{raw['age_days']} 天前）{tail}"], raw


def _habits(tools, day: date) -> tuple[list[str], list[dict]]:
    from .coach import project_stats
    from .todos import TodoStore
    rows, raw = [], []
    for p in TodoStore(tools.cfg).projects(active_only=True):
        start = date.fromisoformat(p["start"])
        if not (start <= day < start + timedelta(days=int(p.get("days") or 0))):
            continue
        try:
            st = project_stats(tools, p["id"], 7, day)
        except Exception:  # noqa: BLE001
            continue
        pct = st.get("overall_pct")
        n = sum(k["total"] for k in st.get("items") or [])
        raw.append({"id": p["id"], "name": p["name"], "pct": pct, "n": n, "day": st["project"]["day"]})
        rows.append(f"{p['name']} 第 {st['project']['day']} 天 " + (f"{pct}%（{n} 次）" if pct is not None else "刚开始"))
    return (["习惯（近 7 天完成率）：" + " · ".join(rows)] if rows else []), raw


def _todos_left(tools, day: date) -> list[str]:
    from .todos import PENDING, TodoStore, sort_key
    left = sorted((t for t in TodoStore(tools.cfg).for_date(day) if t["status"] in PENDING), key=sort_key)
    if not left:
        return ["今天的待办：都做完了"]
    return ["今天还没做：" + "、".join(f"{t['when'] or '—'} {t['title']}" for t in left[:8])]


def _bed_wake(tools, day: date) -> tuple[str | None, str | None, str]:
    """今晚的上床和明早起床：CBT-I 记忆 > 今晚的上床卡 > 起床目标。"""
    from .agent_context import AgentContextStore
    from .todos import TodoStore
    bed = wake = None
    src = ""
    for e in AgentContextStore(tools.cfg).snapshot()["entries"]:
        if e.get("scope") == "sleep.cbti":
            p = e.get("payload") or {}
            bed, wake, src = p.get("earliest_bed"), p.get("wake"), "CBT-I"
    if not bed:
        for t in TodoStore(tools.cfg).for_date(day):
            if t.get("auto") == "bedtime" or t["title"].startswith("上床"):
                bed, src = t.get("when"), "今晚的上床卡"
    if not wake:
        try:
            from .params import Params
            wake = Params(tools.subj).all().get("wake_target")
        except Exception:  # noqa: BLE001
            wake = None
    return bed, wake, src


def timeline(bed: str | None, wake: str | None) -> list[tuple[str, str]]:
    """今晚时间线：全部从上床时间倒推（依据见 cbti/references/sleep-science.md 第 2 节）。"""
    b = _night_min(bed)
    if b is None:
        return []
    out = [
        (_hm(b - 8 * 60), "之后不碰咖啡因（咖啡、浓茶、奶茶、可乐、能量饮料）"),
        (_hm(b - 3 * 60), "前吃完晚饭，之后不吃大餐"),
        (_hm(b - 2 * 60), "前结束剧烈运动（拉伸、散步不算）"),
        (_hm(b - 2 * 60), "后少喝水，只润口（夜里尿醒的话尤其要做）"),
        (f"{_hm(b - 2 * 60)}–{_hm(b - 60)}", "之间洗完热水澡（40℃ 左右 10–15 分钟）"),
        (f"{_hm(b - 60)}–{_hm(b - 30)}", "开始放松：灯调暗、放下手机、拉伸或呼吸"),
        (_hm(b), "最早上床（早于这个点不躺）"),
    ]
    if _mins(wake) is not None:
        out.append((wake, "起床，30 分钟内出门见光 10–20 分钟"))
    return out


def _signals(state: dict, sleep: dict, train: dict, habits: list[dict]) -> list[str]:
    """写死的交叉信号：每条都带触发它的数。"""
    out = []
    rec = (state.get("whoop_recovery") or {})
    resp = (state.get("respiratory_rate") or {})
    rhr = (state.get("resting_heart_rate") or {})
    hrv = (state.get("whoop_hrv_rmssd") or {})

    def high(x, k=1.0, floor=0.0):
        b = x.get("base")
        return bool(b) and x["value"] >= b["mean"] + max(k * b["sd"], floor)

    def low(x, k=1.0):
        b = x.get("base")
        return bool(b) and x["value"] <= b["mean"] - k * b["sd"]

    red = bool(rec) and rec["value"] < 34
    if resp and high(resp, 1.5, 0.6) and ((rhr and high(rhr)) or (hrv and low(hrv)) or red):
        out.append(f"呼吸频率 {resp['value']:.1f}（常态 {resp['base']['mean']:.1f}）和"
                   + ("静息心率" if rhr and high(rhr) else "HRV" if hrv and low(hrv) else "恢复")
                   + " 一起变差 → 留意是不是着凉或累过头：今天不练强度，白天多喝水，按时上床；发烧、咽痛就别练")
    if red:
        out.append(f"恢复 {rec['value']:.0f}（红区）→ 今天按恢复日：不加训练强度，膝盖 / 腰背的康复动作照做但不加量")
    elif rec and rec["value"] < 50 and (train.get("strain_yday") or 0) >= 14:
        out.append(f"昨天 strain {train['strain_yday']:.1f} 偏高、今天恢复 {rec['value']:.0f} → 今天轻一点")
    effs, avg, need = sleep.get("effs") or [], sleep.get("avg"), sleep.get("avg_need")
    if len(effs) >= 5 and sum(1 for e in effs if e >= 90) >= len(effs) - 1 and avg and need and need - avg >= 1.0:
        out.append(f"效率 ≥90% 的有 {sum(1 for e in effs if e >= 90)}/{len(effs)} 晚，但平均只睡 {avg:.1f}h、需要 {need:.1f}h"
                   " → 躺下能睡着，缺的是睡眠时间（睡眠机会不足 / 作息偏晚），不是典型失眠：不要压缩窗口，按周把窗口往需要的时长放")
    starts = sleep.get("starts") or []
    if starts and statistics.median(starts) > 25 * 60:
        out.append(f"入睡中位数 {_hm(statistics.median(starts))}，在凌晨 1 点后 → 作息偏晚：起床固定、起床后马上见光、晚上提前调暗灯")
    ends = sleep.get("ends") or []
    if len(ends) >= 4 and max(ends) - min(ends) >= 90:
        out.append(f"起床时间跨度 {(max(ends) - min(ends)) / 60:.1f}h（{_hm(min(ends))}–{_hm(max(ends))}）→ 固定起床是第一优先，周末也一样")
    if sleep.get("debt5") is not None and sleep["debt5"] >= 10:
        out.append(f"近 5 晚睡眠债 {sleep['debt5']:.1f}h → 一晚补不回来；白天困了最多睡 20 分钟、15:00 前")
    for h in habits:
        if h["pct"] is not None and h["n"] >= 3 and h["pct"] < 50:
            out.append(f"「{h['name']}」近 7 天只做到 {h['pct']}%（{h['n']} 次）→ 问原因，按 habit-coach 降成最低版或换做法，别只是继续排")
    return out


def _gaps(tools, day: date, train: dict, weight: dict, habits: list[dict]) -> list[str]:
    out = []
    # WHOOP / Apple 健康：按 datastatus 的原因写（build 53）。服务器的问题不让老大改设置，手机没开 App 不算缺口
    try:
        from . import datastatus
        out += datastatus.brief_lines(tools.cfg)
    except Exception:  # noqa: BLE001
        pass
    if weight and weight.get("age_days", 0) >= 7:
        out.append(f"体重 {weight['age_days']} 天没称（目标在减重：排一张早上空腹称重卡）")
    for h in habits:
        if h["id"] == "daily-log" and h["pct"] is not None and h["pct"] < 50:
            out.append(f"饮食记录近 7 天 {h['pct']}%：拍照太麻烦就改成一句话记，P-Health 估份量和蛋白质")
    return out


def _profile_missing(cfg) -> list[str]:
    from .agent_context import AgentContextStore
    scopes = [e.get("scope", "") for e in AgentContextStore(cfg).snapshot()["entries"]]
    return [label for label, prefixes in PROFILE_FIELDS if not any(s.startswith(prefixes) for s in scopes)]


def _limits(cfg) -> list[str]:
    from .agent_context import AgentContextStore
    out = []
    for e in AgentContextStore(cfg).snapshot()["entries"]:
        s = e.get("scope", "")
        if s.startswith(("profile.safety", "profile.injury")):
            p = e.get("payload") or {}
            flags = p.get("flags") or ([p.get("injury")] if p.get("injury") else [])
            if flags:
                out.append("、".join(str(f) for f in flags))
    return out


def goals_lines(tools, day: date, goals: list[dict], sleep: dict, weight: dict, habits: list[dict]) -> list[str]:
    out = []
    for g in goals:
        m, target = g.get("metric"), g.get("target")
        prog = ""
        if m == "weight" and weight:
            prog = f"现在 {weight['kg']} kg"
        elif m == "sleep_h" and sleep.get("nights"):
            hit = sum(1 for n in sleep["nights"] if n["asleep_h"] >= float(target))
            prog = f"近 {len(sleep['nights'])} 晚达到 {hit} 晚"
        elif str(m).startswith("project:"):
            h = next((x for x in habits if x["id"] == m.split(":", 1)[1]), None)
            prog = f"近 7 天完成 {h['pct']}%" if h and h["pct"] is not None else ""
        dl = f"，截止 {g['deadline']}" if g.get("deadline") else ""
        out.append(f"{g['title']}{dl}" + (f"（{prog}）" if prog else ""))
    return out


# ---------------------------------------------------------------- 组装
def build(tools, now: datetime | None = None) -> dict:
    from . import goals as goals_mod
    now = now or tools._now()
    day = day_of(now)
    goals = goals_mod.load(tools.cfg)
    state_parts, state = _today_state(tools, day)
    sleep_lines, sleep = _sleep(tools, day)
    train_lines, train = _training(tools, day)
    weight_lines, weight = _weight(tools, day, goals)
    habit_lines, habits = _habits(tools, day)
    bed, wake, bed_src = _bed_wake(tools, day)
    tl = timeline(bed, wake)
    sections = {
        "head": f"【全盘 · {now.strftime('%m-%d')} 周{WD[now.weekday()]} {now.strftime('%H:%M')}】服务器算好的，数字直接用；"
                f"「常态」是老大自己近 30 天的均值±标准差，不是医学标准",
        "today": ["今天：" + " · ".join(state_parts)] if state_parts else ["今天：恢复 / HRV 还没出来"],
        "sleep": sleep_lines,
        "train": train_lines + weight_lines,
        "habits": habit_lines,
        "todos": _todos_left(tools, day),
        "timeline": ([f"今晚时间线（按 {bed_src} {bed} 上床" + (f"、{wake} 起床" if wake else "") + " 倒推）："
                      + " · ".join(f"{a} {b}" for a, b in tl)] if tl else []),
        "limits": ["身体限制：" + "；".join(_limits(tools.cfg))] if _limits(tools.cfg) else [],
        "rehab": _safe(lambda: __import__("pivis_health.rehab", fromlist=["x"]).brief_lines(tools.cfg, day)),
        "nutrition": _safe(lambda: __import__("pivis_health.nutrition", fromlist=["x"]).brief_lines(tools, day)),
        "signals": _signals(state, sleep, train, habits),
        "gaps": _gaps(tools, day, train, weight, habits),
        "goals": goals_lines(tools, day, goals, sleep, weight, habits),
        "profile": _profile_missing(tools.cfg),
    }
    return {"day": day.isoformat(), "sections": sections, "text": render(sections)}


def _safe(fn) -> list[str]:
    try:
        return fn() or []
    except Exception:  # noqa: BLE001  简报的一段出错不能拖垮整份
        return []


def render(s: dict) -> str:
    lines = [s["head"]]
    for k in ("today", "sleep", "train", "habits", "todos", "timeline", "limits"):
        lines += s.get(k) or []
    if s.get("rehab"):
        lines.append("康复（rehab-status 算的，进阶 / 退一步照这里说）：")
        lines += [f"- {x}" for x in s["rehab"]]
    lines += s.get("nutrition") or []
    if s.get("goals"):
        lines.append("目标：" + "；".join(s["goals"]))
    else:
        lines.append("目标：还没定（老大说过的目标用 ./pivis-health goal-set 记下来）")
    if s.get("signals"):
        lines.append("交叉信号（规则算的，回答和推荐要先看这里）：")
        lines += [f"- {x}" for x in s["signals"]]
    if s.get("gaps"):
        lines.append("数据缺口：" + "；".join(s["gaps"]))
    if s.get("profile"):
        lines.append("档案还缺：" + "、".join(s["profile"]) + "（合适的时候用问卡问，一次问一项）")
    return "\n".join(lines)


def _core(s: dict) -> str:
    """判断要不要重写：除了时间和「今天还没做」之外的内容。"""
    keep = {k: v for k, v in s.items() if k not in ("head", "todos")}
    return hashlib.sha1(json.dumps(keep, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def brief_path() -> Path:
    from . import dsh_chat
    return Path(dsh_chat.DSH_CWD) / FILE_NAME


def file_text(text: str) -> str:
    return ("<!-- P-Health 全盘简报：服务器每隔一阵自动重写，不要手改（build 52） -->\n"
            "# 老大此刻的全盘（每轮回答和推荐之前先看这一段）\n\n" + text + "\n")


def refresh(tools, force: bool = False, now: datetime | None = None, path: Path | None = None) -> dict:
    """数据变了就重写简报文件；只有待办变了，最多一小时写一次。"""
    if path is None:
        from .prefs import own_workspace
        if not own_workspace(tools.cfg):
            return {"ok": False, "reason": "数据目录不属于当前 DSH 工作区，不写简报"}
        path = brief_path()
    if not path.parent.is_dir():
        return {"ok": False, "reason": f"{path.parent} 不存在"}
    now = now or tools._now()
    st_path = Path(tools.cfg.data_dir) / STATE
    try:
        st = json.loads(st_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    b = build(tools, now)
    core = _core(b["sections"])
    todos = b["sections"]["todos"]
    last_at = st.get("at")
    age = (now - datetime.fromisoformat(last_at)).total_seconds() if last_at else 1e9
    changed_core = core != st.get("core")
    changed_todos = todos != st.get("todos")
    if not (force or changed_core or (changed_todos and age >= MIN_REWRITE_S) or not path.exists()):
        return {"ok": True, "written": False, "path": str(path)}
    text = file_text(b["text"])
    fd, tmp = tempfile.mkstemp(prefix=".brief-", suffix=".md", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    st_path.write_text(json.dumps({"at": now.isoformat(), "core": core, "todos": todos}, ensure_ascii=False),
                       encoding="utf-8")
    return {"ok": True, "written": True, "path": str(path), "bytes": len(text.encode())}
