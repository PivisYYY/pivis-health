# dsh 接入说明（P-Health bot）

## 直连对话（最终形态，2026-10-31）

**App → 内嵌 dsh 官方会话界面 → P-Health 会话本体**，不经任何中间桥：

- 自有 `dsh web` 实例常驻（launchd `com.pivis.dshweb`，Tailnet `<内网地址>:8960`，token 记录在 `pivis-runtime/dshweb.log`）
- 稳定入口：`http://<内网地址>:8943/dsh` —— 自动带 token 并直达 P-Health 会话（`?session=`）
- iOS App 聊天页 = WKWebView 内嵌该入口；PWA"P-Health"标签同入口；已实测：发消息 → P-Health跑 `./pivis-health doctor` → 带真实数据回复
- P-Health 会话已从归档恢复（`storages/workspace.json`）
- 主观库迁至 bot 工作区 `pivis-runtime/`（沙箱内可写，bot 全部命令免提权）
- 早前的飞书群链路保留为只读镜像展示（主动推送通道已停用：P-Health 不使用飞书，也不自己推送）

## 原生 iOS App（真 App，聊天对象是P-Health）

- 工程：`ios/PivisHealth/`（SwiftUI，零第三方依赖），四个标签：**现在 / 休息 / 运动 / 压力** + 右下角 P 全局对话入口（每页点开自动带板块上下文，如【休息】）
- 聊天链路：App → dsh web API `session/prompt` 直连P-Health会话（cookie 自动换取，401 自动刷新重试）→ App 每 5 秒轮询 `GET /api/chat`（pivis-health 后端解压会话文件）带回——**聊的是真P-Health本人**（它的记忆、工具全在；P-Health 没有定时任务，见下文「定时消息」）
- 已验证：xcodebuild 编译通过、iPhone 17 Pro 模拟器安装运行、真实会话消息渲染、生成式 UI 卡片可点可选
- 对话组件目录（2026-11-03）：options / plan / rating / confirm + StatTile / DataTable / GroupCompare / AttributionBar / BandLine / DecisionCard / MediaCard；每个组件支持受控 style，不需要重新出包即可由 Agent 决定内容与表现
- `MediaCard`：只使用国内平台，优先 B 站；`media_type=embed` 用 WKWebView 内嵌在线视频，`video` / `audio` 用 AVPlayer 播放 mp4/mov/m3u8/mp3/m4a/aac/wav/flac 直链。默认不自动播放；网页加载失败显示明确提示并保留浏览器打开。页面固定槽位同样支持媒体：专项大卡可为 `media`，小卡和待办可带 `media_type/url`
- **共享上下文与事件**（2026-11-04）：`context-record/context-list` 保存跨 Session 的个人记忆与决定，所有编排读取同一 revision；`event_ingest/event_dispatch` 对原始位置/蓝牙事件做幂等存储和至少一次分发，`com.pivis.health-events` 每 30 秒把事件交给 `phealth-event-handler`。事件含义由 P-Health 判断，驾驶中不即时打扰
- 对话驱动优化：工作区 `./pivis-health dialogue-list/dialogue-add/dialogue-remove` 持久化对话规则；`ui-list/ui-set/ui-reset` 调整页面既有组件的真实数据源、文案、图表和样式。配置在 `pivis-runtime/experience.json`，写入进主观库审计；页面数量、Session 路由、卡片上限和数值来源不可由配置改变。（已停用：b44 起 `ui.*`、`dialogue.*` 不再接受，偏好统一用 `context-record` 记 `pref.*`）
- **全部业务组件由 Agent 发布**（2026-11-03）：`agent-pages-publish --page now|sleep|sport|stress|relax` 将真实证据交给每页独立的内部编排 Session，Agent 输出组件 JSON，经结构、Session、数值来源、图表和素材校验后写入 `pivis-runtime/component_publications.json`。四页与放松流程只读已发布组件；规则输出仅作证据，发布失败保留上一版，不回退成规则拼装页面。（v2 旧链路，已停用；v3 由 `publish-v3` 编排页面）
- 定时节拍：launchd `com.pivis.health-composer` 每个整点唤醒，只在北京时间 08 / 13 / 18 点干活：先 `daily-review` 给主会话发【每日推荐】，再 `publish-v3 all` 重排四页（`scripts/v3-cycle.sh`）。对话里改了项目，系统在后台刷新相关页。客户端打开/下拉刷新只读最新版本，不临时等待 LLM
- 装真机：`open ios/PivisHealth/PivisHealth.xcodeproj` → 选你的 Apple ID 作为 Team → Cmd+R（ATS 已放行 Tailnet IP）
- 重编译模拟器版：`cd ios/PivisHealth && xcodebuild -project PivisHealth.xcodeproj -target PivisHealth -sdk iphonesimulator build CODE_SIGNING_ALLOWED=NO SYMROOT=$(pwd)/build`

## 聊天发送的一次性授权（App 登录）

以用户身份发消息需要一次飞书设备码授权（读取群消息不需要）：
`lark-cli auth login --scope "im:message.send_as_user im:message im:chat" --no-wait`
→ 打开验证链接 → `lark-cli auth login --device-code <code>` 完成。未授权时 App 与网页都返回 need_auth 提示，不影响其它功能。

## 已就位的组件

| 组件 | 位置 | 说明 |
|---|---|---|
| 内核代码 | `~/Tools/pivis-health` | 运行时零依赖，系统 Python 3.9.6 直接跑 |
| bot 工作区约定 | `~/.dsh/bot/workspace/AGENTS.md`（自举+命令+红线）、`pivis-health.md`（详版）、`pivis-health`（脚本） | coding-agent 的 AGENTS.md 自动加载约定 |
| bot 系统提示词 | `~/.dsh/bot/state.json`（P-Health instructions 已追加内核契约；**桌面端运行中会内存回写**，改完需重启 dsh 桌面端生效） | revision 已 +1 |
| 手机客户端 | `http://<内网地址>:8943/v2/now`（v2 PWA：现在/休息/运动/压力 + 底部 P 对话抽屉；iOS"添加到主屏幕"即用） | launchd `com.pivis.health` 常驻 |
| 独立直达页 | `/morning` `/relax` `/weekly`（bot 发链接用） | 放松页：内容库挑选→今晚流程→好用/不行评分闭环 |
| 只读客观库 | hermes 的 `health.sqlite3`（12-06 前不迁移写入） | WHOOP 快照同样只读 |
| 主观库 | `runtime/subjective.sqlite3`（0600） | 行为答案/放松评分/规则/推送去重 |

## 定时消息（b44 起，没有 bot 定时任务）

- P-Health 不建、也没有 DSH 定时任务。早前要它自举的四个定时任务（晨报 / 监测 / 覆盖核对 / 就寝提醒）已取消，不用再发自举指令。
- 服务器的 launchd `com.pivis.health-composer`（`scripts/v3-cycle.sh`）每天北京时间 08:00 / 13:00 / 18:00 给主会话发一条【每日推荐】，老大看不到；消息里带当天已排的定时待办数和已发的锁屏推送数。
- 早上那条【每日推荐】顺带做每日整理（看昨天、打分、改轻、漏两次、了解期；以前单独发的整理消息已取消）；周日早上那条再带周复盘要求，每个进行中的项目出一张「本周复盘」提议卡，项目里不写周日的复盘模板。
- 提醒：P-Health 只写带 `when` 的待办卡，App 本地提醒（到点一次，15 分钟后还没做再催一次）。锁屏推送只由服务器发，每天最多 3 条，免打扰和去重在代码里。
- bot 提示词改了以后，仍要重启 dsh 桌面端才生效（见上表「bot 系统提示词」）。

## 渠道

- 主交互：PWA 客户端（`/app`）+ dsh 手机端（到位后切换聊天入口）；微信 `dsh-weixin` 做镜像同步。
- 所有点选交互走客户端页面，不依赖任何装机。

## 验收口径

- [x] CLI 对真实库只读冒烟通过（doctor/today/morning-report/monitor/coverage）
- [x] 32/32 回归测试（含三起历史事故复刻 + 放松闭环）
- [x] 手机客户端五视图浏览器实测（今天/监测/打卡/放松/周报，移动视口 390×844）
- [x] 放松页端到端：挑选→生成流程→评分→推荐变化（UI 实测 👍1 生效）
- [x] bot 工作区三件套 + state.json 提示词更新（重启生效）
- ~~用户重启 dsh 或发一句自举指令（bot 建定时任务）~~ 已取消：b44 起由服务器发【每日推荐】，见「定时消息」
- [ ] 微信镜像首条真实投递核验
