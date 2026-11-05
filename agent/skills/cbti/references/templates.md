# CBT-I 模板（照抄，时间换成老大的）

示例按「起床 08:00、窗口 7.5 小时」写：最早上床 00:30，咖啡截止 16:30，睡前流程 23:30，日记 08:20。
**这些是示例时间，写入前必须换成开始前第 3 步算出的时间。** `start` 用 `./pivis-health now` 的今天。`reviews` 写开始满 7 天后的每个周日。开始不满 7 天的那个周日，复盘卡照样会出，只看执行情况，不调窗口。

## 1. 项目（project-set）
媒体 url 只能从 `./pivis-health media-library` 里选（或用 relaxation-media 选定的 B 站链接），不要照抄占位符。
```json
{"id":"cbti","name":"CBT-I","board":"sleep","start":"2026-11-06","days":42,
 "goal":"固定起床、压缩在床时间，让睡眠变整，再慢慢加回来",
 "rules":["每天 08:00 起床，周末也一样",
          "00:30 前不上床，困了才上床",
          "醒着超过约 20 分钟就下床，困了再回",
          "床只用来睡觉",
          "白天不睡，要睡就 15:00 前、最多 20 分钟",
          "16:30 后不喝咖啡、浓茶",
          "睡前 1 小时不看工作消息"],
 "reviews":[{"date":"2026-11-15","title":"第 1 次复盘：按睡眠效率调窗口"},
            {"date":"2026-11-22","title":"第 2 次复盘"},
            {"date":"2026-11-29","title":"第 3 次复盘"},
            {"date":"2026-12-06","title":"第 4 次复盘"},
            {"date":"2026-12-13","title":"第 5 次复盘：决定维持还是延长"}],
 "daily":[
  {"key":"diary","when":"08:20","title":"记一下昨晚","kind":"fields","submit_label":"记好了",
   "inputs":[{"id":"bed","label":"几点上床","type":"time","submit":"agent"},
             {"id":"latency","label":"躺下后多久睡着","type":"options","options":["15 分内","15–30","30–60","1 小时+"],"submit":"agent"},
             {"id":"wakes","label":"夜里醒了几次","type":"options","options":["0","1","2","3+"],"submit":"agent"},
             {"id":"out","label":"醒着超过 20 分钟，下床了吗","type":"options","options":["没醒那么久","下床了","没下床"],"submit":"agent"},
             {"id":"up","label":"几点起床","type":"time","submit":"agent"},
             {"id":"quality","label":"睡得怎么样","type":"scale","min":1,"max":5,"min_label":"很差","max_label":"很好","submit":"agent"},
             {"id":"relax","label":"昨晚的睡前放松","type":"options","options":["有用","一般","没用","没做"],"submit":"agent"}]},
  {"key":"caffeine","title":"16:30 后不喝咖啡","kind":"done","note":"浓茶、能量饮料也算"},
  {"key":"winddown","when":"23:30","title":"床外拉伸 + 呼吸","kind":"follow","note":"在床外做，手机放远","duration_min":17,
   "steps":[{"title":"床外站立拉伸","media":{"kind":"audio","title":"床外站立拉伸","url":"<media-library 里的 url>","duration_min":11}},
            {"title":"4-7-8 呼吸","media":{"kind":"audio","title":"4-7-8 呼吸跟练","url":"<media-library 里的 url>","duration_min":6}}],
   "verbs":["start","later","skip"]},
  {"key":"bed","when":"00:30","title":"00:30 后再上床","kind":"done","auto":"bedtime","note":"困了再上床，床只用来睡"},
  {"key":"review","weekdays":[7],"title":"本周睡眠复盘","kind":"proposal","until":"22:00",
   "inputs":[{"id":"go","label":"花 3 分钟看这周的数据","type":"options","options":["现在看","明天再看"],"submit":"chat"}]}]}
```
写入：`./pivis-health project-set --json '<上面的 JSON>'`。每周调窗口时用同一个 id 再 set 一次，只改 rules 里的时间，以及 caffeine、winddown、bed 三项的 title 和 when。

## 2. 追问卡（每天最多一张，todo-add）
| 破例 | title | options |
|---|---|---|
| 起晚 | 起晚了，是什么原因 | 没听到闹钟 / 太困起不来 / 想多睡会 / 别的原因 |
| 早上床 | 早上床了，是什么原因 | 太困了 / 没事做 / 想早点睡着 / 别的原因 |
| 没下床 | 醒着没下床，为什么 | 太冷不想动 / 怕更清醒 / 没意识到 / 别的原因 |
| 午睡 | 午睡超时了，为什么 | 太困了 / 闹钟没响 / 没注意时间 / 别的原因 |
| 咖啡 | 下午喝了咖啡，为什么 | 太困了 / 习惯了 / 开会或应酬 / 别的原因 |

```json
{"board":"sleep","title":"起晚了，是什么原因","kind":"options",
 "inputs":[{"id":"why","label":"","type":"options","options":["没听到闹钟","太困起不来","想多睡会","别的原因"],"submit":"agent"}]}
```

## 3. 原因 → 回应（规则不变，只加支持）
| 原因 | 回应里的「明天怎么做」 |
|---|---|
| 没听到闹钟 | 闹钟放到床外够不着的地方，响了必须起身去关 |
| 太困起不来 / 想多睡会 | 头两周会这样。起来先拉开窗帘、到床外坐 5 分钟。困意会让今晚更好睡，这正是要的效果 |
| 太困了（早上床） | 困了先在床外坐着做睡前流程，到点再上床。困而不上床，今晚的睡眠会更整 |
| 没事做 / 想早点睡着 | 列 2 件睡前能做的安静事（看纸质书、听播客），写进睡前流程 |
| 太冷不想动 / 怕更清醒 | 床边放一件外套；下床后只开暗光，做安静的事，困了就回去，不会越来越清醒 |
| 没意识到 | 不看表，感觉「躺了好一会还清醒」就下床 |
| 开会或应酬（咖啡） | 下午换成无咖啡因的饮品，开会时可以喝温水 |
| 别的原因 | escalate 到对话，用 question 卡问一句具体是什么 |

## 4. 记录
- 日记 todo-update：`{"status":"done","summary":"00:35 上床 · 08:00 起 · 入睡 15–30 分","record":{"values":{"bed":"00:35","latency":"15–30","wakes":"1","out":"没醒那么久","up":"08:00","quality":3,"relax":"有用"}}}`
- 追问卡 todo-update：`{"status":"done","summary":"原因：太困起不来 · 规则不变"}`
- 复盘后 `sleep.cbti`：在原 payload 上改 earliest_bed、window_h、week，并在 history 里追加一条。
