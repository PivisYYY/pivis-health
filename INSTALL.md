# 安装 P-Health（DeepSeek Harness 插件）

P-Health 跑在**你自己的 Mac** 上：健康数据、对话、记忆都只在这台电脑里。iPhone 上的 App 扫码连到这台电脑。

需要：一台 macOS 的电脑，装好 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 并登录好模型账号；一部 iPhone（iOS 18 以上）。

## 最快的装法：让 DeepSeek Harness 帮你装

在 DeepSeek Harness 里新开一个对话，把下面这句话发给它：

> 帮我安装 P-Health：先运行 `dsh plugin --profile phealth add github:PivisYYY/pivis-health`，再运行 `~/.dsh/profiles/phealth/node_modules/dsh-plugin-phealth/bin/phealth setup`，最后把出现的二维码给我。

它会问你 P-Health 怎么称呼你，跑完会给你一个二维码。

## 自己在终端里装

```sh
dsh plugin --profile phealth add github:PivisYYY/pivis-health
~/.dsh/profiles/phealth/node_modules/dsh-plugin-phealth/bin/phealth setup --nickname 老大
```

`dsh` 在 `/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh`；没在 PATH 里就用完整路径。

`phealth setup` 会：

- 在 `~/PHealth` 建好数据目录、空的健康数据库和配置（随机生成这台电脑的访问密钥）
- 建一个 P-Health 专用的 DSH profile（`phealth`），和你平时用的 DSH 分开；只有这个 profile 不弹审批（App 里没法点审批），能写的只有 `~/PHealth` 和缓存
- 装好后台任务（`com.phealth.*`）：P-Health 服务器（8943）、DSH web（8960）、提醒、每天三次推荐和页面编排、洞察
- 打印配对二维码

可以重复跑，数据和密钥会沿用。不需要 sudo。

## 装 App、扫码配对

1. 在 iPhone 上打开 TestFlight 公开链接（见 README「安装」），装 P-Health。
2. 打开 App，点「扫码配对」，扫电脑上的二维码（用相机扫也行）。
3. 手机要和这台电脑在同一个 Wi-Fi；出门在外用 [Tailscale](https://tailscale.com)（电脑和手机登同一个账号）。

二维码找不到了：在电脑上运行 `~/.dsh/profiles/phealth/node_modules/dsh-plugin-phealth/bin/phealth pair`，或在这台电脑的浏览器打开 <http://127.0.0.1:8943/pair>。二维码里有这台电脑的访问密钥，不要发给别人。

## 可选：WHOOP

没有 WHOOP 也能用（Apple 健康的数据由 App 传）。有 WHOOP 的话：

1. 在 [WHOOP 开发者后台](https://developer.whoop.com) 建一个应用，回调地址填 `http://127.0.0.1:8765/callback`。
2. `~/PHealth/workspace/pivis-health whoop-auth`，按提示输入 Client ID / Secret 并在浏览器里登录。
3. `.../bin/phealth setup --whoop` 加上每 15 分钟同步。

## 和开发者自己用的版本有什么不同

- **锁屏推送**：推送要用开发者 Apple 账号的密钥，不能放进开源插件。你这边的提醒由 App 在手机上定时提醒（待办到点前、到点），P-Health 的新回复在打开 App 时看到。
- **跟练视频**（把博主视频剪成跟练片）依赖开发者本机的工具，插件版暂时没有。

## 卸载

```sh
~/.dsh/profiles/phealth/node_modules/dsh-plugin-phealth/bin/phealth setup --uninstall   # 停掉后台任务
dsh plugin --profile phealth remove dsh-plugin-phealth
rm -rf ~/PHealth   # 连数据一起删（删了找不回）
```

## 出问题时（给帮你安装的 Agent 看）

- `找不到 DeepSeek Harness`：先装 DeepSeek Harness.app。
- `装插件失败`：看输出；网络问题重试；GitHub 连不上可以先 `git clone` 到本地再 `dsh plugin --profile phealth add <本地目录>`。
- 服务器没起来：看 `~/PHealth/logs/server.err.log`；端口被占用就 `phealth setup --api-port 9943 --dsh-port 9960`。
- DSH 没起来：看 `~/PHealth/logs/dshweb.log`；确认 DeepSeek Harness 能正常对话（模型账号已登录）。
- 手机连不上：手机和电脑是否同一个 Wi-Fi；macOS「系统设置 › 网络 › 防火墙」是否拦了 Python；App 第一次连接时要允许「本地网络」权限。
