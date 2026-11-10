"""老大定下的偏好：记下后写进 AGENTS.local.md（build 51 起不再写进 AGENTS.md），改口替换。"""
from __future__ import annotations

from dataclasses import replace

from pivis_health import prefs
from pivis_health.agent_context import AgentContextStore
from pivis_health.config import Config


def test_sync_writes_block_and_replaces_on_change(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    md = tmp_path / "AGENTS.md"
    md.write_text("# 规则\n\n正文不动\n", encoding="utf-8")
    store = AgentContextStore(cfg)
    store.record("pref.chart", {"rule": "图表一律用折线，不用柱状图"}, "休息", "我喜欢折线")
    store.record("habit.bath", {"meaning": "洗澡"}, "休息", "不是偏好，不进这一段")
    assert prefs.sync_agents_md(cfg, md)["ok"]
    local = tmp_path / "AGENTS.local.md"
    text = local.read_text(encoding="utf-8")
    assert "图表一律用折线" in text and "洗澡" not in text
    assert md.read_text(encoding="utf-8") == "# 规则\n\n正文不动\n"        # AGENTS.md 不动（DSH 不会因为记偏好再补一份全文）
    store.record("pref.chart", {"rule": "图表用柱状图"}, "休息", "还是柱状图吧")
    prefs.sync_agents_md(cfg, md)
    text = local.read_text(encoding="utf-8")
    assert "图表用柱状图" in text and "一律用折线" not in text
    assert text.count(prefs.START) == 1 and text.count(prefs.END) == 1
    assert prefs.sync_agents_md(cfg, md)["changed"] is False


def test_old_block_moves_out_of_agents_md(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    md = tmp_path / "AGENTS.md"
    md.write_text(f"# 规则\n\n正文\n\n{prefs.START}\n- 旧偏好\n{prefs.END}\n", encoding="utf-8")
    AgentContextStore(cfg).record("pref.chart", {"rule": "图表用折线"}, "休息", "x")
    out = prefs.sync_agents_md(cfg, md)
    assert out["ok"] and out.get("moved_from_agents_md")
    assert md.read_text(encoding="utf-8") == "# 规则\n\n正文\n"
    assert "图表用折线" in (tmp_path / "AGENTS.local.md").read_text(encoding="utf-8")


def test_baseline_pref_reads_window(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    assert prefs.baseline_pref(cfg) is None
    AgentContextStore(cfg).record("pref.baseline", {"rule": "跟上一周比", "window": "prev_week"}, "main", "跟一周前比")
    assert prefs.baseline_pref(cfg) == "prev_week"


def test_symlinked_agents_md_is_left_alone(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    real = tmp_path / "real.md"; real.write_text("x", encoding="utf-8")
    link = tmp_path / "AGENTS.md"; link.symlink_to(real)
    assert prefs.sync_agents_md(cfg, link)["ok"] is False
    assert real.read_text(encoding="utf-8") == "x"


# ---- 老大纠正过的专业要点：渲染进 AGENTS.md；同一件事第二次纠正要求写进 skill
def test_corrections_render_and_repeat(tmp_path):
    from dataclasses import replace as _replace
    import pytest as _pytest
    from pivis_health import prefs as _prefs
    from pivis_health.agent_context import AgentContextStore, check_agent_scope
    from pivis_health.config import Config
    cfg = _replace(Config(), data_dir=tmp_path)
    check_agent_scope("correction.sleep.bath")                     # 新分类被接受
    with _pytest.raises(ValueError):
        _prefs.check_correction(cfg, "correction.sleep.bath", {"wrong": "x"})
    p1 = _prefs.check_correction(cfg, "correction.sleep.bath", {"rule": "热水澡在最早上床前 1–2 小时洗完", "wrong": "说成睡前随便洗"})
    assert p1["times"] == 1 and "needs_skill" not in p1
    AgentContextStore(cfg).record("correction.sleep.bath", p1, source_session="休息", reason="test")
    p2 = _prefs.check_correction(cfg, "correction.sleep.bath", {"rule": "热水澡在最早上床前 1–2 小时洗完"})
    assert p2["times"] == 2 and p2["needs_skill"] is True
    block = _prefs.render_block([], [], _prefs.corrections(cfg))
    assert "老大纠正过的专业要点" in block and "热水澡在最早上床前 1–2 小时洗完；之前错在：说成睡前随便洗" in block
