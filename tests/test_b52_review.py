"""build 52：每周对话复盘（算账 → 挑案例 → 写稿校验 → 浮条 → 原样发出 → 逐条决定）和一键反馈。"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from pivis_health import feedback, journal, review
from pivis_health.config import Config

CN = timezone(timedelta(hours=8))
MON = datetime(2026, 11, 16, 8, 30)


class T:
    def __init__(self, tmp):
        self.cfg = replace(Config(), data_dir=tmp)

    def _now(self):
        return MON.replace(tzinfo=CN)


def ms(dt):
    return int(dt.replace(tzinfo=CN).timestamp() * 1000)


def turn(at, user, reply, skills=(), cmds=1, secs=20):
    ev = [{"type": "turn/start", "time": ms(at)},
          {"type": "user/message", "time": ms(at), "data": {"source": {"kind": "user"}, "content": [{"type": "text", "text": user}]}}]
    for s in skills:
        ev.append({"type": "tool/call", "time": ms(at), "data": {"name": "skill", "arguments": json.dumps({"name": s})}})
    for _ in range(cmds):
        ev.append({"type": "tool/call", "time": ms(at), "data": {"name": "bash", "arguments": "{}"}})
    end = at + timedelta(seconds=secs)
    ev.append({"type": "assistant/message", "time": ms(end), "data": {"message": {"content": [{"type": "text", "text": reply}]}}})
    ev.append({"type": "turn/end", "time": ms(end)})
    return ev


def week_events():
    d = MON - timedelta(days=3)
    main = (turn(d, "是不是睡眠节律出问题了", "我不做诊断，数据给你，你自己看：起床 08:19。", secs=30)
            + turn(d + timedelta(hours=1), "今晚几点洗澡", "22:15 去洗、22:30 前洗完（离 00:05 上床 1 小时 35 分）。", skills=["cbti"])
            + turn(d + timedelta(hours=2), "【每日推荐】2026-11-13 08:00｜早上", "早上推荐了：出门走 10 分钟。")
            + turn(d + timedelta(hours=3), "膝盖今天练不练", "练，22:00 那套 6 个动作，疼超过 3/10 就停。"))
    sleep = turn(d + timedelta(hours=5), "昨晚 6 点就醒了", "清晨醒很常见，不用管。")
    return {"": main, "休息": sleep, "运动": [], "压力": []}


def rate(cfg, ctx, at, rating, reasons=(), note=""):
    journal.append(cfg, feedback.FILE, {"at": (MON - timedelta(days=1)).isoformat(), "context": ctx,
                                        "reply_time": at.replace(tzinfo=CN).isoformat(), "rating": rating,
                                        "reasons": list(reasons), "note": note, "reply": "", "user": ""})


def setup_week(tmp):
    tools = T(tmp)
    d = MON - timedelta(days=3)
    rate(tools.cfg, "", d + timedelta(seconds=30), "down", ["不专业"], "你应该给判断")
    rate(tools.cfg, "", d + timedelta(hours=1, seconds=20), "up")
    rate(tools.cfg, "休息", d + timedelta(hours=5, seconds=20), "down", ["太空泛"])
    return tools


def good_reply(cases):
    downs = [c["id"] for c in cases if c["rating"] == "down"]
    return json.dumps({
        "summary": "两次点踩都是没给专业判断",
        "problems": [{"title": "拿不诊断挡回去", "cases": downs[:1], "wrong": "Psir 问节律，回了「你自己看」",
                      "better": "先判断节律没乱：起床稳定，问题在睡得少；再给固定起床和见光", "layer": "rule",
                      "fix": "AGENTS 红线 2 改成必须给判断"},
                     {"title": "早醒只说常见", "cases": downs[1:2], "wrong": "没分原因", "better": "先问是尿意、反刍还是环境",
                      "layer": "knowledge", "fix": "cbti 加早醒分因表"}],
        "exams": [{"case": c, "question": "是不是节律出问题了", "must": ["判断"], "must_not": ["不做诊断"]} for c in downs]},
        ensure_ascii=False)


def test_collect_metrics_and_cases(tmp_path):
    tools = setup_week(tmp_path)
    evs = week_events()
    ts = review.collect(tools, MON - timedelta(days=7), MON, lambda c: evs[c])
    review.join_feedback(tools.cfg, ts, MON - timedelta(days=7))
    m = review.metrics(ts)
    assert m["turns"] == 4 and m["auto_turns"] == 1           # 【每日推荐】不算 Psir 发起的
    assert m["up"] == 1 and m["down"] == 2 and m["down_reasons"] == {"不专业": 1, "太空泛": 1}
    assert m["skill_pct"] == 25
    cases = review.pick_cases(ts)
    assert [c["rating"] for c in cases[:3]] == ["down", "down", "up"]
    assert cases[0]["note"] == "你应该给判断"


def test_validate_rejects_bad_drafts(tmp_path):
    cases = [{"id": "r1", "user": "x", "reply": "起床 08:19", "rating": "down"}]
    m = {"turns": 4, "down": 1}
    good = {"summary": "一次点踩", "problems": [{"title": "挡回去", "cases": ["r1"], "wrong": "没判断", "better": "给判断",
                                                "layer": "rule", "fix": "改红线"}]}
    assert review.validate(good, cases, m)["problems"][0]["apply"] == "dev"
    for bad, msg in ((dict(good, problems=[]), "1–3"),
                     (dict(good, problems=[dict(good["problems"][0], cases=["r9"])]), "案例"),
                     (dict(good, problems=[dict(good["problems"][0], layer="x")]), "layer"),
                     (dict(good, problems=[dict(good["problems"][0], better="应该睡 9.5 小时")]), "没有的数")):
        with pytest.raises(review.ReviewError, match=msg):
            review.validate(bad, cases, m)
    pref = dict(good, problems=[dict(good["problems"][0], layer="preference")])
    assert review.validate(pref, cases, m)["problems"][0]["apply"] == "memory"


def test_cycle_open_decide(tmp_path):
    tools = setup_week(tmp_path)
    evs = week_events()
    asks = []

    def ask(prompt):
        asks.append(prompt)
        cases = json.loads(prompt.split("案例（rating=down 是点踩，up 是点赞，空的是普通对话）：\n", 1)[1]) if len(asks) == 1 else last
        globals()["last"] = cases
        return good_reply(cases)

    assert review.cycle(tools, now=MON + timedelta(days=1), ask=ask, events_of=lambda c: evs[c])["ran"] is False  # 不是周一
    out = review.cycle(tools, ask=ask, events_of=lambda c: evs[c])
    assert out["pending"].startswith("rv-") and out["rounds"] == 1
    msg = out["message"]
    assert msg.startswith("Psir，这周的对话复盘：") and "👎 2" in msg and "```phealth-ui" in msg and "这几条改法" in msg
    st = review.pending_status(tools.cfg)
    assert st["button"] == "看看" and st["text"] == review.BAR_TEXT
    assert len(list(journal.read(tools.cfg, review.CASES))) == 2          # 两条点踩各一道考题
    sent = []
    assert review.open_pending(tools, out["pending"], send=lambda text, ctx: sent.append((text, ctx)) or {"ok": True})["ok"]
    assert sent[0][0].startswith("【洞察复盘 rv-") and sent[0][1] == ""
    assert review.pending_status(tools.cfg) is None
    r1 = review.decide(tools, out["pending"], 1, True)
    assert r1["queued"] is True and len(review.open_fixes(tools.cfg)) == 1
    review.decide(tools, out["pending"], 2, False, "不是这个原因")
    assert "早醒只说常见" in json.dumps(review._load(tools.cfg, review.STATE, {})["rejected"], ensure_ascii=False)
    with pytest.raises(review.ReviewError):
        review.decide(tools, out["pending"], 3, True)


def test_quiet_week_skips(tmp_path):
    tools = T(tmp_path)
    out = review.cycle(tools, ask=lambda p: "{}", events_of=lambda c: [])
    assert out.get("skipped")


def test_status_prefers_insight(tools_env, monkeypatch):
    from pivis_health import insight, v3
    monkeypatch.setattr(review, "pending_status", lambda cfg: {"id": "rv-1", "text": review.BAR_TEXT, "button": "看看"})
    monkeypatch.setattr(insight, "pending_status", lambda cfg: None)
    assert v3.sync_status(tools_env)["insight"]["id"] == "rv-1"
    monkeypatch.setattr(insight, "pending_status", lambda cfg: {"id": "ins-1", "n": 2, "text": "这几天看出 2 件事"})
    assert v3.sync_status(tools_env)["insight"]["id"] == "ins-1"


def test_feedback_ratings_latest_wins(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    at = datetime(2026, 11, 10, 10, 7)
    rate(cfg, "休息", at, "down", ["不专业"])
    rate(cfg, "休息", at, "none")
    rate(cfg, "休息", at + timedelta(minutes=1), "up")
    assert feedback.ratings(cfg, "休息") == {(at + timedelta(minutes=1)).replace(tzinfo=CN).isoformat(): "up"}
    with pytest.raises(ValueError):
        feedback.record(cfg, "", "x", "meh")
