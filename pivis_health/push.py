"""主动触达（APNs）：统一门控 DND → 日配额 → 当日去重，再逐 token 发送。

入口：send_push(tools, ...)：P-Health 立即触达（事件、红旗等），走同一套门控。
旧的定时守护（按规则引擎 needs 在 12:30 / 21:30 推写死的话）build 44 已退役。
"""
from __future__ import annotations

from typing import Any

from .apns import APNS
from .rules import dnd_allows


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
                r = client.send(t["token"], title, body, data=data, env=t.get("env"))
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
    """已退役（build 44）：以前按旧规则引擎的 needs 每天 12:30 / 21:30 推写死的话（「今晚提前上床」），
    绕过 P-Health、占推送额度，还会和计划冲突。锁屏推送只发 P-Health 写的内容（事件推送、红旗）。"""
    return {"ran": False, "reason": "retired"}

