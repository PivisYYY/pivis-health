---
name: relaxation-media
version: 1.0.0
description: "给 Psir 找放松和练习素材（呼吸引导、身体扫描、拉伸视频、正念，以及白噪音或自然声）：练习类只用 follow 出的视频——先查已出的片，不够再联网找公开、免登录、中文的候选，给 2–3 个让 Psir 先看，他同意了再用 follow 出片，出好片用 plan 卡确认后排进待办或项目，用完打分，分低就换；白噪音、雨声只在对话里发音频卡，不当练习。Psir 要放松材料、说现在的素材不好用、要换一个，或要给睡前流程或减压待办配视频时使用。"
---

# 放松素材：先选再定

## 什么时候用
- Psir 说「找点放松的」「睡前听什么」「这个不好用，换一个」「有没有拉伸视频」。
- 你要给 cbti 的睡前流程、stress-recovery 的减压待办、training-coach 的拉伸配视频。
- 早上那次【每日推荐】（顺带做每日整理）时发现昨天用了某个视频但还没打分。

## 先分清两类
- **练习**（呼吸引导、身体扫描、拉伸、正念、入眠练习）：只用 follow 出的视频，卡上是「这个项目 + 一个视频」（AGENTS 红线 9）。B 站、小红书链接不能直接放进待办或项目。
- **背景声**（白噪音、雨声、自然声、轻音乐）：不是练习，只在对话里发音频卡，不做成待办卡。

## 怎么做
1. **弄清需求**（已知的不再问）：先 `./pivis-health context-list --scope pref.media` 和 `--scope learn.media`。缺什么，就用 question 卡问什么，一次最多问 2 题：
   - 类型：呼吸引导 / 身体扫描 / 白噪音或自然声 / 拉伸视频 / 轻音乐
   - 用在什么时候：睡前 / 午间 / 压力大时 / 运动后
   时长按 `references/search.md` 第 1 节的默认值，Psir 另有要求就听他的。
2. **先查已有的**：
   - 练习类：`./pivis-health follow session list`（已出的练习视频，看 title、duration_min、video）。挑类型和时长对得上的，去掉 `learn.media.avoid` 里的。
   - 背景声：`./pivis-health media-library`（`plannable:false` 的只能在对话里发）。
   - 够 2 个就跳到第 4 步。
3. **联网搜**（用 tool-web 的搜索和打开网页）：
   - 搜索词和筛选标准见 `references/search.md`。只用 B 站、小红书，或网页直接能播、不用登录也不要会员的国内平台。
   - 每个候选都要打开页面核对：标题、UP 主或博主、时长、播放量，不要登录、不是会员或充电专属、不是多 P 合集里的后几集。核对不了的不用。
   - 练习类要能交给 follow 出片：一个人出镜、全身入镜、镜头不乱切（见 follow-video「常见问题」）。
   - B 站链接写成干净的 `https://www.bilibili.com/video/BVxxxxxxxxxx`（去掉 `?` 后面的参数）。
   - 不用 YouTube、内网地址、本地路径、网盘链接。
4. **给 2–3 个选项**：一句话说明为什么挑这几个，然后：
   - 已出的练习视频：发 media 卡（`"kind":"video"`，url 用 video 地址）。
   - 网上找到的：先给 Psir 看。B 站的发 media 卡（`"kind":"embed"`），title 写「<名字> · <时长> · <UP 主>」；小红书的写名字、时长、博主。**这一步只是看，不排进计划。**
   - 素材库里的背景声（url 以 `/media/` 开头的音频）：直接发 media 卡（`"kind":"audio"`），App 会补全地址。
   - 最后发一张 question 卡让 Psir 选（模板见下）。
5. **Psir 选了以后**：
   - 选的是网上找到的练习视频：用 follow 出片（`./pivis-health follow make "<链接>" …`，做法见 follow-video），验收过了再往下走。出片做不了（没开放、视频不适合），如实说，换下一个候选。
   - 选的是背景声：不排卡。网上找到的用 `media-add` 收进素材库；要用时在对话里发音频卡（锁屏也能接着放）。
   - 练习视频出好了，发 plan 卡：什么时间、做多久、连续几天、在流程里排第几项、怎么打分。actions：就这样 / 改一下 / 不要。
6. **Psir 点「就这样」后写入**（只放 follow 出的这一个视频）：
   - 已有项目里的流程（比如 cbti 的 winddown）：`project-set` 同一个 id，只换那一项的视频。
   - 只用一次：`todo-add` 一张练习视频卡（模板见下）。
   - 连续用几天、又没有项目：建一个小项目（days 7），写法照 `../cbti/references/templates.md` 第 1 节。
   - `context-record --scope pref.media`（Psir 喜欢的类型、时长、来源），附 receipt 卡。
7. **用完打分**：
   - 在 cbti 项目里：日记里已经有「昨晚的睡前放松」这一题，不另外加卡。
   - 不在项目里：第二天早上那次【每日推荐】（顺带做每日整理）时，如果昨天的练习视频卡是 done、还没打分，就 `todo-add` 一张打分卡（不写 when）。
8. **按分数换**：
   | 打分 | 动作 |
   |---|---|
   | 「没用，换一个」或「没用」 | 当天就回到第 2 步，去掉这个视频，再给 2–3 个 |
   | 连续 2 次「一般」 | 问一句是类型不对还是这一个不对（question 卡），再换 |
   | 累计 3 次「有用」 | 保留，记进 `learn.media.works` |

## 规则与红线
1. 只给 2–3 个选项，让 Psir 选。网上找到的，Psir 点头之前不出片；出好片以后也要等 plan 卡确认再写进计划。
2. 素材只做放松，不当治疗。不选标题写着「治愈失眠」「根治焦虑」的，也不选卖课、卖产品的。
3. 拉伸在床外做，上床前做完。躺到床上只听声音：练习视频和对话里的音频卡锁屏后都能接着放，Psir 可以锁屏听。
4. 拉伸动作要温和：不倒立，不做高强度动作，不做需要器械的。Psir 有伤的部位（`sport.preference.injury`）不做对应动作。
5. 呼吸练习出现头晕、胸闷就停，恢复自然呼吸。反复出现就按 clinical-safety 处理。
6. Psir 说「算了」：按 AGENTS 红线 5。
7. 白噪音、雨声不是练习：只在对话里发音频卡，不做成练习卡。
8. 找不到合格的候选：按 follow-video 的「还没有视频」请 Psir 发一个他喜欢的博主视频，不写文字步骤的卡。

## 模板
选项 question 卡：
```json
{"type":"question","title":"选一个今晚试","fields":[{"id":"pick","label":"用哪个","type":"options","options":["睡前拉伸 · 10 分钟 · 已做好的视频","睡前身体扫描 · 15 分钟 · B 站","温和拉伸 · 8 分钟 · 小红书","都不要，换一批"],"allow_text":true}],"submit_label":"就它"}
```
单次练习视频卡（url 是 follow 出片给的地址）：
```json
{"board":"sleep","when":"23:30","title":"睡前身体扫描","kind":"follow","note":"躺下只听声音，可以锁屏",
 "media":{"kind":"video","title":"身体扫描 · 15 分钟","url":"/media/follow/<ssid>/out.mp4","duration_min":15}}
```
打分卡：
```json
{"board":"sleep","title":"昨晚的放松有用吗","kind":"options",
 "inputs":[{"id":"rate","label":"","type":"options","options":["有用","一般","没用，换一个"],"submit":"agent"}]}
```
收到打分：`todo-update --id <id> --json '{"status":"done","summary":"身体扫描：有用"}'`，再更新 `learn.media`。

## 成长
- `pref.media`：`{"rule":"睡前喜欢身体扫描和雨声，10–15 分钟，中文女声","types":["身体扫描","白噪音"],"len_min":[10,15]}`
- `learn.media`：`{"rule":"身体扫描有用，箱式呼吸没感觉","works":[{"title":"…","url":"…","good":3}],"avoid":[{"title":"…","url":"…","reason":"声音太快"}]}`
- 下次找素材先看 `works`，再看 `avoid`。同一类型已经有 `works` 的，先问 Psir 要不要换，不主动换。
