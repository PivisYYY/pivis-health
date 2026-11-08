# P-Health · pivis-health

**一个会盯着你的健康数据、告诉你今天该做什么、并推着你去做的私人健康管家。**

P-Health 由三部分组成：

- **iOS App**（SwiftUI，黑白细线风格，在 [`ios/`](ios/)）：四个板块页、生成式待办、和 P-Health 对话、锁屏通知。
- **pivis-health**（Python，在仓库根目录）：健康内核和服务端。负责读数据、做确定性计算，提供页面、待办、图表和同步接口。
- **P-Health Agent**（跑在 DSH 上）：页面上写什么、主卡画什么图、待办怎么排，都由它根据真实数据生成。

App 只负责画出来，内核只负责把数算对；中间所有"说什么、做什么"都交给 Agent。

![四个板块：现在 / 休息 / 运动 / 压力](docs/images/pages.png)

> 截图里的数据全部是编出来的演示数据（[`examples/make_demo.py`](examples/make_demo.py) 生成），不来自任何真人。

## 三条原则

1. **监测 → 建议 → 推动执行**。不只是展示指标：先找出眼下最该注意的一件事，给出今天能做的动作，到点提醒，做完记下来。
2. **Agent 原生**。页面结构固定，内容由 P-Health 生成：结论、主卡指标和画法、待办、习惯项目、对话里的卡片都是。
3. **越用越懂你**。你说一次"睡眠图看 14 晚""步数目标 1 万""拉伸用视频"，它就记成偏好，之后页面和对话都照做。

底线：**所有数字都来自内核计算，Agent 不自己编数**；**不做诊断**。常态范围按你自己近 30 天的数据算，不是医学标准。

## 功能

### 四个板块，每页只讲一件事

「现在 / 休息 / 运动 / 压力」，每页从上到下依次是：

- **一句结论**：判断加上该做什么。
- **主卡**：眼下最该注意的那个指标，配档位"需处理 / 留意 / 平稳"。档位点按严重程度有不同动效。
- **坚持习惯**：正在进行的长期项目，比如"睡前放松 · 第 8 天 / 21"。
- **接下来**：0–3 件今天的待办。

### 主卡的图由 P-Health 选

内核提供 7 种画法：

| 画法 | 适合 | 看什么 |
|---|---|---|
| 折线 trend | HRV、呼吸、睡眠时长 | 走势、个人常态带、警戒线 |
| 半圆仪表 gauge | 恢复 | 分数落在哪一档 |
| 睡了 vs 需要 need | 睡眠 | 昨晚差多少，近 7 晚有几晚没睡够 |
| 叠起来 stack | 睡眠债 | 每晚欠的累计到多少 |
| 区间刻度 range | 静息心率 | 今天在自己常态的哪个位置 |
| 进度 progress | 步数 | 按此刻该走到哪 |
| 路线 route | 体重 | 朝目标的计划路线和实际 |

P-Health 只写"画哪项、用哪种、看几天"，数字由内核现算。你在对话里说"换一种看法"，它会先在对话里给你看页面同款的预览，你确认后再改，页面一两分钟后自动换上。

### 生成式待办和习惯

- 待办类型：打勾、填写（选项 / 打分 / 数字 / 时间 / 文字）、拍照、跟做（分步计时，可以带音频或视频）、提议（给 2–3 个选项让你选）。
- 长期项目（睡前放松 21 天、训练计划……）每天自动生成当天的待办。你改了模板，"今晚起"就生效。
- 到点系统提醒，错过再提醒一次；午睡这类可以用系统闹钟。
- 上床这类能自动识别的，设备记到就自动勾上。

### 和 P-Health 对话

![对话：页面同款的图、提问卡；更新中的主卡](docs/images/chat-and-update.png)

- 回复里可以带卡片：提问、方案确认、改动回执、主卡同款的图、音视频跟练。
- 回复过程中会显示它正在做什么，比如"看今天的待办""记下你的偏好"。
- 输入框旁有拍照按钮，拍完直接发给它。饭、试纸这类需要拍照记录的待办，点"拍照"也是拍完直接进对话，它看图后记到那条待办上。

### 改动实时可见

P-Health 改页面或待办时，App 只框住正在变的那一块（上图右）：一道白光沿边框走，框里的内容变朦胧。改好后新内容自动换上，不用手动刷新；下拉也可以刷新。

### 数据

- **Apple 健康**：App 上报睡眠、步数、活动能量等，同一台手机重装 App 也只算一次。
- **WHOOP**：通过官方 API 每 15 分钟同步一次（夜里也拉），提供恢复、HRV、睡眠阶段、"需要睡多久"、静息心率、呼吸频率和训练；有新的恢复 / 睡眠 / 训练就马上重排页面。恢复、HRV、静息心率、呼吸频率算到醒来那天。
- **数据断了就如实说**："HRV 只到 10-31"。不拿旧数冒充新数，也不把缺数据当成正常或异常。WHOOP 断了的晚上，睡眠退回 Apple 健康的时长。

## 架构

```mermaid
flowchart LR
  subgraph iPhone
    App["P-Health App<br/>页面 · 待办 · 对话"]
    HK["Apple 健康"]
  end
  subgraph Mac["本机"]
    Server["pivis-health 服务<br/>页面 / 待办 / 图表 / 同步状态 API"]
    Kernel["健康内核<br/>只读数据层 · 睡眠重建 · 个人基线 · 图表计算"]
    Sync["whoop-sync（每 15 分钟）"]
    Agent["P-Health Agent（DSH）<br/>对话 · 每日推荐（早上顺带整理）<br/>页面编排（单独的轻量会话）"]
  end
  WHOOP["WHOOP 官方 API"]
  HK --> App
  App <-->|HTTP| Server
  App <-->|对话流| Agent
  Server --> Kernel
  Agent -->|./pivis-health 命令| Kernel
  Server -->|编排请求| Agent
  WHOOP --> Sync --> Kernel
```

- App 轮询 `/api/v3/status`：数据、页面或待办一变就自动刷新；哪一块正在被改，就框住哪一块。
- 页面编排时，内核把"证据"（各项数值、能画的图、项目和待办）交给 Agent；Agent 回一份页面 JSON，服务器校验后才发布。
- 偏好保存在 `pref.*` 记忆里，页面编排和对话共用同一份。

## 快速使用

```sh
python3 -m pivis_health.cli doctor             # 自检：库是否可读、各数据源最新到哪天
python3 -m pivis_health.cli viz                # 每项指标现在能不能画、在常态还是过了警戒线
python3 -m pivis_health.cli facts              # 页面编排用的证据
python3 -m pivis_health.cli page-v3 now        # 某个板块页的完整内容（now / sleep / sport / stress）
python3 -m pivis_health.cli todo-list          # 今天的待办
python3 -m pivis_health.cli whoop-status       # WHOOP 快照是否新鲜（不联网）
python3 -m pivis_health.cli serve              # 启动服务（默认 127.0.0.1:8943）
```

- 运行只需系统自带 Python 3.9+，不依赖第三方库。跑测试要装 pytest：`python3 -m venv .venv && .venv/bin/pip install pytest && .venv/bin/python -m pytest`。
- 本机路径、地址和凭据都写在 `config.local.json`，这个文件不进仓库。
- 想看演示环境：`python3 examples/make_demo.py <目录> .`，会生成一整套合成数据和配置。

接入 Agent 的方式见 [docs/DSH-INTEGRATION.md](docs/DSH-INTEGRATION.md)，Agent 的规则见 [agent/AGENTS-v3.md](agent/AGENTS-v3.md)。

## 目录

```text
pivis-health/
├── pivis_health/      # 内核与服务
│   ├── readonly.py    #   只读数据层（同一样本跨重装只算一次）
│   ├── sleep.py       #   睡眠重建（双计 / 平行轨防线）
│   ├── baselines.py   #   个人基线
│   ├── whoop.py / whoop_sync.py   # WHOOP 快照解析 / 官方 API 同步
│   ├── viz.py         #   主卡图表计算（7 种画法）
│   ├── todos.py       #   生成式待办与习惯项目
│   ├── v3.py          #   页面证据、编排、校验，同步状态
│   ├── prefs.py / agent_context.py  # 偏好与共享记忆
│   ├── dsh_chat.py    #   和 DSH 上 P-Health 的对话桥
│   └── web.py / cli.py
├── agent/             # P-Health 的规则（AGENTS-v3.md）和技能
├── examples/          # 合成演示数据生成器
├── install/           # 开发版安装页（ipa 不进仓库）
├── scripts/           # 定时编排脚本
├── tests/             # 回归测试（合成数据）
└── docs/              # 架构、隐私、接入说明、截图
```

## 隐私

- 不上传真实健康记录、餐照或试纸照片、聊天记录、设备标识、私人路径、地址或凭据。
- 截图和示例只用明确标注的合成数据，不用"真实记录改名、改日期"得到的样本。
- 详见 [docs/PRIVACY.md](docs/PRIVACY.md)。

**非医疗器械，不用于诊断、治疗、用药或紧急监测，不能替代医生。** 工程上的异常筛选不等于疾病诊断，消费级设备的记录也不等于临床测量。

## 许可证

本仓库自有内容采用 [MIT](LICENSE)。第三方代码、依赖、模型及平台服务遵循各自许可证。
