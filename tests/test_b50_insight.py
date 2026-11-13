"""build 50：洞察二期（③ 交叉、④ 没注意到的）+ 三期（反馈回流调权、采纳后下一期出结果、确认的规律进记忆）。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from pivis_health import canvas, insight, insight_cross, journal
from pivis_health.agent_context import AgentContextStore
from pivis_health.todos import TodoStore
from test_b49_insight import CN, NOW, FakeTools, _fake_ask, cbti, inst, late_setup, put

TODAY = NOW.date()
DAYS = [TODAY - timedelta(days=i) for i in range(28, 0, -1)]          # 10/13 … 11/9


def _metric(monkeypatch, series: dict[str, dict[date, float]], nights: dict | None = None):
    monkeypatch.setattr(insight.Data, "metric", lambda self, name: series.get(name, {}))
    monkeypatch.setattr(insight.Data, "nights", lambda self: nights or {})


def stretch_project(tmp, done_days, start=date(2026, 10, 1)):
    todos = [inst(d, status="done" if d in done_days else "scheduled") for d in DAYS]
    put(tmp, todos, [cbti(start=start.isoformat())])


# ---------------------------------------------------------------- ③ 分组对比 / 前后天
def test_pair_practice_sleep(tmp_path, monkeypatch):
    done = set(DAYS[::2])
    stretch_project(tmp_path, done)
    sleep = {d: (7.0 if d in done else 6.3) + (0.1 if d.day % 3 == 0 else 0) for d in DAYS}
    _metric(monkeypatch, {"sleep": sleep})
    cands = insight_cross.pair_candidates(insight.Data(FakeTools(tmp_path)))
    c = next(c for c in cands if c["feature"] == "proj:cbti" and c["outcome"] == "sleep_h")
    assert c["numbers"]["n_a"] == 14 and c["numbers"]["n_b"] == 14 and c["better"] is True
    assert c["facts"][0].startswith("做了「睡眠计划」的晚上（14 次）睡着时长平均")
    assert c["option"] == "「睡眠计划」每天都做，试两周"
    assert [r["hi"] for r in c["split"]["rows"]] == [True, False] and c["split"]["rows"][0]["frac"] == 1.0
    assert len(c["dotstrip"]["items"]) == 28


def test_pair_needs_difference_groups_and_four_weeks(tmp_path, monkeypatch):
    done = set(DAYS[::2])
    stretch_project(tmp_path, done)
    _metric(monkeypatch, {"sleep": {d: 6.5 + (0.1 if d in done else 0) for d in DAYS}})     # 差 0.1：在波动里
    assert not insight_cross.pair_candidates(insight.Data(FakeTools(tmp_path)))
    stretch_project(tmp_path, set(DAYS[:4]))                                               # 做了只有 4 次
    _metric(monkeypatch, {"sleep": {d: 7.5 if d in DAYS[:4] else 6.3 for d in DAYS}})
    assert not insight_cross.pair_candidates(insight.Data(FakeTools(tmp_path)))
    stretch_project(tmp_path, done)                                                        # 只有 15 天数据
    _metric(monkeypatch, {"sleep": {d: 7.0 if d in done else 6.3 for d in DAYS[-15:]}})
    assert not insight_cross.pair_candidates(insight.Data(FakeTools(tmp_path)))


def test_pair_away_then_three_days(tmp_path, monkeypatch):
    put(tmp_path, [], [])
    away = {date(2026, 10, 18), date(2026, 10, 28)}
    (tmp_path / "scene_daily.json").write_text(json.dumps({d.isoformat(): {"away_night": d in away} for d in DAYS}))
    after = {d + timedelta(days=k) for d in away for k in (1, 2, 3)}
    rec = {d: (48.0 if d in after else 63.0) + (2 if d.day % 2 else -2) for d in DAYS}
    _metric(monkeypatch, {"recovery": rec})
    c = next(c for c in insight_cross.pair_candidates(insight.Data(FakeTools(tmp_path))) if c["feature"] == "away")
    assert c["numbers"]["n_a"] == 6 and c["better"] is False and "在外过夜之后的 3 天（6 次）恢复平均" in c["facts"][0]
    assert c["option"] == "外宿后 3 天换轻一点的安排"


def test_pair_late_dinner_hrv(tmp_path, monkeypatch):
    late = set(DAYS[1::4])
    todos = [{"id": f"dinner-{d}", "date": d.isoformat(), "when": "19:00", "title": "拍晚饭", "board": "life",
              "kind": "photo", "status": "done",
              "record": {"at": f"{d.isoformat()}T{'21:10' if d in late else '19:20'}:00"}} for d in DAYS]
    put(tmp_path, todos, [])
    hrv = {d: (30.0 if (d - timedelta(days=1)) in late else 40.0) for d in DAYS}
    _metric(monkeypatch, {"hrv": hrv})
    c = next(c for c in insight_cross.pair_candidates(insight.Data(FakeTools(tmp_path))) if c["feature"] == "late_dinner")
    assert c["numbers"]["avg_a"] == 30 and c["numbers"]["avg_b"] == 40 and c["option"] == "晚饭提前到 20:30 前，试两周"


# ---------------------------------------------------------------- ④ 平台期 / 最好的那些天 / 对话主题
def _plateau_setup(tmp, monkeypatch, late_values):
    start = TODAY - timedelta(days=28)
    proj = {**cbti(start=start.isoformat()), "id": "train", "name": "力量训练", "board": "sport"}
    todos = [inst(TODAY - timedelta(days=i), pid="train", key="s", status="scheduled" if i in (3, 11) else "done")
             for i in range(1, 22)]
    put(tmp, todos, [proj])
    rec = {start - timedelta(days=14 - i): 50.0 + (3 if i % 2 else -3) for i in range(14)}
    rec.update({start + timedelta(days=i): 52.0 for i in range(7)})
    rec.update({start + timedelta(days=7 + i): 62.0 + (1 if i % 2 else -1) for i in range(7)})
    rec.update({TODAY - timedelta(days=14 - i): v for i, v in enumerate(late_values)})
    _metric(monkeypatch, {"recovery": rec})


def test_plateau_found_only_when_changed_then_flat(tmp_path, monkeypatch):
    _plateau_setup(tmp_path, monkeypatch, [62.0 + (1 if i % 2 else -1) for i in range(14)])
    c = next(c for c in insight_cross.plateau_candidates(insight.Data(FakeTools(tmp_path))))
    assert c["numbers"] == {"before": 50, "week2": 62, "prev": 62, "recent": 62}
    _plateau_setup(tmp_path, monkeypatch, [62.0 + i for i in range(14)])                  # 还在涨：不是平台期
    assert not insight_cross.plateau_candidates(insight.Data(FakeTools(tmp_path)))


def test_best_days_and_dedupe(tmp_path, monkeypatch):
    put(tmp_path, [], [])
    early = {DAYS[5], DAYS[12], DAYS[19], DAYS[24]}
    nights = {d: {"start_local": f"{d.isoformat()}T{'23:00' if d in early else '00:10'}:00+08:00"} for d in DAYS}
    for d in DAYS:                                        # 00:10 是第二天凌晨：start_local 写成当天 00:10 也按 24:10 算
        if d not in early:
            nights[d]["start_local"] = f"{(d + timedelta(days=1)).isoformat()}T00:10:00+08:00"
    rec = {d: (72.0 if (d - timedelta(days=1)) in early else 58.0 + (d.day % 5)) for d in DAYS}
    _metric(monkeypatch, {"recovery": rec}, nights)
    data = insight.Data(FakeTools(tmp_path))
    c = next(c for c in insight_cross.best_day_candidates(data) if c["feature"] == "early_bed")
    assert c["numbers"]["top_hit"] == 3 and c["numbers"]["rest_pct"] < 10
    assert not insight_cross.best_day_candidates(data, taken={("early_bed", "recovery")})


def test_topics_unmanaged(tmp_path):
    cfg = FakeTools(tmp_path).cfg
    put(tmp_path, [], [])
    for d in ("2026-11-01", "2026-11-03", "2026-11-03", "2026-11-07"):
        journal.append(cfg, insight.TOPICS, {"date": d, "kind": "body", "label": "肩膀"})
    for d in ("2026-11-02", "2026-11-05"):
        journal.append(cfg, insight.TOPICS, {"date": d, "kind": "concern", "label": "累"})
    cands = insight_cross.topic_candidates(insight.Data(FakeTools(tmp_path)))
    assert [c["label"] for c in cands] == ["肩膀"] and cands[0]["numbers"]["days"] == 3
    assert "看医生或康复师" in cands[0]["facts"][1]
    put(tmp_path, [], [{**cbti(), "id": "shoulder", "name": "肩膀康复"}])                 # 已经有计划在管
    assert not insight_cross.topic_candidates(insight.Data(FakeTools(tmp_path)))


def test_split_and_dotstrip_cards(tmp_path):
    tools = FakeTools(tmp_path)
    (tmp_path / insight.CANDS).write_text(json.dumps({"c11104": {
        "split": {"rows": [{"label": "做了", "text": "7", "unit": "小时", "frac": 1.0, "hi": True}], "caption": "x"},
        "dotstrip": {"items": [{"label": "11/1", "on": True, "hi": False}], "legend": {"on": "做了"}}}}))
    lay = canvas.validate({"type": "layout", "layout": {"t": "v", "children": [
        {"t": "split", "bind": "insight:c11104.split"}, {"t": "dotstrip", "bind": "insight:c11104.dotstrip"}]}}, "chat")
    sp, ds = canvas.resolve(tools, lay, TODAY, NOW)["children"]
    assert sp["rows"][0]["hi"] is True and sp["caption"] == "x" and ds["items"][0]["on"] is True
    with pytest.raises(canvas.CanvasError):
        canvas.validate({"t": "split", "bind": "insight:c11104.response"}, "chat")


# ---------------------------------------------------------------- 三期：反馈回流
def simtools(tmp, now=NOW, **kw):
    """模拟时钟：日志、待办记录都走同一个钟（真实环境里是 Psir 那边的钟）。"""
    t = FakeTools(tmp, sim_mode=True, insight_push=True, **kw)
    set_now(t, now)
    return t


def set_now(tools, now):
    tools.now = now
    (tools.cfg.data_dir / "sim_clock.json").write_text(json.dumps({"now": now.replace(tzinfo=CN).isoformat()}))


def record_at(tools, scope, payload, at):
    """记一条记忆，recorded_at 写成本机时间里的 at（和真实环境一样是本机时区、不带时区）。"""
    store = AgentContextStore(tools.cfg)
    store.record(scope, payload)
    raw = json.loads(store.path.read_text())
    raw["entries"][-1]["recorded_at"] = at.replace(tzinfo=CN).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    store.path.write_text(json.dumps(raw, ensure_ascii=False))


def _opened(tools, monkeypatch, texts=()):
    """跑一期并点开；texts = 点开后 Psir 在主对话里说的话。"""
    monkeypatch.setattr(insight, "tag_topics", lambda *a, **k: {"ran": False})
    out = insight.cycle(tools, ask=_fake_ask, force=True)
    insight.open_pending(tools, out["pending"], send=lambda *a: {"ok": True})
    monkeypatch.setattr(insight.Data, "user_texts", lambda self, since: [(since, t) for t in texts])
    return out


def test_feedback_adopted_followup_and_learned(tmp_path, monkeypatch):
    late_setup(tmp_path)
    tools = simtools(tmp_path)
    state = {"scans": [{"keys": ["remind-late-stretch-stretch".replace("stretch-stretch", "cbti-stretch")]}]}
    (tmp_path / insight.STATE).write_text(json.dumps(state))
    _opened(tools, monkeypatch)
    st = json.loads((tmp_path / insight.STATE).read_text())
    f = st["feedback"][-1]
    assert f["outcome"] == "pending" and f["applied"] is True and f["type"] == "remind_late"
    learned = [e for e in AgentContextStore(tools.cfg).snapshot()["entries"] if e["scope"].startswith("learn.remind.")]
    assert learned and "22:40" in learned[0]["payload"]["rule"]
    # 3 天后：没改回 → 采纳；挪到 23:40 以后做了两次，一次当场
    for i, off in enumerate((5, 70)):
        d = TODAY + timedelta(days=i)
        t = inst(d, when="23:40")
        data = json.loads((tmp_path / "todos_v3.json").read_text())
        data["todos"][t["id"]] = t
        (tmp_path / "todos_v3.json").write_text(json.dumps(data))
        at = datetime.combine(d, datetime.min.time()) + timedelta(hours=23, minutes=40 + off)
        journal.append(tools.cfg, journal.TODOS, {"at": at.isoformat(timespec="seconds"), "op": "user_start", "id": t["id"]})
    set_now(tools, NOW + timedelta(days=4))
    m = insight.mine(tools)
    assert {"key": "remind-late-cbti-stretch", "outcome": "adopted"} in m["feedback_closed"]
    fu = next(c for c in m["picked"] if c["type"] == "followup")
    assert fu["tier"] == 0 and "提醒挪到 23:40 以后，2 次里 1 次在 30 分钟内开始（之前 9 次里 2 次）" in fu["facts"][1]


def test_feedback_option_picked_rejected_and_class_block(tmp_path, monkeypatch):
    late_setup(tmp_path)
    tools = simtools(tmp_path)
    monkeypatch.setattr(insight, "tag_topics", lambda *a, **k: {"ran": False})
    st = {"feedback": [
        {"type": "remind_late", "key": "k1", "outcome": "rejected", "at": "2026-11-01T09:00:00", "decided_at": "2026-11-01T10:00:00"},
        {"type": "remind_late", "key": "k2", "outcome": "rejected", "at": "2026-11-04T09:00:00", "decided_at": "2026-11-04T10:00:00"}]}
    w, blocked = insight.type_weights(st, TODAY)
    assert blocked == {"remind_late"} and w["remind_late"] == 0.25
    m = insight.mine(tools, state=st)
    assert next(c for c in m["dropped"] if c["type"] == "remind_late")["dropped"].startswith("这一类 4 周内被否了")
    # 被否：记了 correction.insight.<topic> → rejected，learn 那条撤掉
    (tmp_path / insight.STATE).write_text(json.dumps({"scans": [{"keys": ["remind-late-cbti-stretch"]}]}))
    _opened(tools, monkeypatch)
    record_at(tools, "correction.insight.remind-late-cbti-stretch", {"rule": "那个时间是故意的"}, NOW + timedelta(hours=1))
    state = json.loads((tmp_path / insight.STATE).read_text())
    m = insight.mine(tools, state=state)
    assert {"key": "remind-late-cbti-stretch", "outcome": "rejected"} in m["feedback_closed"]
    assert not [e for e in AgentContextStore(tools.cfg).snapshot()["entries"] if e["scope"].startswith("learn.remind.")]


def test_feedback_reverted_and_ignored(tmp_path, monkeypatch):
    late_setup(tmp_path)
    tools = simtools(tmp_path)
    _opened(tools, monkeypatch, texts=["都先不动"])
    TodoStore(tools.cfg).project_set({"id": "cbti", "daily": [{"key": "stretch", "when": "22:40", "title": "睡前拉伸",
                                                                "kind": "done"}]}, TODAY)
    state = json.loads((tmp_path / insight.STATE).read_text())
    m = insight.mine(tools, state=state)
    assert {"key": "remind-late-cbti-stretch", "outcome": "reverted"} in m["feedback_closed"]
    assert not [c for c in m["picked"] if c["type"] == "followup"]


def test_four_weeks_loop(tmp_path, monkeypatch):
    """连续 4 周：否掉的同类不再出现；采纳的下一期有结果。"""
    late_setup(tmp_path)
    tools = simtools(tmp_path)
    monkeypatch.setattr(insight, "tag_topics", lambda *a, **k: {"ran": False})
    seen = []
    for week in range(4):
        set_now(tools, NOW + timedelta(days=7 * week))
        out = insight.cycle(tools, ask=_fake_ask, force=True)
        keys = [c["type"] for c in out.get("candidates") or []]
        seen.append(keys)
        if out.get("pending"):
            insight.open_pending(tools, out["pending"], send=lambda *a: {"ok": True})
            if week == 0:
                record_at(tools, "correction.insight.remind-late-cbti-stretch", {"rule": "不对"}, tools.now + timedelta(hours=1))
    assert "remind_late" in seen[0]
    assert all("remind_late" not in s for s in seen[1:])


def test_remind_stats(tmp_path):
    late_setup(tmp_path)
    st = insight.reminder_stats(insight.Data(FakeTools(tmp_path)))
    s = next(x for x in st if x["group"] == "cbti:stretch")
    assert (s["when"], s["n"], s["on_time"], s["rate"], s["typical"], s["ignored_streak"]) == \
        ("22:40", 9, 2, 22, "23:47", 0)


def test_project_feature_candidates_carry_project(tmp_path, monkeypatch):
    done = set(DAYS[::2])
    stretch_project(tmp_path, done)
    _metric(monkeypatch, {"sleep": {d: 7.0 if d in done else 6.3 for d in DAYS}})
    c = next(c for c in insight_cross.candidates(insight.Data(FakeTools(tmp_path))) if c["type"] == "cross_pair")
    assert c["project"] == "cbti" and c["board"] == "sleep"
