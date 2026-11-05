# 首周了解：7 个主题

规则：
- 每次只问一个主题，每个主题 2–4 题。
- 老大在对话里，就把下面的 fields 放进 question 卡的 `fields`（可以加 `"allow_text":true`）。
- 老大不在对话里，就放进「了解你 · <主题>」待办的 `inputs`，每项加 `"submit":"agent"`。待办的选项限 2–6 个，不能用 allow_text。
- 记录时 payload 写老大的原话要点和一句 `summary`。`pref.*` 的 payload 必须带一句 `rule`。
- 同一个 scope 的新记录会替换旧的。要补充时，先 `context-list --scope <scope>`，合并旧内容后再写。
- 每个主题下面列了「红旗选项」。老大选了其中任何一个，当场按 `../../clinical-safety/SKILL.md` 处理。

## 1. 目标 → `profile.goals`
```json
[{"id":"focus","label":"这三个月最想改善什么","type":"multi","options":["睡得好","减重","体能 / 网球","压力小一点","白天精力"]},
 {"id":"success","label":"做到什么样算成功","type":"text"},
 {"id":"block","label":"最大的阻碍","type":"options","options":["时间不够","坚持不下来","不知道怎么做","工作压力"]}]
```

## 2. 作息 → `profile.schedule`
```json
[{"id":"wake","label":"工作日一般几点起","type":"time"},
 {"id":"work_start","label":"几点开始工作","type":"options","options":["9 点前","9–10 点","10 点后","不固定"]},
 {"id":"work_end","label":"晚上一般几点收工","type":"options","options":["19 点前","19–21 点","21–23 点","更晚"]},
 {"id":"weekend","label":"周末比平时晚起多少","type":"options","options":["差不多","1 小时内","1–2 小时","2 小时以上"]}]
```

## 3. 睡眠 → `sleep.profile`，安全筛查 → `profile.safety`
```json
[{"id":"issue","label":"现在最困扰的","type":"multi","options":["入睡难","半夜醒","早醒","睡了不解乏","白天犯困","没什么问题"]},
 {"id":"since","label":"持续多久了","type":"options","options":["不到 1 个月","1–3 个月","3 个月以上"]},
 {"id":"body","label":"有没有这些情况","type":"multi","options":["打鼾很响或被说憋气","开车时犯困","腿不舒服总想动","都没有"]},
 {"id":"history","label":"有没有这些情况","type":"multi","options":["双相情感障碍","癫痫","倒班或常上夜班","怀孕","都没有"]}]
```
追加一题（只在对话里问）：「在吃助眠药吗？医生知道你要做睡眠训练吗？」
- 红旗选项：打鼾很响或被说憋气、开车时犯困、双相情感障碍、癫痫、倒班或常上夜班、怀孕。
- `profile.safety` 记 `{"cbti_ok":true,"flags":[],"summary":"…"}`。选了任何红旗选项，就写 `"cbti_ok":false` 并把它写进 flags，再按 cbti 的「开始前」处理。

## 4. 运动 → `sport.preference`
```json
[{"id":"types","label":"现在常做","type":"multi","options":["网球","力量","跑步","拉伸 / 瑜伽","基本不动"]},
 {"id":"freq","label":"每周能练几次","type":"options","options":["1–2 次","3–4 次","5 次以上"]},
 {"id":"time","label":"一般什么时候练","type":"options","options":["早上","中午","晚上","不固定"]},
 {"id":"injury","label":"哪里有伤或常不舒服","type":"multi","options":["都没有","肩","肘","腰","膝","踝"]}]
```

## 5. 饮食与体重 → `life.diet`
```json
[{"id":"meals","label":"一天一般几顿","type":"options","options":["2 顿","3 顿","3 顿 + 加餐","不规律"]},
 {"id":"source","label":"大多吃什么","type":"options","options":["自己做","食堂","外卖","下馆子"]},
 {"id":"hard","label":"最难控制的","type":"multi","options":["晚上饿","零食","饮料 / 奶茶","应酬","吃得太快","都还好"]},
 {"id":"doctor","label":"医生对饮食或用药有什么交代","type":"text"}]
```
- 老大说了目标体重和速度，就按 AGENTS 第 8 节记 `pref.viz.weight`（数字只用老大亲口说的）。
- 用药只记「在用什么、医生交代了什么」，不记剂量建议，也不评价剂量。

## 6. 压力 → `stress.profile`
```json
[{"id":"level","label":"最近压力","type":"scale","min":1,"max":5,"min_label":"很轻","max_label":"很大"},
 {"id":"source","label":"主要来自","type":"multi","options":["工作","人际","家庭","健康","钱","说不清"]},
 {"id":"cope","label":"压力大时通常会","type":"multi","options":["吃东西","刷手机","运动","熬夜","喝酒","找人聊"]},
 {"id":"mood","label":"最近两周情绪","type":"options","options":["还可以","时好时坏","大多时候很低落"]}]
```
- 红旗选项：大多时候很低落。选了就当场按 clinical-safety 的「情绪」处理，处理完再继续。

## 7. 偏好 → `pref.remind`、`pref.tone`、`pref.media`
```json
[{"id":"max","label":"每天最多被提醒几次","type":"options","options":["1 次","2 次","3 次"]},
 {"id":"quiet","label":"哪些时段别打扰","type":"multi","options":["上午工作时","午休","开会","晚饭","都可以"]},
 {"id":"tone","label":"希望我怎么说","type":"options","options":["直接给结论","多讲原理","严格督促"]},
 {"id":"media","label":"放松素材喜欢","type":"multi","options":["呼吸引导","身体扫描","白噪音 / 自然声","拉伸视频","轻音乐"]}]
```
- 三条分开记，例：`pref.remind` `{"rule":"每天最多提醒 2 次，上午工作时不打扰","max":2}`。
- 老大选的提醒次数比 3 少，就按他的来；比 3 多，仍然最多 3 次。

## 问完以后
- `profile.intake` 记 `{"done":["goals","schedule","sleep","sport","diet","stress","prefs"],"finished":"<日期>"}`。
- 发 list 卡「我对你的理解」（5–7 条，每条一句），问哪里不对，再按 phealth-role 第 4 步提项目。
