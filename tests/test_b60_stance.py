"""b60：立场（stance.*）前后一致、改要有新信息；方案书（protocol.*）带理由；专业要点按情况常驻。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from pivis_health import prefs
from pivis_health.agent_context import AgentContextStore, check_agent_scope
from pivis_health.config import Config
from pivis_health.todos import TodoStore


@pytest.fixture()
def cfg(tmp_path):
    return replace(Config(), data_dir=tmp_path)


def test_stance_needs_why_and_new_info_to_change(cfg):
    check_agent_scope("stance.sleep.nap")
    with pytest.raises(ValueError, match="why"):
        prefs.check_stance(cfg, "stance.sleep.nap", {"rule": "窗口期不午睡"})
    p1 = prefs.check_stance(cfg, "stance.sleep.nap", {"rule": "窗口期不午睡", "why": "午睡消耗睡眠压力（A）"})
    AgentContextStore(cfg).record("stance.sleep.nap", p1, source_session="休息", reason="t")
    # Psir 只是不同意、没有新信息：不许改
    with pytest.raises(ValueError, match="changed_because"):
        prefs.check_stance(cfg, "stance.sleep.nap", {"rule": "可以午睡 20 分钟", "why": "Psir 以前午休没事"})
    # 同一立场补充理由：可以
    assert prefs.check_stance(cfg, "stance.sleep.nap", {"rule": "窗口期不午睡", "why": "补充：近 7 晚入睡偏晚"})
    p3 = prefs.check_stance(cfg, "stance.sleep.nap", {"rule": "允许 12–13 点坐着眯 ≤20 分钟",
                                                       "why": "白天犯困影响开车", "changed_because": "Psir 说开车犯困（安全）"})
    assert p3["was"] == "窗口期不午睡"


def test_protocol_steps_need_why(cfg):
    check_agent_scope("protocol.cbti")
    with pytest.raises(ValueError):
        prefs.check_protocol({"rule": "CBT-I", "steps": [{"rule": "08:20 起床"}]})
    ok = prefs.check_protocol({"rule": "CBT-I 6 周", "steps": [{"rule": "08:20 起床", "why": "固定生物钟"}]})
    assert ok["steps"][0]["why"] == "固定生物钟"


def test_block_renders_protocol_stance_and_cores(cfg):
    store = TodoStore(cfg)
    store.project_set({"id": "cbti", "name": "CBT-I", "board": "sleep", "start": "2026-11-08", "days": 42,
                       "goal": "睡得稳", "daily": []}, date(2026, 11, 13), None)
    ctx = AgentContextStore(cfg)
    ctx.record("protocol.cbti", {"rule": "固定起床 + 窗口", "steps": [{"rule": "08:20 起床", "why": "固定生物钟最要紧"}],
                                 "expect": "前两周白天会困", "adjust": "周复盘效率 ≥90% +15 分钟"}, source_session="休息", reason="t")
    ctx.record("protocol.old", {"rule": "结束了的", "steps": [{"rule": "x", "why": "y"}]}, source_session="休息", reason="t")
    ctx.record("stance.sleep.nap", {"rule": "窗口期不午睡", "why": "消耗睡眠压力"}, source_session="休息", reason="t")
    ctx.record("profile.safety", {"rule": "半月板 2 级"}, source_session="运动", reason="t")
    block = prefs.render_block(prefs.active_prefs(cfg), prefs.known_facts(cfg), prefs.corrections(cfg),
                               prefs.stances(cfg), prefs.protocols(cfg), prefs.cores(cfg))
    assert "进行中的方案书" in block and "08:20 起床 —— 为什么：固定生物钟最要紧" in block and "前两周白天会困" in block
    assert "结束了的" not in block                                  # 不是进行中的项目
    assert "你已经表过的态" in block and "窗口期不午睡 —— 理由：消耗睡眠压力" in block
    titles = [t for t, _ in prefs.cores(cfg)]
    assert titles == ["睡眠 / CBT-I", "康复（有伤病时）"]           # 没有运动项目：不放训练要点
    assert "先分型" in block and "半月板 2 级" in block


def test_rules_teach_mentor_stance():
    from pathlib import Path as _P
    repo = _P(__file__).resolve().parent.parent
    agents = (repo / "agent/AGENTS-v3.md").read_text(encoding="utf-8")
    cbti = (repo / "agent/skills/cbti/SKILL.md").read_text(encoding="utf-8")
    assert "导师立场" in agents and "changed_because" in agents and "stance.<领域>.<主题>" in agents
    assert "不上传到任何公网网站" in agents                          # 红线 11
    assert "他是最后拍板的人" not in cbti and "没守住窗口" in cbti and "适应期（前两周）不午睡" in cbti
    for skill in ("cbti", "rehab-coach", "training-coach"):
        assert (repo / f"agent/skills/{skill}/references/core.md").stat().st_size < 2200   # 常驻要点要短


def test_card_check_flags_agreeing_opener():
    from pivis_health import cards
    assert any("附和" in x for x in cards.check_text("你说得对，20 分钟影响不大。")["problems"])
    assert any("附和" in x for x in cards.check_text("问得对，这条最容易做反。")["problems"])
    assert not any("附和" in x for x in cards.check_text("不睡，适应期先守住。")["problems"])
