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
    # 跟练视频（pivis-follow）：默认关；模拟环境 sim_mode 自动开，真实环境验收通过后在 config 里打开
    follow_enabled: bool = False
    # 动作库（hasaneyldrm/exercises-dataset，本机，不进仓库）；空 = ~/Tools/exercises-dataset
    exercise_db_dir: str = ""
    # 洞察（build 49）：每 3 天扫一次，有够格的就存着待发。insight_push 打开前只存不推（上线先给 Psir 看一眼 dry-run）
    insight_push: bool = False
    review_push: bool = True    # 每周对话复盘（build 52）：浮条 + 一周一条锁屏推送（Psir 11-10 同意）
    # App 设备密钥：拿 DSH 令牌（/api/dsh-token、/dsh）必须带上它（X-Pivis-Key），本机直连免。
    # 放本机 ~/.config/pivis-health/app_key（0600）或 config.local.json，永远不进仓库；没配时只有本机能拿
    app_key: str = field(default="", repr=False)
    # 服务端口（build 55，插件装的环境由 setup 写；配对二维码里带给 App）
    api_port: int = 8943

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
        "PIVIS_APP_KEY": "app_key",
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
        follow_enabled=bool(values.get("follow_enabled", values.get("sim_mode", False))),
        exercise_db_dir=str(values.get("exercise_db_dir") or ""),
        insight_push=bool(values.get("insight_push", False)),
        review_push=bool(values.get("review_push", True)),
        app_key=str(values.get("app_key") or _read_app_key()),
        api_port=int(values.get("api_port") or 8943),
    )
    return cfg


APP_KEY_FILE = Path.home() / ".config/pivis-health/app_key"


def _read_app_key() -> str:
    try:
        return APP_KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
