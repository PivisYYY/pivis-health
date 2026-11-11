"""build 55：DeepSeek Harness 插件——配对链接 / 二维码、一条命令安装（不装后台任务、不碰真实 DSH）。"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from pivis_health import pairing, setup
from pivis_health.config import Config


def test_pair_url_and_qr(tmp_path, monkeypatch):
    monkeypatch.setattr(pairing, "computer_name", lambda: "测试 Mac")
    cfg = replace(Config(), data_dir=tmp_path, app_key="k-123", api_port=9943, dsh_web="http://127.0.0.1:9960")
    url = pairing.pair_url(cfg, ["10.0.0.2", "100.64.1.2", "mac.local"])
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.scheme == "phealth" and u.netloc == "pair"
    assert q == {"v": "1", "n": "测试 Mac", "h": "10.0.0.2,100.64.1.2,mac.local", "p": "9943", "d": "9960", "k": "k-123"}
    rows = pairing.terminal(url).splitlines()
    assert len(rows) > 10 and len({len(r) for r in rows}) == 1
    assert pairing.svg(url).startswith("<svg") and "<path" in pairing.svg(url)
    monkeypatch.setattr(pairing, "hosts", lambda: ["10.0.0.2"])
    files = pairing.write_files(cfg)
    assert "k-123" in open(files["txt"]).read() and "<svg" in open(files["html"]).read()
    try:
        pairing.pair_url(replace(cfg, app_key=""))
        assert False, "没有密钥不该出链接"
    except ValueError:
        pass


def test_setup_prepares_everything_without_launchd(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "ensure_profile", lambda dsh_home, profile, spec, home: calls.append(profile))
    monkeypatch.setattr(pairing, "hosts", lambda: ["10.0.0.2"])
    monkeypatch.setattr(pairing, "computer_name", lambda: "Mac")
    home = tmp_path / "PHealth"
    assert setup.main(["--home", str(home), "--nickname", "小王", "--no-launchd", "--api-port", "9943", "--dsh-port", "9960"]) == 0
    cfg = json.loads((home / "config.json").read_text())
    assert cfg["api_port"] == 9943 and cfg["dsh_web"].endswith(":9960") and len(cfg["app_key"]) >= 24
    assert oct((home / "config.json").stat().st_mode)[-3:] == "600"
    tables = {r[0] for r in sqlite3.connect(home / "vault/health.sqlite3").execute("select name from sqlite_master")}
    assert {"samples", "batches", "tombstones"} <= tables
    agents = (home / "workspace/AGENTS.md").read_text()
    assert "小王" in agents and "老大" not in agents
    wrapper = (home / "workspace/pivis-health").read_text()
    assert "PIVIS_HEALTH_CONFIG" in wrapper and "PIVIS_DSH_LOG" in wrapper and str(home) in wrapper
    assert (home / "runtime/pair.html").exists() and calls == ["phealth"]
    key = cfg["app_key"]
    setup.main(["--home", str(home), "--no-launchd"])               # 重跑：密钥和称呼沿用
    assert json.loads((home / "config.json").read_text())["app_key"] == key
    assert "小王" in (home / "workspace/AGENTS.md").read_text()


def test_profile_patch_keeps_permissions_inside_the_profile(tmp_path):
    text = setup.profile_patch(tmp_path / "PHealth")
    assert setup.PROFILE_MARK in text and "policy: never" in text and str(tmp_path / "PHealth") in text


def test_launchd_jobs_point_at_this_install(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "dsh_bin", lambda: "/x/dsh")
    home = tmp_path / "H"
    d = setup.make_dirs(home)
    cfg = {"api_port": 9943, "dsh_web": "http://127.0.0.1:9960", "timezone": "Asia/Shanghai", "app_key": "k"}
    env = setup.env_for(home, d, cfg, "老大")
    jobs = setup.jobs(home, d, env, cfg, "phealth", tmp_path / "dsh", "com.phealth", whoop=False)
    assert set(jobs) == {f"com.phealth.{x}" for x in ("server", "dshweb", "notify", "events", "cycle", "insight")}
    assert jobs["com.phealth.server"]["ProgramArguments"][-4:] == ["--host", "0.0.0.0", "--port", "9943"]
    web = jobs["com.phealth.dshweb"]
    assert web["ProgramArguments"][:2] == ["/x/dsh", "phealth"] and web["StandardOutPath"] == env["PIVIS_DSH_LOG"]
    assert web["EnvironmentVariables"]["DSH_HOME"] == str(tmp_path / "dsh") and web["EnvironmentVariables"]["PHEALTH_HOME"] == str(home)


def test_session_log_decodes_without_zstandard(tmp_path, monkeypatch):
    """DSH 自带的 Python 没有 zstandard：改用 DSH 自带的 Node 逐帧解（多帧拼接的会话记录）。"""
    import builtins
    import pytest
    from pivis_health import dsh_chat
    if not dsh_chat._DSH_NODE.exists():
        pytest.skip("这台机器没装 DeepSeek Harness")
    f = tmp_path / "s.jsonl.zstd"
    f.write_bytes(bytes.fromhex("28b52ffd20084100007b2261223a317d0a28b52ffd20084100007b2262223a327d0a"))      # 两帧 zstd：{"a":1}\n 和 {"b":2}\n
    real_import = builtins.__import__

    def no_zstd(name, *a, **k):
        if name == "zstandard":
            raise ImportError("模拟没有 zstandard")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_zstd)
    assert dsh_chat._decompress(f) == b'{"a":1}\n{"b":2}\n'
