"""老大定下的偏好：记下后写进 AGENTS.md 的固定一段，改口替换，不碰其他内容。"""
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
    text = md.read_text(encoding="utf-8")
    assert "正文不动" in text and "图表一律用折线" in text and "洗澡" not in text
    store.record("pref.chart", {"rule": "图表用柱状图"}, "休息", "还是柱状图吧")
    prefs.sync_agents_md(cfg, md)
    text = md.read_text(encoding="utf-8")
    assert "图表用柱状图" in text and "一律用折线" not in text
    assert text.count(prefs.START) == 1 and text.count(prefs.END) == 1


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
