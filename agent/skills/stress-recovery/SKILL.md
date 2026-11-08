---
name: stress-recovery
version: 1.0.0
description: "压力和恢复：只用工具里的生理信号（HRV 趋势、静息心率、呼吸频率、恢复）判断有没有生理压力信号，给呼吸练习（叹息式、箱式、4-7-8、慢呼吸）和短正念的练习视频（只认 follow 出的片），帮老大定工作边界，知道什么时候转诊。早上那次【每日推荐】（顺带做每日整理）看压力信号时、老大说累、紧张、压力大、问 HRV 为什么低时使用。"
---

# 压力与恢复

## 什么时候用
- 早上那次【每日推荐】（顺带做每日整理）看压力信号。
- 老大说「压力好大」「心很乱」「最近好累」「HRV 怎么这么低」。
- 训练、睡眠 skill 发现恢复持续偏低，需要减压安排时。

呼吸和正念的具体做法、时长、注意事项见 `references/breathing.md`（用来挑视频、请老大找对的视频，不写成卡上的步骤）。

## 怎么做

### 1. 读信号（只用工具）
1. `./pivis-health facts`：看 `hrv_range.ready`、`hrv_trend`、`resting_hr`、`resp_rate`、`recovery_pct`、`recovery_zone`。
2. 静息心率和呼吸频率的变化，用工具算：
   - `./pivis-health compare --metric resting_hr --recent 3`
   - `./pivis-health compare --metric resp_rate --recent 3`
3. 逐条判断（自己和自己比，不是医学标准）：
   | 信号 | 条件 |
   |---|---|
   | HRV 下降 | `hrv_trend.change_pct ≤ -10` |
   | 静息心率上升 | resting_hr 的 compare `change ≥ 3` |
   | 呼吸频率上升 | resp_rate 的 compare `change ≥ 1` |
   | 恢复偏低 | `recovery_zone=red`，或 `recovery_pct.recent` 近 7 天里 ≥ 3 天低于 34 |
   - `hrv_range.ready=true` 时，还可以跑 `./pivis-health viz --metric hrv --kind trend`，看是不是过了警戒线。
   - `resting_hr.source` 不一样的数（WHOOP 和 Apple 健康）不混着比。
4. 结论：
   - **2 条或以上**：有明确的生理压力信号，进入第 2 步。
   - **1 条**：留意。不加待办，老大问起来就如实说。
   - **0 条**：说「压力这块没问题」。
   - compare 输出里说「样本少于 3 天」的那条不算。

### 2. 有信号时：先问原因，不猜情绪
- 对老大只说「生理压力信号偏高」，**不说「你压力大」「你焦虑」**，不从日历或单次 HRV 推断情绪。
- 用 question 卡（multi）问最近有没有：睡得少 / 喝酒 / 训练重 / 好像要感冒 / 工作或生活很紧张 / 都没有。
- 按回答处理：
  | 回答 | 处理 |
  |---|---|
  | 睡得少 | 交给 cbti 或睡眠安排，今天不加训练量 |
  | 喝酒 | 说一句：酒会压低 HRV、抬高心率，今晚不喝 |
  | 训练重 | 按 training-coach 今天降到「收」档 |
  | 好像要感冒 | 休息，多喝水，量体温。发烧或胸闷就按 clinical-safety 处理 |
  | 工作或生活很紧张 | 给一个呼吸练习（第 3 步），谈一条工作边界（第 4 步） |
  | 都没有 | 先观察 1–2 天，不加待办 |

### 3. 呼吸和正念（给具体的，不给「放松一下」）
- 先看 `./pivis-health follow session list` 里有没有这种呼吸的视频（follow 出的片）。
- 有：发 proposal 卡让老大选时间（模板见下）。选了以后把这张卡改成练习视频卡，只放这一个视频。
- 没有：不出卡，不写文字步骤，不用素材库里的音频代替。按 follow-video 的「还没有视频」请老大发一个博主的呼吸跟练视频，出好片再排。
- 默认：白天紧张用**叹息式呼吸 5 分钟**；开会或比赛前用**箱式呼吸 3 分钟**；睡前用 **4-7-8 呼吸 4 轮**，或者身体扫描（候选按 relaxation-media 找，老大同意后 follow 出片）。焦虑一下子上来时用 **5-4-3-2-1 着陆**。
- 第二天按 relaxation-media 第 7 步打分：有用就保留，没用就换一种。

### 4. 工作边界（老大选一条，写进项目 rules 或一张 done 卡）
- 固定收工时间（`profile.schedule.work_end`），收工后不回工作消息。
- 睡前 1 小时不看工作消息（做 CBT-I 时本来就有这条）。
- 每专注 90 分钟起来走 5 分钟。
- 每周至少半天完全不工作。
- 一次只定一条。做到 5/7 天以上满一周，再加下一条（habit-coach）。

### 5. 什么时候转诊（按 clinical-safety 处理）
- 情绪低落或没兴趣，持续两周以上；焦虑影响到睡觉和工作。
- 第一次出现心慌、喘不上气、觉得自己要不行了：先去急诊排除心脏问题，不要当成压力。
- 越来越靠酒、药、暴食来应付压力。
- 有伤害自己的念头：**立刻**按 clinical-safety 的「危机」处理。

## 规则与红线
1. 压力只说「生理压力信号」，数字只来自 `facts`、`compare`、`viz`。
2. 有明确信号（≥ 2 条）才加减压待办，最多一件。都正常就说「压力这块没问题」，不对老大说「数据不足」。
3. 呼吸练习中头晕、手麻、胸闷就停，恢复自然呼吸。有心肺疾病的不做长时间屏气（4-7-8、箱式改成不屏气的慢呼吸）。
4. 不诊断焦虑、抑郁，不推荐药物或保健品。
5. 老大说「算了」：按 AGENTS 红线 5。

## 模板
proposal（有信号时，`until` 必须写）：
```json
{"board":"stress","title":"今天做 5 分钟呼吸？","kind":"proposal","until":"18:00",
 "inputs":[{"id":"choice","label":"","type":"options","options":["午后做","睡前做","今天不用"],"submit":"agent"}]}
```
老大选了「午后做」以后，把这张卡改成练习视频卡（todo-update，只写一个 `media`）：
```json
{"title":"叹息式呼吸 5 分钟","when":"14:30","kind":"follow","note":"呼气要比吸气长","inputs":[],
 "media":{"kind":"video","title":"叹息式呼吸 · 5 分钟","url":"/media/follow/<ssid>/out.mp4","duration_min":5}}
```
箱式呼吸（开会前，todo-add）：
```json
{"board":"stress","title":"箱式呼吸 3 分钟","kind":"follow","note":"吸、停、呼、停各 4 秒",
 "media":{"kind":"video","title":"箱式呼吸 · 3 分钟","url":"/media/follow/<ssid>/out.mp4","duration_min":3}}
```
url 只能是 follow 出片给的地址；没有这种呼吸的视频就不出这张卡，先请老大发视频。

## 成长
- `stress.profile`：压力来源、老大习惯的应对方式、收工时间。
- `learn.stress`：`{"rule":"应酬喝酒后两天 HRV 都偏低","evidence":"近 3 次（facts 的 hrv_trend）"}`、`{"rule":"叹息式呼吸老大觉得有用，箱式没感觉"}`。
- 哪些信号组合之后真的生病了、哪些只是没睡好，记下来，下次先问最可能的那一个。
