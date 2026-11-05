#!/bin/sh
# v3 定时节拍：每天第一次先让各板块 P-Health 做「每日整理」（每板块每天只发一次），再重排四个页面的结论和主卡。
# 由 launchd（com.pivis.health-composer）在 09:35 / 12:30 / 17:30 / 21:30 调用。
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD"
/usr/bin/python3 -m pivis_health.cli daily-review
sleep 120   # 给各板块一点时间加待办，再编排页面
/usr/bin/python3 -m pivis_health.cli publish-v3 all
