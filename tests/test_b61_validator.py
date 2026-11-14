"""b61：页面编排的数字校验不再把日期、计数、紧跟汉字的钟点当成编的数（以前九成的退回都是这类）。"""
from __future__ import annotations

import pytest

from pivis_health import canvas, v3
from pivis_health.canvas import CanvasError

POOL = [29.0, 31.0, 6.5, 93.0]


@pytest.mark.parametrize("text", ["11-07 的数据还没出来", "近 7 晚睡了多久", "按计划22:00 练膝盖", "守住 5/7 晚",
                                  "11/7 起按新窗口", "第 2 周效率 93%", "恢复 29，HRV 31"])
def test_headline_numbers_ok(text):
    v3._check_numbers(POOL, text, "headline")


@pytest.mark.parametrize("text,num", [("恢复 45", "45"), ("睡了 7.2 小时", "7.2")])
def test_headline_made_up_numbers_still_caught(text, num):
    with pytest.raises(ValueError, match=num):
        v3._check_numbers(POOL, text, "headline")


def test_canvas_text_skips_dates_and_counts_but_checks_clock():
    canvas.validate({"t": "text", "text": "近 7 晚 · 11-07 起"}, "hero", POOL, v3._has_number)
    with pytest.raises(CanvasError, match="23"):
        canvas.validate({"t": "countdown", "to": "23:45"}, "hero", POOL, v3._has_number)
