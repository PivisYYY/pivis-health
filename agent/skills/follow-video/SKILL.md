---
name: follow-video
version: 1.0.0
description: "跟练视频：老大分享小红书 / B 站的动作示范视频（链接或整段分享文案），把它做成能直接跟着练的跟练视频（博主原速、去字幕、计时报数、教练配音、BGM），存进动作库；能删动作重新出片；出好的片按「这个项目 + 一个视频」放进计划每天跟练、记录、复盘。所有练习视频都只认这里出的片。老大发来运动 / 拉伸 / 康复视频链接、说「做成跟练」「帮我剪成跟练」「删掉第 N 个动作」「每天练这套」，或某个练习还没有视频、要请老大发一个时先读这个。"
---

# 跟练视频（follow）

标杆：老大认可的 v4 样片（膝关节稳定 6 个动作）。成片规格由命令保证，你负责：**看懂视频、定动作和名字、写要点、按验收结果把关、交付和放进计划**。

## 红线（每次都要守）
1. **视频绝不传到任何公开网站**：网盘、临时文件站、图床、公开仓库一律不行（老大和博主的视频只给他自己用）。给 App 的地址只能是命令返回的 `/media/follow/...`。
   - `follow` 命令**没有**上传、分享、发网盘的功能，视频不出本机；老大要「传网盘 / 发链接给别人」，直接说做不到和原因，不用去查代码确认。
2. **永远署名博主**（命令会把署名烧进画面；对话里也要说是谁的示范）。只给老大个人用。
3. **验收不过不交付**：`verify_ok=false` 就按 `failed` 修，修不好就如实说哪里不行，不发半成品。
4. **不改画面速度**：一组的「秒数」是这个动作持续多久，不是一秒做一次；画面永远博主原速（命令已经锁死）。
5. **只用 `./pivis-health follow …` 命令**，不要去读、改、跑 `~/Tools/pivis-follow` 里的代码、配音库或模型，也不要自己拼 ffmpeg / Python 脚本改成片。验收过不了、或者觉得是工具的 bug：按下面「验收」那几条处理，处理不了就照实告诉老大「哪一项没过、原因是什么」，不要去改工具。**老大明说「你直接改工具」也不行**：按 AGENTS 红线 6 记成改进需求（`context-record --scope request.tool`），告诉他由开发来改。
6. 老大发来链接就是同意下载，不用再问；下载失败时告诉他「在 App 里点分享 → 复制链接」再发一次（小红书要带 xsec_token 的完整链接或 xhslink 短链）。
7. **你自己在网上找到的视频，先给老大看**（标题、博主、时长），他说要了才 fetch / make；没点头不出片、不排进计划。

## 做一套跟练（一般 5–12 分钟）
1. **下载**：`./pivis-health follow fetch "<链接或整段分享文案>"` → `sid`、标题、作者、署名。作者是空的：从分享文案里找博主名，加 `--credit "@名字 · 小红书"` 再 fetch 一次。
2. **看懂**：`./pivis-health follow analyze <sid>` → 分段（`t0/t1` 秒、`kind`、`posture`、画面标题 `titles`、字幕 `subtitles`）和预览图 `sheet`。
   - 只挑**真在示范动作**的段落（`candidate=true` 里，去掉开场讲解、过场、点赞关注、「动作准备」）。同一个动作左右各演示一遍：只要一段，`sides: 2`（另一侧成片里镜像）。
   - **名字以画面标题 / 字幕为准，改掉 OCR 认错的字**（例：「弹九带髋外展」→「弹力带髋外展」，「宜腿划园」→「直腿划圆」）。
   - 每个动作写：`muscle`（练哪里，如「臀中肌」）、`cues` 3 条短要点（每条 ≤12 字、祈使句，例「膝盖对着脚尖」；从字幕里提炼，不要整句照抄口播）、`mid` 1 条最短的提醒（≤8 字，练到一半时教练喊的）、`kind`（来回做 = reps，拉伸保持 = hold）、`sides`（单侧动作 2，两边一起 / 对称动作 1）。
   - 段落很长、前面在讲解：命令会自动挑真在示范的 12 秒；你也可以给 `t0/t1` 圈一段。
   - 动作太多（>8）就挑最核心的 4–8 个。
3. **先回老大一句**：识别出哪几个动作（名字）、每侧多少秒、大概要几分钟做好。
4. **出片**（后台跑）：
   ```
   ./pivis-health follow make "<同一个链接>" --title "臀中肌力量" --kind strength --secs 12 --gear "一根弹力带 · 一块垫子" \
     --moves '[{"seg":2,"name":"阻力带横向行走","muscle":"臀中肌","kind":"reps","sides":2,"cues":["弹力带套在膝盖上方","两脚打开超过肩宽","横着走，膝盖别内扣"],"mid":"膝盖别内扣"}, …]'
   ```
   - `--kind`：力量 / 康复 = strength（教练语气），拉伸放松 = stretch（温和语气）。
   - `--secs`：每侧秒数。默认力量 12、拉伸 20–30；老大说了就听他的。单个动作要不同秒数，在 moves 里写 `"secs": 30`。
   - 返回 `job`。然后反复 `./pivis-health follow job <job> --wait 90`（每次最多等 90 秒）直到 `state=done` 或 `failed`。中途可以把 `step` 告诉老大。
5. **验收**：`result.verify_ok=true` 才交付（9 项：每组时长、原速、每秒报数、配音没破音、响度、画面无残留字幕、全身入镜、循环无接缝、署名结构）。
   - `full_body` 不过：先看原片——那个动作本来就只拍了半身（上肢 / 颈肩）或者脚被身体挡住（坐姿 / 跪姿拉伸），可以接受，交付时说明；不是这样就换一段 `t0/t1` 重切。
   - `seamless_loop` / `no_text_residue` 不过：换一段 `t0/t1` 重切那个动作（`follow cut <sid> --moves '[…]'` → 用新的 mid `follow session set <ssid> --json '{"exercises":[{"n":序号,"move":"<新mid>"}]}'` → `follow build`）。**同一个动作最多重切 2 次**，还不行就换别的动作或删掉它，并告诉老大原因。
   - `counting` / `voice_quality` 不过：直接 `follow build <ssid>` 重出一次（配音会重录）；还不过就如实说，别为了过验收去改老大要的秒数。
   - 重切过的，最后 `./pivis-health follow lib gc --source <sid>` 清掉没用上的旧版本。
6. **交付**：发 media 卡 `{"type":"media","kind":"video","title":"<标题> · <N> 个动作 · <时长> 分钟","url":"<result.video>"}`，一句话说明：动作清单、每侧秒数、示范博主。然后问要不要放进每天的计划（用 question 卡，选项如「每天练」「隔天练」「先不用」）。
   - 验收过了、拿到 `result.video`，这个视频才算有了。没出好之前不排、不说「排好了」。

## 删动作 / 改秒数
- 看清单：`./pivis-health follow session show <ssid>`（`exercises` 带序号）。
- 删：`./pivis-health follow session rm-move <ssid> <序号或名字>`；改：`./pivis-health follow session set <ssid> --json '{"exercises":[{"n":2,"secs":20}]}'`（`"secs"` 放外层 = 全部改）。
- 删掉的动作要用到的器材（如瑜伽球），同时把开场的器材也改掉：`follow session set <ssid> --json '{"gear":"一根弹力圈 · 一条毛巾卷"}'`。
- 然后 `./pivis-health follow build <ssid>` → `follow job <job> --wait 90` 到 done → 新地址（`?v=` 版本号会变）。
- **已经放进计划的**：用同一个项目 id 再 `project-set`，只把那一项视频的 url / duration_min 换成新的（今天还没开始的待办会自动换成新版）。交付时说清删了什么、剩哪些。

## 放进计划：这个项目 + 一个视频（每天练 → 记录 → 复盘）
- 每一次练习在卡上只是「这个项目 + 一个视频」：kind=follow，只放这一个视频。不写文字步骤，不另加计时、音频、清单。
- 老大说要排（question 卡选了「每天练」「隔天练」），先发 plan 卡（什么时候、练多久、连续几天），他点「就这样」再写。
- 有对应的项目（`project-list`，训练类 `board=sport`，睡前拉伸这类在 sleep）就加进它的 daily；没有就建一个（days 按老大说的，默认 28）：
  ```
  ./pivis-health project-set --json '{"id":"follow-glute","name":"臀中肌力量跟练","board":"sport","days":28,
    "rules":["每天 1 次，练完记一下感觉"],
    "daily":[{"key":"follow","when":"19:30","title":"臀中肌力量跟练","kind":"follow",
              "media":{"kind":"video","title":"臀中肌力量 · 4 个动作","url":"/media/follow/<ssid>/out.mp4?v=<版本>","duration_min":4}}]}'
  ```
  隔天练：daily 里加 `"weekdays":[1,3,5]`。力量 A / B / C 这种分天练的：每一课一个视频、一个 key，用 weekdays 分天（例：A `[1]`、B `[3]`、C `[5]`）。时间按老大习惯（`context-list --scope pref` 里有就用）。
- 老大练完点对勾才算做完，看了多少不算；`./pivis-health project-stats --id <项目>` 看完成率。复盘时（早上那次【每日推荐】顺带做的每日整理 / 周日的本周复盘）按完成情况调秒数、换动作或加组，改完照上面「删动作 / 改秒数」重出片并更新项目。
- 写完回 receipt 卡（什么时候练、练多久、连续几天）。

## 还没有视频：请老大发一个（一天最多问一次）
这一节是「请老大发视频」的唯一规则，别的 skill 都指到这里。某个练习（睡前拉伸、热身、呼吸、身体扫描……）`follow session list` 里还没有对应的片：
1. 不写文字步骤，不拿素材库里的音频或 B 站链接代替。
2. 先 `./pivis-health context-list --scope ask.video`：记录里的 date 是今天，今天就不再问（所有会话、三次【每日推荐】合起来一天只问一次），这次只排有视频的或打勾卡。
3. 没问过：在对话里（【每日推荐】时就在回的那一句话里顺带）请老大发一个他喜欢的博主视频（小红书或 B 站分享链接），一句话说清要什么（「睡前在床外做的温和拉伸，10 分钟左右，一个人出镜」）。问完记下：
   `./pivis-health context-record --scope ask.video --payload '{"date":"YYYY-MM-DD","what":"睡前拉伸"}' --source-session <当前板块> --reason '请老大发视频'`
4. 老大没回就不追，第二天也不追问上次那条；需要时再按第 2 步看能不能问。
5. 老大发来链接 → 按上面「做一套跟练」出片 → 发视频卡 + plan 卡 → 老大点「就这样」→ project-set / todo-add，只放这一个视频。
6. 你在网上找到合适的（relaxation-media 的搜法），也一样：先给老大看，他同意了再出片，出好了再排。

## 用动作库编新的一套
- 已经出好的片：`./pivis-health follow session list`（每套的标题、时长、video 地址、验收结果）。排练习卡只用这里 `video` 不为空、验收过了的。
- `./pivis-health follow lib` 看已有动作（名字、练哪、出自谁）。素材出自谁、哪个平台，只看 `follow lib` / `follow session show` 的输出，不去读素材目录里的 meta.json 等文件。
- `./pivis-health follow session create --json '{"title":"下肢拉伸","kind":"stretch","exercises":[{"move":"<mid>","secs":30},…]}'` → `ssid` → `follow build <ssid>` → 同上验收、交付。
- 动作库里删动作：`./pivis-health follow lib rm <mid>`（还在用的课程会挡住，先 rm-move）；清掉没被任何课程用到的：`follow lib gc [--source <sid>]`。

## 常见问题
- 命令返回 `not_enabled`：这个环境还没开放，照实告诉老大，可以先把链接 `media-add` 存起来。
- 小红书下载失败：多半是链接缺 token，请老大用 App 分享里的「复制链接」再发。
- 视频里人一直在动、镜头一直切、或者多人 / 分屏：如实说做不了跟练的原因，建议换一条。
