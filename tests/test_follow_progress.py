"""出片进度是生成器的真实状态；跨环境隔离、失败、重开和验收门禁。"""
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pivis_health import canvas, cards, follow, web
from pivis_health.config import Config


@pytest.fixture
def cfg(tmp_path):
    return replace(Config(), data_dir=tmp_path, follow_enabled=True)


def write_job(cfg, **changes):
    path = follow.pf_home(cfg) / "jobs" / "jtest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    job = {"state": "running", "step": "配音（录制）", "progress": 0.62,
           "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 125)),
           "args": {"url": "private-source", "path": "/private/home"}, "trace": "secret-trace"}
    job.update(changes)
    path.write_text(json.dumps(job), encoding="utf-8")
    return path


def text(node):
    return json.dumps(node, ensure_ascii=False)


def test_live_progress_and_no_private_fields(cfg):
    write_job(cfg)
    node = follow.progress_node(cfg, "jtest")
    assert node["children"][0]["text"] == "正在制作报数和教练配音"
    assert node["children"][1]["fraction"] == 0.62
    assert "2 分" in text(node) and canvas.refresh_after(node) == 3
    assert not any(s in text(node) for s in ["private-source", "/private/home", "secret-trace", "录制"])


@pytest.mark.parametrize("state,result,stage,complete", [
    ("done", {"verify_ok": True}, "验收通过", True),
    ("done", {"verify_ok": False}, "验收未通过", False),
    ("done", {}, "验收未通过", False),
    ("failed", {}, "生成中断", False),
    ("unexpected", {}, "状态待检查", False),
])
def test_terminal_state_gate(cfg, state, result, stage, complete):
    write_job(cfg, state=state, result=result, progress=1)
    node = follow.progress_node(cfg, "jtest")
    assert stage in text(node)
    assert (node["children"][1]["fraction"] == 1) is complete
    assert canvas.refresh_after(node) is None


@pytest.mark.parametrize("value", [-2, 5, math.nan, math.inf, "broken", None])
def test_running_progress_is_finite_and_never_complete(cfg, value):
    write_job(cfg, progress=value)
    bar = follow.progress_node(cfg, "jtest")["children"][1]
    assert 0 <= bar["fraction"] < 1 and math.isfinite(bar["fraction"])


def test_partial_write_retries_but_missing_task_stops(cfg):
    assert canvas.refresh_after(follow.progress_node(cfg, "missing")) is None
    p = write_job(cfg)
    p.write_text('{"state":')
    assert canvas.refresh_after(follow.progress_node(cfg, "jtest")) == 3


def test_stale_task_never_fakes_completion(cfg):
    p = write_job(cfg)
    os.utime(p, (time.time() - 700, time.time() - 700))
    node = follow.progress_node(cfg, "jtest")
    assert "较久没有更新" in text(node)
    assert canvas.refresh_after(node) == 3


def test_terminal_elapsed_is_frozen_and_cut_count_is_visible(cfg, monkeypatch):
    write_job(cfg, step="切动作 2/6", progress=0.3)
    assert "正在剪辑动作 2/6" in text(follow.progress_node(cfg, "jtest"))
    write_job(cfg, state="done", result={"verify_ok": True})
    first = follow.progress_node(cfg, "jtest")["children"][1]["left"]
    later = time.time() + 120
    monkeypatch.setattr(follow.time, "time", lambda: later)
    assert follow.progress_node(cfg, "jtest")["children"][1]["left"] == first


def test_binding_validation_and_disabled_environment(cfg):
    card = follow.progress_card("jtest")
    assert cards.check(card) == []
    assert canvas.estimate(canvas.validate(card, "chat")) < canvas.SLOTS["chat"]["h"]
    for jid in ["../other", "x/y", "x\n", "", "x" * 49]:
        with pytest.raises(ValueError):
            follow.progress_card(jid)
        if jid != "x\n":  # 画布的所有 bind 都会规范化首尾空白。
            with pytest.raises(canvas.CanvasError):
                canvas.validate({"t": "bar", "bind": "follow:" + jid}, "chat")
    disabled = replace(cfg, follow_enabled=False)
    write_job(cfg)
    assert "配音" not in text(follow.progress_node(disabled, "jtest"))


def test_job_symlinks_and_other_environments_are_not_read(cfg, tmp_path):
    other = replace(cfg, data_dir=tmp_path / "other")
    secret = write_job(other)
    jobs = follow.pf_home(cfg) / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "jtest.json").symlink_to(secret)
    assert "配音" not in text(follow.progress_node(cfg, "jtest"))
    (jobs / "jtest.json").unlink()
    jobs.rmdir()
    jobs.symlink_to(secret.parent, target_is_directory=True)
    assert "配音" not in text(follow.progress_node(cfg, "jtest"))


def test_cli_returns_ready_to_send_card(cfg, monkeypatch):
    monkeypatch.setattr(follow.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        stdout='{"job":"jtest","state":"queued"}', stderr="", returncode=0))
    out, code = follow.run_cli(cfg, ["make", "https://example.com/video"])
    assert code == 0 and out["progress_card"] == follow.progress_card("jtest")


def test_canvas_api_fresh_status_and_terminal_no_refresh(tools_env):
    tools_env.cfg = replace(tools_env.cfg, follow_enabled=True)
    cfg = tools_env.cfg
    write_job(cfg)
    srv = web.QuietServer(("127.0.0.1", 0), web.make_handler(cfg, tools_env))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/v3/canvas"

    def fetch():
        body = json.dumps({"layout": follow.progress_card("jtest"), "slot": "chat"}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    try:
        first = fetch()
        assert first["refresh_after"] == 3 and "配音" in text(first)
        write_job(cfg, step="出片 80%", progress=0.82)
        assert "合成" in text(fetch())
        write_job(cfg, state="done", progress=1, result={"verify_ok": False})
        failed = fetch()
        assert failed["refresh_after"] is None and "验收未通过" in text(failed)
        write_job(cfg, state="done", progress=1, result={"verify_ok": True})
        done = fetch()
        assert done["refresh_after"] is None and "验收通过" in text(done)
        assert "100%" in text(done)
    finally:
        srv.shutdown()
        srv.server_close()
