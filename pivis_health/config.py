"""配置：env 覆盖 > 仓库内 config.local.json（gitignored，含本机真实路径）> 默认值。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    # 本机真实路径放 config.local.json（gitignored）；这里只给按当前用户主目录算的默认值
    vault_db: Path = Path.home() / "PivisVault/.pivis/health/db/health.sqlite3"
    whoop_snapshot: Path = Path.home() / ".hermes/profiles/pivis/integrations/whoop/runtime/whoop-snapshot.json"
    # WHOOP OAuth 应用凭据与令牌（目录 0700、文件 0600），永远不放仓库
    whoop_auth_dir: Path = Path.home() / ".config/pivis-health/whoop"
    data_dir: Path = REPO_ROOT / "runtime"
    timezone: str = "Asia/Shanghai"
    # 就寝流程参数（2026-10-31 需求确认：缓冲 30 分钟、免打扰 00:00–08:00、触达 ≤3/天）
    fixed_wake_time: str = "08:30"
    morning_time: str = "08:35"
    buffer_minutes: int = 30
    dnd_hours: tuple[int, int] = (0, 8)
    daily_push_limit: int = 3
    # APNs 配置（key_id/key_path/push_key/bundle_id/env），未配置时推送静默跳过
    apns: dict = field(default_factory=dict)
    # v3 模拟模式：时间由 data_dir/sim_clock.json 决定（测试回放用，正式环境为 False）
    sim_mode: bool = False
    # DSH web 地址（含内网 IP 的真实值放 config.local.json，不进仓库）
    dsh_web: str = "http://127.0.0.1:8960"

    @property
    def subjective_db(self) -> Path:
        return self.data_dir / "subjective.sqlite3"


def load_config(explicit_path: str | None = None) -> Config:
    values: dict = {}
    path = Path(explicit_path or os.environ.get("PIVIS_HEALTH_CONFIG") or (REPO_ROOT / "config.local.json"))
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = Config.__dataclass_fields__.keys()
        values.update({k: v for k, v in raw.items() if k in known})
    # env 覆盖（测试与临时部署用）
    env_map = {
        "PIVIS_HEALTH_VAULT_DB": "vault_db",
        "PIVIS_HEALTH_WHOOP_SNAPSHOT": "whoop_snapshot",
        "PIVIS_WHOOP_AUTH_DIR": "whoop_auth_dir",
        "PIVIS_HEALTH_DATA_DIR": "data_dir",
        "PIVIS_HEALTH_TZ": "timezone",
        "PIVIS_DSH_WEB": "dsh_web",
    }
    for env, key in env_map.items():
        if os.environ.get(env):
            values[key] = os.environ[env]
    dnd = values.get("dnd_hours")
    cfg = Config(
        vault_db=Path(values.get("vault_db", Config.vault_db)),
        whoop_snapshot=Path(values.get("whoop_snapshot", Config.whoop_snapshot)).expanduser(),
        whoop_auth_dir=Path(values.get("whoop_auth_dir", Config.whoop_auth_dir)).expanduser(),
        data_dir=Path(values.get("data_dir", Config.data_dir)),
        timezone=str(values.get("timezone", "Asia/Shanghai")),
        fixed_wake_time=str(values.get("fixed_wake_time", "08:30")),
        morning_time=str(values.get("morning_time", "08:35")),
        buffer_minutes=int(values.get("buffer_minutes", 30)),
        dnd_hours=tuple(dnd) if isinstance(dnd, (list, tuple)) and len(dnd) == 2 else (0, 8),
        daily_push_limit=int(values.get("daily_push_limit", 3)),
        apns=dict(values.get("apns") or {}),
        sim_mode=bool(values.get("sim_mode", False)),
        dsh_web=str(values.get("dsh_web") or Config.dsh_web).rstrip("/"),
    )
    return cfg
