#!/bin/sh
# 洞察和每周对话复盘的定时（launchd com.pivis.health-insight，每个整点的 30 分唤醒一次）。
# 只在 Psir 所在时区（config 里的 timezone，北京）的 08:30 干活；insight-cycle 自己判断离上次扫描满没满 3 天。
# 顺序：whoop-sync（拿最新的恢复 / 睡眠）→ insight-cycle（场景标签 → 对话主题 → 算候选 → 写稿 → 存 → 推）。
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD"
PY="${PHEALTH_PY:-/usr/bin/python3}"   # 插件装的环境用 DSH 自带的 Python（setup 写进 launchd）
H=$("$PY" -c "from datetime import datetime; from zoneinfo import ZoneInfo; from pivis_health.config import load_config; print(datetime.now(ZoneInfo(load_config().timezone)).strftime('%H'))")
[ "$H" = "08" ] || exit 0
"$PY" -m pivis_health.cli whoop-sync >/dev/null 2>&1
"$PY" -m pivis_health.cli insight-cycle
"$PY" -m pivis_health.cli review-cycle   # 每周对话复盘：自己判断是不是周一、离上次满不满 6 天
