"""每周对话复盘（build 52）：和洞察同一个样子，只是复盘的是 P-Health 自己这一周的对话，重点看 Psir 点踩的。

每周一 08:30（insight-cycle.sh 顺带调）：
  1. 服务器算账：这周多少轮对话、👍 / 👎 各多少、按原因分，用了专业技能的比例、回答里带数的比例、回复速度，和上周比。
  2. 挑案例：点踩的全看（最多 8 条），点赞的挑 3 条当范例，再补几条普通的。
  3. 后台写稿会话（和洞察同一套）写：最突出的 1–3 个问题，每个带例子、错在哪、正确该怎么答、改哪一层、具体改法；
     每个案例写成一道考题（存本机的考题库）。校验通过才存。
  4. 主对话入口浮条「这周对话复盘，要看看吗？」。点开 → 服务器把写好的那段话交给 P-Health 原样发出，
     最后一张选项卡让 Psir 逐条点「同意 / 不对」。
  5. 同意的：偏好 / 纠正 / 档案这类 P-Health 当场记；规则、技能、数据、工具这类进待改清单（review_fixes.jsonl），
     Psir 跟开发说「处理复盘」时由开发改，改完先考考题库。点「不对」的撤掉，之后不再提同样的改法。
"""
from __future__ import annotations

import json
import re
import statistics
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from . import journal
from .insight import _load, _numbers_in, _num_ok, _save

STATE = "review_state.json"
PENDING = "review_pending.json"
RUNS = "review_runs.jsonl"
CASES = "review_cases.jsonl"        # 考题库（本机，带 Psir 的原话，不进仓库）
FIXES = "review_fixes.jsonl"        # 待改清单：Psir 同意了、要开发改的
EVERY_DAYS = 6
CONTEXTS = ("", "休息", "运动", "压力")
CONTEXT_NAME = {"": "主对话", "休息": "休息", "运动": "运动", "压力": "压力"}
AUTO_PREFIX = ("【每日推荐】", "【待办提交】", "【洞察", "【反馈", "【事件")
LAYERS = {"knowledge": "技能资料", "rule": "规则", "data": "服务器数据", "tool": "工具", "model": "模型", "preference": "Psir 的偏好"}
COMPOSE_ROUNDS = 4
INJECT_PREFIX = "【洞察复盘"
BAR_TEXT = "这周对话复盘，要看看吗？"


class ReviewError(ValueError):
    pass


# ---------------------------------------------------------------- 1. 收一周的对话
def _text_of(content: list) -> str:
    return " ".join(c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text").strip()


def turns(events: list[dict], context: str, since: datetime, until: datetime, tz: str = "Asia/Shanghai") -> list[dict]:
    """一轮 = 一次 turn/start…turn/end：Psir 那句、P-Health 最后发出的那段、用了哪些命令和 skill、花了多久。
    时间一律换成 Psir 的时区（这台机器是太平洋时间）。"""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz)
    out, cur = [], None
    for e in events:
        t = e.get("type")
        d = e.get("data") or {}
        try:
            ts = datetime.fromtimestamp(int(e.get("time") or 0) / 1000, zone).replace(tzinfo=None)
        except (TypeError, ValueError, OSError):
            continue
        if t == "turn/start":
            cur = {"context": context, "start": ts, "end": None, "user": "", "reply": "", "reply_time": None,
                   "tools": [], "skills": [], "steps": 0}
            out.append(cur)
        elif cur is None:
            continue
        elif t == "user/message":
            src = d.get("source") or {}
            if isinstance(src, dict) and src.get("kind") == "user":
                cur["user"] = (cur["user"] + " " + _text_of(d.get("content"))).strip()
        elif t == "step/start":
            cur["steps"] += 1
        elif t == "tool/call":
            name = d.get("name")
            cur["tools"].append(name)
            if name == "skill":
                try:
                    cur["skills"].append(json.loads(d.get("arguments") or "{}").get("name"))
                except ValueError:
                    pass
        elif t == "assistant/message":
            for c in ((d.get("message") or d).get("content") or []):
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                    cur["reply"], cur["reply_time"] = c["text"], ts
        elif t == "turn/end":
            cur["end"] = ts
    keep = []
    for x in out:
        if not x["user"] or not (since <= x["start"] < until):
            continue
        x["auto"] = x["user"].startswith(AUTO_PREFIX)
        keep.append(x)
    return keep


def collect(tools, since: datetime, until: datetime, events_of: Callable[[str], list] | None = None) -> list[dict]:
    from . import dsh_chat
    events_of = events_of or dsh_chat.read_session_events
    allt = []
    for ctx in CONTEXTS:
        try:
            allt += turns(events_of(ctx), ctx, since, until, tools.cfg.timezone)
        except Exception:  # noqa: BLE001
            continue
    return sorted(allt, key=lambda x: x["start"])


def join_feedback(cfg, ts: list[dict], since: datetime) -> None:
    """把 Psir 的 👍 / 👎 挂到对应那一轮（按回复时间，差 3 秒内）。"""
    from zoneinfo import ZoneInfo
    from . import feedback
    zone = ZoneInfo(cfg.timezone)
    fb = feedback.latest(cfg, since=(since - timedelta(days=1)).isoformat())
    for t in ts:
        t["rating"], t["reasons"], t["note"] = None, [], ""
        if not t.get("reply_time"):
            continue
        for f in fb:
            if f.get("context", "") != t["context"]:
                continue
            try:
                ft = datetime.fromisoformat(f["reply_time"])
                ft = (ft.astimezone(zone) if ft.tzinfo else ft).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
            if abs((ft - t["reply_time"]).total_seconds()) <= 3:
                t["rating"], t["reasons"], t["note"] = f["rating"], f.get("reasons") or [], f.get("note") or ""


# ---------------------------------------------------------------- 2. 算账
def metrics(ts: list[dict]) -> dict:
    user = [t for t in ts if not t["auto"]]
    lat = sorted((t["end"] - t["start"]).total_seconds() for t in user if t.get("end"))
    downs = [t for t in ts if t.get("rating") == "down"]
    reasons: dict[str, int] = {}
    for t in downs:
        for r in t.get("reasons") or []:
            reasons[r] = reasons.get(r, 0) + 1
    pct = (lambda n, d: round(100 * n / d) if d else None)
    return {
        "turns": len(user), "auto_turns": len(ts) - len(user),
        "up": sum(1 for t in ts if t.get("rating") == "up"), "down": len(downs),
        "down_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "skill_pct": pct(sum(1 for t in user if t["skills"]), len(user)),
        "number_pct": pct(sum(1 for t in user if re.search(r"\d", t["reply"] or "")), len(user)),
        "latency_median_s": round(statistics.median(lat)) if lat else None,
        "latency_p90_s": round(lat[int(len(lat) * 0.9)]) if lat else None,
    }


def _case(t: dict, cid: str) -> dict:
    return {"id": cid, "context": CONTEXT_NAME.get(t["context"], t["context"]), "at": t["start"].strftime("%m-%d %H:%M"),
            "rating": t.get("rating"), "reasons": t.get("reasons") or [], "note": t.get("note") or "",
            "user": (t["user"] or "")[:500], "reply": (t["reply"] or "")[:1200],
            "skills": [s for s in t["skills"] if s], "commands": len([x for x in t["tools"] if x == "bash"])}


def pick_cases(ts: list[dict]) -> list[dict]:
    downs = [t for t in ts if t.get("rating") == "down"][-8:]
    ups = [t for t in ts if t.get("rating") == "up"][-3:]
    rest = [t for t in ts if not t.get("rating") and not t["auto"] and t["reply"]]
    rest = sorted(rest, key=lambda t: -len(t["user"]))[: max(0, 6 - len(downs))]   # Psir 说得最多的几轮
    out, n = [], 0
    for t in downs + ups + rest:
        n += 1
        out.append(_case(t, f"r{n}"))
    return out


# ---------------------------------------------------------------- 3. 写稿 + 校验
SCHEMA = """输出格式（只输出这个 JSON）：
{"summary": "一句话说这周对话总体怎样（≤40 字，可以用上面账里的数）",
 "problems": [
   {"title": "问题，≤20 字（例：睡眠问题拿「不诊断」挡回去）",
    "cases": ["r1", "r3"],
    "wrong": "错在哪，≤60 字",
    "better": "当时正确的回答应该是什么样（关键内容，≤120 字）",
    "layer": "knowledge / rule / data / tool / model / preference 之一",
    "fix": "具体改法，≤60 字（改哪个 skill / 规则 / 记哪条偏好）"}
 ],
 "exams": [
   {"case": "r1", "question": "考题：Psir 会怎么问（可以照抄原话）", "must": ["答案必须有的要点"], "must_not": ["不能出现的说法"]}
 ]}
要求：problems 1–3 个，按严重程度排；点踩的案例优先，Psir 写了「应该是…」的照他说的写 better；
每个 problem 至少引用 1 个案例 id；layer 选最根本的那层（偏好 = 只是 Psir 个人的习惯，记一条偏好就能解决）；
exams 给每个点踩的案例各写一道；所有数字只能来自上面的账和案例原文，不要编数。"""


def validate(doc: Any, cases: list[dict], m: dict) -> dict:
    if not isinstance(doc, dict):
        raise ReviewError("要输出一个 JSON 对象")
    ids = {c["id"] for c in cases}
    pool_src = json.dumps(m, ensure_ascii=False) + json.dumps(cases, ensure_ascii=False)
    pool = set(_numbers_in(pool_src))
    pool |= {str(float(x)).rstrip("0").rstrip(".") for x in list(pool) if re.fullmatch(r"\d+(?:\.\d+)?", x)}
    summary = str(doc.get("summary") or "").strip()
    if not summary or len(summary) > 60:
        raise ReviewError("summary 要有，≤40 字")
    probs = doc.get("problems")
    if not isinstance(probs, list) or not 1 <= len(probs) <= 3:
        raise ReviewError("problems 要 1–3 个")
    out = []
    for i, p in enumerate(probs, 1):
        if not isinstance(p, dict):
            raise ReviewError(f"第 {i} 个 problem 不是对象")
        title, wrong, better, fix = (str(p.get(k) or "").strip() for k in ("title", "wrong", "better", "fix"))
        if not title or len(title) > 24:
            raise ReviewError(f"第 {i} 个 problem 的 title 要有，≤20 字（现在：{title[:30]}）")
        if not wrong or not better or not fix:
            raise ReviewError(f"第 {i} 个 problem 的 wrong / better / fix 都要写")
        if len(better) > 160 or len(wrong) > 90 or len(fix) > 90:
            raise ReviewError(f"第 {i} 个 problem 太长：wrong ≤60 字、better ≤120 字、fix ≤60 字")
        layer = str(p.get("layer") or "")
        if layer not in LAYERS:
            raise ReviewError(f"第 {i} 个 problem 的 layer 只能是 {'/'.join(LAYERS)}")
        cs = [c for c in (p.get("cases") or []) if c in ids]
        if not cs:
            raise ReviewError(f"第 {i} 个 problem 要引用至少 1 个案例 id（{', '.join(sorted(ids))}）")
        for field, text in (("summary", summary), ("title", title), ("wrong", wrong), ("better", better), ("fix", fix)):
            bad = [x for x in _numbers_in(text) if not _num_ok(x, pool)]
            if bad:
                raise ReviewError(f"第 {i} 个 problem 的 {field} 里有账和案例里都没有的数：{bad[0]}（「{text[:40]}」）")
        out.append({"title": title, "cases": cs, "wrong": wrong, "better": better, "layer": layer, "fix": fix,
                    "apply": "memory" if layer == "preference" else "dev"})
    exams = []
    for e in doc.get("exams") or []:
        if isinstance(e, dict) and e.get("case") in ids and str(e.get("question") or "").strip():
            exams.append({"case": e["case"], "question": str(e["question"])[:300],
                          "must": [str(x)[:80] for x in (e.get("must") or [])][:6],
                          "must_not": [str(x)[:80] for x in (e.get("must_not") or [])][:6]})
    return {"summary": summary, "problems": out, "exams": exams}


def assemble(v: dict, m: dict, prev: dict | None, cases: list[dict]) -> str:
    """服务器写开头和账，问题按写稿的来，最后一张选项卡逐条「同意 / 不对」。"""
    def delta(k, unit=""):
        if not prev or prev.get(k) is None or m.get(k) is None:
            return ""
        d = m[k] - prev[k]
        return f"（上周 {prev[k]}{unit}）" if d else "（和上周一样）"
    reasons = "、".join(f"{k} {n}" for k, n in (m.get("down_reasons") or {}).items())
    head = [f"Psir，这周的对话复盘：{v['summary']}",
            f"这周 {m['turns']} 轮对话，👍 {m['up']}、👎 {m['down']}{delta('down')}" + (f"（{reasons}）" if reasons else "")
            + (f"；用了专业 skill 的 {m['skill_pct']}%{delta('skill_pct', '%')}" if m.get("skill_pct") is not None else "")
            + (f"，回复一半在 {m['latency_median_s']} 秒内" if m.get("latency_median_s") is not None else "") + "。"]
    by_id = {c["id"]: c for c in cases}
    body = []
    for i, p in enumerate(v["problems"], 1):
        ex = by_id[p["cases"][0]]
        quote = re.sub(r"^【[^】]*】\s*", "", ex["user"])
        quote = re.sub(r"https?://\S+|复制.*$|前往【[^】]*】.*$", "", quote).strip().replace("\n", " ")
        quote = quote[:30] + ("…" if len(quote) > 30 else "")
        body.append(f"**{i}. {p['title']}**\n例：{ex['at']} {ex['context']}，你问「{quote}」。"
                    f"错在{p['wrong'].rstrip('。')}。应该：{p['better'].rstrip('。')}。\n"
                    f"打算：{p['fix'].rstrip('。')}（改{LAYERS[p['layer']]}）。")
    card = {"type": "question", "title": "这几条改法", "submit_label": "确定",
            "fields": [{"id": f"p{i}", "label": f"{i}. {p['title']}", "type": "options", "options": ["同意", "不对"]}
                       for i, p in enumerate(v["problems"], 1)]}
    return "\n\n".join(head + body) + "\n\n```phealth-ui\n" + json.dumps(card, ensure_ascii=False) + "\n```"


def compose(tools, cases: list[dict], m: dict, rejected: list[str], ask: Callable[[str], str] | None = None) -> dict:
    from .insight import _dsh_ask
    from .publications import _parse_json
    ask = ask or _dsh_ask(f"rv{int(time.time() * 1000)}")
    prompt = ("你是 P-Health，在复盘自己这一周和 Psir 的对话，找出最该改的问题。只按格式输出 JSON，不调用工具。\n"
              "判断标准：有没有给专业判断（不拿「不诊断」推回去）、有没有结合 Psir 自己的数据、够不够具体、对不对、有没有照 Psir 说的做。\n"
              + SCHEMA + "\n这周的账：" + json.dumps(m, ensure_ascii=False)
              + ("\nPsir 以前点过「不对」的改法（不要再提）：" + "；".join(rejected) if rejected else "")
              + "\n案例（rating=down 是点踩，up 是点赞，空的是普通对话）：\n" + json.dumps(cases, ensure_ascii=False, indent=1))
    err, attempts = None, []
    for rnd in range(COMPOSE_ROUNDS):
        reply = ask(prompt if rnd == 0 else f"上一次没通过校验：{err}。按同样格式重新输出完整 JSON。")
        try:
            return {**validate(_parse_json(reply), cases, m), "rounds": rnd + 1, "attempts": attempts}
        except (ReviewError, ValueError) as exc:
            err = str(exc)
            attempts.append({"error": err, "reply": str(reply)[:1200]})
    raise ReviewError(f"写稿 {COMPOSE_ROUNDS} 轮都没通过：{err}")


# ---------------------------------------------------------------- 4. 每周跑一次
def cycle(tools, force: bool = False, dry_run: bool = False, ask: Callable[[str], str] | None = None,
          now: datetime | None = None, events_of: Callable[[str], list] | None = None) -> dict:
    cfg = tools.cfg
    now = (now or tools._now()).replace(tzinfo=None)
    state = _load(cfg, STATE, {})
    last = state.get("last_run")
    if not force and now.weekday() != 0:
        return {"ran": False, "reason": "复盘只在周一早上跑"}
    if not force and last and (now - datetime.fromisoformat(last)).days < EVERY_DAYS:
        return {"ran": False, "reason": f"上次复盘 {last[:10]}，不满 {EVERY_DAYS} 天"}
    since = now - timedelta(days=7)
    ts = collect(tools, since, now, events_of)
    join_feedback(cfg, ts, since)
    m = metrics(ts)
    out: dict[str, Any] = {"ran": True, "dry_run": dry_run, "metrics": m}
    if m["turns"] < 3:
        out["skipped"] = "这周对话太少（不到 3 轮），不复盘"
        if not dry_run:
            state["last_run"] = now.isoformat(timespec="seconds")
            _save(cfg, STATE, state)
        return out
    cases = pick_cases(ts)
    try:
        v = compose(tools, cases, m, state.get("rejected") or [], ask)
    except Exception as exc:  # noqa: BLE001
        out["compose_error"] = str(exc)[:300]
        journal.append(cfg, RUNS, {"at": now.isoformat(timespec="seconds"), "op": "cycle", "error": out["compose_error"]})
        return out
    message = assemble(v, m, state.get("last_metrics"), cases)
    out.update({"message": message, "rounds": v["rounds"]})
    if dry_run:
        return out
    pid = f"rv-{now:%Y%m%d-%H%M}"
    for e in v["exams"]:
        c = next(x for x in cases if x["id"] == e["case"])
        journal.append(cfg, CASES, {"at": now.isoformat(timespec="seconds"), "period": pid, **e,
                                    "context": c["context"], "orig_user": c["user"], "orig_reply": c["reply"],
                                    "reasons": c["reasons"], "note": c["note"]})
    prev = _load(cfg, PENDING, {})
    if prev.get("status") == "pending":
        prev["status"] = "replaced"
        _save(cfg, PENDING, prev)
    pending = {"id": pid, "status": "pending", "created_at": now.isoformat(timespec="seconds"), "text": BAR_TEXT,
               "message": message, "problems": v["problems"], "metrics": m}
    _save(cfg, PENDING, pending)
    state.update({"last_run": now.isoformat(timespec="seconds"), "last_metrics": m})
    _save(cfg, STATE, state)
    out["pending"] = pid
    out["push"] = _push(tools, pending)
    journal.append(cfg, RUNS, {"at": now.isoformat(timespec="seconds"), "op": "cycle", "period": pid, "metrics": m,
                               "problems": [p["title"] for p in v["problems"]], "rounds": v["rounds"],
                               "round_errors": [a["error"] for a in v.get("attempts") or []], "push": out["push"]})
    return out


def _push(tools, pending: dict) -> dict:
    from . import notify
    if not getattr(tools.cfg, "review_push", True):
        return {"ok": False, "skipped": "review_push 关着"}
    if not notify.enabled(tools.cfg):
        return {"ok": False, "skipped": "disabled"}
    return notify.apns_sender(tools)("P-Health", pending["text"],
                                     {"why": "insight", "insight": pending["id"], "context": "", "page": "now",
                                      "thread": "insight"})


# ---------------------------------------------------------------- 5. 浮条、点开、收起、逐条决定
def pending_status(cfg) -> dict | None:
    p = _load(cfg, PENDING, {})
    if p.get("status") != "pending":
        return None
    return {"id": p["id"], "n": len(p.get("problems") or []), "text": p["text"], "button": "看看", "kind": "review"}


def inject_text(p: dict) -> str:
    plan = "；".join(f"第 {i} 条 apply={x['apply']} layer={x['layer']} 改法：{x['fix']}"
                     for i, x in enumerate(p.get("problems") or [], 1))
    return (f"【洞察复盘 {p['id']}】Psir 点了「看看」。把 <<< 和 >>> 之间的那段话原样发出：一个字、一个数都不改，"
            f"```phealth-ui 卡片照抄，不加别的话，不跑命令，不用 card-check。\n<<<\n{p['message']}\n>>>\n"
            f"（只给你看，不要发出来）{plan}。Psir 答了「这几条改法」之后，按 insight skill「对话复盘」一节逐条处理。")


def open_pending(tools, pid: str, send: Callable[[str, str], Any] | None = None) -> dict:
    cfg = tools.cfg
    p = _load(cfg, PENDING, {})
    if p.get("id") != pid or p.get("status") != "pending":
        return {"ok": False, "error": "not_pending"}
    p["status"] = "opened"
    p["opened_at"] = tools._now().replace(tzinfo=None).isoformat(timespec="seconds")
    _save(cfg, PENDING, p)
    if send is None:
        from . import dsh_chat
        send = dsh_chat.send_message
        threading.Thread(target=_verify, args=(tools, p), daemon=True).start()
    try:
        r = send(inject_text(p), "")
    except Exception as exc:  # noqa: BLE001
        journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "open", "period": pid, "error": str(exc)[:200]})
        return {"ok": False, "error": "send_failed"}
    journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "open", "period": pid})
    return {"ok": bool((r or {}).get("ok", True))}


def _verify(tools, p: dict, timeout: int = 300) -> None:
    from .insight import _verify_reply
    import pivis_health.insight as ins
    old = ins.INJECT_PREFIX, ins.RUNS
    try:
        ins.RUNS = RUNS
        ins.INJECT_PREFIX = INJECT_PREFIX
        _verify_reply(tools, p, timeout)
    finally:
        ins.INJECT_PREFIX, ins.RUNS = old


def dismiss_pending(tools, pid: str) -> dict:
    cfg = tools.cfg
    p = _load(cfg, PENDING, {})
    if p.get("id") != pid or p.get("status") != "pending":
        return {"ok": False, "error": "not_pending"}
    p["status"] = "dismissed"
    p["dismissed_at"] = tools._now().replace(tzinfo=None).isoformat(timespec="seconds")
    _save(cfg, PENDING, p)
    journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "dismiss", "period": pid})
    return {"ok": True}


def decide(tools, pid: str, n: int, agree: bool, note: str = "") -> dict:
    """Psir 对第 n 条改法的决定。同意 + 要开发改的进待改清单；不对的记下来，以后不再提。"""
    cfg = tools.cfg
    p = _load(cfg, PENDING, {})
    if p.get("id") != pid:
        raise ReviewError(f"没有这一期复盘：{pid}（最近一期是 {p.get('id')}）")
    probs = p.get("problems") or []
    if not 1 <= n <= len(probs):
        raise ReviewError(f"第 {n} 条不存在（这一期有 {len(probs)} 条）")
    x = probs[n - 1]
    x["decision"] = "agree" if agree else "reject"
    x["decided_at"] = journal.now_iso(cfg)
    _save(cfg, PENDING, p)
    out = {"ok": True, "problem": x["title"], "decision": x["decision"], "apply": x["apply"]}
    if agree and x["apply"] == "dev":
        journal.append(cfg, FIXES, {"at": journal.now_iso(cfg), "period": pid, "n": n, "title": x["title"],
                                    "layer": x["layer"], "fix": x["fix"], "better": x["better"], "note": note,
                                    "status": "open"})
        out["queued"] = True
    if not agree:
        state = _load(cfg, STATE, {})
        state["rejected"] = (state.get("rejected") or [])[-19:] + [f"{x['title']}：{x['fix']}"]
        _save(cfg, STATE, state)
    journal.append(cfg, RUNS, {"at": journal.now_iso(cfg), "op": "decide", "period": pid, "n": n,
                               "decision": x["decision"]})
    return out


def open_fixes(cfg) -> list[dict]:
    return [r for r in journal.read(cfg, FIXES) if r.get("status") == "open"]
