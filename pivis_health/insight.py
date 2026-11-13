"""洞察（build 49，一期）：服务器每 3 天扫一次，算出带样本量的候选；P-Health 挑最多 3 条写成一段话，
校验过了存着待发；Psir 点「聊聊」（或点推送）才发进主对话。

一期只算两类：
  ① 闭环断在哪：发现了问题 3 天没给建议 / 同类建议被拒 2 次 / 接受了但两周做到不到一半 / 做到七成满 3 周指标没变
  ② 督促管不管用：某个提醒至少 5 次里 30 分钟内开始的不到四成 / 连续 3 次没理 / 睡不够或外宿后完成率低 30 个点
外加到期小实验（learn.exp.*）的结算。③ 交叉、④ 没注意到的留到二期（数据先攒：场景标签、对话主题）。

规则见需求文档「洞察规则」：五条准入、门槛、挑法、4 周不重复、被否 4 周不说。数字都由这里算，
P-Health 只负责挑和写；那段话里的数字在候选里找不到、有因果词、超过 3 点，整段不发。

文件（都在数据目录，不进仓库）：
  insight_state.json       上次扫描、每次扫描成立的结论（连续两次 = 确认）、说过什么、连续几期没聊
  insight_candidates.json  候选（画布卡 insight:<id>.<字段> 绑定从这里取数）
  insight_pending.json     这一期待发的那段话
  insight_runs.jsonl       每次扫描 / 写稿 / 发出的记录
"""
from __future__ import annotations

import json
import os
import re
import statistics
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import journal
from .clock import day_of as _day_of

STATE = "insight_state.json"
CANDS = "insight_candidates.json"
PENDING = "insight_pending.json"
RUNS = "insight_runs.jsonl"
TOPICS = "chat_topics.jsonl"

WINDOW = 28              # 看最近 4 周
EVERY_DAYS = 3           # 每 3 天扫一次
REPEAT_DAYS = 28         # 同一结论 4 周内不重复
MAX_POINTS = 3
STOP_PUSH_AFTER = 3      # 连续三期没聊：之后只留浮条，不再推送
COMPOSE_ROUNDS = 4       # 写稿：第一稿 + 最多纠正 3 轮

BOARD_LABEL = {"sleep": "休息", "sport": "运动", "stress": "压力", "life": "日常"}
ACT_KINDS = ("done", "follow", "timer", "count", "checklist", "fields", "photo", "confirm", "steps", "measure")
DONE = ("done",)
OPEN_OPS = ("user_start", "user_done", "user_inc", "user_check", "auto_done")
CAUSAL = ("导致", "因为", "造成", "引起", "害得", "使得", "由于", "所以", "因此", "致使", "诱发")
NO_SAY = ("诊断", "患有", "疾病", "综合征", "抑郁症", "焦虑症", "失眠症", "处方", "用药", "吃药", "药量", "剂量",
          "自律", "坚持住", "要努力", "你应该自觉")
SOFT = ("可能", "看起来", "好像", "似乎", "初步")
TIER = {"exp_result": 0, "followup": 0, "loop_no_advice": 1, "loop_rejected": 2, "loop_low_adherence": 2,
        "loop_no_effect": 2, "remind_late": 3, "remind_ignored": 3, "remind_condition": 3,
        "cross_pair": 4, "plateau": 4, "best_days": 4, "topic_unmanaged": 4}
FEEDBACK_DAYS = 3        # 点开后 3 天内看 Psir 有没有采纳（点选项、确认 plan、开实验、没改回）
WEIGHT_DAYS = 56         # 权重看最近 8 周的反应
CLASS_REJECT = 2         # 同一类 4 周内被否 2 次：这一类 4 周内都不说
FOLLOWUP_WAIT = 14       # 采纳后最多等 14 天出结果（数据不够也照实说）


class InsightError(ValueError):
    pass


class ComposeFailed(InsightError):
    def __init__(self, msg: str, attempts: list[dict]) -> None:
        super().__init__(msg)
        self.attempts = attempts


# ---------------------------------------------------------------- 小工具
def _p(cfg, name: str) -> Path:
    return Path(cfg.data_dir) / name


def _load(cfg, name: str, default):
    try:
        return json.loads(_p(cfg, name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _save(cfg, name: str, obj) -> None:
    path = _p(cfg, name)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _hm(s: str | None) -> int | None:
    m = re.match(r"^(\d{1,2}):(\d{2})", str(s or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _fmt_hm(minutes: int) -> str:
    minutes %= 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _md(d: date | str) -> str:
    d = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
    return f"{d.month}/{d.day}"


def _naive(s: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _pct(a: int, b: int) -> int:
    return int(round(100 * a / b)) if b else 0


def _cn_count(n: int) -> str:
    return {1: "一", 2: "两", 3: "三"}.get(n, str(n))


def _slug(*parts: Any) -> str:
    s = "-".join(str(p) for p in parts if p not in (None, ""))
    return re.sub(r"[^A-Za-z0-9_\-一-鿿]+", "-", s).strip("-")[:80]


# ---------------------------------------------------------------- 读数据
class Data:
    """引擎要的数据，一次读好。now 用 tools._now()（模拟回放时是模拟时钟）。"""

    def __init__(self, tools, now: datetime | None = None) -> None:
        self.tools = tools
        self.cfg = tools.cfg
        self.now = (now or tools._now()).replace(tzinfo=None)
        self.today = self.now.date()
        self.since = self.today - timedelta(days=WINDOW)
        self._todos: list[dict] | None = None
        self._log: dict[str, list[dict]] | None = None
        self._nights: dict[date, dict] | None = None
        self._days: dict[date, dict] | None = None

    # ---- 待办（当前 + 归档），按 id 去重
    def todos(self) -> list[dict]:
        if self._todos is None:
            seen: dict[str, dict] = {}
            arch = _p(self.cfg, "todos_archive.jsonl")
            if arch.exists():
                for line in arch.read_text(encoding="utf-8").splitlines():
                    try:
                        t = json.loads(line)
                        seen[t["id"]] = t
                    except Exception:  # noqa: BLE001
                        continue
            from .todos import TodoStore
            seen.update(TodoStore(self.cfg).snapshot().get("todos") or {})
            self._todos = [t for t in seen.values() if str(t.get("date") or "") >= self.since.isoformat()]
        return self._todos

    def projects(self) -> list[dict]:
        from .todos import TodoStore
        return TodoStore(self.cfg).projects()

    def ops(self, todo_id: str) -> list[dict]:
        if self._log is None:
            self._log = {}
            for e in journal.read(self.cfg, journal.TODOS, since=self.since.isoformat()):
                if e.get("id"):
                    self._log.setdefault(e["id"], []).append(e)
        return self._log.get(todo_id, [])

    # ---- 身体数据：WHOOP 存档 + 当前快照（按夜的睡眠、按天的恢复 / HRV）
    def _whoop(self) -> dict:
        from . import whoop as w
        from .whoop_sync import load_archive
        cols = load_archive(self.cfg, since=(self.since - timedelta(days=21)).isoformat())
        snap = w.load_snapshot(self.cfg.whoop_snapshot) or {}
        merged = {}
        for n in ("recovery", "sleep", "cycle", "workout"):
            by = {str(r.get("id") if r.get("id") is not None else r.get("cycle_id")): r for r in cols.get(n) or []}
            for r in snap.get(n) or []:
                by[str(r.get("id") if r.get("id") is not None else r.get("cycle_id"))] = r
            merged[n] = list(by.values())
        return merged

    def nights(self) -> dict[date, dict]:
        if self._nights is None:
            from . import whoop as w
            try:
                self._nights = w.sleep_by_night(self._whoop(), self.cfg.timezone)
            except Exception:  # noqa: BLE001
                self._nights = {}
        return self._nights

    def days(self) -> dict[date, dict]:
        if self._days is None:
            from . import whoop as w
            try:
                self._days = w.recovery_by_day(self._whoop(), self.cfg.timezone)
            except Exception:  # noqa: BLE001
                self._days = {}
        return self._days

    def metric(self, name: str) -> dict[date, float]:
        """sleep = 每晚睡着几小时（按夜）；recovery / hrv / resting_hr = 按醒来那天。缺的天不出现（不当 0）。"""
        out: dict[date, float] = {}
        if name == "sleep":
            for d, v in self.nights().items():
                if isinstance(v.get("asleep_h"), (int, float)) and v["asleep_h"] > 0:
                    out[d] = float(v["asleep_h"])
            return out
        key = {"recovery": "recovery_score", "hrv": "hrv_rmssd", "resting_hr": "resting_heart_rate"}.get(name)
        if not key:
            return out
        for d, v in self.days().items():
            if isinstance(v.get(key), (int, float)):
                out[d] = float(v[key])
        return out

    def user_texts(self, since: str) -> list[tuple[str, str]]:
        """主对话里 Psir 说的话（时间, 原话），since 之后的。点选项卡会把那一项的文字作为 Psir 的消息发出。"""
        from . import dsh_chat
        try:
            msgs = dsh_chat.read_messages(0, None, "")
        except Exception:  # noqa: BLE001
            return []
        return [(str(m.get("time") or "")[:19], str(m.get("text") or "")) for m in msgs
                if m.get("role") == "me" and str(m.get("time") or "")[:19] >= since]

    def actions(self) -> list[dict]:
        return list(journal.read(self.cfg, journal.ACTIONS, since=(self.since - timedelta(days=3)).isoformat()))

    def corrections(self) -> list[dict]:
        from .agent_context import AgentContextStore
        cut = (self.today - timedelta(days=REPEAT_DAYS)).isoformat()
        return [e for e in AgentContextStore(self.cfg).history()
                if str(e.get("scope") or "").startswith("correction.insight.") and str(e.get("recorded_at") or "") >= cut]

    def experiments(self) -> list[dict]:
        """进行中的小实验：learn.exp 的 items（growth-memory 的格式），每项 {id, change, start, days, metric, result}。
        metric 写了引擎才能结算：project:<项目 id>（完成率）或 sleep / hrv / recovery / resting_hr。"""
        from .agent_context import AgentContextStore
        out = []
        for e in AgentContextStore(self.cfg).snapshot()["entries"]:
            scope = str(e.get("scope") or "")
            if scope != "learn.exp" and not scope.startswith("learn.exp."):
                continue
            p = e.get("payload") or {}
            for it in (p.get("items") if isinstance(p.get("items"), list) else [p]):
                if not isinstance(it, dict) or it.get("result") not in (None, ""):
                    continue
                try:
                    start = date.fromisoformat(str(it.get("start"))[:10])
                    end = date.fromisoformat(str(it["end"])[:10]) if it.get("end") else \
                        start + timedelta(days=int(it.get("days") or 14) - 1)
                except (ValueError, TypeError):
                    continue
                out.append({"id": str(it.get("id") or scope), "label": str(it.get("change") or it.get("rule") or "")[:30],
                            "start": start, "end": end, "metric": str(it.get("metric") or "")})
        return out


# ---------------------------------------------------------------- 一张卡什么时候算「动手了」
def _due(t: dict) -> datetime | None:
    from .todos import due_at
    return due_at(t["date"], t["when"]) if t.get("when") else None


def acted_at(data: Data, t: dict) -> datetime | None:
    """Psir 第一次对这张卡动手的时刻：开始 / 打勾 / 计数 / 自动识别；只有做完时间时，用做完减时长估开始。"""
    ops = [e for e in data.ops(t["id"]) if e.get("op") in OPEN_OPS]
    if ops:
        first = min(ops, key=lambda e: str(e.get("at")))
        at = _naive(first.get("at"))
        if first.get("op") == "user_done" and t.get("duration_min"):
            at = at - timedelta(minutes=float(t["duration_min"])) if at else None
        if first.get("op") == "auto_done" and (t.get("record") or {}).get("bedtime"):
            at = _bedtime_at(t) or at
        return at
    rec = t.get("record") or {}
    if rec.get("bedtime"):
        return _bedtime_at(t)
    if rec.get("started_at"):
        return _naive(rec["started_at"])
    if t.get("status") in DONE and rec.get("at"):
        at = _naive(rec["at"])
        if at and t.get("duration_min"):
            at -= timedelta(minutes=float(t["duration_min"]))
        return at
    return None


def _bedtime_at(t: dict) -> datetime | None:
    hm = _hm((t.get("record") or {}).get("bedtime"))
    due = _due(t)
    if hm is None or due is None:
        return None
    at = datetime.combine(due.date(), datetime.min.time()) + timedelta(minutes=hm)
    if at < due - timedelta(hours=12):          # 过了半夜才睡：算第二天凌晨
        at += timedelta(days=1)
    return at


# ---------------------------------------------------------------- ② 督促
def _groups(data: Data, min_n: int = 3) -> dict[str, list[dict]]:
    """「同一个提醒」：项目里同一个模板（项目 id + key）；不在项目里的，同一标题出现 5 次以上的也算一组。"""
    out: dict[str, list[dict]] = {}
    for t in data.todos():
        if not t.get("when") or t.get("kind") not in ACT_KINDS or t.get("status") == "processing":
            continue
        due = _due(t)
        if due is None or due > data.now - timedelta(minutes=60):       # 还没过点（留一小时）不算
            continue
        if t.get("project"):
            key = str(t["id"])[len(f"{t['project']}-{t['date']}-"):] if str(t["id"]).startswith(f"{t['project']}-{t['date']}-") else t.get("title")
            gk = f"{t['project']}:{key}"
        else:
            gk = f"title:{t.get('board')}:{t.get('title')}"
        out.setdefault(gk, []).append(t)
    for gk, ts in out.items():
        ts.sort(key=lambda t: (t["date"], t.get("when") or ""))
        cur = ts[-1].get("when")
        out[gk] = [t for t in ts if t.get("when") == cur]     # 提醒时间改过：只看改完以后的
    return {k: v for k, v in out.items() if len(v) >= min_n}


def _group_name(data: Data, gk: str, ts: list[dict]) -> tuple[str, dict | None]:
    pid = gk.split(":", 1)[0] if not gk.startswith("title:") else None
    proj = next((p for p in data.projects() if p["id"] == pid), None) if pid else None
    return str(ts[-1].get("title") or ""), proj


def reminder_candidates(data: Data) -> list[dict]:
    out = []
    nights = data.metric("sleep")
    from . import scene
    sc = scene.load(data.cfg)
    for gk, ts in _groups(data).items():
        title, proj = _group_name(data, gk, ts)
        if proj is not None and proj.get("status") != "active":
            continue
        when = ts[-1]["when"]
        rows = []
        for t in ts:
            due = _due(t)
            at = acted_at(data, t)
            off = int((at - due).total_seconds() // 60) if at and due else None
            rows.append({"t": t, "due": due, "off": off, "done": t.get("status") in DONE or at is not None,
                         "touched": bool(data.ops(t["id"])) or t.get("status") in ("done", "skipped", "in_progress")})
        subject = f"project:{proj['id']}" if proj else f"todo:{title}"
        base = {"subject": subject, "board": ts[-1].get("board"), "project": proj["id"] if proj else None,
                "group": gk, "label": title, "range": [ts[0]["date"], ts[-1]["date"]]}
        # a. 30 分钟内开始的不到四成（至少 5 次）。做了但不知道几点做的（老数据没有操作记录）不算进来
        known = [r for r in rows if r["off"] is not None or not r["done"]]
        n = len(known)
        on_time = sum(1 for r in known if r["off"] is not None and r["off"] <= 30)
        if n >= 5 and on_time / n < 0.4:
            late = sorted(r["off"] for r in rows if r["off"] is not None and r["off"] > 30)
            cand = {**base, "type": "remind_late", "key": _slug("remind-late", gk),
                    "numbers": {"n": n, "on_time": on_time, "rate": _pct(on_time, n), "remind": when},
                    "facts": [f"「{title}」{when} 提醒，近 {n} 次里 {on_time} 次在提醒后 30 分钟内开始"],
                    "sample": n, "low_cost": True}
            starts = [due_min(r) for r in rows if r["off"] is not None]
            cand["response"] = _response(when, starts, n, ts[0]["date"], ts[-1]["date"])
            if len(late) >= 3:
                med = int(statistics.median(late))
                to_min = (_hm(when) + med) // 10 * 10
                cand["numbers"]["late_n"] = len(late)
                cand["numbers"]["typical"] = _fmt_hm(_hm(when) + med)
                cand["facts"].append(f"其余多在 {_fmt_hm(_hm(when) + med)} 前后才开始（{len(late)} 次）")
                if proj and to_min < 1440 and abs(to_min - _hm(when)) >= 20:
                    to = _fmt_hm(to_min)
                    cand["numbers"]["to"] = to
                    cand["action"] = {"kind": "move_reminder", "project": proj["id"], "key": gk.split(":", 1)[1],
                                      "from": when, "to": to}
                    cand["facts"].append(f"建议：提醒挪到 {to}（P-Health 先改，Psir 说一句就改回）")
            cand.setdefault("action", {"kind": "suggest"})
            cand["option"] = f"「{title}」换个时间"
            out.append(cand)
        # b. 连续 3 次没理（最近 3 次都没动、也没说算了）
        last3 = rows[-3:]
        if len(last3) == 3 and not any(r["touched"] or r["done"] for r in last3):
            out.append({**base, "type": "remind_ignored", "key": _slug("remind-ignored", gk),
                        "numbers": {"n": 3, "remind": when, "from": _md(last3[0]["t"]["date"]), "to_day": _md(last3[-1]["t"]["date"])},
                        "facts": [f"「{title}」{when} 的提醒，{_md(last3[0]['t']['date'])}–{_md(last3[-1]['t']['date'])} 连续 3 次没动"],
                        "sample": 3, "low_cost": False, "action": {"kind": "suggest"},
                        "option": f"停掉「{title}」的提醒"})
        # c. 某种情况下完成率比平时低 30 个点以上（两组各至少 5 次）
        for cond, label, test in (
                ("short_sleep", "前一晚睡不到 6 小时", lambda d: (nights.get(d - timedelta(days=1)) or 99) < 6
                 if (d - timedelta(days=1)) in nights else None),
                ("away", "在外过夜后", lambda d: bool((sc.get((d - timedelta(days=1)).isoformat()) or {}).get("away_night"))
                 if sc else None)):
            a = [r for r in rows if test(r["due"].date()) is True]
            b = [r for r in rows if test(r["due"].date()) is False]
            if len(a) >= 5 and len(b) >= 5:
                ra, rb = _pct(sum(r["done"] for r in a), len(a)), _pct(sum(r["done"] for r in b), len(b))
                if rb - ra >= 30:
                    out.append({**base, "type": "remind_condition", "key": _slug("remind-cond", cond, gk),
                                "numbers": {"n_cond": len(a), "rate_cond": ra, "n_other": len(b), "rate_other": rb,
                                            "gap": rb - ra},
                                "facts": [f"「{title}」{label}的 {len(a)} 次做到 {ra}%，其他 {len(b)} 次做到 {rb}%"],
                                "sample": len(a) + len(b), "low_cost": True, "action": {"kind": "suggest"},
                                "option": f"{label}「{title}」换短版"[:20], "condition": label})
    return out


def due_min(r: dict) -> int:
    """开始的时刻，和提醒在同一条分钟轴上（过了半夜就超过 1440）。"""
    return r["due"].hour * 60 + r["due"].minute + r["off"]


def _response(when: str, starts: list[int], n: int, d0: str, d1: str) -> dict:
    """画布零件 response：提醒线 + 每次开始一个点。分钟都在一条连续的轴上。"""
    remind = _hm(when)
    lo = min([remind] + starts) - 20
    hi = max([remind] + starts) + 20
    start = lo // 60 * 60
    span = max(90, ((hi - start) + 59) // 60 * 60)
    ticks = [{"at": m, "label": _fmt_hm(m)} for m in range(start, start + span + 1, 60)]
    return {"start": start, "span": span, "remind": remind, "points": sorted(starts), "ticks": ticks, "label": "提醒",
            "caption": f"{n} 次 · {_md(d0)}–{_md(d1)}"}


# ---------------------------------------------------------------- ① 闭环
def loop_candidates(data: Data) -> list[dict]:
    out = []
    acts = data.actions()
    # a. 发现了问题，3 天内没给任何建议
    seen: set[str] = set()
    for d in sorted((a for a in acts if a.get("kind") == "discover"), key=lambda a: str(a.get("at")), reverse=True):
        at = _naive(d.get("at"))
        if not at or at.date() < data.since or at > data.now - timedelta(days=3):
            continue
        board = d.get("board")
        k = _slug("loop-no-advice", board, d.get("topic"))
        if k in seen:
            continue
        seen.add(k)
        followed = any(a.get("kind") in ("suggest", "plan") and a.get("board") == board
                       and at <= (_naive(a.get("at")) or at - timedelta(days=1)) <= at + timedelta(days=3) for a in acts)
        if followed:
            continue
        days_since = (data.now - at).days
        topic = TOPIC_CN.get(str(d.get("topic") or ""), str(d.get("topic") or ""))
        out.append({"type": "loop_no_advice", "key": k, "subject": f"board:{board}", "board": board,
                    "label": f"{BOARD_LABEL.get(board, board)}页的{topic}".strip(),
                    "numbers": {"day": _md(at.date()), "days": days_since},
                    "facts": [f"{_md(at.date())} {BOARD_LABEL.get(board, board)}页主卡变成「{'需要处理' if 'act' in str(d.get('detail')) else '留意'}」"
                              f"（{topic}），之后 3 天 P-Health 没给任何建议，到现在 {days_since} 天"],
                    "sample": 1, "low_cost": True, "range": [at.date().isoformat(), data.today.isoformat()],
                    "action": {"kind": "suggest"}, "option": f"给{BOARD_LABEL.get(board, board)}出个方案",
                    "own": True})
    # b. 同类建议被拒 2 次（提议卡被「算了 / 不要」）
    rejected: dict[str, list[dict]] = {}
    for t in data.todos():
        if t.get("kind") == "proposal" and t.get("source") in (None, "agent") and t.get("status") == "skipped":
            rejected.setdefault(t.get("board") or "life", []).append(t)
    for board, ts in rejected.items():
        if len(ts) >= 2:
            ts.sort(key=lambda t: t["date"])
            out.append({"type": "loop_rejected", "key": _slug("loop-rejected", board), "subject": f"board:{board}",
                        "board": board, "label": f"{BOARD_LABEL.get(board, board)}的建议",
                        "numbers": {"n": len(ts)},
                        "facts": [f"近 4 周{BOARD_LABEL.get(board, board)}的提议被拒了 {len(ts)} 次："
                                  + "、".join(f"{_md(t['date'])}「{t.get('title')}」" for t in ts[-3:])],
                        "sample": len(ts), "low_cost": True, "range": [ts[0]["date"], ts[-1]["date"]],
                        "action": {"kind": "suggest"}, "option": f"{BOARD_LABEL.get(board, board)}换个方向"})
    # c / d. 项目：接受了做不到一半；做到七成满 3 周指标没变
    for p in data.projects():
        if p.get("status") != "active":
            continue
        try:
            start = date.fromisoformat(p["start"])
        except (KeyError, ValueError):
            continue
        ts = [t for t in data.todos() if t.get("project") == p["id"] and t.get("kind") in ACT_KINDS
              and t["date"] < data.today.isoformat()]

        def rate(days: int) -> tuple[int, int]:
            cut = (data.today - timedelta(days=days)).isoformat()
            xs = [t for t in ts if t["date"] >= cut]
            return sum(1 for t in xs if t.get("status") in DONE), len(xs)

        name = p.get("name") or p["id"]
        if (data.today - start).days >= 14:
            done, n = rate(14)
            if n >= 7 and done / n < 0.5:
                out.append({"type": "loop_low_adherence", "key": _slug("loop-low", p["id"]), "subject": f"project:{p['id']}",
                            "board": p.get("board"), "project": p["id"], "label": name,
                            "numbers": {"done": done, "n": n, "rate": _pct(done, n)},
                            "facts": [f"「{name}」近两周 {n} 次里做到 {done} 次（{_pct(done, n)}%）"],
                            "sample": n, "low_cost": True,
                            "range": [(data.today - timedelta(days=14)).isoformat(), data.today.isoformat()],
                            "action": {"kind": "suggest"}, "option": f"「{name}」减成容易的版本"[:20]})
        if (data.today - start).days >= 21:
            done, n = rate(21)
            metric = p.get("metric") if p.get("metric") in ("sleep", "hrv", "recovery", "resting_hr") else \
                {"sleep": "sleep", "stress": "hrv", "sport": "recovery"}.get(p.get("board"))
            if metric and n >= 10 and done / n >= 0.7:
                ser = data.metric(metric)
                base = [v for d, v in ser.items() if start - timedelta(days=14) <= d < start]
                recent = [v for d, v in ser.items() if data.today - timedelta(days=7) <= d < data.today]
                if len(base) >= 5 and len(recent) >= 5:
                    sd = statistics.pstdev(base)
                    b, r = statistics.fmean(base), statistics.fmean(recent)
                    if sd > 0 and abs(r - b) < 0.5 * sd:
                        lab, nd = METRIC_LABEL[metric]
                        out.append({"type": "loop_no_effect", "key": _slug("loop-no-effect", p["id"]),
                                    "subject": f"project:{p['id']}", "board": p.get("board"), "project": p["id"],
                                    "label": name,
                                    "numbers": {"done": done, "n": n, "rate": _pct(done, n), "before": round(b, nd),
                                                "recent": round(r, nd), "metric": lab},
                                    "facts": [f"「{name}」近 3 周做到 {_pct(done, n)}%（{n} 次里 {done} 次）",
                                              f"{lab}开始前两周平均 {round(b, nd)}，最近一周平均 {round(r, nd)}，在自己平时的波动以内"],
                                    "sample": n, "low_cost": True,
                                    "range": [(start - timedelta(days=14)).isoformat(), data.today.isoformat()],
                                    "action": {"kind": "suggest"}, "option": f"「{name}」换个方向"[:20]})
    return out


TOPIC_CN = {"hrv": "HRV", "sleep": "睡眠", "sleep_debt": "睡眠债", "recovery": "恢复", "resting_hr": "静息心率",
            "resp_rate": "呼吸频率", "steps": "步数", "weight": "体重", "strain": "负荷"}
METRIC_LABEL = {"sleep": ("睡着时长（小时）", 1), "hrv": ("HRV（ms）", 0), "recovery": ("恢复分数", 0),
                "resting_hr": ("静息心率", 0)}


# ---------------------------------------------------------------- 到期小实验
def experiment_candidates(data: Data, state: dict) -> list[dict]:
    out = []
    settled = set(state.get("settled") or [])
    for e in data.experiments():
        scope, s, end, metric = e["id"], e["start"], e["end"], e["metric"]
        if end >= data.today or scope in settled:
            continue
        span = (end - s).days + 1
        label = e["label"] or scope
        if metric.startswith("project:"):
            pid = metric.split(":", 1)[1]
            ts = [t for t in data.todos() if t.get("project") == pid and t.get("kind") in ACT_KINDS]
            during = [t for t in ts if s.isoformat() <= t["date"] <= end.isoformat()]
            before = [t for t in ts if (s - timedelta(days=span)).isoformat() <= t["date"] < s.isoformat()]
            if len(during) < 5:
                continue
            a = _pct(sum(t.get("status") in DONE for t in during), len(during))
            b = _pct(sum(t.get("status") in DONE for t in before), len(before)) if len(before) >= 5 else None
            nums = {"during": a, "n": len(during), "start": _md(s), "end": _md(end)}
            fact = f"试的这 {span} 天（{_md(s)}–{_md(end)}）做到 {a}%（{len(during)} 次）"
            if b is not None:
                nums["before"] = b
                fact += f"，之前同样长的一段做到 {b}%"
        elif metric in METRIC_LABEL:
            ser = data.metric(metric)
            during = [v for d, v in ser.items() if s <= d <= end]
            before = [v for d, v in ser.items() if s - timedelta(days=span) <= d < s]
            if len(during) < 5:
                continue
            lab, nd = METRIC_LABEL[metric]
            nums = {"during": round(statistics.fmean(during), nd), "n": len(during), "start": _md(s), "end": _md(end)}
            fact = f"试的这 {span} 天（{_md(s)}–{_md(end)}）{lab}平均 {nums['during']}（{len(during)} 天）"
            if len(before) >= 5:
                nums["before"] = round(statistics.fmean(before), nd)
                fact += f"，之前同样长的一段平均 {nums['before']}"
        else:
            continue
        out.append({"type": "exp_result", "key": _slug("exp", scope), "subject": f"exp:{scope}", "label": label,
                    "numbers": nums, "facts": [f"小实验「{label}」到期", fact], "sample": nums["n"], "low_cost": True,
                    "range": [s.isoformat(), end.isoformat()], "action": {"kind": "suggest", "settle": scope},
                    "option": "按结果定下来", "experiment": scope})
    return out


# ---------------------------------------------------------------- 三期：反馈回流
def type_weights(state: dict, today: date) -> tuple[dict[str, float], set[str]]:
    """每一类洞察的权重 =（采纳 + 1）/（说过 + 2），看最近 8 周；同一类 4 周内被否 2 次的，这一类先不说。"""
    said: dict[str, int] = {}
    took: dict[str, int] = {}
    rej: dict[str, int] = {}
    cut8 = (today - timedelta(days=WEIGHT_DAYS)).isoformat()
    cut4 = (today - timedelta(days=REPEAT_DAYS)).isoformat()
    for f in state.get("feedback") or []:
        t, at, out = f.get("type"), str(f.get("at") or ""), f.get("outcome")
        if not t or out == "pending":
            continue
        if at >= cut8:
            said[t] = said.get(t, 0) + 1
            if out == "adopted":
                took[t] = took.get(t, 0) + 1
        if out == "rejected" and str(f.get("decided_at") or at) >= cut4:
            rej[t] = rej.get(t, 0) + 1
    weights = {t: (took.get(t, 0) + 1) / (n + 2) for t, n in said.items()}
    return weights, {t for t, n in rej.items() if n >= CLASS_REJECT}


def _fb_entry(c: dict, pid: str, at: str, outcome: str = "pending", option: str | None = None) -> dict:
    keep = ("type", "key", "topic", "subject", "project", "group", "feature", "outcome", "label", "board", "action")
    return {"period": pid, "at": at, "outcome": outcome, "option": option, "followup_done": False,
            "cand": {k: c.get(k) for k in keep if c.get(k) is not None}, "type": c.get("type"),
            "key": c.get("key"), "numbers": c.get("numbers"), "fb_ref": c.get("fb_ref")}


def _ctx_at(e: dict, cfg) -> str:
    """记忆条目的 recorded_at 是这台机器的本地时间（不带时区，实际是太平洋时间）：换成 Psir 那边的钟再比。"""
    raw = str(e.get("recorded_at") or "")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    from zoneinfo import ZoneInfo
    if dt.tzinfo is None:
        dt = dt.astimezone()                          # 按本机时区理解
    return dt.astimezone(ZoneInfo(cfg.timezone)).replace(tzinfo=None).isoformat(timespec="seconds")


def close_feedback(data: "Data", state: dict) -> list[dict]:
    """点开过的每一点：3 天里 Psir 有没有采纳。证据：点了这一点的选项、确认了改这个项目 / 板块的 plan、开了实验、
    先改后说的提醒没改回；否掉 = 记了 correction.insight.<topic>；「都先不动」或什么都没做 = 没理。"""
    changed = []
    fbs = state.get("feedback") or []
    pending = [f for f in fbs if f.get("outcome") == "pending"]
    if not pending:
        return changed
    from .agent_context import AgentContextStore
    hist = AgentContextStore(data.cfg).history()
    acts = data.actions()
    logs = list(journal.read(data.cfg, journal.TODOS, since=(data.since - timedelta(days=7)).isoformat()))
    for f in pending:
        start = _naive(f.get("at"))
        if not start:
            continue
        at = start.isoformat(timespec="seconds")              # 统一成不带时区的 Psir 那边的钟，和日志比
        end = start + timedelta(days=FEEDBACK_DAYS)
        c = f.get("cand") or {}
        topic = c.get("topic") or f.get("key")
        verdict = None
        if any(e.get("scope") == f"correction.insight.{topic}" and _ctx_at(e, data.cfg) >= at for e in hist):
            verdict = "rejected"
        else:
            act = c.get("action") or {}
            texts = data.user_texts(at)
            picked = f.get("option") and any(t.strip() == str(f["option"]).strip() for _, t in texts)
            planned = bool(c.get("project")) and any(
                a.get("kind") == "plan" and at <= str(a.get("at") or "") <= end.isoformat()
                and a.get("project") == c.get("project") and "洞察先改后说" not in str(a.get("detail") or "")
                for a in acts)
            moved_kept = False
            if act.get("kind") == "move_reminder" and f.get("applied"):
                reverted = any(e.get("op") == "project_set" and e.get("id") == act.get("project")
                               and str(e.get("at") or "") >= at
                               and any(d.get("key") == act.get("key") and d.get("when") == act.get("from")
                                       for d in e.get("daily") or []) for e in logs)
                moved_kept = not reverted
                if reverted:
                    verdict = "reverted"
            if verdict is None and (picked or planned or moved_kept):
                verdict = "adopted"
            if verdict is None and any(t.strip() == "都先不动" for _, t in texts):
                verdict = "ignored"
        if verdict is None and data.now >= end:
            verdict = "ignored"
        if verdict:
            f["outcome"] = verdict
            f["decided_at"] = data.now.isoformat(timespec="seconds")
            changed.append(f)
            if verdict == "rejected":
                _retire_learned(data.cfg, f)
    return changed


def followup_candidates(data: "Data", state: dict) -> list[dict]:
    """采纳过的行动，下一期出结果：提醒挪了以后当场做的比例、项目改了以后的完成率、某个做法开始以后的频率和指标。
    数据不够（< 2 次）先等，最多等 14 天，到时照实说。"""
    out = []
    for f in state.get("feedback") or []:
        if f.get("outcome") != "adopted" or f.get("followup_done"):
            continue
        c = f.get("cand") or {}
        since = _naive(f.get("decided_at") or f.get("at"))
        start = _naive(f.get("at"))
        if not since or not start:
            continue
        waited = (data.now - start).days
        typ = c.get("type") or ""
        act = c.get("action") or {}
        facts, numbers, sample = [], {}, 0
        if typ.startswith("remind") and c.get("group"):
            st = next((x for x in reminder_stats(data) if x["group"] == c["group"]), None)
            after = [r for r in (st or {}).get("rows", []) if r["date"] >= start.date().isoformat()]
            sample = len(after)
            on = sum(1 for r in after if r["on_time"])
            before = (f.get("numbers") or {})
            if sample >= 2 or waited >= FOLLOWUP_WAIT:
                how = f"提醒挪到 {act['to']} 以后" if act.get("kind") == "move_reminder" and act.get("to") else "改了以后"
                facts.append(f"「{c.get('label')}」{how}，{sample} 次里 {on} 次在 30 分钟内开始"
                             + (f"（之前 {before.get('n')} 次里 {before.get('on_time')} 次）" if before.get("n") else ""))
                numbers = {"n": sample, "on_time": on, "before_n": before.get("n"), "before_on": before.get("on_time"),
                           "to": act.get("to")}
        elif c.get("project"):
            pid = c["project"]
            ts = [t for t in data.todos() if t.get("project") == pid and t.get("kind") in ACT_KINDS
                  and t["date"] < data.today.isoformat()]
            after = [t for t in ts if t["date"] >= start.date().isoformat()]
            before = [t for t in ts if (start.date() - timedelta(days=14)).isoformat() <= t["date"] < start.date().isoformat()]
            sample = len(after)
            if sample >= 2 or waited >= FOLLOWUP_WAIT:
                a = _pct(sum(t.get("status") == "done" for t in after), len(after)) if after else 0
                b = _pct(sum(t.get("status") == "done" for t in before), len(before)) if before else None
                facts.append(f"「{c.get('label')}」改了以后 {sample} 次做到 {a}%" + (f"，之前两周 {b}%" if b is not None else ""))
                numbers = {"n": sample, "after": a, "before": b}
        elif c.get("feature"):
            from . import insight_cross
            daily = insight_cross.Daily(data)
            feats = daily.features()
            fword, feat = feats.get(c["feature"], (c.get("label"), {}))
            after = [v for d, v in feat.items() if d >= start.date()]
            before = [v for d, v in feat.items() if start.date() - timedelta(days=14) <= d < start.date()]
            sample = len(after)
            if sample >= 2 or waited >= FOLLOWUP_WAIT:
                facts.append(f"开始以后 {sample} 天里有 {sum(after)} 天{fword}" +
                             (f"（之前两周 {sum(before)} 天）" if before else ""))
                numbers = {"n": sample, "hit": sum(after), "before": sum(before) if before else None}
        elif typ == "topic_unmanaged":
            if waited >= 3:
                cut = start.date().isoformat()
                label = c.get("label") or ""
                managed = any(label in str(t.get("title") or "") for t in data.todos() if t["date"] >= cut) or \
                    any(label in json.dumps(p, ensure_ascii=False) for p in data.projects() if p.get("status") == "active")
                facts.append(f"「{label}」" + ("已经有卡在记了" if managed else "上次说要管，到现在还没有任何卡在记"))
                numbers = {"managed": int(managed)}
                sample = 1
        elif typ == "loop_no_advice":
            if waited >= 3:
                gave = any(a.get("kind") in ("suggest", "plan") and a.get("board") == c.get("board")
                           and str(a.get("at") or "") >= f.get("at", "") for a in data.actions())
                facts.append(f"{BOARD_LABEL.get(c.get('board'), c.get('board'))}那件事，" +
                             ("之后给了方案" if gave else "之后还是没给方案，是我的问题"))
                numbers = {"gave": int(gave)}
                sample = 1
        if not facts:
            continue
        out.append({"type": "followup", "key": _slug("followup", f.get("key"), f.get("period")),
                    "subject": c.get("subject") or f"fb:{f.get('key')}", "label": f"上次采纳的「{c.get('label')}」",
                    "numbers": {k: v for k, v in numbers.items() if v is not None}, "facts": ["上次选了要做的事"] + facts,
                    "sample": sample, "low_cost": True, "range": [start.date().isoformat(), data.today.isoformat()],
                    "action": {"kind": "suggest"}, "option": "按结果定下来", "fb_ref": [f.get("period"), f.get("key")],
                    "project": c.get("project"), "board": c.get("board")})
    return out


def reminder_stats(data: "Data") -> list[dict]:
    """每个重复提醒的执行情况（不设门槛，给 P-Health 排提醒用，也给后续结果用）：
    几点提醒、几次、多少次在 30 分钟内开始、通常几点才开始、最近连续几次没动。"""
    out = []
    for gk, ts in _groups(data, min_n=1).items():
        title, proj = _group_name(data, gk, ts)
        rows = []
        for t in ts:
            due = _due(t)
            at = acted_at(data, t)
            off = int((at - due).total_seconds() // 60) if at and due else None
            rows.append({"date": t["date"], "when": t.get("when"), "off": off,
                         "done": t.get("status") == "done" or at is not None,
                         "on_time": off is not None and off <= 30,
                         "touched": bool(data.ops(t["id"])) or t.get("status") in ("done", "skipped", "in_progress")})
        known = [r for r in rows if r["off"] is not None or not r["done"]]
        late = sorted(r["off"] for r in rows if r["off"] is not None and r["off"] > 30)
        streak = 0
        for r in reversed(rows):
            if r["touched"] or r["done"]:
                break
            streak += 1
        when = ts[-1].get("when")
        out.append({"group": gk, "title": title, "project": proj["id"] if proj else None, "when": when,
                    "n": len(known), "on_time": sum(r["on_time"] for r in known),
                    "rate": _pct(sum(r["on_time"] for r in known), len(known)) if known else None,
                    "typical": _fmt_hm(_hm(when) + int(statistics.median(late))) if len(late) >= 3 else None,
                    "ignored_streak": streak, "rows": rows})
    return out


def _learn_scope(f: dict) -> str | None:
    t = (f.get("cand") or {}).get("type") or f.get("type") or ""
    key = f.get("key") or ""
    if t.startswith("remind"):
        return f"learn.remind.{key}"
    if t in ("cross_pair", "best_days", "plateau"):
        return f"learn.pattern.{key}"
    return None


def _write_learned(cfg, c: dict, period: str) -> None:
    """确认过的规律（连续两次扫描都成立）点开说过以后，写进 learn.*：P-Health 排计划、排提醒先读它。"""
    scope = _learn_scope({"cand": c, "key": c.get("key")})
    if not scope or not c.get("confirmed"):
        return
    try:
        from .agent_context import AgentContextStore
        AgentContextStore(cfg).record(scope, {"rule": "；".join(c.get("facts") or [])[:200], "evidence": c.get("numbers"),
                                              "since": (c.get("range") or [None])[0], "status": "confirmed",
                                              "source": f"洞察 {period}"}, source_session="洞察", reason="洞察确认的规律")
        from . import prefs
        prefs.sync_agents_md(cfg)
    except Exception as exc:  # noqa: BLE001
        journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "learn_error", "error": str(exc)[:200]})


def _retire_learned(cfg, f: dict) -> None:
    scope = _learn_scope(f)
    if not scope:
        return
    try:
        from .agent_context import AgentContextStore
        if AgentContextStore(cfg).retire(scope, "Psir 说这条洞察不对"):
            from . import prefs
            prefs.sync_agents_md(cfg)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 挑
def mine(tools, now: datetime | None = None, state: dict | None = None) -> dict:
    """算候选 + 按规则筛和挑。不写文件（cycle 决定存不存）。"""
    data = Data(tools, now)
    state = state if state is not None else _load(tools.cfg, STATE, {})
    closed = close_feedback(data, state)          # 上几期点开过的：Psir 采纳了没有（只改内存里的 state，cycle 决定存不存）
    raw = experiment_candidates(data, state) + followup_candidates(data, state) + loop_candidates(data) \
        + reminder_candidates(data)
    try:
        from . import insight_cross
        raw += insight_cross.candidates(data)
    except Exception as exc:  # noqa: BLE001  二期算挂了不影响一期
        journal.append(tools.cfg, RUNS, {"at": data.now.isoformat(timespec="seconds"), "op": "cross_error",
                                         "error": f"{type(exc).__name__}: {exc}"[:300]})
    prev_keys = set(((state.get("scans") or [{}])[-1]).get("keys") or [])
    said = state.get("said") or {}
    corrected = {str(e["scope"]).split(".", 2)[-1] for e in data.corrections()}
    weights, blocked = type_weights(state, data.today)
    kept, dropped = [], []
    for c in raw:
        c["tier"] = TIER[c["type"]]
        c["confirmed"] = c["key"] in prev_keys or c["type"] in ("exp_result", "followup")
        c["topic"] = c.get("topic") or c["key"]
        c["weight"] = weights.get(c["type"], 0.5)
        why = None
        if c["key"] in corrected:
            why = "Psir 4 周内否过"
        elif c["type"] in blocked:
            why = f"这一类 4 周内被否了 {CLASS_REJECT} 次"
        elif not c["confirmed"] and not c.get("low_cost"):
            why = "只成立一次，行动又不是能撤回的小实验"
        else:
            last = said.get(c["key"])
            if last and str(last.get("at", ""))[:10] >= (data.today - timedelta(days=REPEAT_DAYS)).isoformat():
                moved = abs(float(c["numbers"].get("rate", c["numbers"].get("gap", 0)) or 0)
                            - float(last.get("rate") or 0)) >= 15
                upgraded = c["confirmed"] and not last.get("confirmed")
                if not (moved or upgraded):
                    why = "4 周内说过"
        (dropped if why else kept).append({**c, **({"dropped": why} if why else {})})
    # 排序：到期实验 → 断在 P-Health 自己的 → 项目卡住 → 督促小调整；同档里确认的、样本多的先
    # 同档里：能先改后说的提醒调整 → Psir 以前更愿意采纳的那类（权重）→ 确认的 → 样本多的
    kept.sort(key=lambda c: (c["tier"], (c.get("action") or {}).get("kind") != "move_reminder", -c["weight"],
                             not c["confirmed"], -int(c.get("sample") or 0)))
    picked, subjects = [], set()
    for c in kept:
        if c["subject"] in subjects:
            continue
        picked.append(c)
        subjects.add(c["subject"])
        if len(picked) >= MAX_POINTS:
            break
    return {"at": data.now.isoformat(timespec="seconds"), "keys": sorted({c["key"] for c in raw}),
            "picked": picked, "others": [c for c in kept if c not in picked], "dropped": dropped,
            "feedback_closed": [{"key": f.get("key"), "outcome": f["outcome"]} for f in closed]}


# ---------------------------------------------------------------- 写那段话（P-Health 在独立后台会话里写）
COMPOSE_SCHEMA = """输出一个 JSON 对象（不要代码块之外的任何文字）：
{"points":[{"cid":"<候选 id>","title":"<一句结论，30 字以内，带一个关键数字>","body":"<一两句说明>",
            "card":<可选，一张 layout 小卡，没有就写 null>,"option":"<这一点能做的事，20 字以内>"}],
 "options_title":"先动哪个？"}
规则：
- 最多 3 点，宁少勿凑；每个候选最多写成 1 点；只写下面给你的候选，不要加别的。
- 数字只能抄候选 facts / numbers 里的；钟点、日期照抄；不要自己算比例、不要四舍五入成别的数。
- 只说「常一起出现」，不说「导致 / 因为 / 造成 / 引起 / 所以」这类因果词（小实验结果可以说「试了之后」）。
- 不诊断、不说病名和用药，不说教（「你要自律」）；只跟 Psir 自己的平时比。
- confirmed=false 的候选（观察中）措辞要软，用「可能 / 看起来 / 好像」——软话放在判断上（「看起来这个提醒时间不合适」），
  数字本身是准的，不要写成「好像只有 2 次」。
- own=true 的是 P-Health 自己的问题：直接认（「是我的问题」）。
- type=followup 的是上次 Psir 采纳的事的结果：照实说做到了多少、数变没变，可以说「试了之后」；没做成也直说，不评价。
- type=topic_unmanaged 是 Psir 反复提到却没人管的事：不诊断，身体部位反复不舒服就建议先记两周、一直不好去看医生或康复师。
- action.kind=move_reminder 的点：P-Health 已经先改好了，body 里直接说「我先把提醒挪到 <to>，不合适回一句我就改回」，
  这一点的 option 写 null（不放进选项卡）。
- card：需要时才配，文字说得清就写 null。只能是 {"type":"layout","layout":{零件树}}。has_response_card=true 的候选
  （提醒和每次几点开始）配这张：{"type":"layout","layout":{"t":"response","bind":"insight:<cid>.response"}}；
  has_split_card=true（两组对比）配 {"type":"layout","layout":{"t":"split","bind":"insight:<cid>.split"}}；
  has_dotstrip_card=true（每天一点）配 {"type":"layout","layout":{"t":"dotstrip","bind":"insight:<cid>.dotstrip"}}；
  一点只配一张；
  数字用 bind 绑 insight:<cid>.<numbers 里的字段>，手写数字也只能抄候选。
- 不要写开头那句「Psir，这几天看出 N 件事」，服务器会加；不要写序号，服务器会编号。
"""


def _numbers_in(text: str) -> list[str]:
    """文字里的「数」：钟点、日期、百分比、整数和小数。试两周、30 分钟这类说法先去掉（规则里的常量，不是数据）。"""
    t = str(text or "")
    for phrase in ("两周", "2 周", "两个星期", "14 天", "30 分钟", "四周", "4 周", "一两句", "一下", "一起", "一直", "一样"):
        t = t.replace(phrase, " ")
    cn = {"二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    t = re.sub(r"([二两三四五六七八九十])(?=次|天|晚|周|个|成|小时|分钟)", lambda m: f" {cn[m.group(1)]} ", t)
    toks = re.findall(r"\d{1,2}:\d{2}|\d{1,2}/\d{1,2}|\d+(?:\.\d+)?", t)
    return toks


def _pool(c: dict) -> set[str]:
    src = json.dumps({k: c.get(k) for k in ("facts", "numbers", "label", "option", "range", "response", "split")},
                     ensure_ascii=False)
    for d in c.get("range") or []:
        src += " " + _md(d)
    toks = set(_numbers_in(src))
    out = set(toks)
    for x in toks:                                   # 22:00 和 22:0 / 5.0 和 5 当同一个数
        try:
            out.add(str(float(x)).rstrip("0").rstrip("."))
        except ValueError:
            pass
    return out


def _num_ok(tok: str, pool: set[str]) -> bool:
    if tok in pool:
        return True
    try:
        return str(float(tok)).rstrip("0").rstrip(".") in pool
    except ValueError:
        return False


def _card_texts(node: Any) -> list[str]:
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("bind", "t", "type", "metric", "kind", "height", "role", "tone", "size", "align", "justify", "gap"):
                continue
            out += _card_texts(v)
    elif isinstance(node, list):
        for v in node:
            out += _card_texts(v)
    elif isinstance(node, (str, int, float)) and not isinstance(node, bool):
        out.append(str(node))
    return out


def _binds(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [str(node["bind"])] if node.get("bind") else []
        return own + [b for v in node.values() for b in _binds(v)]
    if isinstance(node, list):
        return [b for v in node for b in _binds(v)]
    return []


def validate_compose(doc: Any, cands: dict[str, dict]) -> dict:
    """P-Health 写的稿 → 校验过的 {points, options}。不过就抛 InsightError（原因退回去让它改）。"""
    from . import canvas, cards
    if not isinstance(doc, dict) or not isinstance(doc.get("points"), list):
        raise InsightError("要输出 {\"points\":[…]} 这样的 JSON 对象")
    pts = doc["points"]
    if not pts:
        raise InsightError("points 不能为空")
    if len(pts) > MAX_POINTS:
        raise InsightError(f"最多 {MAX_POINTS} 点（现在 {len(pts)} 点）")
    used, out = set(), []
    for i, p in enumerate(pts, 1):
        if not isinstance(p, dict):
            raise InsightError(f"第 {i} 点要是对象")
        cid = str(p.get("cid") or "")
        if cid not in cands:
            raise InsightError(f"第 {i} 点的 cid {cid!r} 不是给你的候选")
        if cid in used:
            raise InsightError(f"候选 {cid} 写了两遍：同一件事最多占 1 点")
        used.add(cid)
        c = cands[cid]
        title = str(p.get("title") or "").strip()
        body = str(p.get("body") or "").strip()
        if not title or not body:
            raise InsightError(f"第 {i} 点要有 title 和 body")
        if len(title) > 30:
            raise InsightError(f"第 {i} 点的结论太长（{len(title)} 字，最多 30）：「{title}」砍到 30 字以内，细节放 body")
        if not re.search(r"\d", title) and not re.search(r"[两三四五六七八九十]次", title):
            raise InsightError(f"第 {i} 点的结论要带一个关键数字")
        text = title + body
        if c["type"] not in ("exp_result", "followup"):
            bad = [w for w in CAUSAL if w in text]
            if bad:
                raise InsightError(f"第 {i} 点用了因果词「{bad[0]}」：只说「常一起出现」")
        bad = [w for w in NO_SAY if w in text]
        if bad:
            raise InsightError(f"第 {i} 点出现了「{bad[0]}」：不诊断、不谈用药、不说教")
        pool = _pool(c)
        for tok in _numbers_in(text):
            if not _num_ok(tok, pool):
                k = text.find(tok)
                near = text[max(0, k - 10):k + len(tok) + 6] if k >= 0 else tok
                raise InsightError(f"第 {i} 点里「{near}」的 {tok} 在候选 {cid} 里找不到：数字只能抄候选（"
                                   f"倍数、天数也别自己算，没有就不写这个数）")
        if not c.get("confirmed") and not any(w in text for w in SOFT):
            raise InsightError(f"第 {i} 点还在观察中（只成立一次），措辞要软：用「可能 / 看起来 / 好像」")
        act = c.get("action") or {}
        option = p.get("option")
        if act.get("kind") == "move_reminder":
            if act["to"] not in body or "改回" not in body:
                raise InsightError(f"第 {i} 点是先改后说：body 里要写「我先把提醒挪到 {act['to']}，不合适回一句我就改回」")
            option = None
        elif not str(option or "").strip():
            raise InsightError(f"第 {i} 点要写 option（这一点能做的事）")
        if option is not None:
            option = str(option).strip()
            if len(option) > 20:
                raise InsightError(f"第 {i} 点的 option 太长（最多 20 字）")
            for tok in _numbers_in(option):
                if not _num_ok(tok, pool):
                    raise InsightError(f"第 {i} 点 option 里的 {tok} 在候选里找不到")
        card = p.get("card")
        if isinstance(card, dict) and card.get("t") and not card.get("type"):
            card = {"type": "layout", "layout": card}                       # 直接给了零件：套上 layout 外壳
        elif isinstance(card, dict) and card.get("layout") and not card.get("type"):
            card = {"type": "layout", "layout": card["layout"]}
        if card in (None, "", {}):
            card = None
        else:
            if not isinstance(card, dict) or str(card.get("type") or "") != "layout":
                raise InsightError(f"第 {i} 点的小卡只能是 {{\"type\":\"layout\",\"layout\":{{…}}}}")
            for b in _binds(card):
                if b.startswith("insight:") and not b.startswith(f"insight:{cid}."):
                    raise InsightError(f"第 {i} 点的小卡绑了别的候选（{b}）：只能绑 insight:{cid}.<字段>")
            for s in _card_texts(card.get("layout")):
                for tok in _numbers_in(s):
                    if not _num_ok(tok, pool):
                        raise InsightError(f"第 {i} 点小卡里的 {tok} 在候选里找不到：数字用 bind 或抄候选")
            try:
                card = {"type": "layout", "layout": canvas.validate(card, "chat")}
            except canvas.CanvasError as exc:
                raise InsightError(f"第 {i} 点的小卡不合格：{exc}") from exc
            probs = cards.check(card)
            if probs:
                raise InsightError(f"第 {i} 点的小卡：{probs[0]}")
        out.append({"cid": cid, "topic": c["topic"], "title": title.rstrip("。.") + "。", "body": body, "card": card,
                    "option": option})
    opts = [p["option"] for p in out if p["option"]]
    options = None
    if opts:
        options = {"type": "options", "title": str(doc.get("options_title") or "先动哪个？")[:14],
                   "options": opts + ["都先不动"]}
        probs = cards.check(options)
        if probs:
            raise InsightError(f"选项卡：{probs[0]}")
    return {"points": out, "options": options}


def assemble(v: dict) -> str:
    """校验过的稿 → 发进主对话的那段话（markdown + ```phealth-ui 卡片）。开头和编号由服务器加。"""
    parts = [f"Psir，这几天看出{_cn_count(len(v['points']))}件事："]
    for i, p in enumerate(v["points"], 1):
        parts.append(f"**{i}. {p['title']}**{p['body']}")
        if p["card"]:
            parts.append("```phealth-ui\n" + json.dumps(p["card"], ensure_ascii=False) + "\n```")
    if v["options"]:
        parts.append("```phealth-ui\n" + json.dumps(v["options"], ensure_ascii=False) + "\n```")
    return "\n\n".join(parts)


def _public(c: dict) -> dict:
    keep = ("id", "type", "label", "facts", "numbers", "confirmed", "own", "action", "option", "range")
    out = {k: c[k] for k in keep if k in c}
    for k in ("response", "split", "dotstrip"):
        if c.get(k):
            out[f"has_{k}_card"] = True
    return out


def _dsh_ask(run_id: str) -> Callable[[str], str]:
    """后台写稿会话（和页面编排同一套：独立工作目录 + 轻量预设，不进 P-Health 的会话列表）。"""
    from . import dsh_chat
    from .publications import _ensure_composer, _new_assistant_text
    context = f"组件编排:insight:{run_id}"
    _ensure_composer("insight", run_id)

    def ask(prompt: str, timeout: int = 300) -> str:
        before = len(dsh_chat.read_session_events(context))
        dsh_chat.send_message(prompt, context)
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(2)
            new = dsh_chat.read_session_events(context)[before:]
            if any(d.get("type") == "turn/end" for d in new):
                return _new_assistant_text(new)
        raise TimeoutError("写稿超时")
    return ask


def compose(tools, picked: list[dict], ask: Callable[[str], str] | None = None) -> dict:
    """候选 → P-Health 写稿 → 校验（最多纠正 3 轮）→ {message, points, options}。"""
    from .publications import _parse_json
    cands = {c["id"]: c for c in picked}
    ask = ask or _dsh_ask(f"i{int(time.time() * 1000)}")
    prompt = ("你是 P-Health，在给 Psir 写这几天的洞察（一段话，最多 3 点）。只按下面的格式输出 JSON，不调用任何工具。\n"
              + COMPOSE_SCHEMA + "\n候选（已按优先级排好，靠前的优先）：\n"
              + json.dumps([_public(c) for c in picked], ensure_ascii=False, indent=1))
    err = None
    attempts = []
    for rnd in range(COMPOSE_ROUNDS):
        reply = ask(prompt if rnd == 0 else f"上一次的稿没通过校验：{err}。按同样格式重新输出完整 JSON。")
        try:
            v = validate_compose(_parse_json(reply), cands)
            return {"message": assemble(v), **v, "rounds": rnd + 1, "attempts": attempts}
        except (InsightError, ValueError) as exc:
            err = str(exc)
            attempts.append({"error": err, "reply": str(reply)[:1500]})
    raise ComposeFailed(f"写稿 {COMPOSE_ROUNDS} 轮都没通过校验：{err}", attempts)


# ---------------------------------------------------------------- 一期一期地扫
def _period_id(now: datetime) -> str:
    return f"ins-{now:%Y%m%d-%H%M}"


def cycle(tools, dry_run: bool = False, force: bool = False, ask: Callable[[str], str] | None = None,
          now: datetime | None = None) -> dict:
    """每天 08:30 由 launchd 调一次；离上次扫描不满 3 天就跳过。顺序：场景标签 → 对话主题（每周）→ 算候选 → 写稿 → 存 → 推。
    dry_run：只打印候选和那段话，不存、不推、不改任何东西。"""
    cfg = tools.cfg
    now = (now or tools._now()).replace(tzinfo=None)
    state = _load(cfg, STATE, {})
    last = state.get("last_scan")
    if not force and last and (now.date() - date.fromisoformat(last)).days < EVERY_DAYS:
        return {"ran": False, "reason": f"上次扫描 {last}，不满 {EVERY_DAYS} 天"}
    # 真实环境：Psir 看过 dry-run、打开 insight_push 之前，定时任务也只试算（不存、不推、App 里不出浮条），结果记进日志备查
    gated = not dry_run and not cfg.insight_push and not cfg.sim_mode
    dry_run = dry_run or gated
    out: dict[str, Any] = {"ran": True, "dry_run": dry_run, **({"gated": True} if gated else {})}
    if not dry_run:
        from . import scene
        try:
            out["scene"] = scene.update(cfg)
        except Exception as exc:  # noqa: BLE001
            out["scene"] = {"error": str(exc)[:120]}
        try:
            out["topics"] = tag_topics(tools, now=now)
        except Exception as exc:  # noqa: BLE001
            out["topics"] = {"error": str(exc)[:120]}
    m = mine(tools, now, state)
    pid = _period_id(now)
    for n, c in enumerate(m["picked"] + m["others"], 1):
        c["id"] = f"c{now:%m%d}{n}"
    out["candidates"] = [{k: c.get(k) for k in ("id", "type", "label", "facts", "confirmed", "action")}
                         for c in m["picked"]]
    out["others"] = len(m["others"])
    out["dropped"] = [{"key": c["key"], "why": c["dropped"]} for c in m["dropped"]]
    composed = None
    if m["picked"]:
        try:
            composed = compose(tools, m["picked"], ask)
            out["message"] = composed["message"]
            out["rounds"] = composed["rounds"]
            out["attempts"] = composed.get("attempts")
        except Exception as exc:  # noqa: BLE001
            out["compose_error"] = str(exc)[:300]
            out["attempts"] = getattr(exc, "attempts", None)
    if dry_run:
        if gated:
            journal.append(cfg, RUNS, {"at": now.isoformat(timespec="seconds"), "op": "gated_dry_run",
                                       "picked": [c["key"] for c in m["picked"]], "message": out.get("message"),
                                       "compose_error": out.get("compose_error")})
        return out
    # 记扫描（连续两次成立 = 确认），存候选（画布卡绑定要取数）
    state["last_scan"] = now.date().isoformat()
    state["scans"] = (state.get("scans") or [])[-9:] + [{"at": now.isoformat(timespec="seconds"), "keys": m["keys"]}]
    allc = _load(cfg, CANDS, {})
    for c in m["picked"] + m["others"]:
        allc[c["id"]] = {**c, "period": pid}
    if len(allc) > 300:
        allc = dict(sorted(allc.items(), key=lambda kv: kv[1].get("period", ""))[-300:])
    _save(cfg, CANDS, allc)
    prev = _load(cfg, PENDING, {})
    if prev.get("status") == "pending":                 # 上一期没理：被新的一期替换，算一次没聊
        state["unopened"] = int(state.get("unopened") or 0) + 1
        prev["status"] = "replaced"
        _save(cfg, PENDING, prev)
        _note_unopened(state, prev, allc, now.isoformat(timespec="seconds"))
    if composed:
        n = len(composed["points"])
        pending = {"id": pid, "status": "pending", "created_at": now.isoformat(timespec="seconds"), "n": n,
                   "text": f"这几天看出 {n} 件事，要聊聊吗？", "message": composed["message"],
                   "points": [{"cid": p["cid"], "topic": p["topic"], "title": p["title"], "option": p["option"],
                               "type": allc[p["cid"]]["type"]} for p in composed["points"]],
                   "changes": [allc[p["cid"]]["action"] for p in composed["points"]
                               if (allc[p["cid"]].get("action") or {}).get("kind") == "move_reminder"],
                   "settle": [allc[p["cid"]]["action"]["settle"] for p in composed["points"]
                              if (allc[p["cid"]].get("action") or {}).get("settle")]}
        _save(cfg, PENDING, pending)
        out["pending"] = pid
        out["push"] = _push(tools, pending, state)
    _save(cfg, STATE, state)
    journal.append(cfg, RUNS, {"at": now.isoformat(timespec="seconds"), "op": "cycle", "period": pid,
                               "picked": [c["key"] for c in m["picked"]], "others": len(m["others"]),
                               "dropped": len(m["dropped"]), "pending": bool(composed),
                               "compose_error": out.get("compose_error"), "push": out.get("push"),
                               "rounds": out.get("rounds"),
                               "round_errors": [a["error"] for a in out.get("attempts") or []]})
    return out


def _push(tools, pending: dict, state: dict) -> dict:
    from . import notify
    if not tools.cfg.insight_push:
        return {"ok": False, "skipped": "insight_push 没打开（先给 Psir 看 dry-run）"}
    if not notify.enabled(tools.cfg):
        return {"ok": False, "skipped": "disabled"}
    if int(state.get("unopened") or 0) >= STOP_PUSH_AFTER:
        return {"ok": False, "skipped": f"连续 {STOP_PUSH_AFTER} 期没聊，只留浮条"}
    return notify.apns_sender(tools)("P-Health", pending["text"],
                                     {"why": "insight", "insight": pending["id"], "context": "", "page": "now",
                                      "thread": "insight"})


# ---------------------------------------------------------------- 状态、点开、收起
def pending_status(cfg) -> dict | None:
    p = _load(cfg, PENDING, {})
    if p.get("status") != "pending":
        return None
    return {"id": p["id"], "n": p["n"], "text": p["text"]}


INJECT_PREFIX = "【洞察"


def inject_text(p: dict) -> str:
    topics = "；".join(f"第 {i} 点 topic={x['topic']}" for i, x in enumerate(p.get("points") or [], 1))
    changes = "；".join(f"已把项目 {c['project']} 里 {c['key']} 的提醒从 {c['from']} 挪到 {c['to']}"
                        for c in (p.get("applied") or []))
    return (f"【洞察 {p['id']}】Psir 点了「聊聊」。把 <<< 和 >>> 之间的那段话原样发出：一个字、一个数都不改，"
            f"```phealth-ui 卡片照抄，不加别的话，不跑命令，不用 card-check。\n<<<\n{p['message']}\n>>>\n"
            f"（只给你看，不要发出来）{topics}。" + (f"{changes}（Psir 说「改回去」就按 insight skill 改回原来的时间）。" if changes else "")
            + "Psir 之后说哪一点不对，按 insight skill 记 correction.insight.<topic>。")


def _apply_changes(tools, p: dict) -> list[dict]:
    """先改后说：那段话发出的同时，把提醒挪好（改项目模板里那一项的时间），记进行动日志。"""
    from .todos import TodoStore
    store = TodoStore(tools.cfg)
    done = []
    for ch in p.get("changes") or []:
        try:
            proj = next((x for x in store.projects() if x["id"] == ch["project"]), None)
            if not proj:
                continue
            daily = [dict(d) for d in proj.get("daily") or []]
            hit = False
            for d in daily:
                if d.get("key") == ch["key"] and d.get("when") == ch["from"]:
                    d["when"] = ch["to"]
                    hit = True
            if not hit:
                continue
            store.project_set({"id": proj["id"], "daily": daily}, _day_of(tools._now()), tools._now())
            journal.action(tools.cfg, "plan", board=proj.get("board"), project=proj["id"], ref=p["id"],
                           detail=f"洞察先改后说：{ch['key']} {ch['from']}→{ch['to']}")
            done.append(ch)
        except Exception as exc:  # noqa: BLE001
            journal.append(tools.cfg, RUNS, {"at": journal.now_iso(tools.cfg), "op": "change_error", "period": p["id"],
                                             "error": str(exc)[:200]})
    return done


def open_pending(tools, pid: str, send: Callable[[str, str], Any] | None = None) -> dict:
    cfg = tools.cfg
    p = _load(cfg, PENDING, {})
    if p.get("id") != pid or p.get("status") != "pending":
        return {"ok": False, "error": "not_pending"}
    p["status"] = "opened"
    p["opened_at"] = tools._now().replace(tzinfo=None).isoformat(timespec="seconds")
    _save(cfg, PENDING, p)
    p["applied"] = _apply_changes(tools, p)
    _save(cfg, PENDING, p)
    state = _load(cfg, STATE, {})
    state["unopened"] = 0
    said = state.setdefault("said", {})
    allc = _load(cfg, CANDS, {})
    for x in p.get("points") or []:
        c = allc.get(x["cid"]) or {}
        said[x["topic"]] = {"at": p["opened_at"], "rate": (c.get("numbers") or {}).get("rate",
                            (c.get("numbers") or {}).get("gap")), "confirmed": bool(c.get("confirmed"))}
    state["settled"] = sorted(set(state.get("settled") or []) | set(p.get("settle") or []))
    applied = {(a.get("project"), a.get("key")) for a in p.get("applied") or []}
    fbs = state.setdefault("feedback", [])
    for x in p.get("points") or []:
        c = allc.get(x["cid"]) or {}
        if c.get("type") == "followup":                       # 上次采纳的结果说过了：这条不再跟
            ref = c.get("fb_ref") or []
            for f in fbs:
                if [f.get("period"), f.get("key")] == list(ref):
                    f["followup_done"] = True
            continue
        e = _fb_entry(c, pid, p["opened_at"], option=x.get("option"))
        act = c.get("action") or {}
        e["applied"] = (act.get("project"), act.get("key")) in applied if act.get("kind") == "move_reminder" else False
        fbs.append(e)
        if c.get("type") != "exp_result":
            _write_learned(cfg, c, pid)
    state["feedback"] = fbs[-300:]
    _save(cfg, STATE, state)
    if send is None:
        from . import dsh_chat
        send = dsh_chat.send_message
        threading.Thread(target=_verify_reply, args=(tools, p), daemon=True).start()
    try:
        r = send(inject_text(p), "")
    except Exception as exc:  # noqa: BLE001  DSH 没接上：这一期算点开过（改动已生效），告诉 App 没发进去
        journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "open", "period": pid, "applied": p["applied"],
                                   "error": str(exc)[:200]})
        return {"ok": False, "error": "send_failed"}
    journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "open", "period": pid, "applied": p["applied"]})
    return {"ok": bool((r or {}).get("ok", True))}


def _verify_reply(tools, p: dict, timeout: int = 300) -> None:
    """P-Health 照抄出去的和存的对不对：数字和卡片不一致记一条错误（不撤回，Psir 已经看到了）。"""
    from . import dsh_chat
    try:
        before = len(dsh_chat.read_session_events(""))
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            ev = dsh_chat.read_session_events("")
            new = ev[before:]
            seen_inject = False
            texts: list[str] = []
            for d in new:
                if d.get("type") == "user/message" and INJECT_PREFIX in json.dumps(d, ensure_ascii=False)[:4000]:
                    seen_inject, texts = True, []
                elif seen_inject and d.get("type") == "assistant/message":
                    from .notify import _assistant_texts
                    texts += _assistant_texts(d)
                elif seen_inject and d.get("type") == "turn/end":
                    got = "\n".join(texts)
                    ok = sorted(_numbers_in(got)) == sorted(_numbers_in(p["message"])) and \
                        got.count("```phealth-ui") == p["message"].count("```phealth-ui")
                    journal.append(tools.cfg, RUNS, {"at": journal.now_iso(tools.cfg), "op": "verify", "period": p["id"],
                                                     "ok": ok, **({} if ok else {"got": got[:400]})})
                    return
        journal.append(tools.cfg, RUNS, {"at": journal.now_iso(tools.cfg), "op": "verify", "period": p["id"], "ok": False,
                                         "error": "timeout"})
    except Exception as exc:  # noqa: BLE001
        journal.append(tools.cfg, RUNS, {"at": journal.now_iso(tools.cfg), "op": "verify", "period": p.get("id"), "ok": False,
                                         "error": str(exc)[:200]})


def dismiss_pending(tools, pid: str) -> dict:
    cfg = tools.cfg
    p = _load(cfg, PENDING, {})
    if p.get("id") != pid or p.get("status") != "pending":
        return {"ok": False, "error": "not_pending"}
    p["status"] = "dismissed"
    p["dismissed_at"] = tools._now().replace(tzinfo=None).isoformat(timespec="seconds")
    _save(cfg, PENDING, p)
    state = _load(cfg, STATE, {})
    state["unopened"] = int(state.get("unopened") or 0) + 1
    _note_unopened(state, p, _load(cfg, CANDS, {}), p["dismissed_at"])
    _save(cfg, STATE, state)
    journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "dismiss", "period": pid})
    return {"ok": True}


def _note_unopened(state: dict, p: dict, allc: dict, at: str) -> None:
    """没点开（划掉 / 被新一期替换）：每一点记一次「没理」，权重里算未采纳。"""
    fbs = state.setdefault("feedback", [])
    for x in p.get("points") or []:
        c = allc.get(x["cid"]) or {"type": x.get("type"), "key": x.get("topic")}
        if c.get("type") == "followup":
            continue
        e = _fb_entry(c, p.get("id"), at, outcome="ignored", option=x.get("option"))
        e["decided_at"] = at
        fbs.append(e)
    state["feedback"] = fbs[-300:]


# ---------------------------------------------------------------- 画布卡绑定 insight:<候选 id>.<字段>
def bind_value(cfg, bind: str) -> Any:
    m = re.match(r"^insight:([A-Za-z0-9]+)\.([A-Za-z_]+)$", bind)
    if not m:
        raise KeyError(f"insight 绑定写成 insight:<候选 id>.<字段>：{bind}")
    c = _load(cfg, CANDS, {}).get(m.group(1))
    if not c:
        raise KeyError(f"没有候选 {m.group(1)}")
    field = m.group(2)
    if field in ("response", "split", "dotstrip"):
        if not c.get(field):
            raise KeyError(f"这个候选没有 {field} 数据")
        return c[field]
    if field not in (c.get("numbers") or {}):
        raise KeyError(f"候选 {m.group(1)} 没有 {field}")
    return c["numbers"][field]


# ---------------------------------------------------------------- 对话主题（每周一次，一期只攒）
TOPIC_KINDS = {"body": "身体部位", "concern": "困扰", "mention": "提到的事"}


def tag_topics(tools, ask: Callable[[str], str] | None = None, now: datetime | None = None) -> dict:
    """上周 Psir 在四个对话里说的话 → 主题标签（身体部位、困扰、提到的事），存 chat_topics.jsonl。离上次不满 7 天就跳过。"""
    cfg = tools.cfg
    now = (now or tools._now()).replace(tzinfo=None)
    state = _load(cfg, STATE, {})
    last = state.get("topics_at")
    if last and (now.date() - date.fromisoformat(last)).days < 7:
        return {"ran": False, "reason": f"上次 {last}"}
    from . import dsh_chat
    since = (now - timedelta(days=7)).isoformat(timespec="seconds")
    lines = []
    for ctx in ("", "休息", "运动", "压力"):
        try:
            msgs = dsh_chat.read_messages(0, None, ctx)
        except Exception:  # noqa: BLE001
            continue
        for msg in msgs:
            if msg.get("role") == "me" and str(msg.get("time") or "") >= since and msg.get("text"):
                lines.append(f"{str(msg['time'])[:10]} {str(msg['text'])[:200]}")
    if not lines:
        state["topics_at"] = now.date().isoformat()
        _save(cfg, STATE, state)
        return {"ran": True, "items": 0}
    ask = ask or _dsh_ask(f"t{int(time.time() * 1000)}")
    from .publications import _parse_json
    prompt = ("给 Psir 上周说的话打主题标签。只输出 JSON：{\"items\":[{\"date\":\"YYYY-MM-DD\",\"kind\":\"body|concern|mention\","
              "\"label\":\"≤8 字\"}]}。body=身体部位（肩膀、膝盖），concern=困扰（睡不着、累），mention=提到的事（打网球、出差）。"
              "同一天同一个标签只写一次；不写人名、地名；没有就给空列表。不调用任何工具。\n"
              + "\n".join(lines[-300:]))
    try:
        doc = _parse_json(ask(prompt))
    except Exception as exc:  # noqa: BLE001
        return {"ran": True, "error": str(exc)[:120]}
    n = 0
    seen = set()
    for it in (doc or {}).get("items") or []:
        if not isinstance(it, dict) or it.get("kind") not in TOPIC_KINDS:
            continue
        label = str(it.get("label") or "").strip()[:8]
        d = str(it.get("date") or "")[:10]
        if not label or not re.match(r"^\d{4}-\d{2}-\d{2}$", d) or (d, label) in seen:
            continue
        seen.add((d, label))
        journal.append(cfg, TOPICS, {"at": now.isoformat(timespec="seconds"), "date": d, "kind": it["kind"],
                                     "label": label})
        n += 1
    state["topics_at"] = now.date().isoformat()
    _save(cfg, STATE, state)
    return {"ran": True, "items": n}
