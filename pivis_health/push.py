"""主动触达（APNs）：统一门控 DND → 日配额 → 当日去重，再逐 token 发送。

两类入口：
- run_pushd(tools)：定时守护（launchd 每分钟调 --once），午间 12:30 / 今晚 21:30
  扫各页 needs，把窗口命中的待办推到锁屏。
- send_push(tools, ...)：bot 立即触达（不确定事项提问等），走同一套门控。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from .apns import APNS
from .rules import dnd_allows

# 专项 → 客户端页面 key
SPECIALTY_PAGE = {"睡眠": "sleep", "运动": "sport", "压力": "stress"}

# 固定推送时刻表：window 标签 → (hour, minute)；命中后 10 分钟宽限内都可发（当日去重保证只发一次）
WINDOW_TIMES = {
    "午间": (12, 30),
    "今晚": (21, 30),
}
WINDOW_GRACE_MIN = 10


def gate_and_send(tools, title: str, body: str, kind: str,
                  data: dict[str, Any] | None = None,
                  level: str = "notice") -> dict[str, Any]:
    """门控后发送。kind 即当日去重 key（如 "pushd:sleep:catch_up_sleep"）。"""
    now = tools._now()
    local_date = now.date().isoformat()
    result: dict[str, Any] = {"ok": False, "kind": kind}
    if not dnd_allows(level, now.hour, tools.cfg.dnd_hours):
        result["skipped"] = "dnd"
    elif tools.subj.push_count(local_date) >= tools.cfg.daily_push_limit:
        result["skipped"] = "quota"
    elif not tools.subj.push_once(local_date, kind):
        result["skipped"] = "dedup"
    else:
        client = APNS(tools.cfg.apns)
        tokens = tools.subj.apns_tokens_list()
        sent: list[dict] = []
        errors: list[dict] = []
        if not tokens:
            result["skipped"] = "no_tokens"
        elif not client.configured:
            result["skipped"] = "not_configured"
        else:
            for t in tokens:
                r = client.send(t["token"], title, body, data=data)
                item = {"token": t["token"][:16] + "…", "env": t["env"], **r}
                (sent if r["ok"] else errors).append(item)
            result.update({"ok": bool(sent), "sent": sent, "errors": errors,
                           "tokens": len(tokens)})
    tools.subj.record(local_date, "push_result", {"title": title, "body": body, **result})
    return result


def send_push(tools, title: str, body: str, page: str | None = None,
              pending: str | None = None, level: str = "notice",
              kind: str | None = None) -> dict[str, Any]:
    """bot 立即触达。page ∈ sleep/sport/stress/today；pending 为生成式 UI 问句。"""
    data: dict[str, Any] = {}
    if page:
        data["page"] = page
    if pending:
        data["pending"] = pending
    k = kind or f"manual:{page or 'now'}:{pending or title[:16]}"
    return gate_and_send(tools, title, body, k, data=data, level=level)


def run_pushd_once(tools) -> dict[str, Any]:
    """守护单轮：当前分钟命中时刻表才处理；逐页扫 needs，窗口匹配则推送。"""
    from .pages import V2Pages

    now = tools._now()
    window_hit = None
    for label, (h, m) in WINDOW_TIMES.items():
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if start <= now < start + timedelta(minutes=WINDOW_GRACE_MIN):
            window_hit = label
            break
    if window_hit is None:
        return {"ran": False, "reason": "no_window", "time": now.isoformat(timespec="minutes")}

    pages = V2Pages(tools)
    results: list[dict] = []
    for page_name in ("today", "sleep", "sport", "stress"):
        page = getattr(pages, page_name)()
        for need in page.get("needs") or []:
            if need.get("window") != window_hit:
                continue
            client_page = SPECIALTY_PAGE.get(need.get("specialty") or "", "today")
            kind = f"pushd:{page_name}:{need.get('need_type')}"
            results.append(gate_and_send(
                tools,
                title="P-Health",
                body=f"{need['title']}——{need['action']}",
                kind=kind,
                data={"page": client_page, "need": need.get("need_type")},
            ))
    return {"ran": True, "window": window_hit, "time": now.isoformat(timespec="seconds"),
            "results": results}
