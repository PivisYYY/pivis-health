"""客户端同步状态、对话照片、App 重装导致的重复样本、WHOOP 断更时的睡眠兜底。"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from pivis_health import v3, viz
from pivis_health.readonly import _dedupe_app_installs


def test_dedupe_app_installs_counts_each_sample_once():
    # (sample_id, type, start, end, unit, value, category, device)
    rows = [
        ("hkagg-step_count-20261102", "step_count", "2026-11-01T16:00:00Z", None, "count", 14076.0, None, "iphone-A"),
        ("hkagg-step_count-20261102", "step_count", "2026-11-01T16:00:00Z", None, "count", 14076.0, None, "iphone-B"),
        ("hkagg-step_count-20261105", "step_count", "2026-11-04T16:00:00Z", None, "count", 755.0, None, "iphone-A"),
        ("hkagg-step_count-20261105", "step_count", "2026-11-04T16:00:00Z", None, "count", 3890.0, None, "iphone-C"),
        ("hkslp-1", "sleep_analysis", "2026-11-04T15:00:00Z", None, "category", None, "asleep_core", "iphone-A"),
        ("hkslp-1", "sleep_analysis", "2026-11-04T15:00:00Z", None, "category", None, "asleep_core", "iphone-B"),
        ("imported-1", "step_count", "2026-10-20T01:00:00Z", None, "count", 100.0, None, "69c140de"),
        ("imported-1", "step_count", "2026-10-20T01:00:00Z", None, "count", 100.0, None, "other-device"),
    ]
    out = _dedupe_app_installs(rows)
    steps = {r[0]: r[5] for r in out if r[1] == "step_count" and r[0].startswith("hkagg")}
    assert steps == {"hkagg-step_count-20261102": 14076.0, "hkagg-step_count-20261105": 3890.0}
    assert sum(1 for r in out if r[0] == "hkslp-1") == 1
    assert sum(1 for r in out if r[0] == "imported-1") == 2      # 非 App 上报的不动


def _tools(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path, vault_db=tmp_path / "vault.db", whoop_snapshot=tmp_path / "w.json")
    return SimpleNamespace(cfg=cfg, _now=lambda: __import__("datetime").datetime(2026, 11, 5, 20, 0))


def test_sync_status_rev_and_updating(tmp_path, monkeypatch):
    monkeypatch.setattr(v3, "_turn", lambda ctx: {"busy": ctx == "休息", "last_tool": "bash", "last_args": "{}"})
    t = _tools(tmp_path)
    a = v3.sync_status(t)
    assert a["updating"] == [] and a["agent"]["busy"] and a["agent"]["context"] == "休息"
    (tmp_path / "pages_v3.json").write_text("{}")
    b = v3.sync_status(t)
    assert b["rev"] != a["rev"]
    (tmp_path / "republish.lock").write_text("1")              # 文件在但没人持锁：不算在跑
    (tmp_path / "republish.progress.json").write_text(json.dumps({"current": "sleep", "left": ["sport", "stress"]}))
    assert v3.sync_status(t)["updating"] == []
    import fcntl
    with open(tmp_path / "republish.lock", "a") as fh:            # 真有一个进程持着锁
        fcntl.flock(fh, fcntl.LOCK_EX)
        assert v3.sync_status(t)["updating"] == ["sleep", "sport", "stress"]
        (tmp_path / "republish.again").write_text("1")
        assert v3.sync_status(t)["updating"] == list(v3.PAGES)


def test_publish_all_single_runner_and_backoff(tmp_path, monkeypatch):
    t = _tools(tmp_path)
    calls = []

    def fake_publish(tools, pg, timeout=420):
        calls.append(pg)
        if pg == "sport":
            raise TimeoutError("DSH 不通")
        return {"published_at": "x"}
    monkeypatch.setattr(v3, "publish", fake_publish)
    out = v3.publish_all(t, ["sleep", "sport"])
    assert out["sleep"]["ok"] and "error" in out["sport"]
    st = json.loads((tmp_path / "republish.state.json").read_text())
    assert st["pages"]["sport"]["fails"] == 1 and st["pages"]["sport"]["next_try"] > 0
    calls.clear()
    out = v3.publish_all(t, ["sleep", "sport"])                  # sport 还在退避里，不再重来
    assert calls == ["sleep"] and out["sport"] == {"skipped": "backoff"}
    import fcntl
    with open(tmp_path / "republish.lock", "a") as fh:            # 另一个进程在跑：这次不跑，记「再跑一遍」
        fcntl.flock(fh, fcntl.LOCK_EX)
        assert v3.publish_all(t, ["sleep"]) == {"busy": True}
    assert (tmp_path / "republish.again").exists()


def test_republish_async_throttled(tmp_path, monkeypatch):
    t = _tools(tmp_path)
    spawned = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
    monkeypatch.delenv("PIVIS_NO_REPUBLISH")
    assert v3.republish_async(t.cfg) is True
    assert v3.republish_async(t.cfg) is False                    # 一分钟内不再拉起
    assert len(spawned) == 1


def test_chat_photo_saved_and_served_by_name_only(tmp_path):
    t = _tools(tmp_path)
    r = v3.save_chat_photo(t, b"\xff\xd8\xff" + b"0" * 100)
    assert r["name"].startswith("chat-") and r["name"].endswith(".jpg")
    assert v3.photo_file(t, r["name"]).read_bytes()[:3] == b"\xff\xd8\xff"
    assert v3.photo_file(t, "../vault.db") is None
    with pytest.raises(ValueError):
        v3.save_chat_photo(t, b"not an image")


class SleepTools:
    """最近几晚只有 Apple 健康时长（没有「需要」）：need 画不了，要退回折线。"""
    cfg = None

    def __init__(self, nights):
        self._n = nights

    def _now(self):
        import datetime as dt
        return dt.datetime(2026, 11, 5, 20, 0)


def test_sleep_need_falls_back_to_trend_when_need_missing(monkeypatch):
    monkeypatch.setattr(viz, "prefs_for", lambda cfg: {})
    day = date(2026, 11, 5)
    nights = []
    for i in range(10):
        d = day - timedelta(days=10 - i)
        nights.append({"date": d.isoformat(), "actual": 6.0 + (i % 3) * 0.4,
                       "need": 8.5 if i < 6 else None})
    monkeypatch.setattr(viz, "_sleep_nights", lambda tools, d: nights)
    v = viz.build(SleepTools(nights), {"metric": "sleep", "kind": "need", "days": 7}, day)
    assert v["kind"] == "trend" and v["fallback_from"] == "need"
    assert v["asof"] == nights[-1]["date"] and v["band"] and v["warn"] is not None


def test_resting_hr_and_resp_rate_prefer_whoop_without_mixing(tools_env):
    """戴 WHOOP 的这段时间整段用 WHOOP 的静息心率 / 呼吸频率；更早、WHOOP 没覆盖的时段才用 Apple。"""
    from pivis_health.tools import HealthTools
    t: HealthTools = tools_env
    nights = sorted(t._whoop_daily("whoop_resting_hr", date(2100, 1, 1), 9999))
    end = nights[-1]
    rhr = t.daily_series("resting_heart_rate", end, 30)
    resp = t.daily_series("respiratory_rate", end, 30)
    assert rhr and set(rhr.values()) == {58.0}          # 全是 WHOOP 的值，没混进 Apple 的
    assert resp and set(resp.values()) == {15.8}
    assert t.series_source("resting_heart_rate", end, 30) == "whoop"
    # WHOOP 覆盖之前的一段：退回 Apple（夹具里没有 Apple 静息心率就是空，而不是借 WHOOP 的数）
    old_end = nights[0] - timedelta(days=40)
    assert t.series_source("resting_heart_rate", old_end, 10) == "apple"
    assert all(v != 58.0 for v in t.daily_series("resting_heart_rate", old_end, 10).values())
