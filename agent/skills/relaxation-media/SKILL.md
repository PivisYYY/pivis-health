---
name: relaxation-media
version: 1.0.0
description: "给老大找放松和跟练素材（呼吸引导、身体扫描、白噪音或自然声、拉伸视频、正念）：先用 media-library，不够再联网搜索公开、免登录、中文的素材，给 2–3 个让老大选，选定后用 plan 卡确认，再写进待办或项目，用完打分，分低就换。老大要放松材料、说现在的素材不好用、要换一个，或要给睡前流程或减压待办配素材时使用。"
---

# 放松素材：先选再定

## 什么时候用
- 老大说「找点放松的」「睡前听什么」「这个不好用，换一个」「有没有拉伸视频」。
- 你要给 cbti 的睡前流程、stress-recovery 的减压待办、training-coach 的拉伸配素材。
- 【每日整理】时发现昨天用了某个素材但还没打分。

## 怎么做
1. **弄清需求**（已知的不再问）：先 `./pivis-health context-list --scope pref.media` 和 `--scope learn.media`。缺什么，就用 question 卡问什么，一次最多问 2 题：
   - 类型：呼吸引导 / 身体扫描 / 白噪音或自然声 / 拉伸视频 / 轻音乐
   - 用在什么时候：睡前 / 午间 / 压力大时 / 运动后
   时长按 `references/search.md` 第 1 节的默认值，老大另有要求就听他的。
2. **先查素材库**：`./pivis-health media-library`。挑类型和时长对得上的，去掉 `learn.media.avoid` 里的。够 2 个就跳到第 4 步。
3. **联网搜**（用 tool-web 的搜索和打开网页）：
   - 搜索词和筛选标准见 `references/search.md`。只用 B 站，或网页直接能播、不用登录也不要会员的国内平台。
   - 每个候选都要打开页面核对：标题、UP 主、时长、播放量，不要登录、不是会员或充电专属、不是多 P 合集里的后几集。核对不了的不用。
   - 链接写成干净的 `https://www.bilibili.com/video/BVxxxxxxxxxx`（去掉 `?` 后面的参数）。
   - 不用 YouTube、内网地址、本地路径、网盘链接。
4. **给 2–3 个选项**：一句话说明为什么挑这几个，然后：
   - 网上找到的：每个发一张 media 卡（B 站链接 `"kind":"embed"`），title 写「<名字> · <时长> · <UP 主>」。
   - 素材库里的（url 以 `/media/` 开头的音频）：直接发 media 卡（`"kind":"audio"`），App 会补全地址。
   - 最后发一张 question 卡让老大选（模板见下）。
5. **老大选了以后，发 plan 卡**：什么时间、做多久、连续几天、在流程里排第几步、怎么打分。actions：就这样 / 改一下 / 不要。
6. **老大点「就这样」后写入**：
   - 已有项目里的流程（比如 cbti 的 winddown）：`project-set` 同一个 id，只换那一项的 steps。
   - 只用一次：`todo-add` 一张 kind=follow 的卡。
   - 连续用几天、又没有项目：建一个小项目（days 7），写法照 `../cbti/references/templates.md` 第 1 节。
   - 写进待办的 media：B 站视频用 `"kind":"video"`（跟做页会嵌入 B 站播放器），音频文件用 `"kind":"audio"`。
   - 网上找到、老大选中的素材收进他的素材库，下次不用重搜：`./pivis-health media-add --json '{"title":"…","url":"https://www.bilibili.com/video/BV…","duration_min":15,"type":"身体扫描"}'`
   - `context-record --scope pref.media`（老大喜欢的类型、时长、来源），附 receipt 卡。
7. **用完打分**：
   - 在 cbti 项目里：日记里已经有「昨晚的睡前放松」这一题，不另外加卡。
   - 不在项目里：第二天【每日整理】时，如果昨天的 follow 卡是 done、还没打分，就 `todo-add` 一张打分卡（不写 when，不推送）。
8. **按分数换**：
   | 打分 | 动作 |
   |---|---|
   | 「没用，换一个」或「没用」 | 当天就回到第 2 步，去掉这个素材，再给 2–3 个 |
   | 连续 2 次「一般」 | 问一句是类型不对还是这一个不对（question 卡），再换 |
   | 累计 3 次「有用」 | 保留，记进 `learn.media.works` |

## 规则与红线
1. 只给 2–3 个选项，让老大选。老大没选之前不写进计划，选了以后也要等 plan 卡确认。
2. 素材只做放松，不当治疗。不选标题写着「治愈失眠」「根治焦虑」的，也不选卖课、卖产品的。
3. 睡前素材不要选亮屏的长视频。拉伸视频安排在床外、上床前做完，躺到床上只听音频或者不听。
4. 拉伸动作要温和：不倒立，不做高强度动作，不做需要器械的。老大有伤的部位（`sport.preference.injury`）不做对应动作。
5. 呼吸练习出现头晕、胸闷就停，恢复自然呼吸。反复出现就按 clinical-safety 处理。
6. 老大说「算了」：今天不再推荐素材，第二天也不追问。

## 模板
选项 question 卡：
```json
{"type":"question","title":"选一个今晚试","fields":[{"id":"pick","label":"用哪个","type":"options","options":["身体扫描 · 12 分钟 · 素材库","睡前冥想引导 · 15 分钟 · B 站","雨声白噪音 · 60 分钟 · B 站","都不要，换一批"],"allow_text":true}],"submit_label":"就它"}
```
单次 follow 卡（B 站视频）：
```json
{"board":"sleep","when":"23:30","title":"睡前身体扫描","kind":"follow","note":"在床外坐着做","duration_min":15,
 "steps":[{"title":"身体扫描引导","media":{"kind":"video","title":"身体扫描引导","url":"https://www.bilibili.com/video/BV1xxxxxxxxx","duration_min":15}}],
 "verbs":["start","later","skip"]}
```
（url 换成第 3 步核对过的真实链接。）
打分卡：
```json
{"board":"sleep","title":"昨晚的放松有用吗","kind":"options",
 "inputs":[{"id":"rate","label":"","type":"options","options":["有用","一般","没用，换一个"],"submit":"agent"}]}
```
收到打分：`todo-update --id <id> --json '{"status":"done","summary":"身体扫描：有用"}'`，再更新 `learn.media`。

## 成长
- `pref.media`：`{"rule":"睡前喜欢身体扫描和雨声，10–15 分钟，中文女声","types":["身体扫描","白噪音"],"len_min":[10,15]}`
- `learn.media`：`{"rule":"身体扫描有用，箱式呼吸没感觉","works":[{"title":"…","url":"…","good":3}],"avoid":[{"title":"…","url":"…","reason":"声音太快"}]}`
- 下次找素材先看 `works`，再看 `avoid`。同一类型已经有 `works` 的，先问老大要不要换，不主动换。
