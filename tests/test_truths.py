"""开屏健康观：内容格式守规矩、最近看过的不重复、和正在做的项目相关的更常出现。"""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import date

from pivis_health import truths
from pivis_health.config import Config
from pivis_health.todos import TodoStore


def test_every_truth_is_complete_and_short_enough():
    assert len(truths.TRUTHS) == 100
    ids = set()
    for t in truths.TRUTHS:
        assert t["id"] not in ids
        ids.add(t["id"])
        assert len(t["headline"]) <= 16, t["headline"]
        assert len(t["lead"]) <= 40, t["lead"]
        assert 2 <= len(t["body"]) <= 3 and all(len(p) <= 110 for p in t["body"]), t["id"]
        assert t["do"] and t["sources"]
        assert t["topic"] in ("sleep", "sport", "stress", "food", "life")


def test_pick_skips_recently_seen(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    rng = random.Random(1)
    got = [truths.pick(cfg, rng)["id"] for _ in range(truths.KEEP_SEEN)]
    assert len(set(got)) == truths.KEEP_SEEN


def test_pick_prefers_current_projects(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    TodoStore(cfg).project_set({"id": "cbti", "name": "CBT-I", "board": "sleep", "days": 42}, date(2026, 11, 5))
    rng = random.Random(7)
    sleepy = 0
    for _ in range(300):
        (tmp_path / truths.SEEN_FILE).unlink(missing_ok=True)
        got = truths.pick(cfg, rng)["id"]
        if "sleep" in next(t for t in truths.TRUTHS if t["id"] == got)["tags"]:
            sleepy += 1
    share = sum(1 for t in truths.TRUTHS if "sleep" in t["tags"]) / len(truths.TRUTHS)
    assert sleepy / 300 > share + 0.15       # 相关的明显更常出现
