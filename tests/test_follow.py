"""跟练视频：开关、/media/follow 路径白名单、公开网盘链接一律拒绝"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pivis_health.config import Config
from pivis_health.follow import media_path, run_cli
from pivis_health.todos import TodoError, _check_url


def test_disabled_env_refuses(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path, follow_enabled=False)
    out, code = run_cli(cfg, ["lib"])
    assert code == 2 and out["error"] == "not_enabled"


def test_media_path_whitelist(tmp_path):
    cfg = replace(Config(), data_dir=tmp_path)
    d = tmp_path / "follow" / "sessions" / "sabc123"
    d.mkdir(parents=True)
    (d / "out.mp4").write_bytes(b"x")
    (d / "session.json").write_text("{}")
    assert media_path(cfg, "/media/follow/sabc123/out.mp4?v=2") == d / "out.mp4"
    assert media_path(cfg, "/media/follow/sabc123/session.json") is None
    assert media_path(cfg, "/media/follow/../etc/out.mp4") is None
    assert media_path(cfg, "/media/follow/sabc123/poster.jpg") is None      # 不存在


@pytest.mark.parametrize("url", ["https://a.uguu.se/x.mp4", "https://files.catbox.moe/a.mp4", "https://gofile.io/d/abc",
                                 "https://tmpfiles.org/1/x.mp4", "https://pan.baidu.com/s/1x"])
def test_public_file_hosts_rejected(url):
    with pytest.raises(TodoError):
        _check_url(url)


def test_own_media_and_bilibili_ok():
    _check_url("/media/follow/sabc/out.mp4")
    _check_url("https://www.bilibili.com/video/BV1K1fCBmE2Y")
