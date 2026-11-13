# 待办字段

`board`（sleep/sport/stress/life，必填；life＝日常，比如饭、试纸这类记录，只出现在「此刻」页）· `title`（必填，≤14 字）· `when`（HH:MM，可空）· `date` · `note`（可空，≤16 字，只写有信息量的一句，比如「在床外做，床只用来睡」；不写操作说明，比如「做了就点一下」「到点闹钟叫醒你」，App 会自己表达）· `kind` · `inputs` · `media` · `steps` · `duration_min` · `alarm`（HH:MM，到点响闹钟）· `auto`（"bedtime"：设备识别入睡自动打勾）· `submit_label` · `until`（HH:MM，过点没回就自动收起；**提议卡一定要写**，比如午睡提议 14:30、当天训练提议 20:00）

新形式专用：
- follow（练习视频）：一个 `media`，`{"kind":"video","title":"…","url":"/media/follow/<ssid>/out.mp4","duration_min":8}`，url 只能是 follow 出片给的地址。系统会把它放进唯一的一步。todo-update 换视频时只写新的 `media`，会替换那一步。不写文字步骤。
- counter：`target`（1–20）、`unit`（≤4 字，默认「次」）
- timer：`duration_min`（必填）、`alarm`。只用于午睡、闭眼歇
- confirm：不用额外字段（App 记下完成时间）

## inputs（每项）
`{"id":"latency","label":"躺下后多久睡着","type":"options","options":["15 分内","15–30","30–60","1 小时+"],"submit":"local"}`
- type：options / multi / scale（min、max、min_label、max_label）/ number（unit；`step` 画加减按钮；`default`："last" 先填上次的值，或一个数）/ text（placeholder）/ time / photo（拍照或从相册选，submit 用 agent，照片会交给你看）
- 待办卡上的 options / multi 不能让 Psir 自己写一句（`allow_text` 无效，不要写）；要文字就单独加一项 type=text。
- **submit**：`local` 直接记录；`agent` 交给你处理（卡片进入等待态，你收到【待办提交】后用 todo-update 更新）；`chat` 直接转到对话。文字输入默认 agent。

## 主动作（不用写）
每张卡只有一个主动作，系统按 kind 定：练习视频是开始 + 做完（点对勾），计时是开始，打勾卡是做完，其余没有。没有「晚点」「算了」，不要写 `verbs`。
