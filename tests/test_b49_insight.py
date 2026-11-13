"""build 49：洞察一期（① 闭环、② 督促、到期小实验）+ 数据底子（推送 / 行动 / 待办日志、WHOOP 存档、场景标签）。

全部用合成数据和临时目录，不碰真实环境、不推送、不连 DSH。
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pivis_health import canvas, insight, journal, notify, scene, whoop_sync
from pivis_health.agent_context import AgentContextStore
from pivis_health.config import Config
from pivis_health.todos import TodoStore

CN = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 11, 10, 9, 0)


class FakeTools:
    def __init__(self, tmp, now=NOW, **cfg):
        self.cfg = replace(Config(), data_dir=tmp, whoop_snapshot=tmp / "whoop.json", whoop_auth_dir=tmp / "wauth",
                           **cfg)
        self.now = now

    def _now(self):
        return self.now.replace(tzinfo=CN)


def put(tmp, todos, projects=()):
    (tmp / "todos_v3.json").write_text(json.dumps({"todos": {t["id"]: t for t in todos},
                                                   "projects": {p["id"]: p for p in projects}, "log": []},
                                                  ensure_ascii=False), encoding="utf-8")


def cbti(start="2026-10-20", when="22:40"):
    return {"id": "cbti", "name": "睡眠计划", "board": "sleep", "start": start, "days": 60, "status": "active",
            "revision": 1, "daily": [{"key": "stretch", "when": when, "title": "睡前拉伸", "kind": "done"}]}


def inst(d: date, status="done", when="22:40", pid="cbti", key="stretch", kind="follow", title="睡前拉伸", **kw):
    return {"id": f"{pid}-{d.isoformat()}-{key}", "project": pid, "source": "project", "date": d.isoformat(),
            "when": when, "board": "sleep", "kind": kind, "title": title, "status": status, **kw}


def started(tmp, todo_id, at: datetime):
    journal.append(type("C", (), {"data_dir": tmp})(), journal.TODOS,
                   {"at": at.isoformat(timespec="seconds"), "op": "user_start", "id": todo_id})


def late_setup(tmp, offsets=(5, 10, 48, 55, 61, 67, 72, 85, 92)):
    days = [date(2026, 11, 1) + timedelta(days=i) for i in range(len(offsets))]
    (tmp / journal.TODOS).unlink(missing_ok=True)
    todos = [inst(d) for d in days]
    put(tmp, todos, [cbti()])
    for d, off in zip(days, offsets):
        started(tmp, f"cbti-{d.isoformat()}-stretch", datetime.combine(d, datetime.min.time()) + timedelta(hours=22, minutes=40 + off))
    return days


# ---------------------------------------------------------------- ② 督促
def test_reminder_late_found_with_move(tmp_path):
    late_setup(tmp_path)
    cands = insight.reminder_candidates(insight.Data(FakeTools(tmp_path)))
    c = next(c for c in cands if c["type"] == "remind_late")
    assert c["numbers"]["n"] == 9 and c["numbers"]["on_time"] == 2 and c["numbers"]["rate"] == 22
    assert c["numbers"]["typical"] == "23:47"
    assert c["action"] == {"kind": "move_reminder", "project": "cbti", "key": "stretch", "from": "22:40", "to": "23:40"}
    r = c["response"]
    assert r["remind"] == 22 * 60 + 40 and len(r["points"]) == 9 and r["points"][-1] == 22 * 60 + 40 + 92
    assert r["ticks"][0]["label"] == "22:00" and r["caption"].startswith("9 次 · 11/1–11/9")


def test_reminder_threshold_edges(tmp_path):
    late_setup(tmp_path, offsets=(5, 10, 50, 60, 70))       # 5 次里 2 次 = 40%：不够格（要低于四成）
    assert not [c for c in insight.reminder_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "remind_late"]
    late_setup(tmp_path, offsets=(5, 50, 60, 70, 80))       # 5 次里 1 次：够格
    assert [c for c in insight.reminder_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "remind_late"]
    late_setup(tmp_path, offsets=(5, 50, 60, 70))           # 只有 4 次：样本不够
    assert not [c for c in insight.reminder_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "remind_late"]


def test_reminder_counts_only_after_time_change(tmp_path):
    days = late_setup(tmp_path)
    data = json.loads((tmp_path / "todos_v3.json").read_text())
    for d in days[-3:]:                                      # 最近 3 次已经挪到 23:40：之前的不算
        data["todos"][f"cbti-{d.isoformat()}-stretch"]["when"] = "23:40"
    (tmp_path / "todos_v3.json").write_text(json.dumps(data))
    assert not [c for c in insight.reminder_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "remind_late"]


def test_reminder_ignored_three_times(tmp_path):
    days = [date(2026, 11, 1) + timedelta(days=i) for i in range(6)]
    todos = [inst(d) for d in days[:3]] + [inst(d, status="scheduled") for d in days[3:]]
    put(tmp_path, todos, [cbti()])
    c = next(c for c in insight.reminder_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "remind_ignored")
    assert c["low_cost"] is False and "连续 3 次没动" in c["facts"][0]
    # 「算了」不算没理
    todos[-1]["status"] = "skipped"
    put(tmp_path, todos, [cbti()])
    assert not [c for c in insight.reminder_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "remind_ignored"]


def test_reminder_condition_short_sleep(tmp_path, monkeypatch):
    days = [date(2026, 11, 1) + timedelta(days=i) for i in range(9)] + [date(2026, 10, 25)]
    short = set(days[:5])
    todos = [inst(d, status="done" if (d not in short or d == days[0]) else "scheduled") for d in days]
    put(tmp_path, todos, [cbti()])
    nights = {d - timedelta(days=1): (5.2 if d in short else 7.4) for d in days}
    monkeypatch.setattr(insight.Data, "metric", lambda self, name: nights if name == "sleep" else {})
    c = next(c for c in insight.reminder_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "remind_condition")
    assert c["numbers"] == {"n_cond": 5, "rate_cond": 20, "n_other": 5, "rate_other": 100, "gap": 80}


# ---------------------------------------------------------------- ① 闭环
def test_loop_no_advice(tmp_path):
    cfg = FakeTools(tmp_path).cfg
    put(tmp_path, [])
    journal.action(cfg, "discover", board="stress", topic="hrv", detail="act · HRV", at="2026-11-05T09:00:00")
    journal.action(cfg, "discover", board="sleep", topic="sleep", detail="watch · 睡眠", at="2026-11-04T09:00:00")
    journal.action(cfg, "suggest", board="sleep", at="2026-11-05T21:00:00")
    journal.action(cfg, "discover", board="sport", topic="recovery", detail="act", at="2026-11-09T09:00:00")   # 还不满 3 天
    cands = insight.loop_candidates(insight.Data(FakeTools(tmp_path)))
    got = [c for c in cands if c["type"] == "loop_no_advice"]
    assert [c["board"] for c in got] == ["stress"]
    assert got[0]["own"] is True and got[0]["numbers"] == {"day": "11/5", "days": 5}


def test_loop_rejected_and_low_adherence(tmp_path):
    proj = {"id": "walk", "name": "饭后走路", "board": "sport", "start": "2026-10-20", "days": 60, "status": "active",
            "revision": 1, "daily": []}
    todos = [inst(NOW.date() - timedelta(days=i), status="done" if i % 4 == 0 else "scheduled", pid="walk", key="w",
                  kind="done", title="饭后走路") for i in range(1, 15)]
    todos += [{"id": f"p{i}", "kind": "proposal", "board": "stress", "date": f"2026-11-0{i}", "title": "试试呼吸",
               "status": "skipped", "source": "agent"} for i in (3, 6)]
    put(tmp_path, todos, [proj])
    cands = insight.loop_candidates(insight.Data(FakeTools(tmp_path)))
    low = next(c for c in cands if c["type"] == "loop_low_adherence")
    assert low["numbers"] == {"done": 3, "n": 14, "rate": 21}
    rej = next(c for c in cands if c["type"] == "loop_rejected")
    assert rej["board"] == "stress" and rej["numbers"]["n"] == 2


def test_loop_no_effect(tmp_path, monkeypatch):
    start = NOW.date() - timedelta(days=25)
    proj = {**cbti(start=start.isoformat()), "id": "relax", "name": "睡前放松"}
    todos = [inst(NOW.date() - timedelta(days=i), pid="relax", key="r", status="scheduled" if i in (2, 9, 15) else "done")
             for i in range(1, 22)]
    put(tmp_path, todos, [proj])
    vals = [6.1, 6.9, 6.4, 6.6, 6.2, 7.0, 6.5, 6.3, 6.8, 6.4, 6.6, 6.2, 6.7, 6.5]
    ser = {start - timedelta(days=14 - i): v for i, v in enumerate(vals)}
    ser.update({NOW.date() - timedelta(days=i): 6.5 for i in range(1, 8)})
    monkeypatch.setattr(insight.Data, "metric", lambda self, name: ser if name == "sleep" else {})
    c = next(c for c in insight.loop_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "loop_no_effect")
    assert c["numbers"]["rate"] == 86 and c["numbers"]["recent"] == 6.5
    ser.update({NOW.date() - timedelta(days=i): 7.6 for i in range(1, 8)})          # 变好了：不是「没变」
    assert not [c for c in insight.loop_candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "loop_no_effect"]


# ---------------------------------------------------------------- 实验结算、确认、不重复、被否
def test_experiment_settles_once(tmp_path):
    tools = FakeTools(tmp_path)
    days = [date(2026, 10, 25) + timedelta(days=i) for i in range(14)] + [date(2026, 10, 11) + timedelta(days=i) for i in range(14)]
    put(tmp_path, [inst(d, status="done" if d >= date(2026, 10, 25) and d.day % 3 else "scheduled") for d in days], [cbti()])
    AgentContextStore(tools.cfg).record("learn.exp", {"items": [
        {"id": "stretch-early", "change": "拉伸提前到 22:00", "start": "2026-10-25", "days": 14, "metric": "project:cbti",
         "result": None},
        {"id": "no-metric", "change": "睡前不看手机", "start": "2026-10-25", "days": 7, "measure": "日记", "result": None}]})
    m = insight.mine(tools)
    exps = [c for c in m["picked"] + m["others"] if c["type"] == "exp_result"]
    assert len(exps) == 1                                     # 没写 metric 的实验引擎结算不了，留给周复盘
    c = exps[0]
    assert c["numbers"]["n"] == 14 and c["numbers"]["before"] == 0 and c["action"]["settle"] == "stretch-early"
    assert c["numbers"]["start"] == "10/25" and c["numbers"]["end"] == "11/7"
    state = {"settled": ["stretch-early"]}
    assert not [c for c in insight.mine(tools, state=state)["picked"] if c["type"] == "exp_result"]


def test_observing_needs_low_cost_and_confirmation(tmp_path):
    days = [date(2026, 11, 1) + timedelta(days=i) for i in range(6)]
    put(tmp_path, [inst(d) for d in days[:3]] + [inst(d, status="scheduled") for d in days[3:]], [cbti()])
    tools = FakeTools(tmp_path)
    m = insight.mine(tools, state={})
    ign = next(c for c in m["dropped"] if c["type"] == "remind_ignored")
    assert "只成立一次" in ign["dropped"]
    m2 = insight.mine(tools, state={"scans": [{"keys": m["keys"]}]})              # 连续两次扫描都成立 = 确认
    assert next(c for c in m2["picked"] if c["type"] == "remind_ignored")["confirmed"] is True


def test_no_repeat_and_correction(tmp_path):
    late_setup(tmp_path)
    tools = FakeTools(tmp_path)
    key = next(c for c in insight.mine(tools)["picked"] if c["type"] == "remind_late")["key"]
    said = {"said": {key: {"at": "2026-11-01T09:00:00", "rate": 22, "confirmed": False}}}
    assert next(c for c in insight.mine(tools, state=said)["dropped"] if c["key"] == key)["dropped"] == "4 周内说过"
    said["said"][key]["rate"] = 60                                               # 数字明显变了：可以再说
    assert any(c["key"] == key for c in insight.mine(tools, state=said)["picked"])
    AgentContextStore(tools.cfg).record(f"correction.insight.{key}", {"rule": "这个提醒时间是故意的"})
    assert next(c for c in insight.mine(tools, state={})["dropped"] if c["key"] == key)["dropped"] == "Psir 4 周内否过"


def test_pick_order_and_one_per_subject(tmp_path):
    late_setup(tmp_path)
    cfg = FakeTools(tmp_path).cfg
    journal.action(cfg, "discover", board="stress", topic="hrv", detail="act", at="2026-11-05T09:00:00")
    m = insight.mine(FakeTools(tmp_path))
    assert [c["type"] for c in m["picked"]][:2] == ["loop_no_advice", "remind_late"]
    assert len({c["subject"] for c in m["picked"]}) == len(m["picked"])


# ---------------------------------------------------------------- 写稿校验
def _cand(**kw):
    c = {"id": "c11101", "type": "remind_late", "key": "remind-late-cbti-stretch", "topic": "remind-late-cbti-stretch",
         "label": "睡前拉伸", "confirmed": True, "low_cost": True,
         "numbers": {"n": 9, "on_time": 2, "rate": 22, "remind": "22:40", "typical": "23:47", "to": "23:40"},
         "facts": ["「睡前拉伸」22:40 提醒，近 9 次里 2 次在提醒后 30 分钟内开始", "其余多在 23:47 前后才开始（7 次）"],
         "action": {"kind": "move_reminder", "project": "cbti", "key": "stretch", "from": "22:40", "to": "23:40"},
         "range": ["2026-11-01", "2026-11-09"], "response": {"start": 1320, "span": 180}}
    c.update(kw)
    return c


GOOD = {"cid": "c11101", "title": "拉伸提醒 9 次里只有 2 次当场做", "body": "22:40 提醒，其余多在 23:47 前后才开始。"
        "我先把提醒挪到 23:40，不合适回一句我就改回。", "card": {"type": "layout", "layout": {"t": "response",
        "bind": "insight:c11101.response"}}, "option": None}


def test_validate_good_and_assemble():
    v = insight.validate_compose({"points": [GOOD]}, {"c11101": _cand()})
    assert v["options"] is None and v["points"][0]["option"] is None
    msg = insight.assemble(v)
    assert msg.startswith("Psir，这几天看出一件事：\n\n**1. 拉伸提醒 9 次里只有 2 次当场做。**22:40 提醒")
    assert msg.count("```phealth-ui") == 1


@pytest.mark.parametrize("patch, why", [
    ({"title": "拉伸提醒 9 次里只有 3 次当场做"}, "3 在候选"),
    ({"body": "因为太晚了。我先把提醒挪到 23:40，不合适回一句我就改回。"}, "因果词"),
    ({"body": "其余多在 23:47 才开始。"}, "先改后说"),
    ({"title": "拉伸提醒总是做得晚"}, "关键数字"),
    ({"body": "你要自律。我先把提醒挪到 23:40，不合适回一句我就改回。"}, "说教"),
    ({"card": {"type": "layout", "layout": {"t": "value", "value": "35%"}}}, "35"),
    ({"card": {"type": "layout", "layout": {"t": "response", "bind": "insight:c99999.response"}}}, "别的候选"),
])
def test_validate_rejects(patch, why):
    with pytest.raises(insight.InsightError) as e:
        insight.validate_compose({"points": [{**GOOD, **patch}]}, {"c11101": _cand()})
    assert why.split()[0] in str(e.value) or why in str(e.value)


def test_validate_counts_and_soft_words():
    cands = {f"c{i}": _cand(id=f"c{i}", action={"kind": "suggest"}, confirmed=False) for i in range(4)}
    p = {"title": "拉伸 9 次里 2 次当场做", "body": "提醒时间可能不合适。", "option": "换个时间"}
    with pytest.raises(insight.InsightError, match="最多 3 点"):
        insight.validate_compose({"points": [{**p, "cid": f"c{i}"} for i in range(4)]}, cands)
    with pytest.raises(insight.InsightError, match="措辞要软"):
        insight.validate_compose({"points": [{**p, "cid": "c0", "body": "提醒时间不合适。"}]}, cands)
    with pytest.raises(insight.InsightError, match="写了两遍"):
        insight.validate_compose({"points": [{**p, "cid": "c0"}, {**p, "cid": "c0"}]}, cands)
    v = insight.validate_compose({"points": [{**p, "cid": "c0"}, {**p, "cid": "c1"}]}, cands)
    assert v["options"]["options"] == ["换个时间", "换个时间", "都先不动"]
    assert insight.assemble(v).startswith("Psir，这几天看出两件事：")


def test_numbers_in_ignores_rule_constants():
    assert insight._numbers_in("试两周，30 分钟内开始；9 次里两次，22:40 提醒，11/5 起") == ["9", "2", "22:40", "11/5"]


# ---------------------------------------------------------------- 一期：存、推、点开、收起
_LAST = {}


def _fake_ask(prompt: str) -> str:
    m = re.search(r'"id": "(c\d+)"', prompt)
    cid = _LAST["cid"] = m.group(1) if m else _LAST["cid"]
    body = "22:40 提醒，其余多在 23:47 前后才开始，看起来这个时间不合适。我先把提醒挪到 23:40，不合适回一句我就改回。"
    return json.dumps({"points": [{**GOOD, "cid": cid, "body": body, "card": {"type": "layout", "layout": {
        "t": "response", "bind": f"insight:{cid}.response"}}}]}, ensure_ascii=False)


def test_cycle_open_and_change(tmp_path, monkeypatch):
    late_setup(tmp_path)
    monkeypatch.setattr(insight, "tag_topics", lambda *a, **k: {"ran": False})
    tools = FakeTools(tmp_path, sim_mode=True)
    tools.now = NOW
    (tmp_path / "sim_clock.json").write_text(json.dumps({"now": "2026-11-10T09:00:00+08:00"}))
    dry = insight.cycle(tools, dry_run=True, ask=_fake_ask)
    assert dry["message"].startswith("Psir，这几天看出一件事") and not (tmp_path / insight.PENDING).exists()
    out = insight.cycle(tools, ask=_fake_ask)
    assert out["push"]["skipped"].startswith("insight_push 没打开")
    st = insight.pending_status(tools.cfg)
    assert st == {"id": "ins-20261110-0900", "n": 1, "text": "这几天看出 1 件事，要聊聊吗？"}
    assert insight.cycle(tools, ask=_fake_ask) == {"ran": False, "reason": "上次扫描 2026-11-10，不满 3 天"}
    sent = []
    r = insight.open_pending(tools, st["id"], send=lambda text, ctx: sent.append((text, ctx)) or {"ok": True})
    assert r == {"ok": True} and sent[0][1] == "" and sent[0][0].startswith("【洞察 ins-20261110-0900】")
    assert "topic=remind-late" in sent[0][0]
    proj = TodoStore(tools.cfg).projects()[0]
    assert proj["daily"][0]["when"] == "23:40"                                   # 先改后说：点开时改好
    assert insight.pending_status(tools.cfg) is None
    assert insight.open_pending(tools, st["id"], send=lambda *a: {"ok": True}) == {"ok": False, "error": "not_pending"}
    state = json.loads((tmp_path / insight.STATE).read_text())
    assert state["unopened"] == 0 and any(k.startswith("remind-late") for k in state["said"])
    acts = list(journal.read(tools.cfg, journal.ACTIONS))
    assert any("先改后说" in (a.get("detail") or "") for a in acts)


def test_dismiss_and_push_rules(tmp_path, monkeypatch):
    late_setup(tmp_path)
    monkeypatch.setattr(insight, "tag_topics", lambda *a, **k: {"ran": False})
    tools = FakeTools(tmp_path, insight_push=True)
    pushed = []
    monkeypatch.setattr(notify, "enabled", lambda cfg: True)
    monkeypatch.setattr(notify, "apns_sender", lambda t: (lambda title, body, data: pushed.append(data) or {"ok": True}))
    out = insight.cycle(tools, ask=_fake_ask)
    assert out["push"] == {"ok": True} and pushed[0]["why"] == "insight" and pushed[0]["context"] == ""
    assert insight.dismiss_pending(tools, out["pending"]) == {"ok": True}
    assert insight.pending_status(tools.cfg) is None
    state = json.loads((tmp_path / insight.STATE).read_text())
    state["unopened"] = 3
    (tmp_path / insight.STATE).write_text(json.dumps(state))
    tools.now = NOW + timedelta(days=3)
    out = insight.cycle(tools, ask=_fake_ask, force=True)
    assert "只留浮条" in out["push"]["skipped"] and insight.pending_status(tools.cfg)


# ---------------------------------------------------------------- 画布
def test_canvas_insight_bind_and_response(tmp_path):
    tools = FakeTools(tmp_path)
    (tmp_path / insight.CANDS).write_text(json.dumps({"c11101": _cand(response={
        "start": 1320, "span": 180, "remind": 1360, "points": [1365, 1430], "ticks": [{"at": 1320, "label": "22:00"}],
        "label": "提醒", "caption": "2 次 · 11/1–11/2"})}))
    lay = canvas.validate({"type": "layout", "layout": {"t": "v", "children": [
        {"t": "response", "bind": "insight:c11101.response"}, {"t": "stat", "label": "当场做", "bind": "insight:c11101.on_time"}]}},
        "chat")
    out = canvas.resolve(tools, lay, NOW.date(), NOW)
    resp, stat = out["children"]
    assert resp["t"] == "response" and resp["points"] == [1365, 1430] and resp["caption"].startswith("2 次")
    assert stat["text"] == "2"
    with pytest.raises(canvas.CanvasError):
        canvas.validate({"t": "response", "bind": "sleep"}, "chat")
    missing = canvas.resolve(tools, canvas.validate({"t": "response", "bind": "insight:c00000.response"}, "chat"))
    assert missing.get("fallback")


def test_dots_and_columns_go_to_90_days_weekly_after_30():
    assert canvas.validate({"t": "dots", "bind": "steps.week", "days": 60}, "chat")["days"] == 60
    assert canvas.validate({"t": "columns", "metric": "hrv", "days": 120}, "chat")["days"] == 90
    items = [{"label": f"d{i}", "on": i % 2 == 0, "value": float(i)} for i in range(35)]
    w = canvas._weekly({"items": items, "caption": "x"}, "columns")
    assert w["weekly"] and len(w["items"]) == 5 and w["items"][0] == {"label": "d0", "on": True, "week": True,
                                                                      "value": 3.0, "text": "3"}
    assert canvas._weekly({"items": items[:30]}, "dots") == {"items": items[:30]}


# ---------------------------------------------------------------- 数据底子
def test_todo_log_kept_with_when_and_key(tmp_path):
    cfg = FakeTools(tmp_path).cfg
    st = TodoStore(cfg)
    st.project_set(cbti(start="2026-11-09"), date(2026, 11, 9))
    st.materialize(date(2026, 11, 9))
    tid = "cbti-2026-11-09-stretch"
    st.user_submit(tid, "start", {}, None, None, datetime(2026, 11, 9, 23, 5))
    st.update(tid, {"when": "23:00"})
    ops = [e for e in journal.read(cfg, journal.TODOS) if e.get("id") == tid]
    assert [e["op"] for e in ops] == ["materialize", "user_start", "update"]
    assert ops[1]["at"] == "2026-11-09T23:05:00" and ops[1]["key"] == "stretch" and ops[1]["when"] == "22:40"
    assert ops[2]["prev_when"] == "22:40" and ops[2]["when"] == "23:00"
    assert any(e["op"] == "project_set" for e in journal.read(cfg, journal.TODOS))


def test_push_log_and_tap(tmp_path):
    cfg = FakeTools(tmp_path).cfg
    pid = journal.new_push_id()
    journal.push_sent(cfg, pid, "睡前拉伸", "10 分钟后 · 22:40", {"why": "pre", "todo": "t1"}, {"ok": True})
    journal.push_tap(cfg, pid, "open", "2026-11-09T22:31:00+08:00")
    rows = list(journal.read(cfg, journal.PUSH))
    assert [r["type"] for r in rows] == ["sent", "tap"] and rows[0]["id"] == rows[1]["id"] == pid
    with pytest.raises(ValueError):
        journal.push_tap(cfg, "", "open", None)


def test_chat_suggestion_cards_logged(tmp_path):
    cfg = FakeTools(tmp_path).cfg
    texts = ["好的\n```phealth-ui\n{\"type\":\"plan\",\"title\":\"睡前放松\",\"items\":[{\"title\":\"拉伸\"}]}\n```",
             "```phealth-ui\n{\"type\":\"receipt\",\"change\":\"x\"}\n```"]
    notify.note_cards(cfg, "休息", texts, NOW)
    acts = list(journal.read(cfg, journal.ACTIONS))
    assert len(acts) == 1 and acts[0]["kind"] == "suggest" and acts[0]["board"] == "sleep"


def test_page_discovery_logged(tmp_path):
    from pivis_health.v3 import V3PageStore
    cfg = FakeTools(tmp_path).cfg
    store = V3PageStore(cfg)
    store.save("sleep", {"hero": {"level": "steady", "board": "sleep", "label": "睡眠", "metric": "sleep"}})
    store.save("sleep", {"hero": {"level": "act", "board": "sleep", "label": "睡眠", "metric": "sleep"}})
    store.save("sleep", {"hero": {"level": "act", "board": "sleep", "label": "睡眠", "metric": "sleep"}})
    acts = [a for a in journal.read(cfg, journal.ACTIONS) if a["kind"] == "discover"]
    assert len(acts) == 1 and acts[0]["board"] == "sleep" and acts[0]["topic"] == "sleep"


def test_whoop_archive_merges_and_never_drops(tmp_path):
    cfg = FakeTools(tmp_path).cfg
    rec = {"id": "s1", "start": "2026-11-08T15:30:00Z", "end": "2026-11-08T22:30:00Z", "updated_at": "2026-11-09T01:00:00Z"}
    whoop_sync.archive(cfg, {"sleep": [rec], "recovery": [], "cycle": [], "workout": []})
    whoop_sync.archive(cfg, {"sleep": [{**rec, "updated_at": "2026-11-08T00:00:00Z", "stale": True}]})
    whoop_sync.archive(cfg, {"sleep": [{"id": "s2", "start": "2026-11-09T15:00:00Z", "end": "2026-11-09T23:00:00Z"}]})
    day = json.loads((whoop_sync.archive_dir(cfg) / "2026-11-09.json").read_text())
    assert [r["id"] for r in day["sleep"]] == ["s1"] and "stale" not in day["sleep"][0]     # 醒来那天；旧版本不覆盖新版本
    whoop_sync.archive(cfg, {"sleep": [{**rec, "updated_at": "2026-11-10T00:00:00Z", "score": 1}]})
    got = whoop_sync.load_archive(cfg)["sleep"]
    assert {r["id"] for r in got} == {"s1", "s2"} and next(r for r in got if r["id"] == "s1")["score"] == 1


def test_scene_labels_without_coordinates(tmp_path):
    db = tmp_path / "events.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE raw_events (seq INTEGER PRIMARY KEY, event_id TEXT, type TEXT, occurred_at TEXT, "
                "occurred_ts REAL, source TEXT, payload_json TEXT, envelope_digest TEXT, received_at TEXT, received_ts REAL)")
    home, far = (10.00, 20.00), (12.00, 23.00)

    def ev(typ, local: datetime, payload):
        ts = local.replace(tzinfo=CN).timestamp()
        con.execute("INSERT INTO raw_events (event_id,type,occurred_at,occurred_ts,source,payload_json,envelope_digest,"
                    "received_at,received_ts) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"e{ts}{typ}", typ, local.isoformat(), ts, "t", json.dumps(payload), "d", "", ts))

    for d in (1, 2, 3):
        ev("location", datetime(2026, 11, d, 2, 0), {"lat": home[0], "lon": home[1], "accuracy_m": 20})
    ev("location", datetime(2026, 11, 2, 9, 0), {"lat": home[0], "lon": home[1], "accuracy_m": 20})
    ev("location", datetime(2026, 11, 2, 9, 10), {"lat": home[0] + 0.05, "lon": home[1], "accuracy_m": 20})   # 10 分钟 5.5 km
    ev("location", datetime(2026, 11, 5, 2, 0), {"lat": far[0], "lon": far[1], "accuracy_m": 20})
    ev("wearable_removed", datetime(2026, 11, 3, 23, 0), {})
    ev("wearable_restored", datetime(2026, 11, 3, 23, 40), {})
    con.commit()
    days, h = scene.compute(db, "Asia/Shanghai")
    assert h is not None
    assert days["2026-11-02"]["home"] and days["2026-11-02"]["out"] and days["2026-11-02"]["drive_min"] == 10
    assert days["2026-11-04"]["away_night"] is True                      # 5 日凌晨在外地 = 4 日晚上外宿
    assert days["2026-11-03"]["watch_off_min"] == 40 and days["2026-11-03"]["watch_off"] == [["23:00", "23:40"]]
    assert "lat" not in json.dumps(days) and "20.0" not in json.dumps(days)


def test_move_only_time_skips_video_recheck(tmp_path):
    """先改后说只挪时间：练习卡的视频不在素材库里（老数据）也照样能改，不再被「练习只用视频」挡住。"""
    tools = FakeTools(tmp_path)
    proj = {**cbti(), "daily": [{"key": "stretch", "when": "22:40", "title": "睡前拉伸", "kind": "follow",
                                 "steps": [{"title": "拉伸", "media": {"kind": "video", "url": "/media/follow/gone/out.mp4"}}]}]}
    put(tmp_path, [], [proj])
    p = {"id": "ins-x", "changes": [{"kind": "move_reminder", "project": "cbti", "key": "stretch", "from": "22:40",
                                     "to": "23:40"}]}
    assert insight._apply_changes(tools, p) == p["changes"]
    assert TodoStore(tools.cfg).projects()[0]["daily"][0]["when"] == "23:40"


def test_open_send_failure_and_change_error_paths(tmp_path, monkeypatch):
    late_setup(tmp_path)
    monkeypatch.setattr(insight, "tag_topics", lambda *a, **k: {"ran": False})
    tools = FakeTools(tmp_path, insight_push=True)
    out = insight.cycle(tools, ask=_fake_ask)
    monkeypatch.setattr(TodoStore, "project_set", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    def broken_send(text, ctx):
        raise RuntimeError("dsh down")
    assert insight.open_pending(tools, out["pending"], send=broken_send) == {"ok": False, "error": "send_failed"}
    runs = [json.loads(x) for x in (tmp_path / insight.RUNS).read_text().splitlines()]
    assert [r["op"] for r in runs][-2:] == ["change_error", "open"] and runs[-1]["error"] == "dsh down"
    bj = datetime.now(CN).replace(tzinfo=None)                           # Psir 那边的钟，不是这台机器的系统时区
    assert abs((datetime.fromisoformat(runs[-1]["at"]) - bj).total_seconds()) < 120


def test_journal_uses_user_clock(tmp_path):
    cfg = replace(FakeTools(tmp_path).cfg, sim_mode=True)
    (tmp_path / "sim_clock.json").write_text(json.dumps({"now": "2026-11-10T22:41:00+08:00"}))
    journal.action(cfg, "discover", board="sleep")
    assert next(journal.read(cfg, journal.ACTIONS))["at"] == "2026-11-10T22:41:00"


def test_real_env_gated_until_push_enabled(tmp_path, monkeypatch):
    """真实环境（不是模拟）没打开 insight_push：定时也只试算，不存待发、不出浮条，结果记进日志。"""
    late_setup(tmp_path)
    monkeypatch.setattr(insight, "tag_topics", lambda *a, **k: {"ran": False})
    tools = FakeTools(tmp_path)                       # sim_mode=False, insight_push=False
    out = insight.cycle(tools, ask=_fake_ask)
    assert out["gated"] and out["dry_run"] and insight.pending_status(tools.cfg) is None
    assert not (tmp_path / insight.STATE).exists()
    runs = [json.loads(x) for x in (tmp_path / insight.RUNS).read_text().splitlines()]
    assert runs[-1]["op"] == "gated_dry_run" and runs[-1]["message"].startswith("Psir，这几天看出")
