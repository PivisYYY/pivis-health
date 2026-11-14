"""b61：主卡加载慢——只排受影响的页、几页同时排、排的时候又有变化只再排变了的那几页。"""
from __future__ import annotations

import json
import subprocess
import threading
import time

from pivis_health import v3


def _cfg(tools_env):
    return tools_env.cfg


def test_publish_all_runs_pages_in_parallel(tools_env, monkeypatch):
    seen, lock = [], threading.Lock()

    def fake(tools, pg, timeout=420):
        with lock:
            seen.append(("start", pg, time.time()))
        time.sleep(0.3)
        return {"published_at": "x"}

    monkeypatch.setattr(v3, "publish", fake)
    t0 = time.time()
    out = v3.publish_all(tools_env, ["now", "sleep", "sport", "stress"], force=True)
    took = time.time() - t0
    assert all(out[p]["ok"] for p in ("now", "sleep", "sport", "stress"))
    assert took < 0.9                          # 一页一页排要 1.2 秒以上
    assert not (_cfg(tools_env).data_dir / "republish.progress.json").exists()


def test_again_only_redoes_changed_pages(tools_env, monkeypatch):
    calls = []

    def fake(tools, pg, timeout=420):
        calls.append(pg)
        if len(calls) == 1:
            v3._add_again(tools.cfg, ["sport"])  # 排的时候运动页又变了
        time.sleep(0.05)
        return {"published_at": "x"}

    monkeypatch.setattr(v3, "publish", fake)
    v3.publish_all(tools_env, ["now", "sleep", "sport", "stress"], force=True)
    assert sorted(calls[:4]) == ["now", "sleep", "sport", "stress"] and calls[4:] == ["sport"]


def test_again_old_format_means_all_pages(tools_env):
    (_cfg(tools_env).data_dir / "republish.again").write_text("1731500000.0")
    assert v3._again_pages(_cfg(tools_env)) == list(v3.PAGES)
    v3._add_again(_cfg(tools_env), ["sleep"])
    assert v3._again_pages(_cfg(tools_env)) == list(v3.PAGES)


def test_republish_async_targets_pages_and_throttles_per_page(tools_env, monkeypatch):
    spawned = []
    monkeypatch.delenv("PIVIS_NO_REPUBLISH")
    monkeypatch.setattr(subprocess, "Popen", lambda args, **k: spawned.append(args))
    cfg = _cfg(tools_env)
    assert v3.republish_async(cfg, ["sport"]) is True
    assert spawned[-1][-3:] == ["publish-v3", "sport", "--auto"]
    assert v3.republish_async(cfg, ["sport"]) is False            # 同一页一分钟内不再拉起
    assert v3.republish_async(cfg, ["sport", "sleep"]) is True    # 别的页照样排
    assert spawned[-1][-3:] == ["publish-v3", "sleep", "--auto"]


def test_status_updating_lists_only_pages_left(tools_env, monkeypatch):
    cfg = _cfg(tools_env)
    (cfg.data_dir / "republish.progress.json").write_text(json.dumps({"current": None, "left": ["stress"]}))
    monkeypatch.setattr(v3, "_republish_lock_busy", lambda c: True)
    st = v3.sync_status(tools_env)
    assert st["updating"] == ["stress"]
    v3._add_again(cfg, ["now"])
    assert v3.sync_status(tools_env)["updating"] == ["now", "stress"]
