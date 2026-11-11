"""build 54：夜里醒（Apple 健康睡眠分段的「醒着」段）——按晚归组、去重、合并、去掉起床那段。"""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

from pivis_health import sleepwakes
from pivis_health.config import Config


def _tools(tmp_path, rows):
    db = tmp_path / "h.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE samples (device_id TEXT, sample_id TEXT, batch_id TEXT, type TEXT, start_at TEXT, end_at TEXT,"
                " unit TEXT, numeric_value REAL, category_value TEXT)")
    for i, (s, e) in enumerate(rows):
        con.execute("INSERT INTO samples VALUES ('d', ?, 'b', 'sleep_analysis', ?, ?, 'category', NULL, 'awake')", (f"s{i}", s, e))
    con.commit()
    con.close()
    cfg = replace(Config(), data_dir=tmp_path, vault_db=db, timezone="Asia/Shanghai")
    return SimpleNamespace(cfg=cfg, _today=lambda: date(2026, 11, 11), _now=lambda: datetime(2026, 11, 11, 9, 0), _whoop=None)


def test_groups_merges_and_drops_short_and_wake_up(tmp_path, monkeypatch):
    # 合成数据（北京时间）：不用真实记录
    rows = [("2026-11-10T22:40:00Z", "2026-11-10T22:52:00Z"),     # 06:40 12 分钟
            ("2026-11-10T22:40:00Z", "2026-11-10T22:52:00Z"),     # 重复
            ("2026-11-10T22:53:30Z", "2026-11-10T23:10:00Z"),     # 隔 1.5 分钟：合并 → 06:40 30 分钟
            ("2026-11-10T19:00:00Z", "2026-11-10T19:00:30Z"),     # 03:00 半分钟：太短
            ("2026-11-11T00:30:00Z", "2026-11-11T00:40:00Z"),     # 08:30 起床之后
            ("2026-11-09T22:20:00Z", "2026-11-09T22:35:00Z")]     # 前一晚 06:20 15 分钟
    tools = _tools(tmp_path, rows)
    from pivis_health import coach
    monkeypatch.setattr(coach, "sleep_week", lambda t, n, d: {"nights": [{"night_of": "2026-11-10", "end": "08:20"}]})
    d = sleepwakes.nights(tools, 3, 5)
    by = {r["night_of"]: r for r in d["nights"]}
    assert by["2026-11-10"]["wakes"] == [{"at": "06:40", "min": 30}] and by["2026-11-10"]["early"] == ["06:40"]
    assert by["2026-11-09"]["wakes"] == [{"at": "06:20", "min": 15}]
    assert d["summary"]["nights_with_early"] == 2 and d["summary"]["early_typical"] == "06:30"
    assert "06:30" in sleepwakes.brief_line(tools, date(2026, 11, 11))[0]
