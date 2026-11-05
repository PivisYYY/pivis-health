# 资产搬运来源对照（hermes → pivis-health）

| 新实现 | 来源（hermes） | 说明 |
|---|---|---|
| `readonly.py` 投影语义/只读门禁 | `skills/pivis-health/scripts/pivis_health/store.py` + `scripts/pivis_sleep_alert.py` 的 ReadOnlyStore | 睡眠 12:00→12:00 归属、tombstones 排除、query_only、库身份校验逐条等价 |
| `sleep.py` 全套 | `scripts/pivis_health_apple.py` 的 sleep_data/分轨重建/门禁 | 2026-09-18 双计事故与 09-28 平行轨事故的修复逻辑原样移植；print 改 notes |
| `insights.py` | `scripts/health_insight_engine.py` | SRI/社交时差/周末战士/HRR/睡眠需求 公式移植，去掉文案卡 |
| `rules.py` 合理性边界 | `pivis_health/risk_rules.py` v1 | PLAUSIBILITY 表与非诊断纪律继承；三级分级为 v2 新增 |
| `insights.parse_ts` 纳秒截断 | 引擎 `_p()` 的正则修复 | 真库时间戳 9 位小数 |
| 静默/防重复/0600 契约 | `skills/pivis-health/SKILL.md` 事故教训 | push_log marker、正常即静默、≥3 天才报断更、缺数据≠异常 |
| WHOOP 快照解析 | `integrations/whoop/runtime/whoop-snapshot.json` 结构 | 只读；RMSSD 与 Apple SDNN 不混算 |

## 尚未搬运（按 12-06 交棒计划）

- `integrations/whoop/`（OAuth 服务 + sync.py）→ 交棒日搬入 collector
- `pivis_health/` 包的导入器（importer/validation/schema）→ 交棒日搬入 collector
- `pivis_health_apple.py` 渲染 → 已被 web 晨报页取代，不搬；视觉稿待老板验收后迭代
- 旧渲染迭代稿 / paused 补投任务 → 不搬，留在 hermes 归档
