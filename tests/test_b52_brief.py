"""build 52：全盘简报（服务器算好的全部数据 + 今晚时间线 + 交叉信号 + 数据缺口）、目标。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from pivis_health import brief, goals
from pivis_health.agent_context import AgentContextStore

CN = timezone(timedelta(hours=8))


def test_timeline_counts_back_from_bed():
    tl = dict((b, a) for a, b in brief.timeline("00:05", "08:20"))
    assert tl["之后不碰咖啡因（咖啡、浓茶、奶茶、可乐、能量饮料）"] == "16:05"
    assert tl["之间洗完热水澡（40℃ 左右 10–15 分钟）"] == "22:05–23:05"
    assert tl["开始放松：灯调暗、放下手机、拉伸或呼吸"] == "23:05–23:35"
    assert tl["最早上床（早于这个点不躺）"] == "00:05"
    assert brief.timeline(None, "08:20") == []
    assert dict((b, a) for a, b in brief.timeline("23:00", None))["之后不碰咖啡因（咖啡、浓茶、奶茶、可乐、能量饮料）"] == "15:00"


def test_signals_rules():
    base = lambda m, sd: {"mean": m, "sd": sd, "n": 30}  # noqa: E731
    state = {"whoop_recovery": {"value": 30, "base": base(60, 15)},
             "respiratory_rate": {"value": 17.2, "base": base(16.2, 0.4)},
             "resting_heart_rate": {"value": 66, "base": base(61, 3)}}
    sleep = {"effs": [95, 94, 96, 93, 91, 84, 92], "avg": 6.5, "avg_need": 9.0,
             "starts": [85 + 24 * 60, 80 + 24 * 60, 120 + 24 * 60, 60 + 24 * 60], "ends": [460, 500, 655, 492], "debt5": 13.0}
    sig = brief._signals(state, sleep, {}, [{"id": "daily-log", "name": "饮食记录", "pct": 14, "n": 7}])
    text = "\n".join(sig)
    assert "着凉" in text and "恢复日" in text
    assert "睡眠机会不足" in text and "不要压缩窗口" in text
    assert "作息偏晚" in text and "固定起床" in text and "睡眠债" in text
    assert "饮食记录" in text and "14%" in text
    calm = brief._signals({"whoop_recovery": {"value": 80, "base": base(60, 15)}}, {}, {}, [])
    assert calm == []


def test_goals_store(tmp_path):
    from dataclasses import replace
    from pivis_health.config import Config
    cfg = replace(Config(), data_dir=tmp_path)
    with pytest.raises(ValueError):
        goals.set_goal(cfg, {"id": "w", "title": "减重", "metric": "weight"}, date(2026, 11, 10))   # 没有 target
    goals.set_goal(cfg, {"id": "weight", "title": "减到 70 kg", "metric": "weight", "target": 70}, date(2026, 11, 10))
    goals.set_goal(cfg, {"id": "weight", "deadline": "2027-03-01"}, date(2026, 11, 11))
    g = goals.load(cfg)
    assert len(g) == 1 and g[0]["deadline"] == "2027-03-01" and g[0]["created"] == "2026-11-10"
    goals.set_goal(cfg, {"id": "weight", "status": "done"}, date(2026, 12, 1))
    assert goals.load(cfg) == [] and len(goals.load(cfg, include_done=True)) == 1


def test_build_and_refresh(tools_env, monkeypatch, tmp_path):
    tools = tools_env
    monkeypatch.setattr(type(tools), "_now", lambda self: datetime(2026, 11, 10, 9, 0, tzinfo=CN))
    AgentContextStore(tools.cfg).record("sleep.cbti", {"earliest_bed": "00:05", "wake": "08:20"}, "休息", "t")
    AgentContextStore(tools.cfg).record("profile.safety", {"flags": ["半月板损伤"], "rule": "x"}, "运动", "t")
    goals.set_goal(tools.cfg, {"id": "sleep8", "title": "每晚睡够 8 小时", "metric": "sleep_h", "target": 8},
                   date(2026, 11, 10))
    b = brief.build(tools)
    text = b["text"]
    assert text.startswith("【全盘 · 11-10 周二 09:00】")
    assert "今晚时间线（按 CBT-I 00:05 上床、08:20 起床 倒推）" in text
    assert "身体限制：半月板损伤" in text and "每晚睡够 8 小时" in text
    assert "档案还缺：" in text and "伤病和限制" not in text.split("档案还缺：")[1]
    assert len(text.encode()) < 4000
    # 写文件：第一次写；没变不重写；数据变了才重写
    path = tmp_path / "CLAUDE.local.md"
    assert brief.refresh(tools, path=path)["written"] is True
    assert "Psir 此刻的全盘" in path.read_text(encoding="utf-8")
    assert brief.refresh(tools, path=path)["written"] is False
    AgentContextStore(tools.cfg).record("sleep.cbti", {"earliest_bed": "23:50", "wake": "08:00"}, "休息", "t")
    assert brief.refresh(tools, path=path)["written"] is True


def test_refresh_refuses_foreign_workspace(tools_env):
    out = brief.refresh(tools_env)            # 测试的数据目录不属于工作区：不写
    assert out["ok"] is False


def test_plan_lint_rules():
    from pivis_health import plan_lint
    plan = {"bed": "00:05", "wake": "08:20", "cbti": True}
    p = lambda **t: plan_lint.problems(t, plan)  # noqa: E731
    assert p(title="23:15 前洗完澡", when="23:15")                 # 离上床 50 分钟
    assert not p(title="洗热水澡", when="22:15")                    # 1 小时 50 分
    assert p(title="网球专项力量", when="22:30")                    # 剧烈运动离上床 95 分钟
    assert not p(title="膝盖康复", when="22:30")                    # 康复动作不算剧烈
    assert not p(title="睡前拉伸", when="23:30")
    assert p(title="上床", when="23:40")                            # 早于最早上床
    assert not p(title="上床", when="00:05")
    assert p(title="午睡", when="15:30", duration_min=20)
    assert p(title="午睡", when="13:00", duration_min=40)
    assert not p(title="午睡", when="13:00", duration_min=20)
    assert plan_lint.problems({"title": "洗澡", "when": "23:30"}, {}) == []   # 没有睡眠安排：不查


def test_agent_card_blocked_on_conflict(tools_env):
    from pivis_health.todos import TodoError, TodoStore
    tools = tools_env
    AgentContextStore(tools.cfg).record("sleep.cbti", {"earliest_bed": "00:05", "wake": "08:20"}, "休息", "t")
    st = TodoStore(tools.cfg)
    with pytest.raises(TodoError, match="和睡眠安排冲突"):
        st.add({"board": "sleep", "when": "23:15", "title": "洗完澡", "kind": "done"}, date(2026, 11, 10))
    t = st.add({"board": "sleep", "when": "22:15", "title": "洗完澡", "kind": "done"}, date(2026, 11, 10))
    with pytest.raises(TodoError, match="和睡眠安排冲突"):
        st.update(t["id"], {"when": "23:30"})
    st.update(t["id"], {"when": "23:30"}, by="user")                  # Psir 自己挪的不拦


def test_event_filter_drops_repeats():
    from pivis_health import event_dispatch as ed
    def loc(i, lat, lon, ts):
        return {"event_id": f"l{i}", "type": "location", "payload": {"lat": lat, "lon": lon}, "received_ts": ts}
    evs = [loc(1, 10.0, 20.0, 0), loc(2, 10.0001, 20.0001, 600), loc(3, 10.0, 20.0, 1200),
           {"event_id": "b1", "type": "bluetooth_scan", "payload": {"devices": []}, "received_ts": 1300},
           loc(4, 10.1, 20.0, 1500),                                     # 挪了 11 km
           loc(5, 10.1, 20.0, 1500 + 7 * 3600),                          # 同一处，但离上次交过去 7 小时
           {"event_id": "p1", "type": "location_permission", "payload": {"state": "denied"}, "received_ts": 1600},
           {"event_id": "p2", "type": "location_permission", "payload": {"state": "denied"}, "received_ts": 1700}]
    keep, skip, st = ed.classify(evs, {})
    assert [e["event_id"] for e in keep] == ["l1", "l4", "l5", "p1"]
    assert {e["event_id"] for e in skip} == {"l2", "l3", "b1", "p2"}


def test_dispatch_filtered_batches(tmp_path):
    import json as _json
    from dataclasses import replace as _replace
    from pivis_health.config import Config
    from pivis_health import event_dispatch as ed
    from pivis_health.event_ingest import EventStore
    cfg = _replace(Config(), data_dir=tmp_path)
    with EventStore(tmp_path / "events.sqlite3") as store:
        for i, (typ, payload) in enumerate([("location", {"lat": 10.0, "lon": 20.0}), ("location", {"lat": 10.0, "lon": 20.0}),
                                           ("bluetooth_scan", {"devices": []})]):
            store.append({"event_id": f"e{i}", "type": typ, "occurred_at": f"2026-11-10T09:0{i}:00+08:00",
                          "source": "t", "payload": payload})
    sent = []
    out = ed.dispatch_filtered(cfg, send_text=lambda text: sent.append(text) or True)
    assert out["dispatched"] == 1 and out["skipped"] == 2 and len(sent) == 1 and out["pending"] == 0
    assert "shared_context" not in sent[0] and len(sent[0]) < 3000
