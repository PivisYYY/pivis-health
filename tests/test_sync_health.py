"""下拉刷新时的 WHOOP 同步：模拟环境不连、60 秒内不重复拉、失败如实说。"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from pivis_health import v3, whoop_sync
from pivis_health.config import Config


def _tools(tmp_path, sim=False):
    return SimpleNamespace(cfg=replace(Config(), data_dir=tmp_path, sim_mode=sim))


def test_sim_mode_never_calls_whoop(tmp_path, monkeypatch):
    monkeypatch.setattr(whoop_sync, "sync", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该连")))
    assert v3.sync_health(_tools(tmp_path, sim=True))["whoop"] == "skipped"


def test_manual_sync_forces_and_throttles(tmp_path, monkeypatch):
    calls = []

    def fake(cfg, **kw):
        calls.append(kw)
        return {"ok": True, "latest_recovery_night": "2026-11-04"}

    monkeypatch.setattr(whoop_sync, "sync", fake)
    t = _tools(tmp_path)
    first = v3.sync_health(t)
    assert first["whoop"] == "synced" and first["latest"] == "2026-11-04"
    assert calls == [{"force": True}]          # 老大自己下拉：静默时段也拉
    assert v3.sync_health(t)["whoop"] == "recent" and len(calls) == 1


def test_failure_is_reported_and_retried(tmp_path, monkeypatch):
    def boom(cfg, **kw):
        raise whoop_sync.WhoopError("token 过期")

    monkeypatch.setattr(whoop_sync, "sync", boom)
    t = _tools(tmp_path)
    r = v3.sync_health(t)
    assert r["ok"] is False and "token 过期" in r["message"]
    assert v3.sync_health(t)["whoop"] == "failed"   # 失败不算「刚同步过」，下次下拉还会再试
