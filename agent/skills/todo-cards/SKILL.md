---
name: todo-cards
version: 1.0.0
description: "写待办卡用的 13 种形式（全部以 `./pivis-health todo-forms` 为准：打勾、单选、数值、日记、计数、计时、练习视频、拍照、打分、提议、追问……）。练习一律是「这个项目 + 一个 follow 视频」。要给老大加或改待办（todo-add / todo-update / project-set 里的 daily 模板）、想把一件事做成卡片、或不确定该用哪种 kind 时使用。"
---

# 待办卡：13 种形式

待办出现在页面的「接下来」里：左边时间，中间标题和一句备注，右边一个主动作；要填东西的点开后在下面展开。你只写字段，App 按形式画。

## 怎么做
1. 先想清楚：这件事要老大**做**什么、你要**拿回**什么（一个数？一个选择？一张照片？只要知道做没做？）。
2. 按下表选形式，用 `./pivis-health todo-forms --form <名字>` 拿模板（不加参数列出全部 13 种，以它为准）；全部字段见 references/fields.md，午睡、练习视频、提议的完整流程见 references/flows.md。
3. 按模板改字段，`./pivis-health todo-add --json '<JSON>'`（长期每天出现的写进项目的 `daily`，用 project-set）。
4. 老大交了需要你处理的（submit 是 agent），你会收到【待办提交】，按 AGENTS.md 第 6 节处理。

## 选哪种
| 要什么 | 形式（form → kind） |
|---|---|
| 只要知道做没做 | check → done；设备能自动识别的（入睡）用 auto → done + `"auto":"bedtime"` |
| 一个选择 | options；用完东西后的评价用 rating；破了规则问原因用 ask（只给选项） |
| 一个数 | number（`unit`、`step`；体重这类 `"default":"last"` 先填上次的值） |
| 一次记好几样 | fields（time、options、number+step、scale、text 混用，最多 5 项） |
| 一天点好几次 | counter（`target`、`unit`） |
| 午睡、闭眼歇 | timer（`duration_min`，要叫醒就写 `alarm` = 开始 + 时长）。只用于这两种休息，不用于练习 |
| 练习（拉伸、力量、呼吸、身体扫描、睡前流程、入眠练习） | follow（练习视频）：这个项目 + 一个 follow 出的视频 |
| 一张照片 | photo → fields + 一个 `type:"photo"` 输入 |
| 想改计划，等老大拍板 | proposal（原因写 note，2–3 个方案，**一定写 until**） |
| 要留下几点做的 | confirm（用药、打针；卡上只写「按医嘱…」，不写剂量） |

## 练习视频卡
- 只放一个视频，视频只认 follow 出片给的地址（`./pivis-health follow session list` 里的 video）：
  `{"board":"sleep","when":"22:40","title":"睡前拉伸","kind":"follow","media":{"kind":"video","title":"睡前拉伸 · 8 分钟","url":"/media/follow/<ssid>/out.mp4","duration_min":8}}`
- 不写文字步骤，不用计时、音频、清单当练习；B 站、小红书链接不能直接放进卡。还没有视频：请老大发一个博主视频，follow 出片后再排（follow-video skill 的「还没有视频」）。
- 老大点对勾才算做完；看了多少不算。
- todo-update 换视频：只写新视频的 `media`，会替换原来那一个。

## 写法规矩
- `title` ≤14 字，说做什么；`note` ≤16 字，只写有信息量的一句（「在床外做，床只用来睡」），不写操作说明（「做了就点一下」）。
- 每张卡只有一个主动作，没有回复框、「晚点」「算了」。不要写 `verbs`，待办卡的输入也不要写 `allow_text`（写了也没用）。老大要改时间、今天不做、多说一句，会点卡上的 P-Health 图标进对话说，消息开头带【待办 …】（见 AGENTS 第 6 节）。
- 选项 2–4 个最好（最多 6）；拿不准老大怎么答，就加一个「别的原因」这类选项。
- 会响的卡（带 `when`）有上限，写 `when` 前看 daily-reminders。
- 同一件事别同时出两张卡：项目已经有的，改项目模板，不要另加。
- 到点问老大、提醒老大，都用带 `when` 的待办卡（AGENTS 红线 7）。
- 老大要你「给个提议卡让我选」「给几个方案」时，**一定用 proposal 待办卡**（todo-add，kind=proposal，2–3 个方案，`until` 写今天晚些时候），不要用对话里的 plan 卡代替：plan 卡是你已经定了一个方案、等他点头。哪怕你建议不改，也照样出提议卡，把你建议的放第一个选项（「先不动，下周日按数据调」），原因写进 note；对话里一句话说明「提议卡在休息页，选了我就照做」。
- 项目里的卡会自动带「上次」（练习视频卡显示上次的评价，数值卡先填上次的数），不用你写。

## 交上来以后
- counter / timer / confirm / 练习视频卡是 App 直接记的，不会发给你；老大有话会带着这张卡进对话说（消息开头【待办 …】）。
- 有 `submit:"agent"` 的输入交上来时卡片进入「P-Health 在看」，你要在这一轮里用 todo-update 把它改成 done（summary 写一句结果）或改成追问卡；不改，系统会把卡退回并打开对话。
