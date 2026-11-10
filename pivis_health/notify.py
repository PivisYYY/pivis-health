"""通知（APNs）：老大在等的几类事都推到锁屏（2026-11-08 老大要求放宽通知）。

- P-Health 回了新消息：每一轮回复说完（turn/end）推一条，正文是这轮最后一段话（去掉卡片代码块）
- 待办：到点前 N 分钟（老大的 pref.remind.lead_min，默认 10）、到点各一条；练习 / 打勾类过点 15 分钟还没做再催一次。
  卡片时间写真实时刻，提前量只由这里给（不再把卡片时间往前挪）
- 计时：开始后到「叫你」的时刻推一条（和手机上的系统闹钟同时到，闹钟没授权或静音时兜底）
- P-Health 新问了一句：新出现的要选 / 要填的卡（提议、单选），或者给某张卡标了「有话问」

服务进程里一个后台线程每 20 秒巡一次（两个服务进程都起线程，flock 保证同一时间只有一个在巡）；
每件事只推一次（notify_state.json 记着推过什么）。不占每日推送额度、不受夜间免打扰：这几类都是老大自己在等的。
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
PRE_MIN = 10          # 到点前多久提醒（默认；老大可以用 pref.remind 的 lead_min 改）
NUDGE_MIN = 15        # 练习 / 打勾过点多久还没做再催
GRACE_MIN = 5         # 到点那条：服务刚重启时，过点 5 分钟内还补发，更久就不补了（别一开机推一串）
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
    """一段回复 → 锁屏上的一行：去掉卡片代码块和 markdown 记号；只有卡片时说「发来一张卡：标题」。"""
    titles = []
    for m in _FENCE.finditer(text or ""):
        try:
            card = json.loads(m.group(1))
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
        if out.get("ok") and data.get("why") in ("pre", "due", "nudge", "timer", "insight"):
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
    """到点前多久提醒：老大在 pref.remind 里定的 lead_min（0–60），没定就 PRE_MIN。"""
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
    """计时卡在什么时刻叫老大（不带时区）：卡上写了「几点叫你」（alarm）且还在开始之后，就按它；否则开始 + 时长。
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


def todos(state: dict, send, store, now: datetime, lead: int = PRE_MIN) -> list[dict]:
    from .todos import due_at
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
                r = send(t.get("title") or "P-Health", "时间到了" + (f" · {t['note'][:40]}" if t.get("note") else ""),
                         {"todo": tid, "kind": "timer", "page": t.get("board") if t.get("board") in CONTEXT_PAGE.values() else "now",
                          "thread": f"todo-{tid}", "why": "timer"})
                sent[key] = now.isoformat()
                out.append({"why": "timer", "todo": tid, "ok": r.get("ok")})
            continue
        if not tid or t.get("status") not in ("scheduled", "proposed") or t.get("auto"):
            continue
        page = t.get("board") if t.get("board") in CONTEXT_PAGE.values() else "now"
        data = {"todo": tid, "kind": t.get("kind"), "page": page, "thread": f"todo-{tid}"}
        # 新问的：要选的卡 / 标了「有话问」的卡（只算刚出现的，别把老卡都推一遍）
        ask_key = f"ask:{tid}" if t.get("kind") in ASK_KINDS else (f"esc:{tid}" if t.get("escalate") == "chat" else None)
        if ask_key and ask_key not in sent and t.get("source") == "agent":
            stamp = str(t.get("updated_at") or t.get("created_at") or "")
            try:   # 待办的时间戳是这台机器的本地时间（todos._now_iso），不是老大那边的钟
                fresh = datetime.now() - datetime.fromisoformat(stamp[:19]) <= timedelta(minutes=ASK_FRESH_MIN)
            except ValueError:
                fresh = False
            if fresh:
                r = send("P-Health 问你", t.get("title") or "", {**data, "why": "ask"})
                out.append({"why": "ask", "todo": tid, "ok": r.get("ok")})
            sent[ask_key] = now.isoformat()                  # 不新鲜的也记上，以后不再看
        due = due_at(t["date"], t["when"]) if t.get("when") else None
        if due is None:
            continue
        hhmm = t["when"]
        note = (t.get("note") or "").strip()
        plan = [
            ("pre", due - timedelta(minutes=lead), due, f"{lead} 分钟后 · {hhmm}" + (f" · {note[:40]}" if note else "")),
            ("due", due, due + timedelta(minutes=GRACE_MIN), "到时间了" + (f" · {note[:40]}" if note else "")),
        ]
        if lead <= 0:
            plan = plan[1:]                                   # 老大说不要提前提醒
        if t.get("kind") in NUDGE_KINDS:
            mins = t.get("duration_min")
            plan.append(("nudge", due + timedelta(minutes=NUDGE_MIN), due + timedelta(minutes=60),
                         "还没开始？" + (f"{int(mins)} 分钟就好" if mins else "")))
        for what, start, end, body in plan:
            key = f"{what}:{tid}:{t['date']}:{hhmm}"            # 改了时间算新的一件
            if key in sent or not (start <= nowl < end):
                continue
            r = send(t.get("title") or "P-Health", body, {**data, "why": what})
            sent[key] = now.isoformat()
            out.append({"why": what, "todo": tid, "ok": r.get("ok")})
    return out


# ---------------------------------------------------------------- 巡一次 / 后台线程
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
                      on_cards=None if first else (lambda ctx, texts: note_cards(cfg, ctx, texts, now)))
        if first:
            # 第一次：待办只记下已经过了的提醒，不补推
            out += todos(state, lambda *_a: {"ok": False, "skipped": "first_run"}, TodoStore(cfg), now, lead_minutes(cfg))
        else:
            out += todos(state, send, TodoStore(cfg), now, lead_minutes(cfg))
        state["sent"] = _prune(state.get("sent", {}), now)
        state["at"] = now.isoformat()
        _save(path, state)
        return {"ran": True, "first": first, "sent": out}
    finally:
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()


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
