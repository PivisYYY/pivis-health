# 训练模板

## 1. 热身（开始前 8–10 分钟，kind=follow 的 steps）
| 项目 | steps |
|---|---|
| 网球 | 慢跑 + 开合跳 2 分钟 → 肩绕环 + 手臂画圈 2 分钟 → 弓步转体 2 分钟 → 侧滑步 + 交叉步 1 分钟 → 挥拍空练 2 分钟 |
| 力量 | 快走或单车 3 分钟 → 猫牛式 + 世界上最伟大的拉伸 2 分钟 → 徒手深蹲 10 次 + 臀桥 10 次 2 分钟 → 第一个动作做 2 组轻重量 |
| 跑步 | 快走 3 分钟 → 高抬腿 + 后踢腿 2 分钟 → 摆腿（前后、左右）2 分钟 → 慢跑 3 分钟后再提速 |
| 灵活性 | 不用单独热身，从最轻的动作开始 |

```json
[{"title":"慢跑 + 开合跳","duration_min":2},{"title":"肩绕环 + 手臂画圈","duration_min":2},
 {"title":"弓步转体","duration_min":2},{"title":"侧滑步 + 交叉步","duration_min":1},{"title":"挥拍空练","duration_min":2}]
```

## 2. 放松（结束后 5–10 分钟）
| 项目 | steps |
|---|---|
| 网球 | 慢走 2 分钟 → 肩后侧拉伸（每边 30 秒）→ 前臂伸肌、屈肌拉伸（每边 30 秒）→ 股四头肌、小腿拉伸（每边 30 秒） |
| 力量 | 慢走 2 分钟 → 练过的肌群各拉 30 秒 → 4-7-8 呼吸 4 轮 |
| 跑步 | 慢走 3 分钟 → 小腿、腘绳肌、髋屈肌拉伸（每边 30 秒） |
有合适的拉伸视频，就按 relaxation-media 选好之后放进 steps 的 media。

## 3. 每周结构（按 `sport.preference.freq` 选）
| 每周能练 | 结构 |
|---|---|
| 1–2 次 | 全身力量 1 次 + 网球或跑步 1 次；每天 8 分钟灵活性（可选） |
| 3–4 次 | 全身力量 2 次（A、B 交替）+ 网球或跑步 1–2 次 |
| 5 次以上 | 力量 3 次 + 网球或跑步 2 次，周中安排一天只做灵活性 |
- 力量和高强度网球之间至少隔 24 小时；同一天都要做，就先打球后力量，力量减量。
- 在用 GLP-1 类药物减重：力量每周至少 2 次。

## 4. 力量课（全身 A / B）
| 课 | 动作（组 × 次，最后一组还能做 2 个左右） |
|---|---|
| A | 深蹲或高脚杯深蹲 3×8–12 · 卧推或俯卧撑 3×8–12 · 划船 3×8–12 · 平板支撑 3×30–45 秒 |
| B | 罗马尼亚硬拉 3×8–12 · 站姿推举 3×8–12 · 高位下拉或弹力带下拉 3×8–12 · 臀桥 3×12–15 · 肩外旋（弹力带）2×15 |
- 在家没有器械：深蹲换徒手或负重背包，卧推换俯卧撑，划船换弹力带或单手哑铃。
- 加量：每组都做到次数上限，且最后一组还能做 ≥ 2 个，下次上肢 +2.5 kg、下肢 +5 kg。
- 新手前两周只练动作，RPE ≤ 6。

## 5. 跑步
| 类型 | 怎么跑 |
|---|---|
| 轻松跑 | 能说完整句子的速度，20–40 分钟。每周大部分时间用这种 |
| 快跑（每周最多 1 次） | 热身后 4–6 × 2 分钟稍快（RPE 7），中间走或慢跑 2 分钟 |
| 长跑 | 每周最长的一次不超过当周总量的 30% |
- 每周总时长最多 +10%。连续 3 周加量后，第 4 周回到第 1 周的量。

## 6. 网球专项预防（每周 2 次，每次 8 分钟）
弹力带肩外旋 2×15 → 前臂伸肌离心（哑铃慢放）2×15 → 肩胛后缩 2×15 → 侧桥每边 30 秒。

## 7. 项目 JSON（示例：周一、周四力量，周六网球；时间按老大定的）
```json
{"id":"strength","name":"力量 + 网球","board":"sport","start":"2026-11-09","days":28,
 "goal":"每周 2 次全身力量，配合网球，4 周后加量",
 "rules":["力量做到次数上限、还能再做 2 个才加重","恢复红区当天只做灵活性","哪里尖锐地疼就停这个动作"],
 "reviews":[{"date":"2026-11-15","title":"第 1 周复盘"},{"date":"2026-11-22","title":"第 2 周复盘"},
            {"date":"2026-11-29","title":"第 3 周复盘"},{"date":"2026-12-06","title":"第 4 周复盘：决定加量还是减量周"}],
 "daily":[
  {"key":"str_a","weekdays":[1],"when":"19:00","title":"力量 A · 40 分钟","kind":"follow","duration_min":40,
   "steps":[{"title":"热身：单车 + 动态拉伸","duration_min":5},
            {"title":"高脚杯深蹲","note":"3 组 × 8–12","duration_min":8},
            {"title":"俯卧撑或卧推","note":"3 组 × 8–12","duration_min":8},
            {"title":"单手哑铃划船","note":"3 组 × 8–12","duration_min":8},
            {"title":"平板支撑","note":"3 组 × 30–45 秒","duration_min":5},
            {"title":"放松拉伸","duration_min":6}]},
  {"key":"str_b","weekdays":[4],"when":"19:00","title":"力量 B · 40 分钟","kind":"follow","duration_min":40,
   "steps":[{"title":"热身：单车 + 动态拉伸","duration_min":5},
            {"title":"罗马尼亚硬拉","note":"3 组 × 8–12","duration_min":8},
            {"title":"站姿推举","note":"3 组 × 8–12","duration_min":8},
            {"title":"弹力带下拉","note":"3 组 × 8–12","duration_min":8},
            {"title":"臀桥 + 肩外旋","note":"各 2–3 组","duration_min":5},
            {"title":"放松拉伸","duration_min":6}]},
  {"key":"str_log","weekdays":[1,4],"title":"练完记一下","kind":"fields","submit_label":"记好了",
   "inputs":[{"id":"rpe","label":"整体多累","type":"scale","min":1,"max":10,"min_label":"很轻松","max_label":"极限","submit":"agent"},
             {"id":"rir","label":"最后一组还能做几个","type":"options","options":["0","1–2","3–4","5+"],"submit":"agent"},
             {"id":"done","label":"完成度","type":"options","options":["全做完","做了大半","一半以下"],"submit":"agent"},
             {"id":"body","label":"哪里不舒服","type":"multi","options":["都还好","肩","肘","腰","膝"],"submit":"agent"}]},
  {"key":"tennis_warm","weekdays":[6],"when":"16:50","title":"打球前热身","kind":"follow","duration_min":9,
   "steps":[{"title":"慢跑 + 开合跳","duration_min":2},{"title":"肩绕环 + 手臂画圈","duration_min":2},
            {"title":"弓步转体","duration_min":2},{"title":"侧滑步 + 交叉步","duration_min":1},{"title":"挥拍空练","duration_min":2}]},
  {"key":"tennis_log","weekdays":[6],"title":"打完记一下","kind":"fields",
   "inputs":[{"id":"rpe","label":"整体多累","type":"scale","min":1,"max":10,"min_label":"很轻松","max_label":"极限","submit":"agent"},
             {"id":"body","label":"哪里不舒服","type":"multi","options":["都还好","肩","肘","腰","膝"],"submit":"agent"}]},
  {"key":"review","weekdays":[7],"title":"本周训练复盘","kind":"proposal","until":"22:00",
   "inputs":[{"id":"go","label":"花 3 分钟看这周练得怎么样","type":"options","options":["现在看","明天再看"],"submit":"chat"}]}]}
```

## 8. 每天 8 分钟灵活性（可以单独做成项目，也可以并进上面的项目）
```json
{"key":"mobility","when":"21:00","title":"8 分钟灵活性","kind":"follow","duration_min":8,
 "steps":[{"title":"猫牛式","duration_min":1},{"title":"世界上最伟大的拉伸","note":"每边 1 分钟","duration_min":2},
          {"title":"90/90 髋转换","duration_min":2},{"title":"胸椎旋转","note":"每边 1 分钟","duration_min":2},
          {"title":"深蹲停留","duration_min":1}]}
```
如果老大同时在做 CBT-I，晚上已经有睡前流程，灵活性就不要单独再占一个提醒时间点：并进睡前流程的 steps，或者不写 when。
