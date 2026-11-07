"""测试用的跟练成片：练习只认 follow 出的片（/media/follow/<ssid>/out.mp4），建卡前得真有这个文件。"""
from __future__ import annotations

from pathlib import Path


def make_clip(data_dir, ssid: str = "s1", minutes: float = 8, title: str = "跟练") -> dict:
    d = Path(data_dir) / "follow" / "sessions" / ssid
    d.mkdir(parents=True, exist_ok=True)
    (d / "out.mp4").write_bytes(b"\0" * 16)
    return {"kind": "video", "title": title, "url": f"/media/follow/{ssid}/out.mp4", "duration_min": minutes}
