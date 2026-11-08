# 12-06 交棒日清单（CBT-I 疗程结束日）

并行只读期结束，一次性把采集与写权从 hermes 切到 pivis-health。
**原则：任一项验收不过，整体顺延一周，hermes 原样保留。**

## 切换前一周（11-30 起）

- [ ] `pivis-health collector` 采集链就绪：Apple webhook 导入路由 + WHOOP 同步服务搬入（从 `~/.hermes/profiles/pivis/` 的 `integrations/whoop/` 与 `pivis_health` 包移植，保持幂等去重与 refresh token 轮换）
- [ ] WHOOP OAuth 凭据迁移演练：确认 cloudflared 隧道与回调 URL 变更方案，一次成功，不触发重新授权
- [ ] 导入器回归：`pivis-health-import-v1.schema.json` 校验 + 幂等（同批次重放零新增）
- [ ] 主观库/规则/推送记录完整（`runtime/subjective.sqlite3` 无损坏，count 对得上）

## 交棒日（12-06）

- [ ] 停 hermes 侧 WHOOP 同步 cron（`2ff06193d841`）→ 启 pivis-health collector → 首次同步数据连续性核对（快照窗口无空洞）
- [ ] Apple webhook 路由切到 pivis-health（gateway 路由摘除前，先双观察一天导入成功率）
- [ ] sqlite 写权交棒：pivis-health 从只读连接转为写入者（readonly.py 的 ro 门禁仅用于旧库；新写入走 collector 自己的库文件）
- [ ] CBT-I 三任务在 hermes 自然结束（12-06 最后一晚），F5 常态就寝流程次日起由 P-Health 的项目待办接棒（带 `when` 的卡，App 到点提醒；不建 dsh 定时任务）
- [ ] hermes 健康 cron 退役归档：`03636a24aa7d / 1380cace / a43987fe / b8d481f4 / a6f788bb / 8072c47b / 50571433 / 5db69088 / 55573eaf / ab82cfefd093`（逐个核对 `hermes cron list`，防止"孤儿脚本"事故重演——注释声称的调用必须核实）
- [ ] 微信镜像首条真实投递人工核验
- [ ] Time Machine 确认备份到交棒后状态

## 回滚

任一环节失败：hermes 侧 cron 全部恢复（未删配置，仅停用），pivis-health 回到只读模式，一周后重试。
