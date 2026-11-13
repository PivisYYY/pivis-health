# 减重与饮食的专业依据

回答减重、饮食、体重波动、目标怎么算、用药期间怎么吃之前先读这一页。执行流程（评估、目标、照片 → meal-log、复盘、路线）在 `../SKILL.md`；份量怎么估在 `food-portions-cn.md`；反馈怎么说在 `meal-feedback.md`；伤病 / 训练 / 睡眠怎么吃在 `recovery-nutrition.md`；补剂在 `supplements.md`。
体重、热量、蛋白质克数等数字只来自 `./pivis-health`（facts、compare、viz、nutrition-targets、meal-log、nutrition-day、nutrition-week）；这里只放原理和判据。不评价任何药物剂量。

证据等级：**A** 指南或多 RCT / 系统综述一致；**B** 单项 RCT 或较强观察研究；**C** 机制或经验。C 级要直说证据弱。

---

## 1. 体重为什么变（先懂这个）

| 要点 | 说明 | 等级 |
|---|---|---|
| 长期看是能量差 | 吃进去少于消耗，体重才会持续下降；没有哪种「神奇食物」或时间点能绕开 [1] | A |
| 单天是水 | 一天上下 0.5–1.5 kg 主要是水、盐、糖原和肠道内容物：咸的一顿、多吃主食、便秘、喝酒、月经周期、练完腿（肌肉水肿）、刚开始吃肌酸都会让第二天变重 | A |
| 所以看 7 天平均 | 每天称、看 7 天均值的周变化；单天涨不代表胖了 | B |
| 速度 | 一般建议每周减体重的 0.5–1%；初期（尤其开始用药或少吃主食时）前 1–2 周掉得快，多是水 [1] | A |
| 消耗会跟着降 | 「每天少 500 千卡 = 每周减 0.5 kg」短期大致对，长期会高估：体重下降后消耗也下降 [2] | A |
| 平台期 | 原来的吃法差距变小；执行到位时连续 2–3 周 7 天均值不动才算平台 | A |

## 2. 目标怎么算（`nutrition-targets` 的依据，跟 Psir 解释时用）

| 项 | 做法 | 依据 | 等级 |
|---|---|---|---|
| 基础代谢（BMR） | Mifflin-St Jeor 公式：男 = 10 × 体重 kg + 6.25 × 身高 cm − 5 × 年龄 + 5；女 = 同式 − 161 | 健康成人里最准的预测公式，约七到八成人误差在 ±10% 以内 [3][4] | A–B |
| 每日总消耗（TDEE） | BMR × 活动系数（久坐约 1.2，到很活跃约 1.7–1.9）；服务器按步数 / WHOOP 定 | 活动系数本身误差不小，所以给范围 | C |
| 减脂热量 | 有体重目标时在 TDEE 上减一个缺口（大约 10–25%），给区间 | 缺口太大掉肌肉、难坚持 [1][5] | A–B |
| 蛋白质 | 减脂 + 有力量训练：每天 1.6–2.2 g / kg；没有训练或维持：1.2–1.6 g / kg | 热量缺口下更高蛋白保住瘦体重 [5][6][7][8] | A |
| 脂肪下限 | 不低于总热量的约 20%（中国居民推荐脂肪供能比 20–30%）| 太低影响激素和脂溶性维生素 [9] | B–C |
| 膳食纤维 | 每天 25–30 g | [9][10] | A |
| 喝水 | 成年男性每天约 1700 ml、女性约 1500 ml 的饮水，运动和天热另加 | 中国居民膳食指南 2022 [11] | B |
- 公式只是起点：**按执行到位（每周记录 ≥ 4 天）2–3 周的 7 天体重均值校准**。没按路线走就把份量减一处（例如晚饭主食 −1 捧），不去改公式。
- 为什么都是范围：公式误差约 ±10%、活动系数误差、食物估算误差（第 7 节）叠在一起，单一数字是假精确。

## 3. 吃什么最重要（按优先级）

1. **蛋白质够**：按第 2 节的范围，分到每餐，**每餐约 0.3–0.4 g / kg（多数人 1–2 掌）**；蛋白质最顶饱、最保肌肉 [5][12]。
2. **蔬菜和膳食纤维**：每顿 1–2 拳蔬菜（约半盘），主食换一部分全谷杂豆 [10]。
3. **少吃超加工食品**：同样随便吃的情况下，超加工饮食每天多吃约 500 千卡 [13]。零食、甜饮、加工肉、外卖重油重酱是最常见的超标来源。
4. **主食控量，不必戒**：低碳和低脂长期减重效果差不多，选自己能坚持的 [1]（A）。
5. **饮料**：含糖饮料、奶茶、果汁算一顿加餐；酒精每克约 7 千卡，还会让人多吃、压低恢复（recovery-nutrition.md）。
6. **水**：口渴、尿色深就是不够。

**中国居民平衡膳食宝塔（2022）每天的量**（解释「一天大概吃成什么样」用）[11]：
| 类别 | 每天 |
|---|---|
| 谷类 | 200–300 g（其中全谷物和杂豆 50–150 g），薯类 50–100 g |
| 蔬菜 / 水果 | 蔬菜 300–500 g（深色占一半）/ 水果 200–350 g |
| 动物性食物 | 120–200 g（每周至少 2 次水产品，每天一个鸡蛋） |
| 奶 / 大豆和坚果 | 奶及奶制品 300–500 g / 大豆和坚果 25–35 g |
| 盐 / 油 | 盐 < 5 g / 烹调油 25–30 g |
| 添加糖 / 酒 | 添加糖 < 50 g，最好 < 25 g / 成年人如饮酒，酒精 ≤ 15 g |
（这是指南的参考量，不用来给某一顿估克数；照片只估手掌份量。）

## 4. 怎么吃（时间和方式）

| 问题 | 结论 | 等级 |
|---|---|---|
| 轻断食 / 16:8 比普通少吃更好吗 | **不更好**。同样的总热量，限时进食和普通少吃一年后效果没有差别 [14]；适合的人可以用它来少吃，但不是必须 | A |
| 晚饭吃晚了会胖吗 | 总量决定体重；但晚饭离睡觉太近会影响睡眠（大餐离上床 ≥ 3 小时，cbti），且晚上更容易吃多 | B |
| 一定要吃早饭吗 | 不一定；看自己哪种吃法总量更好控制 | A |
| 吃得慢有用吗 | 有：慢吃、每口放下筷子，更早有饱感，尤其用 GLP-1 类药物时 | B |
| 每顿的顺序 | 先蔬菜和蛋白质，再主食：饱得更早、餐后血糖更平稳 | B |
| 睡得少会多吃吗 | 会：睡眠被压缩时饥饿激素升高、平均每天多吃约 385 千卡 [15][16] | A |

## 5. 运动和减重

- 单靠运动减重效果有限，**主要作用是保住肌肉、防反弹、改善代谢和心肺** [1][17]。
- 减重期间每周 **≥ 2 次力量训练**（training-coach），配合足够蛋白质，减掉的更多是脂肪 [6][7]。
- 长期维持体重的人共同的做法：规律称重、每天活动（步数）、吃法稳定 [17]。

## 6. GLP-1 / GIP 类药物期间（司美格鲁肽、替尔泊肽等）

- 这类药通过降低食欲、延缓胃排空减重，临床试验里一年多下来平均减重约 15–20%（替尔泊肽高剂量组约 20%）[18][19]。**剂量、加减量、停药都只听医生的。**
- 风险点是**减掉的里面肌肉占比不低**：蛋白质优先（每餐先吃蛋白质，按 `nutrition-targets` 的上限）、力量训练每周 ≥ 2 次是用药期最重要的两件事（A-）。
- 吃得少时最容易缺：蛋白质、水、膳食纤维（便秘）。没胃口也先保证喝水和蛋白质（豆浆、牛奶、蛋、酸奶）。
- 常见反应：恶心（少量多餐、慢吃、少油、别吃到撑）、便秘（水 + 蔬菜 + 活动）、反酸（睡前 3 小时不吃）。持续严重的告诉医生。
- 红旗（马上就医）：持续剧烈腹痛（可能放射到后背）、吐到喝不进水、尿少头晕、眼睛皮肤发黄、过敏肿胀、呼吸困难 —— 见 clinical-safety。
- 停药后体重容易回升：生活方式（蛋白质、力量、称重、步数）要在用药期间就养成。

## 7. 估算有多准（为什么只给范围、只看趋势）

| 要点 | 说明 | 等级 |
|---|---|---|
| 自我报告普遍少报 | 自认「吃得很少却不瘦」的人，实际摄入平均被少报近一半 [20] | B |
| 照片 / 目测估份量 | 单顿误差常有 20–40%：油、酱汁、被挡住的部分、碗的深度最难判断（C） | C |
| 手掌法 | 手掌和家用量具都只适合估大概，单顿误差大 [21]；好处是随身、和体型成比例、不用称 | B–C |
| 所以 | P-Health 只估手掌份量，服务器换算成范围；看多天的平均和体重趋势，不纠结一顿；永远不说单一的精确千卡数 | C |

## 8. 常见问题决策表

| Psir 说 | 结论 | 为什么 | 等级 |
|---|---|---|---|
| 「今天突然重了 1 公斤」 | 正常波动，看 7 天平均；想一下昨天是不是咸、吃主食多、喝酒、便秘、练了腿 | 第 1 节 | A |
| 「两周没掉了」 | 先查执行（称重天数、`nutrition-week` 的记录天数和蛋白质达标天数、步数、力量），再看是不是真平台 | 第 1、2 节 | A |
| 「我到底该吃多少」 | 跑 `nutrition-targets`，按手掌份量说每顿，热量和蛋白质只给范围 | 第 2 节 | A–B |
| 「晚上饿得受不了」 | 白天蛋白质和蔬菜够不够；晚饭加 1 掌蛋白质；需要就计划一个小加餐（无糖酸奶、蛋、豆腐干），不硬扛到暴食 | 第 3 节 | B |
| 「吃多了一顿，明天要少吃吗」 | 不补偿，下一顿正常吃 | 补偿性节食容易引出下一次暴食 | B |
| 「要不要吃代餐 / 减肥茶 / 酵素」 | 代餐偶尔替代一顿可以，不顿顿替代；减肥茶多是泻药利尿，不用；酵素没有减重证据 | | A |
| 「能喝酒吗」 | 减脂期最好不喝；喝就 ≤ 1 份（酒精 ≤ 15 g）、和饭一起、睡前 3–4 小时停 | [11]，recovery-nutrition.md | A |
| 「蛋白粉要喝吗」 | 饮食能吃够就不必；吃不够（没胃口、用药期、外卖为主）是方便的补充 | supplements.md | A |
| 「要不要自己算热量」 | 不必。P-Health 估手掌份量，服务器换算成范围；照片估热量误差大，看趋势 | 第 7 节 | C |
| 「外卖怎么点」 | 先挑做法（蒸煮炖拌 > 炒 > 红烧 / 干锅 / 炸），饭减半，备注少油少酱 | food-portions-cn.md | C |

## 9. 什么时候建议就医或转营养科

- 每周减重持续超过 1 kg（尤其用药期）、头晕乏力、心慌；第 6 节的红旗。
- 暴食后催吐、怕吃东西、体重已经偏低还在节食 → clinical-safety「体重和进食」。
- 肾病、糖尿病在用胰岛素或促泌剂、痛风反复、怀孕哺乳、进食障碍史 → 营养科门诊（这些人的目标要医生和营养师定）。

## 文献
1. Jensen MD, et al. 2013 AHA/ACC/TOS guideline for the management of overweight and obesity in adults. *Circulation*. 2014;129(25 Suppl 2):S102–S138.
2. Hall KD, et al. Quantification of the effect of energy imbalance on bodyweight. *Lancet*. 2011;378:826–837.
3. Mifflin MD, St Jeor ST, Hill LA, Scott BJ, Daugherty SA, Koh YO. A new predictive equation for resting energy expenditure in healthy individuals. *Am J Clin Nutr*. 1990;51:241–247.
4. Frankenfield D, Roth-Yousey L, Compher C. Comparison of predictive equations for resting metabolic rate in healthy nonobese and obese adults: a systematic review. *J Am Diet Assoc*. 2005;105:775–789.
5. Helms ER, Aragon AA, Fitschen PJ. Evidence-based recommendations for natural bodybuilding contest preparation: nutrition and supplementation. *J Int Soc Sports Nutr*. 2014;11:20.
6. Jäger R, et al. International Society of Sports Nutrition position stand: protein and exercise. *J Int Soc Sports Nutr*. 2017;14:20.
7. Morton RW, et al. A systematic review, meta-analysis and meta-regression of the effect of protein supplementation on resistance training-induced gains in muscle mass and strength in healthy adults. *Br J Sports Med*. 2018;52:376–384.
8. Longland TM, et al. Higher compared with lower dietary protein during an energy deficit combined with intense exercise promotes greater lean mass gain and fat mass loss: a randomized trial. *Am J Clin Nutr*. 2016;103:738–746.
9. 中国营养学会. 中国居民膳食营养素参考摄入量（2023 版）. 人民卫生出版社; 2023.
10. Reynolds A, et al. Carbohydrate quality and human health: a series of systematic reviews and meta-analyses. *Lancet*. 2019;393:434–445.
11. 中国营养学会. 中国居民膳食指南（2022）. 人民卫生出版社; 2022.
12. Leidy HJ, et al. The role of protein in weight loss and maintenance. *Am J Clin Nutr*. 2015;101:1320S–1329S.
13. Hall KD, et al. Ultra-processed diets cause excess calorie intake and weight gain: an inpatient randomized controlled trial of ad libitum food intake. *Cell Metab*. 2019;30:67–77.
14. Liu D, et al. Calorie restriction with or without time-restricted eating in weight loss. *N Engl J Med*. 2022;386:1495–1504.
15. Spiegel K, Tasali E, Penev P, Van Cauter E. Brief communication: sleep curtailment in healthy young men is associated with decreased leptin levels, elevated ghrelin levels, and increased hunger and appetite. *Ann Intern Med*. 2004;141:846–850.
16. Al Khatib HK, et al. The effects of partial sleep deprivation on energy balance: a systematic review and meta-analysis. *Eur J Clin Nutr*. 2017;71:614–624.
17. Wing RR, Phelan S. Long-term weight loss maintenance. *Am J Clin Nutr*. 2005;82(1 Suppl):222S–225S.
18. Wilding JPH, et al. Once-weekly semaglutide in adults with overweight or obesity. *N Engl J Med*. 2021;384:989–1002.
19. Jastreboff AM, et al. Tirzepatide once weekly for the treatment of obesity. *N Engl J Med*. 2022;387:205–216.
20. Lichtman SW, et al. Discrepancy between self-reported and actual caloric intake and exercise in obese subjects. *N Engl J Med*. 1992;327:1893–1898.
21. Gibson AA, et al. Accuracy of hands v. household measures as portion size estimation aids. *J Nutr Sci*. 2016;5:e29.
