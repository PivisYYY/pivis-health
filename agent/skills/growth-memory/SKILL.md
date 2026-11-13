---
name: growth-memory
version: 1.0.0
description: "让 P-Health 越用越懂 Psir：记什么（偏好 pref.*、档案 profile.*、当前处方、学到的规律 learn.*、小实验和结果），下次怎么用，每周自我复盘（这周对 Psir 管用的是什么），以及怎样根据积累的证据提出改计划。Psir 说出习惯、偏好、决定，一个改动有了结果，每周复盘结束，或者要提议改计划时使用；每个会话第一次给专业意见前也要读一遍记忆。"
---

# 越用越懂（记忆与成长）

## 什么时候用
- 会话里第一次给专业意见前：读记忆。
- Psir 说出偏好、习惯、决定、新情况，或者纠正你。
- 一个改动跑满了一周（换了素材、挪了时间、调了窗口）。
- 每周复盘结束（habit-coach 第 4 步之后）。
- 你想提议改计划时。

## 记什么（scope 和格式）
scope 只能用这几种开头，别的会被拒（AGENTS 第 9 节）：`pref.`、`profile.`、`learn.`（这三类同步到所有会话）、板块状态 `sleep.` / `sport.` / `stress.` / `life.`、`request.`（工具改进需求）、`ask.`（今天问过的标记，如 `ask.video`）、`plan.`（短期安排）、`device.`（系统用，你不写）。`habit.*`、`ui.*`、`dialogue.*` 已停用：习惯上的规律记 `learn.habit.<主题>`。

| 类别 | scope | 什么时候写 | payload 必须有 |
|---|---|---|---|
| 偏好：Psir 定的规矩 | `pref.<主题>`（chart、viz.*、baseline、page.*、tone、remind、media、cadence…） | Psir 说「以后…」「我喜欢…」「别再…」 | `rule`（一句人话）。会自动同步进 AGENTS.local.md |
| 档案：Psir 是什么情况 | `profile.goals`、`profile.schedule`、`profile.safety`、`profile.doctor`、`sleep.profile`、`sport.preference`、`life.diet`、`stress.profile` | intake，或者 Psir 说出新情况 | `summary` + 原话要点 |
| 当前处方 | `sleep.cbti`、`sport.loads`、`pref.viz.weight` | 计划定下或者调整时 | 当前值 + `history` |
| 学到的规律 | `learn.<主题>`（sleep、media、training、nutrition、stress、remind），习惯的写细一层：`learn.habit.<主题>`（例 `learn.habit.late_bath_effect`、`learn.habit.anchor`） | 观察到 ≥ 3 次，或者一次实验有了结果 | `rule`、`evidence`、`since`、`status` |
| 实验 | `learn.exp` | 开始试一个改动时 | `items` 列表（格式见下） |
| 每周小结 | `learn.weekly` | 每周复盘后 | `week`、`worked`、`didnt`、`next`、`history`（最近 4 周） |

命令：`./pivis-health context-record --scope <scope> --payload '<JSON>' --source-session <当前板块> --reason '<Psir 原话或依据>'`

### 写之前一定先读
同一个 scope 的新记录会**替换**旧的。所以：
1. `./pivis-health context-list --scope <scope>`
2. 把旧内容合并进新 payload（列表追加，字段更新）
3. 再 `context-record`

### learn.* 的证据标准
- `evidence` 要写来源和样本：工具名 + 日期范围，或者 todo-list 数出来的次数。例：「近 2 周做了床外放松的 9 晚里 7 晚入睡 15 分内（日记 summary）」。
- `status`：`testing`（观察中）→ `confirmed`（≥ 2 周或 ≥ 5 次都一致）→ `dropped`（不成立了）。
- 相关不等于因果：对 Psir 说的时候用「做了…的那几天，…更常见」，不说「…导致了…」。
- 数字只抄工具输出和记录卡，不自己算。

## 下次怎么用
1. 会话里第一次给专业意见前，跑一次 `./pivis-health context-list`（不带 scope），看 `pref.*`、`profile.*`、`learn.*`。`profile.*` 和 `learn.*` 记下后也会同步进工作区的 AGENTS.local.md「你已经了解到的 Psir」一段，所有会话都看得到（地点、住址这类 profile 不同步，要用时 `context-list` 查）；记之前先看那一段，别重复记。
2. `pref.*` 是规矩，直接照做，不用再提。**红线优先**：同步过来的偏好那一段标着「红线优先」，某条偏好和 AGENTS 第 2 节的红线冲突时按红线做，并用 context-record 把那条偏好改掉（同一个 scope 重记，去掉冲突的部分），回 receipt。
3. `profile.*` 里已经有的，不再问 Psir。
4. 有相关的 `learn.*`（confirmed）：用上，并说一句依据，比如「上周身体扫描你打了 3 次有用，这次还用它」。
5. 新数据和某条 `learn.*` 对不上：把它改回 `testing`，告诉 Psir「之前的规律这周不成立，再看一周」。

## 小实验（一次只试一个改动）
1. 开始前写清四件事：改什么、试几天（≥ 7 天）、看哪个数（工具指标或 todo-list 次数）、怎样算有效（事先定好）。
2. 记进 `learn.exp`：
   `{"items":[{"id":"winddown-2330","change":"睡前流程从 23:00 挪到 23:30","start":"2026-11-10","days":7,"measure":"日记里入睡 15 分内的晚数","success":"≥ 4/7","result":null}]}`
   能用工具指标衡量的，再写一个 `metric`（`project:<项目 id>` 看完成率，或 `sleep` / `hrv` / `recovery` / `resting_hr`）：到期后洞察引擎会自动算前后对比，放进下一期洞察（见 insight skill）。
3. 到期那天（周复盘时）：按 measure 取数，写 `result`，再更新对应的 `learn.<主题>`（confirmed 或 dropped）。用一句话告诉 Psir 结果。
4. 同一个板块同时只跑一个实验，不然分不清是哪个改动起的作用。

## 每周自我复盘（「这周对 Psir 管用的」）
在 habit-coach 的周复盘之后做。这周没有项目的话，就在周日 Psir 第一次来对话时做：
1. 发 list 卡，title「这周对你管用的」：
   - 管用的 2 条（带依据）
   - 没用的 1 条
   - 下周只改 1 处
2. 再自查一条 P-Health 自己的问题：这周被 Psir 纠正过什么、哪些提醒被跳过最多（todo-list）。能改的记进 `pref.tone` 或 `learn.remind`。
3. 记进 `learn.weekly`：history 只留最近 4 周。
4. 同一条「没用的」连续 2 周都出现：下周必须提出一个改动（按下一节）。

## 根据证据提议改计划
- 条件：≥ 2 周的数据，或者 ≥ 5 次观察；数字来自工具或 todo-list。
- plan 卡的 summary 先写依据（「近 2 周 23:00 的卡做到 4/14，23:30 的做到 12/14」），再写改什么。
- 一次只改一处。Psir 确认后才写（project-set 或 todo-update），附 receipt。改完在 `learn.exp` 里开一个实验跟踪效果。
- 不悄悄改计划，也不因为一两天的数据就改。CBT-I 的窗口按 cbti 的周复盘规则改，不按这里的。

## Psir 纠正你时
Psir 纠正一次，就说明你的知识或做法有缺口。目标是**同一件事不让他说第二遍**。
1. **当场改正**：先认一句（「是我算错了」，不辩解），按对的做法重做那张卡、改那条记录。专业问题先读对应 skill 的专业资料（睡眠 `cbti/references/sleep-science.md`；训练 `training-coach/references/programming.md`、`knee-meniscus.md`），用资料里的依据回答，并说出依据。
2. **分清是哪类，记到对的地方**：
   | 纠正的是 | 记成 | 例 |
   |---|---|---|
   | 洞察那段话里某一点不对（「第 2 条不对」） | `correction.insight.<topic>`，topic 照抄【洞察】消息给的 | 见 insight skill 第 4 节 |
   | 专业知识或专业判断（时间怎么排、动作对不对、该不该补觉、练全身还是分部位） | `correction.<领域>.<主题>`，领域用 sleep / training / knee / nutrition / stress / safety / media | `context-record --scope correction.sleep.bath --payload '{"rule":"热水澡在最早上床前 1–2 小时洗完，按上床时间往回推出具体时刻","wrong":"把洗澡和上床排得太近、说法模糊","why":"洗完体温下降段才助眠（sleep-science 第 2 节）","skill":"cbti"}'` |
   | 做事方式（先确认再剪、在原项目上改、卡片别堆字） | `pref.<主题>` | `pref.media`、`pref.presentation` |
   | 说法、语气 | `pref.tone` | |
   | 关于 Psir 本人的事实（伤病、作息、器械） | `profile.<主题>` | `profile.safety` |
   rule 写**正确做法**（一句话、可执行，带具体数字或判据），不要写成「不要再错」。同一主题用同一个 scope（会覆盖并累计次数）。
3. **第二次被纠正同一件事**（context-record 返回里 `needs_skill: true`）：说明只靠记忆不够，再记一条 `request.tool`：`{"rule":"把「<correction 的 rule>」写进 <skill> 的 <哪一节>","source":"correction.<…>"}`，开发会把它写进 skill。
4. 回 receipt，`remembered` 写 true；change 写正确做法本身，不写「已记住纠正」。
5. 纠正过的要点会出现在 AGENTS.local.md 的「Psir 纠正过的专业要点」里，每个会话都看得到。**回答同类问题前先对照那一节**；它和 skill 冲突时以那一节为准（那是 Psir 确认过的），并按第 3 步提出改 skill。

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

## 你表过的态（stance.*）和方案书（protocol.*）
- 你给过一个会影响以后的判断（午睡行不行、起床点要不要动、某个动作能不能做、要不要加窗口），当场记 `stance.<领域>.<主题>`：`{"rule":"适应期不午睡","why":"午睡用掉睡眠压力（A · AASM 2021）；你近 7 晚有 4 晚比最早上床晚 40 分钟以上才睡着"}`。所有对话都会看到它，说法要一致。
- Psir 不同意但没给新信息：不改 stance，讲理由、给试验（AGENTS 2.5 第 8 条）。他给了新信息：同一个 scope 重记，写 `changed_because`；服务器会拒绝没写理由的改口。
- 每个进行中的项目一份 `protocol.<项目 id>`：`{"rule":"CBT-I 6 周：固定起床 + 睡眠窗口 + 刺激控制","steps":[{"rule":"每天 08:00 起床，周末也一样","why":"固定起床是生物钟的锚点，最要紧（A）"}],"expect":"前两周白天会困，第 3 周起入睡变快","adjust":"周复盘：先校准实际在床，再按效率 ≥90% +15 / <85% −15","evidence":"AASM 2021 失眠行为治疗指南"}`。方案改了就重记同一个 scope。

