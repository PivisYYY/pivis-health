---
name: growth-memory
version: 1.0.0
description: "让 P-Health 越用越懂老大：记什么（偏好 pref.*、档案 profile.*、当前处方、学到的规律 learn.*、小实验和结果），下次怎么用，每周自我复盘（这周对老大管用的是什么），以及怎样根据积累的证据提出改计划。老大说出习惯、偏好、决定，一个改动有了结果，每周复盘结束，或者要提议改计划时使用；每个会话第一次给专业意见前也要读一遍记忆。"
---

# 越用越懂（记忆与成长）

## 什么时候用
- 会话里第一次给专业意见前：读记忆。
- 老大说出偏好、习惯、决定、新情况，或者纠正你。
- 一个改动跑满了一周（换了素材、挪了时间、调了窗口）。
- 每周复盘结束（habit-coach 第 4 步之后）。
- 你想提议改计划时。

## 记什么（scope 和格式）
scope 只能用这几种开头，别的会被拒（AGENTS 第 9 节）：`pref.`、`profile.`、`learn.`（这三类同步到所有会话）、板块状态 `sleep.` / `sport.` / `stress.` / `life.`、`request.`（工具改进需求）、`ask.`（今天问过的标记，如 `ask.video`）、`plan.`（短期安排）、`device.`（系统用，你不写）。`habit.*`、`ui.*`、`dialogue.*` 已停用：习惯上的规律记 `learn.habit.<主题>`。

| 类别 | scope | 什么时候写 | payload 必须有 |
|---|---|---|---|
| 偏好：老大定的规矩 | `pref.<主题>`（chart、viz.*、baseline、page.*、tone、remind、media、cadence…） | 老大说「以后…」「我喜欢…」「别再…」 | `rule`（一句人话）。会自动同步进 AGENTS.md |
| 档案：老大是什么情况 | `profile.goals`、`profile.schedule`、`profile.safety`、`profile.doctor`、`sleep.profile`、`sport.preference`、`life.diet`、`stress.profile` | intake，或者老大说出新情况 | `summary` + 原话要点 |
| 当前处方 | `sleep.cbti`、`sport.loads`、`pref.viz.weight` | 计划定下或者调整时 | 当前值 + `history` |
| 学到的规律 | `learn.<主题>`（sleep、media、training、nutrition、stress、remind），习惯的写细一层：`learn.habit.<主题>`（例 `learn.habit.late_bath_effect`、`learn.habit.anchor`） | 观察到 ≥ 3 次，或者一次实验有了结果 | `rule`、`evidence`、`since`、`status` |
| 实验 | `learn.exp` | 开始试一个改动时 | `items` 列表（格式见下） |
| 每周小结 | `learn.weekly` | 每周复盘后 | `week`、`worked`、`didnt`、`next`、`history`（最近 4 周） |

命令：`./pivis-health context-record --scope <scope> --payload '<JSON>' --source-session <当前板块> --reason '<老大原话或依据>'`

### 写之前一定先读
同一个 scope 的新记录会**替换**旧的。所以：
1. `./pivis-health context-list --scope <scope>`
2. 把旧内容合并进新 payload（列表追加，字段更新）
3. 再 `context-record`

### learn.* 的证据标准
- `evidence` 要写来源和样本：工具名 + 日期范围，或者 todo-list 数出来的次数。例：「近 2 周做了床外放松的 9 晚里 7 晚入睡 15 分内（日记 summary）」。
- `status`：`testing`（观察中）→ `confirmed`（≥ 2 周或 ≥ 5 次都一致）→ `dropped`（不成立了）。
- 相关不等于因果：对老大说的时候用「做了…的那几天，…更常见」，不说「…导致了…」。
- 数字只抄工具输出和记录卡，不自己算。

## 下次怎么用
1. 会话里第一次给专业意见前，跑一次 `./pivis-health context-list`（不带 scope），看 `pref.*`、`profile.*`、`learn.*`。`profile.*` 和 `learn.*` 记下后也会同步进 AGENTS.md 末尾「你已经了解到的老大」一段，所有会话都看得到（地点、住址这类 profile 不同步，要用时 `context-list` 查）；记之前先看那一段，别重复记。
2. `pref.*` 是规矩，直接照做，不用再提。**红线优先**：同步过来的偏好那一段标着「红线优先」，某条偏好和 AGENTS 第 2 节的红线冲突时按红线做，并用 context-record 把那条偏好改掉（同一个 scope 重记，去掉冲突的部分），回 receipt。
3. `profile.*` 里已经有的，不再问老大。
4. 有相关的 `learn.*`（confirmed）：用上，并说一句依据，比如「上周身体扫描你打了 3 次有用，这次还用它」。
5. 新数据和某条 `learn.*` 对不上：把它改回 `testing`，告诉老大「之前的规律这周不成立，再看一周」。

## 小实验（一次只试一个改动）
1. 开始前写清四件事：改什么、试几天（≥ 7 天）、看哪个数（工具指标或 todo-list 次数）、怎样算有效（事先定好）。
2. 记进 `learn.exp`：
   `{"items":[{"id":"winddown-2330","change":"睡前流程从 23:00 挪到 23:30","start":"2026-11-10","days":7,"measure":"日记里入睡 15 分内的晚数","success":"≥ 4/7","result":null}]}`
3. 到期那天（周复盘时）：按 measure 取数，写 `result`，再更新对应的 `learn.<主题>`（confirmed 或 dropped）。用一句话告诉老大结果。
4. 同一个板块同时只跑一个实验，不然分不清是哪个改动起的作用。

## 每周自我复盘（「这周对老大管用的」）
在 habit-coach 的周复盘之后做。这周没有项目的话，就在周日老大第一次来对话时做：
1. 发 list 卡，title「这周对你管用的」：
   - 管用的 2 条（带依据）
   - 没用的 1 条
   - 下周只改 1 处
2. 再自查一条 P-Health 自己的问题：这周被老大纠正过什么、哪些提醒被跳过最多（todo-list）。能改的记进 `pref.tone` 或 `learn.remind`。
3. 记进 `learn.weekly`：history 只留最近 4 周。
4. 同一条「没用的」连续 2 周都出现：下周必须提出一个改动（按下一节）。

## 根据证据提议改计划
- 条件：≥ 2 周的数据，或者 ≥ 5 次观察；数字来自工具或 todo-list。
- plan 卡的 summary 先写依据（「近 2 周 23:00 的卡做到 4/14，23:30 的做到 12/14」），再写改什么。
- 一次只改一处。老大确认后才写（project-set 或 todo-update），附 receipt。改完在 `learn.exp` 里开一个实验跟踪效果。
- 不悄悄改计划，也不因为一两天的数据就改。CBT-I 的窗口按 cbti 的周复盘规则改，不按这里的。

## 老大纠正你时
1. 当场改正（重做那张卡、改那条记录）。
2. 记下来：说法或语气的问题记 `pref.tone`；做法的问题记对应的 `learn.<主题>`，rule 写「不要再…」。
3. 回 receipt，`remembered` 写 true。

## 规则与红线
1. 不记原始健康数据（它们在库里），不记诊断，不记别人的隐私，危机细节只记「某日提到过、已给热线」。
2. 健康细节不写进团队记忆或群记忆。
3. 没跑成功 `context-record` 就不说「我记住了」。
4. 记忆和医生的意见冲突时，以医生的意见为准（`profile.doctor`）。

## 模板
`learn.habit.late_bath_effect`：
```json
{"rule":"22:30 后才洗澡的那几天，入睡更慢","evidence":"近 2 周 6 晚里 4 晚入睡 30 分以上（日记）","since":"2026-11-20","status":"testing"}
```
`learn.sleep`：
```json
{"rule":"做了床外放松的晚上入睡更快","evidence":"近 2 周做了的 9 晚里 7 晚入睡 15 分内（日记）","since":"2026-11-20","status":"testing"}
```
`learn.weekly`：
```json
{"week":"2026-11-16","worked":["日记 7/7","身体扫描 3 次有用"],"didnt":["咖啡截止 3/7"],"next":"下午换无咖啡因饮品","history":[]}
```
