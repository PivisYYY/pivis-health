"""通知（APNs）：Psir 在等的几类事都推到锁屏（2026-11-08 Psir 要求放宽通知）。

- P-Health 回了新消息：每一轮回复说完（turn/end）推一条，正文是这轮最后一段话（去掉卡片代码块）
- 待办：到点前 N 分钟（Psir 的 pref.remind.lead_min，默认 10）、到点各一条；练习 / 打勾类过点 15 分钟还没做再催一次。
  卡片时间写真实时刻，提前量只由这里给（不再把卡片时间往前挪）
- 计时：开始后到「叫你」的时刻推一条（和手机上的系统闹钟同时到，闹钟没授权或静音时兜底）
- P-Health 新问了一句：新出现的要选 / 要填的卡（提议、单选），或者给某张卡标了「有话问」

服务进程里一个后台线程每 20 秒巡一次（两个服务进程都起线程，flock 保证同一时间只有一个在巡）；
每件事只推一次（notify_state.json 记着推过什么）。不占每日推送额度、不受夜间免打扰：这几类都是 Psir 自己在等的。
模拟回放 / 演示 / 封版测试环境不推（sim_mode、会话前缀、没配 APNs）。
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from .clock import day_of as _day_of

TICK_S = 20
PRE_MIN = 10          # 到点前多久提醒（默认；Psir 可以用 pref.remind 的 lead_min 改）
NUDGE_MIN = 15        # 练习 / 打勾过点多久还没做再催
GRACE_MIN = 5         # 计时到了：过点 5 分钟内还补发
DUE_LATE_MIN = 15     # 到点那条 / 另加的钟点：服务停过、推送失败，过点 15 分钟内补发（build 53，以前 5 分钟）
ASK_FRESH_MIN = 30    # 新卡多久之内算「新问的」
KEEP_DAYS = 3
STATE_FILE = "notify_state.json"
LOCK_FILE = "notify.lock"

# 对话：板块标签 → 通知标题里的名字、点开切到的页
CONTEXT_LABEL = {"": "", "休息": "休息", "运动": "运动", "压力": "压力"}
CONTEXT_PAGE = {"": "now", "休息": "sleep", "运动": "sport", "压力": "stress"}
BOARD_CONTEXT = {"sleep": "休息", "sport": "运动", "stress": "压力", "life": ""}
ASK_KINDS = ("proposal", "options")
NUDGE_KINDS = ("follow", "done")

_FENCE = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)```", re.S)


def enabled(cfg) -> bool:
    from . import dsh_chat
    return (not getattr(cfg, "sim_mode", False)) and not dsh_chat.DSH_PREFIX and bool((cfg.apns or {}).get("key_path"))


# ---------------------------------------------------------------- 文本
def summarize(text: str, limit: int = 120) -> str:
    """一段回复 → 锁屏上的一行：去掉卡片代码块和 markdown 记号；只有卡片时说「发来一张卡：标题」，只有表情包时说「发来一个表情：抱抱」。"""
    titles = []
    sticker = ""
    for m in _FENCE.finditer(text or ""):
        try:
            card = json.loads(m.group(1))
            if isinstance(card, dict) and str(card.get("type") or "").lower() == "sticker":
                sticker = sticker or str(card.get("name") or "")      # 表情包不算「一张卡」
                continue
            t = card.get("title") or (card.get("media") or {}).get("title") if isinstance(card, dict) else None
            if t:
                titles.append(str(t))
        except Exception:  # noqa: BLE001
            pass
    body = _FENCE.sub(" ", text or "")
    body = re.sub(r"[*_`#>]+", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    if not body and titles:
        body = "发来一张卡：" + titles[0]
    elif not body and sticker:
        body = "发来一个表情：" + sticker
    return body if len(body) <= limit else body[: limit - 1].rstrip() + "…"


def _assistant_texts(d: dict) -> list[str]:
    data = d.get("data", d)
    msg = data.get("message", data)
    return [c["text"] for c in msg.get("content", []) if isinstance(c, dict) and c.get("type") == "text"
            and str(c.get("text", "")).strip() and not str(c["text"]).startswith("[model changed:")]


# ---------------------------------------------------------------- 状态
def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(path: Path, state: dict) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _prune(sent: dict, now: datetime) -> dict:
    cut = (now - timedelta(days=KEEP_DAYS)).isoformat()
    return {k: v for k, v in sent.items() if str(v) >= cut}


# ---------------------------------------------------------------- 发送
def apns_sender(tools) -> Callable[[str, str, dict], dict]:
    from .apns import APNS
    client = APNS(tools.cfg.apns)

    def send(title: str, body: str, data: dict) -> dict:
        from . import journal
        data = {**data, "push_id": data.get("push_id") or journal.new_push_id()}
        out = _send(title, body, data)
        journal.push_sent(tools.cfg, data["push_id"], title, body, data, out, at=tools._now().isoformat(timespec="seconds"))
        if out.get("ok") and data.get("why") in ("pre", "due", "nudge", "extra", "timer", "insight", "reminder"):
            todo = data.get("todo")
            journal.action(tools.cfg, "remind", board=data.get("page") if data.get("page") in BOARD_CONTEXT else None,
                           ref=todo or data.get("insight"), detail=f"{data.get('why')} · {title}"[:60],
                           at=tools._now().isoformat(timespec="seconds"))
        return out

    def _send(title: str, body: str, data: dict) -> dict:
        tokens = tools.subj.apns_tokens_list()
        if not tokens or not client.configured:
            return {"ok": False, "skipped": "no_tokens" if not tokens else "not_configured"}
        results = []
        for t in tokens:
            extra = {"thread-id": data.get("thread", "phealth")}
            if data.get("category"):
                extra["category"] = data["category"]        # 通知上的按钮（拟的时间：「好」「换个时间」）
            if data.get("why") in ("timer", "due"):
                # 计时到了 / 到点：带声音、时效性（专注模式下也能出来），和手机上的闹钟一起响
                extra.update({"sound": "default", "interruption-level": "time-sensitive"})
            r = client.send(t["token"], title, body, data=data, env=t.get("env"), aps_extra=extra)
            if r.get("reason") in ("BadDeviceToken", "Unregistered"):
                tools.subj.apns_token_drop(t["token"])        # 卸载 / 换签名后作废的令牌：清掉，别每次都失败
            results.append(r)
        out = {"ok": any(r.get("ok") for r in results), "tokens": len(tokens),
               "errors": [r.get("reason") for r in results if not r.get("ok")]}
        try:
            tools.subj.record(_day_of(tools._now()).isoformat(), "push_result",
                              {"title": title, "body": body, "kind": f"notify:{data.get('why', '')}", **out})
        except Exception:  # noqa: BLE001
            pass
        return out
    return send


# ---------------------------------------------------------------- 三类事
def replies(state: dict, send, events_of: Callable[[str], list[dict]], on_cards=None) -> list[dict]:
    """每个对话：上次看到哪儿（事件条数）→ 之后每个说完的回合推一条。第一次看到的会话只记位置，不补推历史。"""
    seen = state.setdefault("replies", {})
    out = []
    for ctx in CONTEXT_LABEL:
        try:
            ev = events_of(ctx)
        except Exception:  # noqa: BLE001  某个会话读不了不影响别的
            continue
        key = ctx or "main"
        last = seen.get(key)
        if last is None or last > len(ev):      # 新会话 / 会话换了
            seen[key] = len(ev)
            continue
        texts: list[str] = []
        done_to = last
        for i in range(last, len(ev)):
            t = ev[i].get("type")
            if t == "turn/start":
                texts = []
            elif t == "assistant/message":
                texts += _assistant_texts(ev[i])
            elif t == "turn/end":
                if on_cards is not None:
                    try:
                        on_cards(ctx, texts)
                    except Exception:  # noqa: BLE001
                        pass
                body = summarize(texts[-1]) if texts else ""
                if body:
                    label = CONTEXT_LABEL[ctx]
                    data = {"why": "reply", "context": ctx, "page": CONTEXT_PAGE[ctx], "thread": f"chat-{key}"}
                    r = send("P-Health" + (f" · {label}" if label else ""), body, data)
                    out.append({"why": "reply", "context": ctx, "ok": r.get("ok")})
                texts = []
                done_to = i + 1                  # 只推进到说完的回合：还在说的下一轮从回合开头再读
        seen[key] = done_to
    return out


def lead_minutes(cfg) -> int:
    """到点前多久提醒：Psir 在 pref.remind 里定的 lead_min（0–60），没定就 PRE_MIN。"""
    try:
        from .agent_context import AgentContextStore
        for e in AgentContextStore(cfg).snapshot()["entries"]:
            if e.get("scope") == "pref.remind":
                v = (e.get("payload") or {}).get("lead_min")
                if v is not None and 0 <= int(v) <= 60:
                    return int(v)
    except Exception:  # noqa: BLE001
        pass
    return PRE_MIN


def timer_end(t: dict) -> datetime | None:
    """计时卡在什么时刻叫 Psir（不带时区）：卡上写了「几点叫你」（alarm）且还在开始之后，就按它；否则开始 + 时长。
    App 定系统闹钟用的是同一条规则。"""
    from .todos import due_at
    started = str((t.get("record") or {}).get("started_at") or "")
    if not started:
        return None
    try:
        start = datetime.fromisoformat(started).replace(tzinfo=None)
    except ValueError:
        return None
    if t.get("alarm"):
        at = due_at(t["date"], t["alarm"])
        if at and at > start:
            return at
    mins = t.get("duration_min")
    return start + timedelta(minutes=float(mins)) if mins else None


MAX_TRIES = 3          # 推送失败（APNs 没接）：下一轮再试，最多 3 次
DRAFT_CATEGORY = "TODO_TIME"


def _try_send(state: dict, key: str, send, title: str, body: str, data: dict, now: datetime) -> dict | None:
    """发一条；成功才记「推过」。失败记次数，下一轮再试，第 3 次还失败就放弃（记在 failed 里，自检会报）。"""
    sent = state.setdefault("sent", {})
    tries = state.setdefault("tries", {})
    r = send(title, body, data) or {}
    if r.get("ok") or r.get("skipped") in ("disabled", "first_run", "not_configured", "no_tokens"):
        sent[key] = now.isoformat()
        tries.pop(key, None)
    else:
        tries[key] = int(tries.get(key, 0)) + 1
        if tries[key] >= MAX_TRIES:
            sent[key] = now.isoformat()
            state.setdefault("failed", {})[key] = now.isoformat()
            tries.pop(key, None)
    return r


def reminder_plan(t: dict, lead: int) -> list[tuple[str, datetime, datetime, str]]:
    """这张卡的提醒：(哪一条, 从, 到, 正文)。窗口内没推出去（服务重启、推送失败）下一轮补；过了窗口就不补了。
    P-Health 可以用卡上的 remind 改：off 不提醒；lead_min 提前量；extra 另加钟点；nudge 过点再不再催。"""
    from .todos import due_at
    rem = t.get("remind") or {}
    if rem.get("off") or not t.get("when"):
        return []
    due = due_at(t["date"], t["when"])
    if due is None:
        return []
    hhmm, note = t["when"], (t.get("note") or "").strip()
    lead = int(rem["lead_min"]) if rem.get("lead_min") is not None else lead
    plan = []
    if lead > 0:
        plan.append(("pre", due - timedelta(minutes=lead), due,
                     f"{lead} 分钟后 · {hhmm}" + (f" · {note[:40]}" if note else "")))
    plan.append(("due", due, due + timedelta(minutes=DUE_LATE_MIN), "到时间了" + (f" · {note[:40]}" if note else "")))
    for x in rem.get("extra") or []:
        at = due_at(t["date"], x)
        if at:
            plan.append((f"extra{x.replace(':', '')}", at, at + timedelta(minutes=DUE_LATE_MIN),
                         f"{hhmm} 的事" if at < due else "还没做的话，现在做"))
    nudge = rem.get("nudge")
    if nudge or (nudge is None and t.get("kind") in NUDGE_KINDS):
        mins = t.get("duration_min")
        plan.append(("nudge", due + timedelta(minutes=NUDGE_MIN), due + timedelta(minutes=60),
                     "还没开始？" + (f"{int(mins)} 分钟就好" if mins else "")))
    return plan


def todos(state: dict, send, store, now: datetime, lead: int = PRE_MIN) -> list[dict]:
    sent = state.setdefault("sent", {})
    nowl = now.replace(tzinfo=None)
    out = []
    items = []
    for d in (nowl.date() - timedelta(days=1), nowl.date()):      # 昨天的 00:30 那张，今天凌晨才到点
        try:
            items += store.for_date(d)
        except Exception:  # noqa: BLE001
            pass
    for t in items:
        tid = t.get("id")
        if tid and t.get("kind") == "timer" and t.get("status") == "in_progress":
            end = timer_end(t)
            key = f"timer:{tid}:{(t.get('record') or {}).get('started_at')}"
            if end and key not in sent and end <= nowl < end + timedelta(minutes=GRACE_MIN):
                r = _try_send(state, key, send, t.get("title") or "P-Health",
                              "时间到了" + (f" · {t['note'][:40]}" if t.get("note") else ""),
                              {"todo": tid, "kind": "timer", "page": t.get("board") if t.get("board") in CONTEXT_PAGE.values() else "now",
                               "thread": f"todo-{tid}", "why": "timer"}, now)
                out.append({"why": "timer", "todo": tid, "ok": r.get("ok")})
            continue
        if not tid or t.get("status") not in ("scheduled", "proposed") or t.get("auto"):
            continue
        page = t.get("board") if t.get("board") in CONTEXT_PAGE.values() else "now"
        data = {"todo": tid, "kind": t.get("kind"), "page": page, "thread": f"todo-{tid}"}
        fresh = _fresh(t)
        # 新问的：要选的卡 / 标了「有话问」的卡（只算刚出现的，别把老卡都推一遍）
        ask_key = f"ask:{tid}" if t.get("kind") in ASK_KINDS else (f"esc:{tid}" if t.get("escalate") == "chat" else None)
        if ask_key and ask_key not in sent and t.get("source") == "agent":
            if fresh:
                r = _try_send(state, ask_key, send, "P-Health 问你", t.get("title") or "", {**data, "why": "ask"}, now)
                out.append({"why": "ask", "todo": tid, "ok": r.get("ok")})
            else:
                sent[ask_key] = now.isoformat()              # 不新鲜的也记上，以后不再看
        # 拟的时间：请 Psir 确认（「好」「换个时间」两个按钮）；不回就按这个时间提醒
        if t.get("time_draft") and t.get("when"):
            dkey = f"draft:{tid}:{t['when']}"
            if dkey not in sent:
                if fresh:
                    why = t.get("draft_why") or ""
                    r = _try_send(state, dkey, send, "P-Health 先排了个时间",
                                  f"「{t.get('title') or ''}」{t['when']}" + (f"（{why}）" if why else "") + "，行吗？",
                                  {**data, "why": "draft", "when": t["when"], "category": DRAFT_CATEGORY}, now)
                    out.append({"why": "draft", "todo": tid, "ok": r.get("ok")})
                else:
                    sent[dkey] = now.isoformat()
        for what, start, end, body in reminder_plan(t, lead):
            key = f"{what}:{tid}:{t['date']}:{t['when']}"            # 改了时间算新的一件
            if key in sent or not (start <= nowl < end):
                continue
            r = _try_send(state, key, send, t.get("title") or "P-Health", body, {**data, "why": what}, now)
            out.append({"why": what, "todo": tid, "ok": r.get("ok")})
    return out


def _fresh(t: dict) -> bool:
    stamp = str(t.get("updated_at") or t.get("created_at") or "")
    try:   # 待办的时间戳是这台机器的本地时间（todos._now_iso），不是 Psir 那边的钟
        return datetime.now() - datetime.fromisoformat(stamp[:19]) <= timedelta(minutes=ASK_FRESH_MIN)
    except ValueError:
        return False


# ---------------------------------------------------------------- 单独的提醒（不是卡）
REMINDERS = "reminders.json"


def add_reminder(cfg, day: str, at: str, title: str, body: str = "", board: str | None = None) -> dict:
    """P-Health 自己排一条到点推送（不是待办卡），比如「22:30 提醒 Psir 收手机」。服务器到点一定推。"""
    import re as _re
    from datetime import date as _date
    if not _re.match(r"^([01]\d|2[0-3]):[0-5]\d$", at or ""):
        raise ValueError("at 必须是 HH:MM")
    _date.fromisoformat(day)
    title = (title or "").strip()
    if not title or len(title) > 20:
        raise ValueError("title 必填，最多 20 个字")
    path = Path(cfg.data_dir) / REMINDERS
    rows = _load(path).get("items", []) if path.exists() else []
    item = {"id": f"r{int(time.time() * 1000)}", "date": day, "at": at, "title": title, "body": (body or "")[:80],
            "board": board if board in CONTEXT_PAGE.values() else None, "created_at": datetime.now().isoformat(timespec="seconds")}
    rows = [r for r in rows if str(r.get("date", "")) >= (_date.fromisoformat(day) - timedelta(days=KEEP_DAYS)).isoformat()]
    rows.append(item)
    _save(path, {"items": rows})
    return item


def reminders(state: dict, send, cfg, now: datetime) -> list[dict]:
    from .todos import due_at
    path = Path(cfg.data_dir) / REMINDERS
    if not path.exists():
        return []
    nowl = now.replace(tzinfo=None)
    out = []
    for r in _load(path).get("items", []):
        key = f"rem:{r['id']}"
        at = due_at(r["date"], r["at"])
        if key in state.get("sent", {}) or at is None or not (at <= nowl < at + timedelta(minutes=DUE_LATE_MIN)):
            continue
        res = _try_send(state, key, send, r["title"], r.get("body") or "P-Health 提醒",
                        {"why": "reminder", "page": r.get("board") or "now", "thread": f"rem-{r['id']}"}, now)
        out.append({"why": "reminder", "id": r["id"], "ok": res.get("ok")})
    return out


def _created_local(t: dict, tz: str) -> datetime | None:
    """待办的 created_at 是这台机器的本地时间：换成 Psir 那边的钟（不带时区），好和提醒时间比。"""
    from zoneinfo import ZoneInfo
    try:
        return datetime.fromisoformat(str(t.get("created_at"))[:19]).astimezone(ZoneInfo(tz)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def audit(state: dict, store, now: datetime, lead: int = PRE_MIN, tz: str = "Asia/Shanghai") -> list[dict]:
    """自检：今天有时间、窗口已过、却没推出去的提醒（服务停了、推送一直失败）。卡是窗口过了才加的不算。"""
    nowl = now.replace(tzinfo=None)
    sent, failed = state.get("sent", {}), state.get("failed", {})
    missed = []
    try:
        items = store.for_date(nowl.date())
    except Exception:  # noqa: BLE001
        return []
    for t in items:
        if t.get("auto") or not t.get("id"):
            continue
        done_at = str((t.get("record") or {}).get("at") or "")
        for what, start, end, _body in reminder_plan(t, lead):
            if t.get("status") in ("done", "skipped") and done_at and done_at[:16] <= start.isoformat()[:16]:
                continue                                   # 没到点就做完了：本来就不用提醒
            key = f"{what}:{t['id']}:{t['date']}:{t['when']}"
            made = _created_local(t, tz)
            if what in ("pre", "due") and end <= nowl and (key not in sent or key in failed) \
                    and made is not None and made < start:
                missed.append({"todo": t["id"], "title": t.get("title"), "what": what, "at": start.isoformat()[11:16]})
    return missed


# ---------------------------------------------------------------- 巡一次 / 后台线程
BRIEF_EVERY_S = 600
SELF_CHECK_S = 3600


def tick(tools, send=None, events_of=None, now: datetime | None = None) -> dict:
    """巡一次。同一时间只有一个进程在巡；第一次跑只记位置不推。"""
    from . import dsh_chat
    from .todos import TodoStore
    cfg = tools.cfg
    lockf = open(Path(cfg.data_dir) / LOCK_FILE, "a")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lockf.close()
        return {"ran": False, "reason": "busy"}
    try:
        path = Path(cfg.data_dir) / STATE_FILE
        state = _load(path)
        now = now or tools._now()
        if send is None:                           # 模拟 / 测试环境：照样巡（记 P-Health 发的建议卡），但不推送
            send = apns_sender(tools) if enabled(cfg) else (lambda *_a: {"ok": False, "skipped": "disabled"})
        first = not state
        out = replies(state, send if not first else (lambda *_a: {"ok": False}), events_of or dsh_chat.read_session_events,
                      on_cards=None if first else (lambda ctx, texts: _after_turn(cfg, state, ctx, texts, now)))
        if first:
            # 第一次：待办只记下已经过了的提醒，不补推
            out += todos(state, lambda *_a: {"ok": False, "skipped": "first_run"}, TodoStore(cfg), now, lead_minutes(cfg))
        else:
            out += todos(state, send, TodoStore(cfg), now, lead_minutes(cfg))
            out += reminders(state, send, cfg, now)
        # 每小时自检（build 53）：数据连接（服务器拒收、WHOOP 一直失败）、漏推的提醒——记进 dev_alerts.jsonl
        last_check = state.get("self_check")
        if not first and (not last_check or (now - datetime.fromisoformat(last_check)).total_seconds() >= SELF_CHECK_S):
            state["self_check"] = now.isoformat()
            try:
                from . import datastatus
                datastatus.self_check(cfg)
                missed = audit(state, TodoStore(cfg), now, lead_minutes(cfg), cfg.timezone)
                for m in missed:
                    datastatus._alert(cfg, f"reminder_missed:{m['todo']}:{m['what']}",
                                      f"{m['at']} {m['title']} 的 {m['what']} 提醒没推出去", now)
            except Exception as exc:  # noqa: BLE001
                state["self_check_error"] = str(exc)[:200]
        # 全盘简报（build 52）：每 10 分钟看一次，数据变了才重写 CLAUDE.local.md（DSH 会补进每个对话）
        last = state.get("brief_check")
        if not last or (now - datetime.fromisoformat(last)).total_seconds() >= BRIEF_EVERY_S:
            state["brief_check"] = now.isoformat()
            try:
                from . import brief
                brief.refresh(tools, now=now)
            except Exception as exc:  # noqa: BLE001  简报出错不能拖垮推送
                state["brief_error"] = str(exc)[:200]
        state["sent"] = _prune(state.get("sent", {}), now)
        state["failed"] = _prune(state.get("failed", {}), now)
        state["at"] = now.isoformat()
        _save(path, state)
        return {"ran": True, "first": first, "sent": out}
    finally:
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()


def _after_turn(cfg, state: dict, ctx: str, texts: list[str], now: datetime) -> None:
    note_cards(cfg, ctx, texts, now)
    # b61：回执核对。没写成功的「记好了」让 P-Health 自己更正；同一个对话 10 分钟最多催一次
    from . import receipts
    last = (state.setdefault("receipt_audit", {}) or {}).get(ctx or "main")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < 600:
        receipts.audit_turn(cfg, ctx, texts, None)
        return
    def _send(msg: str, c: str) -> None:
        from . import dsh_chat
        dsh_chat.send_message(msg, c)
    if receipts.audit_turn(cfg, ctx, texts, _send):
        state["receipt_audit"][ctx or "main"] = now.isoformat()


def note_cards(cfg, ctx: str, texts: list[str], now: datetime) -> None:
    """这一轮 P-Health 在对话里发的建议类卡片（plan、问卡、选项卡）记进行动日志：洞察引擎看「发现了之后有没有建议」。"""
    from . import cards, journal
    board = BOARD_OF_CONTEXT.get(ctx)
    for text in texts:
        for m in cards._BLOCK.finditer(text or ""):
            obj, _err, _fixed = cards.parse(m.group(1).strip())
            if not isinstance(obj, dict) or str(obj.get("type") or "").lower() not in journal.SUGGEST_KINDS:
                continue
            journal.action(cfg, "suggest", board=board, ref=f"chat:{ctx or 'main'}",
                           detail=f"{obj.get('type')} · {obj.get('title') or ''}"[:60],
                           at=now.isoformat(timespec="seconds"))


BOARD_OF_CONTEXT = {"休息": "sleep", "运动": "sport", "压力": "stress", "": None}


def start_background(tools) -> bool:
    """服务进程启动时调用：起一个守护线程，每 TICK_S 秒巡一次；出错记到 agent_runs.jsonl，不让线程死掉。
    没配推送（模拟 / 测试环境）也巡，只是不推：建议卡照样记进行动日志。"""

    def loop() -> None:
        while True:
            try:
                tick(tools)
            except Exception as exc:  # noqa: BLE001
                try:
                    from .v3 import _log_agent_error
                    _log_agent_error(tools.cfg, "notify", "tick", f"{type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(TICK_S)

    threading.Thread(target=loop, name="phealth-notify", daemon=True).start()
    return True
