"""跟练视频：./pivis-health follow … → pivis-follow（本机 ~/Tools/pivis-follow，Vision + LaMa + Qwen3-TTS）。
素材库按环境分开：<data_dir>/follow（真实 / 模拟 / 演示互不影响）。成片只经自己的服务器 /media/follow/ 给 App，绝不外传。"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .config import Config

PF = Path(os.environ.get("PIVIS_FOLLOW_HOME", str(Path.home() / "Tools/pivis-follow")))
SAFE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")


def pf_home(cfg: Config) -> Path:
    return cfg.data_dir / "follow"


def run_cli(cfg: Config, argv: list[str]) -> tuple[dict, int]:
    if not cfg.follow_enabled:
        return {"error": "not_enabled", "message": "跟练视频功能还在模拟环境验收，这个环境暂未开放。可以先把视频链接存进素材库（media-add）。"}, 2
    if not argv or argv[0] in ("-h", "--help", "help"):
        argv = ["--help"]
    env = dict(os.environ, PF_HOME=str(pf_home(cfg)))
    r = subprocess.run([str(PF / "pf.sh"), *argv], capture_output=True, text=True, env=env, timeout=3600)
    txt = r.stdout.strip()
    if argv == ["--help"]:
        return {"help": txt}, 0
    try:
        out = json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        out = {"output": txt[-3000:]}
    if r.returncode and not out:
        out = {"error": "follow_failed", "message": (r.stderr or txt)[-800:]}
    if isinstance(out, dict):
        _localize(out, cfg)
    return out, (0 if r.returncode == 0 else 1)


def _localize(obj, cfg):
    """本机文件路径里的素材库前缀换短，方便看"""
    return obj


def media_path(cfg: Config, path: str) -> Path | None:
    """/media/follow/<ssid>/<out.mp4|poster.jpg> → 文件（只认这两种，ssid 只能是字母数字）"""
    parts = path.split("?")[0].strip("/").split("/")
    if len(parts) != 4 or parts[0] != "media" or parts[1] != "follow":
        return None
    ssid, name = parts[2], parts[3]
    if not SAFE.match(ssid) or name not in ("out.mp4", "poster.jpg"):
        return None
    f = pf_home(cfg) / "sessions" / ssid / name
    return f if f.is_file() else None
