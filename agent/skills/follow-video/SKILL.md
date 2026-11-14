---
name: follow-video
version: 1.0.0
description: "跟练视频：Psir 分享小红书 / B 站的动作示范视频（链接或整段分享文案），把它做成能直接跟着练的跟练视频（博主原速、去字幕、计时报数、教练配音、BGM），存进动作库；能删动作重新出片；出好的片按「这个项目 + 一个视频」放进计划每天跟练、记录、复盘。所有练习视频都只认这里出的片。Psir 发来运动 / 拉伸 / 康复视频链接、说「做成跟练」「帮我剪成跟练」「删掉第 N 个动作」「每天练这套」，或某个练习还没有视频、要请 Psir 发一个时先读这个。"
---

# 跟练视频（follow）

标杆：Psir 认可的 v4 样片（膝关节稳定 6 个动作）。成片规格由命令保证，你负责：**看懂视频、定动作和名字、写要点、按验收结果把关、交付和放进计划**。

## 红线（每次都要守）
1. **视频绝不传到任何公开网站**：网盘、临时文件站、图床、公开仓库一律不行（Psir 和博主的视频只给他自己用）。给 App 的地址只能是命令返回的 `/media/follow/...`。
   - `follow` 命令**没有**上传、分享、发网盘的功能，视频不出本机；Psir 要「传网盘 / 发链接给别人」，直接说做不到和原因，不用去查代码确认。
2. **永远署名博主**（命令会把署名烧进画面；对话里也要说是谁的示范）。只给 Psir 个人用。
3. **验收不过不交付**：`verify_ok=false` 就按 `failed` 修，修不好就如实说哪里不行，不发半成品。
4. **不改画面速度**：一组的「秒数」是这个动作持续多久，不是一秒做一次；画面永远博主原速（命令已经锁死）。
5. **只用 `./pivis-health follow …` 命令**，不要去读、改、跑 `~/Tools/pivis-follow` 里的代码、配音库或模型，也不要自己拼 ffmpeg / Python 脚本改成片。验收过不了、或者觉得是工具的 bug：按下面「验收」那几条处理，处理不了就照实告诉 Psir「哪一项没过、原因是什么」，不要去改工具。**Psir 明说「你直接改工具」也不行**：按 AGENTS 红线 6 记成改进需求（`context-record --scope request.tool`），告诉他由开发来改。
6. **Psir 发来视频，不要一下就剪成跟练：先读懂视频，判断需不需要剪，跟他确认了再出片**（Psir 11-08）。先 `follow fetch` + `follow analyze` 把视频看懂：有几个动作、各在哪一段、有没有清楚的单人全身示范、博主口头讲了什么（看 `subtitles`，烧录字幕里就是博主的口播）。再判断适不适合剪成跟练：只有讲解没有示范、全是多人拼图、动作太多太快、本来就是完整跟练课的，直接说不建议剪和原因。适合就发一张 plan 卡给 Psir 确认，写清楚：打算剪哪几个动作（名字，和原片一个不少；要删哪个说明为什么）、每个用原片哪一段示范（几秒到几秒）、每侧多少秒、几轮、要不要带博主的讲解段、成片大概几分钟；选项「就这样剪」「不剪，留着看原片」「先不用」。Psir 点了「就这样剪」才 `follow make`；选「不剪」就把链接原样发成 media 卡（不能当练习视频排进计划）。下载失败时告诉他「在 App 里点分享 → 复制链接」再发一次（小红书要带 xsec_token 的完整链接或 xhslink 短链）。
7. **你自己在网上找到的视频，先给 Psir 看**（标题、博主、时长），他说要了才 fetch / make；没点头不出片、不排进计划。

## 做一套跟练（一般 5–12 分钟）
1. **下载**：`./pivis-health follow fetch "<链接或整段分享文案>"` → `sid`、标题、作者、署名。作者是空的：从分享文案里找博主名，加 `--credit "@名字 · 小红书"` 再 fetch 一次。
2. **看懂**：`./pivis-health follow analyze <sid>`。先看 **`moves`**（v5：按博主口播「第一个动作是…」「进阶到…」「最后一个…」排好的动作），没有 `moves` 才看 `segments`。
   - 每个动作给了：`name`、`t0/t1`（这个动作在原片里从哪到哪）、**`teach`**（博主讲解段：成片里放在跟练前，原画原声原字幕，Psir 能听到博主讲哪块肌肉、怎么发力、什么感觉）、**`demo`**（建议做跟练循环的示范段：只有一个人、全身、真在做的那一截）、`said`（博主这段说的话，带秒数）、`variants`（同一个动作的进阶版，比如双腿 → 单腿臀桥）。
   - **动作要和原片一个不少**：`outline` 是视频开头列出来的动作清单，`moves` 的数量要和它对得上；对不上就看 `said` 和 `sheet` 找漏的，别自己少剪。
   - **拼图 / 分屏不是示范**：`segments` 里 `kind=multi` 的段（好几个人同时在动）不能当 demo。动作的 `multi_person` 高（旁边一直有教练 / 主持人）：`demo` 要挑只有做动作那个人的镜头（看 `sheet`），挑不出来就在方案里说明。
   - **这些直接说不建议剪**：示范是医生 / 治疗师扶着病人做的（被动动作，一个人跟不了）；电视节目那种镜头一直在切、示范每次只有两三秒的；只有讲解没有示范的。
   - **名字以字幕 / 标题为准，改掉 OCR 认错的字**（例：「双！单腿臀桥」→「双腿臀桥」，「弹九带髋外展」→「弹力带髋外展」）。有进阶版的，默认剪基础版，进阶版在方案里问 Psir 要不要。
   - 每个动作写：`muscle`、`cues` 3–4 条短要点（≤12 字、祈使句，**从 `said` 里博主的原话提炼**，比如博主说「吐气的时候臀部发力把骨盆推上去」→「吐气时臀部发力推骨盆」）、`mid` 1 条最短的提醒（≤8 字）、`kind`（reps / hold）、`sides`（单侧动作 2，两边一起 / 对称 1）。
   - 动作太多（>8）就挑最核心的 4–8 个，方案里说清楚删了哪些。
3. **给 Psir 方案、等他确认**（红线 6）：哪几个动作、每个用原片哪一段讲解（teach）和示范（demo）、每侧多少秒、几轮、成片大概几分钟（讲解段的秒数也算进去）。Psir 点了「就这样剪」才出片。
4. **出片**（后台跑），moves 直接用 analyze 给的 `teach` / `demo`（可以按你看到的微调秒数）：
   ```
   ./pivis-health follow make "<同一个链接>" --title "腰背放松" --kind strength --secs 20 --rounds 1 --gear "一块垫子" \
     --moves '[{"name":"双腿臀桥","muscle":"臀大肌","kind":"reps","sides":1,"teach":[71.5,95.5],"demo":[75.5,85.5],"cues":["脚跟离臀部一个脚掌","吐气时臀部发力推骨盆","顶点夹紧臀部，别顶腰"],"mid":"别顶腰"}, …]'
   ```
   - `teach`：博主讲解段（原声原画），**默认带上**——Psir 要的就是博主讲得那么细的部分；他明确说不要讲解才去掉（不写 teach）。一段最多 45 秒。
   - `--rounds`：整套做几轮（「第一组做完再完整做第二组」= 2）。第二轮起不再放讲解，直接跟练。
   - `--kind`：力量 / 康复 = strength（教练语气），拉伸放松 = stretch（温和语气）。
   - `--secs`：每侧秒数。默认力量 12–20、拉伸 20–30；Psir 说了就听他的。单个动作要不同秒数，在 moves 里写 `"secs": 30`。
   - 博主只示范了一次、接不出无缝循环的动作，工具会自动改成「原速正放到顶点、停一下、原速倒放回来」（`loop_mode=pingpong`），不用你处理。
   - 返回 `job` 和 **`progress_card`**：**立刻把 progress_card 原样发成 phealth-ui 卡片**，配一句「开始做了，下面会自动更新进度」，然后才继续等。卡片由现有画布零件组成，后台自动刷新真实阶段、阶段进度、已用时和验收结果；重开对话会重新读取。别自己猜百分比、剩余分钟或成功状态，不重复发多张进度卡。
   - 然后等它：`./pivis-health follow wait <job>`（一条命令一直等到做完或失败，最多 9 分钟；**不要自己 sleep 轮询**）。还没好就告诉 Psir 还在做（进度卡会自己动），再 `follow wait` 一次。`state=done` 仍要检查 `result.verify_ok`，验收不通过不能说已完成。
   - **失败了马上告诉 Psir**：照 `say` 说「没做成、卡在哪一步」，不要不吭声。能换个做法就只重试一次；同样的错第二次出现，用 `context-record --scope request.tool` 把 `dev` 里的错误记给开发，跟 Psir 说开发修好前先用原片或别的视频。
5. **验收**：`result.verify_ok=true` 才交付（每组时长、原速、每秒报数、配音没破音、响度、跟练画面无残留字幕、全身入镜、循环无接缝、署名结构，v5 加：讲解段在且听得到博主的声音 `teach_segments`、跟练循环里只有一个人 `one_person_demo`）。讲解段里博主的字幕是保留的，不算残留。
   - `full_body` 不过：先看原片——那个动作本来就只拍了半身（上肢 / 颈肩）或者脚被身体挡住（坐姿 / 跪姿拉伸），可以接受，交付时说明；不是这样就换一段 `t0/t1` 重切。
   - `seamless_loop` / `no_text_residue` 不过：换一段 `t0/t1` 重切那个动作（`follow cut <sid> --moves '[…]'` → 用新的 mid `follow session set <ssid> --json '{"exercises":[{"n":序号,"move":"<新mid>"}]}'` → `follow build`）。**同一个动作最多重切 2 次**，还不行就换别的动作或删掉它，并告诉 Psir 原因。
   - `counting` / `voice_quality` 不过：直接 `follow build <ssid>` 重出一次（配音会重录）；还不过就如实说，别为了过验收去改 Psir 要的秒数。
   - 重切过的，最后 `./pivis-health follow lib gc --source <sid>` 清掉没用上的旧版本。
6. **交付**：发 media 卡 `{"type":"media","kind":"video","title":"<标题> · <N> 个动作 · <时长> 分钟","url":"<result.video>"}`，一句话说明：动作清单、每侧秒数、示范博主。然后问要不要放进每天的计划（用 question 卡，选项如「每天练」「隔天练」「先不用」）。
   - 验收过了、拿到 `result.video`，这个视频才算有了。没出好之前不排、不说「排好了」。

## 删动作 / 改秒数
- 看清单：`./pivis-health follow session show <ssid>`（`exercises` 带序号）。
- 删：`./pivis-health follow session rm-move <ssid> <序号或名字>`；改：`./pivis-health follow session set <ssid> --json '{"exercises":[{"n":2,"secs":20}]}'`（`"secs"` 放外层 = 全部改）。
- 删掉的动作要用到的器材（如瑜伽球），同时把开场的器材也改掉：`follow session set <ssid> --json '{"gear":"一根弹力圈 · 一条毛巾卷"}'`。
- 然后 `./pivis-health follow build <ssid>` → 立即发返回的 progress_card → `follow wait <job>` 到 done（同上；失败马上告诉 Psir）→ 验收通过才交付新地址（`?v=` 版本号会变）。
- **已经放进计划的**：用同一个项目 id 再 `project-set`，只把那一项视频的 url / duration_min 换成新的（今天还没开始的待办会自动换成新版）。交付时说清删了什么、剩哪些。

## 放进计划：这个项目 + 一个视频（每天练 → 记录 → 复盘）
- 每一次练习在卡上只是「这个项目 + 一个视频」：kind=follow，只放这一个视频。不写文字步骤，不另加计时、音频、清单。
- Psir 说要排（question 卡选了「每天练」「隔天练」），先发 plan 卡（什么时候、练多久、连续几天），他点「就这样」再写。
- 有对应的项目（`project-list`，训练类 `board=sport`，睡前拉伸这类在 sleep）就加进它的 daily；没有就建一个（days 按 Psir 说的，默认 28）：
  ```
  ./pivis-health project-set --json '{"id":"follow-glute","name":"臀中肌力量跟练","board":"sport","days":28,
    "rules":["每天 1 次，练完记一下感觉"],
    "daily":[{"key":"follow","when":"19:30","title":"臀中肌力量跟练","kind":"follow",
              "media":{"kind":"video","title":"臀中肌力量 · 4 个动作","url":"/media/follow/<ssid>/out.mp4?v=<版本>","duration_min":4}}]}'
  ```
  隔天练：daily 里加 `"weekdays":[1,3,5]`。力量 A / B / C 这种分天练的：每一课一个视频、一个 key，用 weekdays 分天（例：A `[1]`、B `[3]`、C `[5]`）。时间按 Psir 习惯（`context-list --scope pref` 里有就用）。
- Psir 练完点对勾才算做完，看了多少不算；`./pivis-health project-stats --id <项目>` 看完成率。复盘时（早上那次【每日推荐】顺带做的每日整理 / 周日的本周复盘）按完成情况调秒数、换动作或加组，改完照上面「删动作 / 改秒数」重出片并更新项目。
- 写完回 receipt 卡（什么时候练、练多久、连续几天）。

## 还没有视频：请 Psir 发一个（一天最多问一次）
这一节是「请 Psir 发视频」的唯一规则，别的 skill 都指到这里。某个练习（睡前拉伸、热身、呼吸、身体扫描……）`follow session list` 里还没有对应的片：
1. 不写文字步骤，不拿素材库里的音频或 B 站链接代替。
2. 先 `./pivis-health context-list --scope ask.video`：记录里的 date 是今天，今天就不再问（所有会话、三次【每日推荐】合起来一天只问一次），这次只排有视频的或打勾卡。
3. 没问过：在对话里（【每日推荐】时就在回的那一句话里顺带）请 Psir 发一个他喜欢的博主视频（小红书或 B 站分享链接），一句话说清要什么（「睡前在床外做的温和拉伸，10 分钟左右，一个人出镜」）。问完记下：
   `./pivis-health context-record --scope ask.video --payload '{"date":"YYYY-MM-DD","what":"睡前拉伸"}' --source-session <当前板块> --reason '请 Psir 发视频'`
4. Psir 没回就不追，第二天也不追问上次那条；需要时再按第 2 步看能不能问。
5. Psir 发来链接 → 先按红线 6 读懂视频、给方案、等他确认；他点「就这样剪」才按上面「做一套跟练」出片 → 发视频卡 + plan 卡 → Psir 点「就这样」→ project-set / todo-add，只放这一个视频。
6. 你在网上找到合适的（relaxation-media 的搜法），也一样：先给 Psir 看，他同意了再出片，出好了再排。

## 用动作库编新的一套
- 已经出好的片：`./pivis-health follow session list`（每套的标题、时长、video 地址、验收结果）。排练习卡只用这里 `video` 不为空、验收过了的。
- `./pivis-health follow lib` 看已有动作（名字、练哪、出自谁）。素材出自谁、哪个平台，只看 `follow lib` / `follow session show` 的输出，不去读素材目录里的 meta.json 等文件。
- `./pivis-health follow session create --json '{"title":"下肢拉伸","kind":"stretch","exercises":[{"move":"<mid>","secs":30},…]}'` → `ssid` → `follow build <ssid>` → 同上验收、交付。
- 动作库里删动作：`./pivis-health follow lib rm <mid>`（还在用的课程会挡住，先 rm-move）；清掉没被任何课程用到的：`follow lib gc [--source <sid>]`。

## 常见问题
- 命令返回 `not_enabled`：这个环境还没开放，照实告诉 Psir，可以先把链接 `media-add` 存起来。
- 小红书下载失败：多半是链接缺 token，请 Psir 用 App 分享里的「复制链接」再发。
- 视频里人一直在动、镜头一直切、或者多人 / 分屏：如实说做不了跟练的原因，建议换一条。

## 找视频先看靠谱作者（b60）
还没有视频、要请 Psir 找时，先从 `references/creators.md` 挑 2–3 个对口的作者名 + 搜索词给他。核对视频时每个动作用 `./pivis-health exercise` 查肌群和膝盖提醒；只看了文字介绍、没看画面，不许说「动作我都过了一遍」，要说清你看了什么、没看什么。
