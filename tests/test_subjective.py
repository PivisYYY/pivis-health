"""主观库：记录、轮换、规则、推送去重与配额。"""
from __future__ import annotations

from datetime import date

from pivis_health.subjective import SubjectiveStore


def test_record_and_entries_roundtrip(tmp_path):
    s = SubjectiveStore(tmp_path / "s.sqlite3")
    s.record("2026-10-28", "behavior_answer", {"question_id": "dinner_time", "answer": "20点后"})
    rows = s.entries(kinds=["behavior_answer"])
    assert rows[0]["payload"]["answer"] == "20点后"
    import os
    assert os.stat(s.db_path).st_mode & 0o777 == 0o600  # 权限门禁


def test_rotation_prefers_unanswered_and_skips_today(tools_env):
    from pivis_health.report import QUESTION_POOL
    subj = tools_env.subj
    day = "2026-10-28"
    first = subj.rotation_pick(QUESTION_POOL, day, k=2)
    assert len(first) == 2
    # 答掉一个问题
    subj.record(day, "behavior_answer", {"question_id": first[0]["id"], "answer": "x"})
    second = subj.rotation_pick(QUESTION_POOL, day, k=2)
    assert first[0]["id"] not in [q["id"] for q in second]  # 今天已答的跳过
    assert second[0]["id"] == first[1]["id"]


def test_custom_rules_crud(tools_env):
    rid = tools_env.subj.add_rule("hrv_sdnn", "below", 35.0, 3, "alert", "连三天低于35提醒我")
    rules = tools_env.subj.list_rules()
    assert any(r["id"] == rid and r["metric"] == "hrv_sdnn" for r in rules)
    assert tools_env.subj.remove_rule(rid) is True
    assert all(r["id"] != rid for r in tools_env.subj.list_rules())


def test_push_once_dedup_and_limit(tools_env):
    day = date(2026, 10, 28)
    assert tools_env.push_reserve("morning", day)["allowed"] is True
    assert tools_env.push_reserve("morning", day)["allowed"] is False  # 当日去重
    assert tools_env.push_reserve("evening", day)["allowed"] is True
    assert tools_env.push_reserve("alert", day)["allowed"] is True
    assert tools_env.push_reserve("extra", day)["allowed"] is False  # 超 ≤3/天 配额
