"""b60：做 CBT-I 时简报只按 CBT-I 的口径说（不写睡眠债、需要多久、补觉），并写出窗口执行情况。"""
from __future__ import annotations

from pivis_health import brief
from test_canvas_parts import NOW, env  # noqa: F401  合成数据 + CBT-I 项目（01:30 后上床、08:30 起）


def test_brief_in_cbti_mode(env):  # noqa: F811
    text = brief.build(env, NOW)["text"]
    assert "睡眠债" not in text.replace("不提睡眠债", "")
    assert "需要 " not in text and "最多睡 20 分钟" not in text and "按周把窗口往需要的时长放" not in text
    assert "CBT-I：第 " in text and "窗口 01:30–08:30（7h）" in text
    # 合成的每晚 23:20 睡、06:20 起：7 晚都早于最早上床，起床早 130 分钟
    assert "守住 0/7 晚" in text and "早于最早上床 7 晚" in text and "比起床点早 30 分钟以上起 7 晚（中位早 130 分钟）" in text
    assert "先把窗口守住再谈效率" in text and "周中不改窗口" in text


def test_brief_without_cbti_keeps_sleep_need(tools_env):
    s = brief.build(tools_env)["sections"]
    assert not any(line.startswith("CBT-I") for line in s["sleep"])
    assert not any("做 CBT-I" in x for x in s["signals"])
