# 训练怎么编排（专业依据）

排训练计划、回答「一天练全身还是分部位」「一周练几次」「加多少」、挑或审跟练视频之前先读这一页。每天能练多重、加量减量的规则在 `../SKILL.md`；伤在身时先读 `knee-meniscus.md`；网球专项动作在 `tennis.md`。

证据等级：A 指南或多 RCT 一致，B 单项研究，C 经验或机制。

---

## 1. 一周的基本量（健康成年人）

| 内容 | 量 | 依据 |
|---|---|---|
| 有氧 | 每周 150–300 分钟中等强度（或 75–150 分钟高强度）；网球算进来 | WHO 2020 [1]、ACSM [2]（A） |
| 力量 | **每周 ≥ 2 次，覆盖全身主要肌群** | [1][2]（A） |
| 灵活性 / 平衡 | 每周 ≥ 2–3 次；有膝伤或 > 40 岁更要有平衡 | [2]（A-） |
| 防伤专项 | 力量训练能把运动伤害减少约三分之一，拉伸单独做效果不明显 | [5]（A） |

## 2. 全身练还是分部位练

**结论：每周练力量 2–3 次的人，每次都练全身，不要一天只练一个部位。**

- 每个肌群每周练 **2 次以上**，比 1 次的力量和肌肉增长更好 [3]（A）。一周 2–3 次课，只有「每次全身」才能让每个肌群练到 2 次。
- 分化（上肢日 / 下肢日，或胸背腿分开）适合每周练 **4 次以上**、追求肌肉量的人；对运动员的体能和健康目标没有额外好处，还会让漏一次课就整周缺一个部位。
- 打网球的人尤其要全身：网球需要的是全身协调发力（腿 → 髋 → 躯干 → 肩 → 手），不是单个部位的围度。

**一次全身课的结构**（40–60 分钟）：
热身 8–10 分钟 → 下肢主项（蹲类 / 髋铰链类，各 1 个）→ 上肢推 + 拉（各 1 个）→ 单侧 / 稳定（分腿蹲、单腿硬拉、侧走）→ 核心抗旋（Pallof、死虫）→ 专项（网球的肩袖、前臂离心）→ 放松 5 分钟。
每个动作 2–4 组。没时间就砍组数，不砍部位。

## 3. 和网球、康复放在一周里

| 每周打球 | 力量课 | 排法 |
|---|---|---|
| 1–2 次 | 2–3 次全身 | 力量课和球不放同一天；**打球前一天不练下肢大重量**；打完第二天可练上肢 + 核心，下肢轻 |
| 3 次以上 | 2 次全身 | 力量放在没球的日子；赛季期每次力量课缩短到 30–40 分钟，保量不加量 |
| 康复阶段（膝伤等） | 康复动作 3–4 次（每次 15–25 分钟）+ 1–2 次全身 | 康复动作可以和打球同一天（打球前作激活、或隔几小时）；下肢大重量按 knee-meniscus.md 的阶段来 |

- 两次全身力量课之间隔 ≥ 48 小时（同一肌群恢复）。
- 恢复 / 睡眠差的日子按 SKILL.md 第 1 步降档，不是取消一周的结构。

## 4. 强度、次数和加量

| 目标 | 组 × 次 | 难度 | 依据 |
|---|---|---|---|
| 健康 / 刚开始 / 康复 | 2–3 × 10–15 | 最后还能做 2–3 次（RIR 2–3，RPE 7–8） | [2][4] |
| 力量 | 3–5 × 4–6 | RIR 1–3 | [4] |
| 肌肉耐力 / 网球专项小肌群（肩袖、前臂） | 2–3 × 15–20 | RIR 2–3，慢放 | [6] |

- **双重递进**：先在同一重量上把次数做到范围上限（比如每组 12 次），再加重量、次数回到下限。具体加多少见 SKILL.md 第 5 步。
- 新动作、伤后回来、停练 ≥ 1 周：先从上次的 70% 或「感觉很轻」开始。
- 用 RIR（还剩几次）而不是「练到力竭」：力竭对健康目标没有额外好处，受伤风险更高。

## 5. 审跟练视频：内容要对得上处方

每次把视频排进计划之前、或 Psir 发来新视频时，**逐个动作核对**（follow 出片后用 `follow session show <ssid>` 看动作列表；原片用 `follow analyze` 的动作候选和预览图）：
1. 这个动作练的是哪个肌群？和这节课需要的（第 2 节结构、knee-meniscus.md 第 2 节、tennis.md）对得上吗？缺了哪个关键肌群？
2. 有没有伤病禁忌动作（knee-meniscus.md 第 3 节的红灯）？
3. 强度合不合适：冲击、幅度、速度是不是这个阶段该做的？
4. 画面是不是一个人完整演示（不是四宫格、不是只拍局部）？
对不上的：剪掉、换片，或告诉 Psir「这个视频缺 X / 有 Y 不适合，建议找 Z 这样的视频」。**在对话里列出核对结果**（每个动作一行：练哪 · 合不合适），不要只说「已经看过了」。

## 6. 已有习惯和项目：改，不新建

- 排计划前先 `./pivis-health project-list`。目的相同（同一个部位的康复、同一项运动的训练）的项目已经在了，**就在那个项目上改**（同一个 `id` 再 `project-set`：换视频、改时间、加动作），不要再建一个新项目。
- 真的要拆成两个（比如康复和网球力量本来就是两件事），先在 plan 卡里说清两个各管什么、为什么分开，Psir 点头再建。
- Psir 说「在原来的基础上改」：用原来的 id；误建的新项目用 `project-set --json '{"id":"<误建的 id>","status":"done"}'` 结束掉，附 receipt 说明。

## 文献
1. Bull FC, et al. World Health Organization 2020 guidelines on physical activity and sedentary behaviour. *Br J Sports Med*. 2020;54:1451–1462.
2. Garber CE, et al. American College of Sports Medicine position stand. Quantity and quality of exercise for developing and maintaining cardiorespiratory, musculoskeletal, and neuromotor fitness in apparently healthy adults. *Med Sci Sports Exerc*. 2011;43:1334–1359.
3. Schoenfeld BJ, Ogborn D, Krieger JW. Effects of resistance training frequency on measures of muscle hypertrophy: a systematic review and meta-analysis. *Sports Med*. 2016;46:1689–1697.
4. American College of Sports Medicine. Position stand: progression models in resistance training for healthy adults. *Med Sci Sports Exerc*. 2009;41:687–708.
5. Lauersen JB, Bertelsen DM, Andersen LB. The effectiveness of exercise interventions to prevent sports injuries: a systematic review and meta-analysis of randomised controlled trials. *Br J Sports Med*. 2014;48:871–877.
6. Ellenbecker TS, Cools A. Rehabilitation of shoulder impingement syndrome and rotator cuff injuries: an evidence-based review. *Br J Sports Med*. 2010;44:319–327.
7. Helms ER, et al. Application of the repetitions in reserve-based rating of perceived exertion scale for resistance training. *Strength Cond J*. 2016;38(4):42–49.
