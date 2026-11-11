#!/bin/sh
# v3 定时节拍（launchd com.pivis.health-composer，每个整点唤醒一次）。
# 只在老大所在时区（config 里的 timezone，北京）的 8 点、13 点、18 点干活：本机时区和夏令时怎么变都不会错。
# 先让 P-Health 按场景主动推荐 1–2 件事（每档每天只发一次），再重排四个页面的结论和主卡。
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD"
PY="${PHEALTH_PY:-/usr/bin/python3}"   # 插件装的环境用 DSH 自带的 Python（setup 写进 launchd）
H=$("$PY" -c "from datetime import datetime; from zoneinfo import ZoneInfo; from pivis_health.config import load_config; print(datetime.now(ZoneInfo(load_config().timezone)).strftime('%H'))")
case "$H" in
  08|13|18) ;;
  *) exit 0 ;;
esac
"$PY" -m pivis_health.cli whoop-sync >/dev/null 2>&1   # 先拿最新的恢复 / 睡眠 / 训练，推荐和页面才是今早的数
"$PY" -m pivis_health.cli daily-review
sleep 150   # 给 P-Health 一点时间加待办，再编排页面
"$PY" -m pivis_health.cli publish-v3 all
