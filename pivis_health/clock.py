"""统一时钟：正式环境用真实时间；模拟回放（sim_mode）用 data_dir/sim_clock.json 里的时间。

模拟时钟只在 sim_mode=True 的配置下生效，避免测试时间泄漏到真实环境。
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Config


def _clock_file(cfg: Config):
    return cfg.data_dir / "sim_clock.json"


def now(cfg: Config) -> datetime:
    tz = ZoneInfo(cfg.timezone)
    if cfg.sim_mode:
        try:
            raw = json.loads(_clock_file(cfg).read_text(encoding="utf-8"))
            value = datetime.fromisoformat(raw["now"])
            return value if value.tzinfo else value.replace(tzinfo=tz)
        except (OSError, KeyError, ValueError):
            pass
    return datetime.now(tz)


def set_now(cfg: Config, value: str) -> datetime:
    if not cfg.sim_mode:
        raise PermissionError("模拟时钟只在 sim_mode 下可用")
    tz = ZoneInfo(cfg.timezone)
    dt = datetime.fromisoformat(value)
    dt = dt if dt.tzinfo else dt.replace(tzinfo=tz)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    _clock_file(cfg).write_text(json.dumps({"now": dt.isoformat()}), encoding="utf-8")
    return dt
