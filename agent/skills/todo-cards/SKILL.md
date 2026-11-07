---
name: todo-cards
version: 1.0.0
description: "写待办卡用的 14 种形式：打勾、单选、数值、多字段日记、计数、计时、跟做、子清单、拍照、打分、提议、追问加文字、设备自动完成、确认加时间。要给老大加或改待办（todo-add / todo-update / project-set 里的 daily 模板）、想把一件事做成卡片、或不确定该用哪种 kind 时使用。"
---

# 待办卡：14 种形式

待办出现在页面的「接下来」里：左边时间，中间标题和一句备注，右边一个动作；要填东西的点开后在下面展开。你只写字段，App 按形式画。

## 怎么做
1. 先想清楚：这件事要老大**做**什么、你要**拿回**什么（一个数？一个选择？一张照片？只要知道做没做？）。
2. 按下表选形式，用 `./pivis-health todo-forms --form <名字>` 拿模板（不加参数列出全部 14 种）；全部字段见 references/fields.md，午睡、跟做、提议的完整流程见 references/flows.md。
3. 按模板改字段，`./pivis-health todo-add --json '<JSON>'`（长期每天出现的写进项目的 `daily`，用 project-set）。
4. 老大交了需要你处理的（submit 是 agent），你会收到【待办提交】，按 AGENTS.md 第 6 节处理。

## 选哪种
| 要什么 | 形式（form → kind） |
|---|---|
| 只要知道做没做 | check → done；设备能自动识别的（入睡）用 auto → done + `"auto":"bedtime"` |
| 一个选择 | options；用完东西后的评价用 rating；破了规则问原因用 ask（加 `"allow_text":true`） |
| 一个数 | number（`unit`、`step`；体重这类 `"default":"last"` 先填上次的值） |
| 一次记好几样 | fields（time、options、number+step、scale、text 混用，最多 5 项） |
| 一天点好几次 | counter（`target`、`unit`） |
| 有时长、到点结束 | timer（`duration_min`，要叫醒就写 `alarm` = 开始 + 时长） |
| 要跟着音频 / 视频 / 步骤做 | follow（`steps` / `media`，素材先查 media-library） |
| 一件事拆成几小步 | checklist（`items`，2–8 步，每步 ≤20 字） |
| 一张照片 | photo → fields + 一个 `type:"photo"` 输入 |
| 想改计划，等老大拍板 | proposal（原因写 note，2–3 个方案，**一定写 until**） |
| 要留下几点做的 | confirm（用药、打针；卡上只写「按医嘱…」，不写剂量） |

## 写法规矩
- `title` ≤14 字，说做什么；`note` ≤16 字，只写有信息量的一句（「在床外做，床只用来睡」），不写操作说明（「做了就点一下」）。
- 每张卡 App 都自带「和 P-Health 说」和回复框，不要自己加。
- 选项 2–4 个最好（最多 6）；不确定老大怎么答就加 `allow_text`。
- 一天主动加的提醒不超过 3 个时间点；老大自己要的不算（见 daily-reminders skill）。
- 同一件事别同时出两张卡：项目已经有的，改项目模板，不要另加。
- 到点问老大、提醒老大，都用带 `when` 的待办卡，不用定时任务（schedule_* 工具）；老大明说「用定时任务」也一样，见 AGENTS 红线 7。
- 老大要你「给个提议卡让我选」「给几个方案」时，**一定用 proposal 待办卡**（todo-add，kind=proposal，2–3 个方案，`until` 写今天晚些时候），不要用对话里的 plan 卡代替：plan 卡是你已经定了一个方案、等他点头。哪怕你建议不改，也照样出提议卡，把你建议的放第一个选项（「先不动，下周日按数据调」），原因写进 note；对话里一句话说明「提议卡在休息页，选了我就照做」。
- 项目里的卡会自动带「上次」（跟做卡显示上次的评价，数值卡先填上次的数），不用你写。

## 交上来以后
- counter / checklist / timer / confirm 是 App 直接记的，不会发给你，除非老大在回复框里说话。
- 有 `submit:"agent"` 的输入交上来时卡片进入「P-Health 在看」，你要在这一轮里用 todo-update 把它改成 done（summary 写一句结果）或改成追问卡；不改，系统会把卡退回并打开对话。
