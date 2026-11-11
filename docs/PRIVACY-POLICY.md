# P-Health 隐私政策 / Privacy Policy

最后更新：2026-11-11

## 中文

P-Health 是开源软件。App 只和**你自己电脑上**运行的 P-Health 服务（DeepSeek Harness 插件）通信，开发者不运营任何收集你数据的服务器。

**App 读取并发送到你自己电脑的数据**：Apple 健康里的睡眠、步数、活动能量、心率等（需你授权）；你在 App 里记录的待办、饭的照片、对话；用于判断在家 / 外出的位置和蓝牙信息（需你授权）。这些数据只存在你自己的电脑上，由你电脑上的 P-Health 和你自己配置的 DeepSeek Harness 模型处理。

**发往第三方的数据**：只有你在自己电脑上配置的服务——你选择的大模型服务（DeepSeek Harness 里登录的账号或 API Key），以及你自己授权的 WHOOP。开发者收不到你的任何数据。

**推送**：开发者自己的电脑使用 Apple 推送服务；其他用户的提醒由手机本地安排，不经过开发者。

**演示模式**：使用 App 内置的合成数据，不联网。

**删除数据**：在电脑上删除 `~/PHealth` 文件夹即可删除全部数据；在 iPhone 上删除 App 即删除手机上的缓存。

**联系**：在 GitHub 仓库 https://github.com/PivisYYY/pivis-health 提 Issue（请勿在公开 Issue 里贴健康数据）。

## English

P-Health is open-source software. The app talks only to the P-Health service running **on your own computer** (a DeepSeek Harness plugin). The developer runs no server that collects your data.

**Data the app reads and sends to your own computer**: sleep, steps, active energy, heart rate and similar Apple Health data (with your permission); todos, meal photos and chats you enter in the app; location and Bluetooth signals used to tell home from away (with your permission). This data is stored only on your computer and processed by P-Health and the language model you configured in DeepSeek Harness.

**Data sent to third parties**: only services you configure on your own computer — the language-model provider you signed in to in DeepSeek Harness, and WHOOP if you authorize it. The developer receives none of your data.

**Notifications**: the developer's own computer uses Apple Push Notification service; for everyone else, reminders are scheduled locally on the phone and never pass through the developer.

**Demo mode** uses synthetic sample data built into the app and makes no network requests.

**Deleting data**: delete the `~/PHealth` folder on your computer to remove all data; deleting the app removes its cache on the phone.

**Contact**: open an issue at https://github.com/PivisYYY/pivis-health (please do not post health data in public issues).
