"""媒体文件的 Range：正常段 206、越界 416；客户端中途断开不打堆栈。"""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pivis_health import web


@pytest.fixture()
def server(tools_env, tmp_path, monkeypatch):
    home = tmp_path / "home"
    audio = home / ".dsh/bot/workspace/sleep-audio"
    audio.mkdir(parents=True)
    (audio / "a.m4a").write_bytes(bytes(range(256)) * 4)          # 1024 字节
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    httpd = web.QuietServer(("127.0.0.1", 0), web.make_handler(tools_env.cfg, tools_env))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url, rng=None):
    req = urllib.request.Request(url, headers={"Range": rng} if rng else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_sleep_audio_ranges(server):
    url = server + "/media/sleep-audio/a.m4a"
    code, h, body = _get(url)
    assert code == 200 and len(body) == 1024 and h["Accept-Ranges"] == "bytes"
    code, h, body = _get(url, "bytes=10-19")
    assert code == 206 and body == bytes(range(10, 20)) and h["Content-Range"] == "bytes 10-19/1024"
    code, h, body = _get(url, "bytes=-4")
    assert code == 206 and len(body) == 4
    code, h, _ = _get(url, "bytes=999999999-")
    assert code == 416 and h["Content-Range"] == "bytes */1024"
    assert _get(server + "/media/sleep-audio/nope.m4a")[0] == 404


def test_client_disconnect_is_quiet(capsys):
    srv = web.QuietServer.__new__(web.QuietServer)
    try:
        raise BrokenPipeError(32, "Broken pipe")
    except BrokenPipeError:
        srv.handle_error(None, ("127.0.0.1", 1))
    assert capsys.readouterr().err == ""
