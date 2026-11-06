# 拼好的整卡例子

每张都在演示数据上用 `./pivis-health canvas` 预览过、没超高。照着改 bind 和标题，**发之前自己再预览一遍**（数据不同，某格可能算不出来）。
项目 id（这里的 `cbti`）和待办 key（`project:cbti:bed` 里的 `bed`）换成 `./pivis-health project-list` 里真实的。

## 睡眠主卡（主卡 --slot hero）
主卡：一个数 + 离需要多远 + 近 7 晚够不够（hero.layout，标题行 App 画，所以不写 title）
```json
{"t": "v", "gap": 12, "children": [{"t": "h", "justify": "between", "align": "baseline", "children": [{"t": "value", "bind": "sleep", "size": "xl"}, {"t": "stat", "label": "需要", "bind": "sleep.need"}]}, {"t": "bar", "bind": "sleep"}, {"t": "dots", "bind": "sleep.nights", "days": 7}]}
```

## CBT-I 窗口（对话卡）
对话卡：CBT-I 这周的窗口、近 7 晚守没守、离今晚上床还有多久
```json
{"t": "v", "gap": 12, "children": [{"t": "text", "text": "这周的睡眠窗口", "role": "title"}, {"t": "time_range", "bind": "project:cbti"}, {"t": "sleep_window", "days": 7}, {"t": "countdown", "to": "project:cbti:bed", "label": "离上床还有"}]}
```

## 压力两条线（对话卡）
对话卡：两项一起看才说明问题时，dual_line 画走势，delta 写清各变了多少
```json
{"t": "v", "gap": 12, "children": [{"t": "text", "text": "HRV 往下，静息心率没动", "role": "title"}, {"t": "dual_line", "a": "hrv", "b": "resting_hr", "days": 14}, {"t": "h", "children": [{"t": "delta", "bind": "hrv", "baseline": "prev3"}, {"t": "delta", "bind": "resting_hr", "baseline": "prev3"}]}]}
```

## 身体状态三个数（对话卡）
对话卡：老大要「用几个数字告诉我」——stat_spark 横排，数 + 方向
```json
{"t": "v", "gap": 12, "children": [{"t": "text", "text": "今天的身体状态", "role": "title"}, {"t": "h", "justify": "between", "children": [{"t": "stat_spark", "bind": "hrv", "label": "HRV"}, {"t": "stat_spark", "bind": "resting_hr", "label": "静息心率"}, {"t": "stat_spark", "bind": "resp_rate", "label": "呼吸"}]}]}
```

## 训练强度（对话卡）
对话卡：这周强度构成 + 最近一次在各区间停了多久（要 WHOOP 训练的心率区间）
```json
{"t": "v", "gap": 12, "children": [{"t": "text", "text": "这周练得偏轻松", "role": "title"}, {"t": "donut", "bind": "training.zones"}, {"t": "zones", "bind": "workout.last"}]}
```

## 习惯坚持（对话卡）
对话卡：几个项目各做到多少 + 一个坚持类目标的连续天数
```json
{"t": "v", "gap": 12, "children": [{"t": "text", "text": "这周的几个习惯", "role": "title"}, {"t": "progress_list", "bind": "projects", "days": 7}, {"t": "streak", "bind": "wake:08:30"}]}
```

## 欠觉主卡（主卡 --slot hero）
主卡：睡眠债 + 每晚比需要少多少 + 昨晚分期构成
```json
{"t": "v", "gap": 12, "children": [{"t": "value", "bind": "sleep_debt", "size": "xl"}, {"t": "diverging", "bind": "sleep.need", "days": 7}, {"t": "stack", "bind": "sleep.stages"}]}
```
