"""洞察二期：③ 几种数据放在一起、④ 你没注意到的（build 50）。

都要至少 4 周数据（结果指标在窗口里有 ≥ 20 天）；数据缺的天不当 0、不进任何一组。
  分组对比 / 前后天  事先定好的「行为或场景 × 结果」配对（白名单，不全量乱撞）；两组各 ≥ 5 次，差别大过 Psir 自己平时的波动
  平台期              习惯做到七成以上满 3 周：开始后指标变过，最近 2 周不再变
  最好的那些天        结果最好的一成日子里，某个做法出现的比例是其他日子的 2 倍以上
  对话主题            同一部位或困扰 14 天里提了 ≥ 3 次（不同的天），没有计划在管

配对表和阈值是通用规则，可以进仓库；Psir 的数据、算出来的数都只在数据目录里。
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from typing import Any, Callable

MIN_DAYS = 20            # 结果指标在 4 周窗口里至少有这么多天，③④ 才算
MIN_GROUP = 5
OUTCOMES = {             # 结果：标签、单位、小数位、最小有意义差别、越大越好
    "sleep_h": ("睡着时长", "小时", 1, 0.3, True),
    "recovery": ("恢复", "", 0, 5.0, True),
    "hrv": ("HRV", "ms", 0, 3.0, True),
    "completion": ("习惯完成率", "%", 0, 15.0, True),
}


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


# ---------------------------------------------------------------- 每天的行为 / 场景 / 结果
class Daily:
    """把各处的数据整理成「哪天 → 有没有 / 多少」。日期约定：
    睡着时长按夜（晚上那天）；恢复、HRV 按醒来那天；行为按发生那天；外宿按那一夜（晚上那天）。"""

    def __init__(self, data) -> None:
        self.data = data
        self.today: date = data.today
        self.since: date = data.since
        self.days = [self.since + timedelta(days=i) for i in range((self.today - self.since).days)]

    def outcome(self, name: str) -> dict[date, float]:
        if name == "completion":
            return self.completion()
        if name == "sleep_h":
            return {d: v for d, v in self.data.metric("sleep").items()}
        return self.data.metric({"recovery": "recovery", "hrv": "hrv"}[name])

    def completion(self) -> dict[date, float]:
        by: dict[date, list[bool]] = {}
        from .insight import ACT_KINDS
        for t in self.data.todos():
            if t.get("project") and t.get("kind") in ACT_KINDS and t["date"] < self.today.isoformat():
                by.setdefault(date.fromisoformat(t["date"]), []).append(t.get("status") == "done")
        return {d: 100.0 * sum(xs) / len(xs) for d, xs in by.items() if xs}

    def project_done(self, pid: str) -> dict[date, bool]:
        out: dict[date, bool] = {}
        from .insight import ACT_KINDS
        for t in self.data.todos():
            if t.get("project") == pid and t.get("kind") in ACT_KINDS and t["date"] < self.today.isoformat():
                d = date.fromisoformat(t["date"])
                out[d] = out.get(d, False) or t.get("status") == "done"
        return out

    def train(self) -> dict[date, bool]:
        """练了：运动板块的项目那天做了，或者 WHOOP 记到一次训练。"""
        out: dict[date, bool] = {}
        for p in self.data.projects():
            if p.get("board") == "sport":
                for d, v in self.project_done(p["id"]).items():
                    out[d] = out.get(d, False) or v
        try:
            from . import whoop as w
            for x in w.workouts(self.data._whoop(), self.data.cfg.timezone):
                d = date.fromisoformat(x["date"])
                out[d] = True
        except Exception:  # noqa: BLE001
            pass
        return out

    def scene(self, key: str, test: Callable[[dict], bool | None]) -> dict[date, bool]:
        from . import scene
        out = {}
        for ds, e in scene.load(self.data.cfg).items():
            v = test(e)
            if v is not None:
                out[date.fromisoformat(ds)] = bool(v)
        return out

    def early_bed(self, before: str = "23:30") -> dict[date, bool]:
        """那一夜在 23:30 前睡着（WHOOP 记的入睡时刻；按夜）。"""
        lim = int(before[:2]) * 60 + int(before[3:])
        out = {}
        for night, v in self.data.nights().items():
            s = str(v.get("start_local") or "")
            if len(s) >= 16:
                m = int(s[11:13]) * 60 + int(s[14:16])
                m = m + 1440 if m < 12 * 60 else m          # 过了半夜按 24+ 算
                out[night] = m <= lim
        return out

    def late_dinner(self, after: str = "20:30") -> dict[date, bool]:
        """晚饭吃得晚：日常板块标题里有「晚饭 / 晚餐」的卡，实际做完（拍照 / 打勾）的时刻在 20:30 以后。"""
        lim = int(after[:2]) * 60 + int(after[3:])
        out = {}
        for t in self.data.todos():
            if t.get("status") != "done" or not any(w in str(t.get("title") or "") for w in ("晚饭", "晚餐")):
                continue
            at = str((t.get("record") or {}).get("at") or "")
            if len(at) >= 16:
                m = int(at[11:13]) * 60 + int(at[14:16])
                out[date.fromisoformat(t["date"])] = m >= lim
        return out

    def features(self) -> dict[str, tuple[str, dict[date, bool]]]:
        """行为 / 场景：key → (说法, 每天有没有)。"""
        f: dict[str, tuple[str, dict[date, bool]]] = {}
        for p in self.data.projects():
            if p.get("status") != "active":
                continue
            f[f"proj:{p['id']}"] = (f"做了「{p.get('name') or p['id']}」", self.project_done(p["id"]))
        f["train"] = ("练了", self.train())
        f["away"] = ("在外过夜", self.scene("away", lambda e: e.get("away_night")))
        f["drive_long"] = ("开车超过 1 小时", self.scene("drive", lambda e: None if e.get("drive_min") is None
                                                     else e["drive_min"] >= 60))
        f["early_bed"] = ("23:30 前睡着", self.early_bed())
        f["late_dinner"] = ("晚饭在 20:30 以后", self.late_dinner())
        return f


# ---------------------------------------------------------------- 配对白名单
# (行为前缀, 结果, 结果在行为之后的第几天（列表 = 这几天都算「之后」）, 板块限制)
PAIRS = [
    ("proj:", "sleep_h", [0], "sleep"),       # 睡前练习那晚 × 睡着时长
    ("proj:", "recovery", [1], "sport"),      # 训练那天 × 第二天恢复
    ("train", "sleep_h", [0], None),          # 练了那天 × 当晚睡眠
    ("away", "recovery", [1, 2, 3], None),    # 在外过夜后 3 天 × 恢复
    ("away", "completion", [1, 2, 3], None),  # 在外过夜后 3 天 × 习惯完成率
    ("drive_long", "sleep_h", [0], None),     # 开车久那天 × 当晚睡眠
    ("late_dinner", "hrv", [1], None),        # 晚饭晚 × 第二天 HRV
    ("early_bed", "recovery", [1], None),     # 早睡 × 第二天恢复
]
LAG_WORD = {(0,): "的晚上", (1,): "的第二天", (1, 2, 3): "之后的 3 天"}


def option_for(key: str, fword: str, better: bool) -> str:
    """这一点能做的事（≤ 20 字；里面的钟点都来自行为说法本身，候选里找得到）。"""
    if key.startswith("proj:"):
        name = fword.replace("做了", "")
        return (f"{name}每天都做，试两周" if better else f"{name}换个时间，试两周")[:20]
    table = {
        "train": ("练的那天照常练，试两周", "练的那天晚上早点收"),
        "away": ("外宿后照常安排", "外宿后 3 天换轻一点的安排"),
        "drive_long": ("开车久的那天照常", "开车久的那天早点上床"),
        "late_dinner": ("晚饭照常", "晚饭提前到 20:30 前，试两周"),
        "early_bed": ("23:30 前睡着，试两周", "睡觉时间先不动"),
    }
    good, bad = table.get(key, (f"多{fword}，试两周", f"少{fword}，试两周"))
    return (good if better else bad)[:20]


def _groups(feat: dict[date, bool], out: dict[date, float], lags: list[int]) -> tuple[list, list]:
    """A = 行为之后那几天的结果；B = 前面那几天都确定「没有」的日子。行为缺数据的天两边都不进。"""
    a, b = [], []
    for x, v in out.items():
        src = [x - timedelta(days=l) for l in lags]
        known = [feat.get(s) for s in src]
        if any(k is True for k in known):
            a.append((x, v))
        elif all(k is False for k in known):
            b.append((x, v))
    return a, b


def _proj_board(data, key: str) -> str | None:
    pid = key.split(":", 1)[1]
    p = next((p for p in data.projects() if p["id"] == pid), None)
    return p.get("board") if p else None


def pair_candidates(data, daily: Daily | None = None) -> list[dict]:
    daily = daily or Daily(data)
    feats = daily.features()
    outs: dict[str, dict[date, float]] = {}
    res = []
    for prefix, oname, lags, board in PAIRS:
        if oname not in outs:
            outs[oname] = {d: v for d, v in daily.outcome(oname).items() if data.since <= d < data.today}
        out = outs[oname]
        if len(out) < MIN_DAYS:
            continue
        label, unit, nd, min_abs, up = OUTCOMES[oname]
        sd = statistics.pstdev(out.values()) if len(out) > 1 else 0
        for key, (fword, feat) in feats.items():
            if not (key == prefix or (prefix.endswith(":") and key.startswith(prefix))):
                continue
            if board and key.startswith("proj:") and _proj_board(data, key) != board:
                continue
            a, b = _groups(feat, out, lags)
            if len(a) < MIN_GROUP or len(b) < MIN_GROUP:
                continue
            ma, mb = statistics.fmean(v for _, v in a), statistics.fmean(v for _, v in b)
            diff = ma - mb
            if abs(diff) < max(min_abs, 0.5 * sd):
                continue
            better = (diff > 0) == up
            fmt = (lambda v: f"{round(v, nd):g}") if nd else (lambda v: f"{int(round(v))}")
            when = fword + LAG_WORD.get(tuple(lags), "之后")
            other = "其他日子" if lags != [0] else "没有的晚上"
            fact = (f"{when}（{len(a)} 次）{label}平均 {fmt(ma)}{unit}，{other}（{len(b)} 次）{fmt(mb)}{unit}，"
                    f"差 {fmt(abs(diff))}{unit}，大过平时的波动")
            option = option_for(key, fword, better)
            dmin = min(d for d, _ in a + b)
            dmax = max(d for d, _ in a + b)
            res.append({
                "type": "cross_pair", "key": f"cross-{key.replace(':', '-')}-{oname}-{''.join(map(str, lags))}",
                "subject": f"feature:{key}", "label": f"{fword} × {label}", "feature": key, "outcome": oname,
                "numbers": {"n_a": len(a), "avg_a": round(ma, nd), "n_b": len(b), "avg_b": round(mb, nd),
                            "diff": round(abs(diff), nd), "unit": unit},
                "facts": [fact], "sample": len(a) + len(b), "low_cost": True,
                "range": [dmin.isoformat(), dmax.isoformat()], "action": {"kind": "suggest"},
                "option": option, "better": better,
                "split": {"rows": [
                    {"label": ("做了" if key.startswith("proj:") else fword)[:6] if lags == [0] else "之后",
                     "text": fmt(ma), "unit": unit, "frac": None, "hi": True},
                    {"label": "没做" if key.startswith("proj:") else "其他", "text": fmt(mb), "unit": unit,
                     "frac": None, "hi": False}], "caption": f"{label} · {_md(dmin)}–{_md(dmax)}"},
                "dotstrip": _strip(daily, feat, out, lags, fword, label, up),
            })
    for c in res:                                         # 柱子长短：两组按同一个比例画（从 0 起）
        rows = c["split"]["rows"]
        top = max(float(r["text"]) for r in rows) or 1
        for r in rows:
            r["frac"] = round(float(r["text"]) / top, 3) if top > 0 else 0
    return res


def _strip(daily: Daily, feat, out, lags, fword: str, label: str, up: bool) -> dict:
    """每天一点：实心 = 那天有这个行为；下面一道 = 结果好过自己的中位数（「之后」那几天按行为那天算）。"""
    med = statistics.median(out.values()) if out else 0
    items = []
    for d in daily.days:
        later = [out.get(d + timedelta(days=l)) for l in lags]
        later = [v for v in later if v is not None]
        good = bool(later) and ((statistics.fmean(later) > med) == up)
        items.append({"label": _md(d), "on": bool(feat.get(d)), "hi": good})
    return {"items": items, "legend": {"on": fword, "hi": f"{label}好过平时"},
            "caption": f"近 {len(items)} 天"}


# ---------------------------------------------------------------- 平台期
def plateau_candidates(data, daily: Daily | None = None) -> list[dict]:
    from .insight import ACT_KINDS, METRIC_LABEL
    res = []
    for p in data.projects():
        if p.get("status") != "active":
            continue
        try:
            start = date.fromisoformat(p["start"])
        except (KeyError, ValueError):
            continue
        if (data.today - start).days < 21:
            continue
        ts = [t for t in data.todos() if t.get("project") == p["id"] and t.get("kind") in ACT_KINDS
              and (data.today - timedelta(days=21)).isoformat() <= t["date"] < data.today.isoformat()]
        if len(ts) < 10 or sum(t.get("status") == "done" for t in ts) / len(ts) < 0.7:
            continue
        metric = p.get("metric") if p.get("metric") in METRIC_LABEL else \
            {"sleep": "sleep", "stress": "hrv", "sport": "recovery"}.get(p.get("board"))
        if not metric:
            continue
        ser = data.metric(metric)
        base = [v for d, v in ser.items() if start - timedelta(days=14) <= d < start]
        early = [v for d, v in ser.items() if start + timedelta(days=7) <= d < start + timedelta(days=14)]
        last = [v for d, v in ser.items() if data.today - timedelta(days=7) <= d < data.today]
        prev = [v for d, v in ser.items() if data.today - timedelta(days=14) <= d < data.today - timedelta(days=7)]
        if min(len(base), len(early), len(last), len(prev)) < 4:
            continue
        sd = statistics.pstdev(base)
        b, e, l, pv = (statistics.fmean(x) for x in (base, early, last, prev))
        up = metric != "resting_hr"
        if sd <= 0 or ((e - b) * (1 if up else -1)) < 0.5 * sd:      # 一开始没变过：那是「没效果」，不是平台期
            continue
        if abs(l - pv) >= 0.25 * sd or ((l - e) * (1 if up else -1)) >= 0.5 * sd:   # 最近两周还在变
            continue
        lab, nd = METRIC_LABEL[metric]
        name = p.get("name") or p["id"]
        r = lambda v: round(v, nd) if nd else int(round(v))  # noqa: E731
        res.append({"type": "plateau", "key": f"plateau-{p['id']}", "subject": f"project:{p['id']}",
                    "board": p.get("board"), "project": p["id"], "label": name,
                    "numbers": {"before": r(b), "week2": r(e), "prev": r(pv), "recent": r(l)},
                    "facts": [f"「{name}」开始前两周{lab}平均 {r(b)}，第 2 周到 {r(e)}",
                              f"最近两周停在 {r(pv)}、{r(l)}，不再变（做到七成以上满 3 周）"],
                    "sample": len(ts), "low_cost": True,
                    "range": [(start - timedelta(days=14)).isoformat(), data.today.isoformat()],
                    "action": {"kind": "suggest"}, "option": f"「{name}」换下一步，试两周"[:20]})
    return res


# ---------------------------------------------------------------- 最好的那些天
BEST_OUTCOMES = ("recovery", "sleep_h")


def best_day_candidates(data, daily: Daily | None = None, taken: set | None = None) -> list[dict]:
    """结果最好的一成日子（至少 3 天）里，前一天 / 当晚的某个做法出现的比例是其他日子的 2 倍以上，且至少 3 次。
    taken：已经由分组对比报过的（行为, 结果），不重复报。"""
    daily = daily or Daily(data)
    feats = daily.features()
    taken = taken or set()
    res = []
    for oname in BEST_OUTCOMES:
        out = {d: v for d, v in daily.outcome(oname).items() if data.since <= d < data.today}
        if len(out) < MIN_DAYS:
            continue
        label, unit, nd, _min, up = OUTCOMES[oname]
        k = max(3, math.ceil(len(out) * 0.1))
        ranked = sorted(out.items(), key=lambda kv: kv[1], reverse=up)
        top = [d for d, _ in ranked[:k]]
        rest = [d for d, _ in ranked[k:]]
        lag = 1 if oname == "recovery" else 0          # 恢复看前一天 / 前一晚做了什么；睡眠看当天
        for key, (fword, feat) in feats.items():
            if (key, oname) in taken:
                continue
            t_known = [feat.get(d - timedelta(days=lag)) for d in top]
            r_known = [feat.get(d - timedelta(days=lag)) for d in rest]
            t_known = [x for x in t_known if x is not None]
            r_known = [x for x in r_known if x is not None]
            if len(t_known) < 3 or len(r_known) < MIN_GROUP:
                continue
            t_hit, r_hit = sum(t_known), sum(r_known)
            tr, rr = t_hit / len(t_known), r_hit / len(r_known)
            if t_hit < 3 or (rr > 0 and tr < 2 * rr):          # 至少出现 3 次：3 天里碰巧 2 天不算
                continue
            when = "前一天" if lag else "当天"
            res.append({"type": "best_days", "key": f"best-{oname}-{key.replace(':', '-')}",
                        "subject": f"feature:{key}", "label": f"{label}最好的日子 × {fword}", "feature": key,
                        "outcome": oname,
                        "numbers": {"top": len(t_known), "top_hit": t_hit, "top_pct": int(round(100 * tr)),
                                    "rest": len(r_known), "rest_pct": int(round(100 * rr))},
                        "facts": [f"{label}最好的 {len(t_known)} 天里，有 {t_hit} 天{when}{fword}；"
                                  f"其他 {len(r_known)} 天里只有 {int(round(100 * rr))}%"],
                        "sample": len(t_known) + len(r_known), "low_cost": True,
                        "range": [min(out).isoformat(), max(out).isoformat()], "action": {"kind": "suggest"},
                        "option": option_for(key, fword, True),
                        "dotstrip": {"items": [{"label": _md(d), "on": bool(feat.get(d - timedelta(days=lag))),
                                                "hi": d in top} for d in daily.days],
                                     "legend": {"on": f"{when}{fword}", "hi": f"{label}最好的日子"},
                                     "caption": f"近 {len(daily.days)} 天"}})
    return res


# ---------------------------------------------------------------- 对话主题
def topic_candidates(data) -> list[dict]:
    from . import journal
    from .insight import TOPICS
    cut = (data.today - timedelta(days=14)).isoformat()
    days: dict[tuple[str, str], set[str]] = {}
    for e in journal.read(data.cfg, TOPICS):
        if e.get("kind") in ("body", "concern") and cut <= str(e.get("date") or "") < data.today.isoformat():
            days.setdefault((e["kind"], e["label"]), set()).add(e["date"])
    managed_text = json.dumps([{k: p.get(k) for k in ("name", "rules", "daily")} for p in data.projects()
                               if p.get("status") == "active"], ensure_ascii=False)
    managed_text += json.dumps([t.get("title") for t in data.todos() if str(t.get("date") or "") >= cut],
                               ensure_ascii=False)
    res = []
    for (kind, label), ds in days.items():
        if len(ds) < 3 or label in managed_text:
            continue
        dl = sorted(ds)
        facts = [f"两周里有 {len(dl)} 天提到「{label}」（{'、'.join(_md(date.fromisoformat(x)) for x in dl[:5])}），"
                 f"现在没有计划在管"]
        if kind == "body":
            facts.append("同一个地方反复不舒服，先记两周；一直不好就去看医生或康复师")
        res.append({"type": "topic_unmanaged", "key": f"topic-{kind}-{label}", "subject": f"topic:{label}",
                    "label": label, "numbers": {"days": len(dl)}, "facts": facts, "sample": len(dl),
                    "low_cost": True, "range": [dl[0], dl[-1]], "action": {"kind": "suggest"},
                    "option": (f"「{label}」先记两周" if kind == "body" else f"给「{label}」排个方案")[:20]})
    return res


def candidates(data) -> list[dict]:
    """二期全部候选。分组对比报过的（行为, 结果）不再从「最好的那些天」重复报。"""
    daily = Daily(data)
    pairs = pair_candidates(data, daily)
    taken = {(c["feature"], c["outcome"]) for c in pairs}
    out = pairs + plateau_candidates(data, daily) + best_day_candidates(data, daily, taken) + topic_candidates(data)
    for c in out:                                   # 行为是某个项目：记上项目和板块（采纳 = 确认了改这个项目的 plan）
        f = str(c.get("feature") or "")
        if f.startswith("proj:") and not c.get("project"):
            pid = f.split(":", 1)[1]
            p = next((p for p in data.projects() if p["id"] == pid), None)
            c["project"] = pid
            if p:
                c["board"] = p.get("board")
    return out


def card_data(c: dict, field: str) -> Any:
    if field in ("split", "dotstrip") and c.get(field):
        return c[field]
    raise KeyError(f"这个候选没有 {field} 数据")
