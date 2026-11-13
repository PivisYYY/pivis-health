"""下拉刷新（build 53）：不当场等 WHOOP，马上回数据有多新；需要时后台补拉；只有真要 Psir 动手才 ok=False。"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pivis_health import v3, whoop_sync
from pivis_health.config import Config


def _tools(tmp_path, sim=False, age_min=None, authorised=True, error_code=None):
    auth = tmp_path / "auth"
    auth.mkdir(exist_ok=True)
    snap = tmp_path / "whoop-snapshot.json"
    if age_min is not None:
        end = datetime.now(timezone.utc) - timedelta(minutes=age_min)
        snap.write_text(json.dumps({"window_end_utc": end.isoformat()}))
    if authorised:
        (auth / "tokens.json").write_text("{}")
    if error_code:
        (tmp_path / "whoop_sync_status.json").write_text(json.dumps({"ok": False, "error_code": error_code,
                                                                    "at_utc": datetime.now(timezone.utc).isoformat()}))
    cfg = replace(Config(), data_dir=tmp_path, sim_mode=sim, whoop_snapshot=snap, whoop_auth_dir=auth,
                  vault_db=tmp_path / "none.sqlite3")
    return SimpleNamespace(cfg=cfg)


def test_sim_mode_never_calls_whoop(tmp_path, monkeypatch):
    monkeypatch.setattr(whoop_sync, "sync", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该连")))
    r = v3.sync_health(_tools(tmp_path, sim=True))
    assert r["ok"] is True and r["pulling"] is False


def test_fresh_data_answers_at_once_without_pulling(tmp_path, monkeypatch):
    monkeypatch.setattr(whoop_sync, "sync", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该连")))
    r = v3.sync_health(_tools(tmp_path, age_min=3))
    assert r["ok"] is True and r["whoop"] == "fresh" and r["pulling"] is False and r["action"] is None


def test_stale_pulls_in_background_and_does_not_block(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow(cfg, **kw):
        started.set()
        release.wait(5)
        return {"ok": True}

    monkeypatch.setattr(whoop_sync, "sync", slow)
    t = _tools(tmp_path, age_min=40)
    t0 = time.monotonic()
    r = v3.sync_health(t)
    assert time.monotonic() - t0 < 1 and r["pulling"] is True and r["ok"] is True
    assert started.wait(2)
    assert v3.sync_health(t)["pulling"] is False          # 还在拉：不重复起
    release.set()


def test_failures_only_surface_when_login_needed(tmp_path, monkeypatch):
    monkeypatch.setattr(whoop_sync, "sync", lambda *a, **k: {"ok": True})
    r = v3.sync_health(_tools(tmp_path, age_min=300, error_code="api_error"))
    assert r["ok"] is True and r["action"] is None        # 接口失败：服务器自己重试，不打扰 Psir
    r = v3.sync_health(_tools(tmp_path / "x", age_min=300, error_code="not_authorised")) if (tmp_path / "x").mkdir() is None else None
    assert r["ok"] is False and "WHOOP" in r["action"]
