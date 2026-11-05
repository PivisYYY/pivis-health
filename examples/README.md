# 示例：合成演示数据

`make_demo.py` 生成一整套**编出来的**演示环境，用来截图、录屏、试功能。里面没有任何真人数据：

- `demo-vault.sqlite3`：40 天的 Apple 健康样本（睡眠分段、步数、活动能量、体重）
- `demo-whoop.json`：最近 14 晚的 WHOOP 快照（恢复、HRV、睡眠阶段、需要睡多久、训练）
- `config.demo.json`：指向上面两份数据、独立的运行目录、固定的模拟时钟（2026-11-05 21:10）
- `pivis-health`：这个演示目录专用的命令入口（DSH 会话前缀 `phealth-demo-`，和真实会话隔离）

故事设定：这周睡得偏少、HRV 往下走、每周二和周六打网球、步数 8–9 千、慢慢朝目标体重走。

```sh
python3 examples/make_demo.py ~/demo-phealth
~/demo-phealth/pivis-health viz             # 每项指标的数和档位
~/demo-phealth/pivis-health page-v3 now     # 页面（需要先编排：publish-v3 all，要 DSH 上的 P-Health）
```

README 里的截图就是用这套数据、在模拟器里跑真实 App 拍的。
