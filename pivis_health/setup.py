"""一条命令装好 P-Health（build 55，DeepSeek Harness 插件）：别人在自己的 Mac 上装，数据都在自己电脑上。

./bin/phealth setup [--home ~/PHealth] [--nickname 老大] [--api-port 8943] [--dsh-port 8960] [--profile phealth]

做的事（都可以重复跑，已有的不覆盖数据）：
1. 目录：<home>/runtime（数据）、vault/health.sqlite3（空的健康库）、whoop/、whoop-auth/（0700）、workspace/（P-Health 的 DSH 工作区）
2. 配置 <home>/config.json（0600）：路径、本机时区、端口、随机生成的设备密钥（配对时给 App）
3. 工作区：AGENTS.md（P-Health 规则，称呼换成 --nickname）、./pivis-health 入口
4. DSH：P-Health 专用的 profile（默认 phealth，带 web 界面 + 本插件），和你平时用的 DSH 分开
5. 后台任务（launchd，标签 com.phealth.*）：P-Health 服务器、DSH web、提醒兜底、手机事件、每天三次推荐和编排、洞察
6. 配对：终端里打印二维码，<home>/runtime/pair.html 也有一份；App 扫码即连
不需要 sudo，不改你平时用的 DSH profile，不碰别的 launchd 任务。
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent          # 插件目录（仓库根）
DSH_APP = Path("/Applications/DeepSeek Harness.app/Contents/Resources/runtime")
VAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, batch_digest TEXT NOT NULL, acknowledgement_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence_outbox (batch_id TEXT PRIMARY KEY REFERENCES batches(batch_id), acknowledgement_json TEXT NOT NULL, evidence_timestamp TEXT);
CREATE TABLE IF NOT EXISTS projection_outbox (local_date TEXT PRIMARY KEY, generation INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tombstones (device_id TEXT NOT NULL, sample_id TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(batch_id), PRIMARY KEY (device_id, sample_id));
CREATE TABLE IF NOT EXISTS samples (device_id TEXT NOT NULL, sample_id TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(batch_id),
  type TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL, unit TEXT NOT NULL, numeric_value REAL, category_value TEXT,
  PRIMARY KEY (device_id, sample_id));
"""


def say(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- 找环境
def python_bin() -> str:
    """优先用 DSH 自带的 Python（3.12，不依赖 Xcode 命令行工具），没有再用系统的。"""
    for p in sorted((DSH_APP / "primary-runtime/dependencies/python/bin").glob("python3.1*")) if DSH_APP.exists() else []:
        if re.fullmatch(r"python3\.\d+", p.name) and os.access(p, os.X_OK):
            return str(p)
    for p in ("/usr/bin/python3", shutil.which("python3") or ""):
        if p and os.access(p, os.X_OK):
            return p
    raise SystemExit("找不到 Python：先装好 DeepSeek Harness（自带 Python），或装 Xcode 命令行工具")


def dsh_bin() -> str:
    p = DSH_APP / "cli/bin/dsh"
    if p.exists():
        return str(p)
    found = shutil.which("dsh")
    if found:
        return found
    raise SystemExit("找不到 DeepSeek Harness：先从官网装好 DeepSeek Harness.app")


def local_timezone() -> str:
    try:
        target = os.readlink("/etc/localtime")
        m = re.search(r"zoneinfo/(.+)$", target)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "Asia/Shanghai"


# ---------------------------------------------------------------- 文件
def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def make_dirs(home: Path) -> dict:
    d = {"home": home, "runtime": home / "runtime", "vault": home / "vault", "whoop": home / "whoop",
         "whoop_auth": home / "whoop-auth", "workspace": home / "workspace", "logs": home / "logs"}
    for k, p in d.items():
        p.mkdir(parents=True, exist_ok=True)
    os.chmod(d["whoop_auth"], 0o700)
    os.chmod(home, 0o700)
    return d


def make_vault(path: Path) -> bool:
    new = not path.exists()
    con = sqlite3.connect(path)
    try:
        con.executescript(VAULT_SCHEMA)
        con.commit()
    finally:
        con.close()
    path.chmod(0o600)
    return new


def write_config(home: Path, d: dict, api_port: int, dsh_port: int) -> dict:
    path = home / "config.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cfg = {
        "vault_db": str(d["vault"] / "health.sqlite3"),
        "whoop_snapshot": str(d["whoop"] / "whoop-snapshot.json"),
        "whoop_auth_dir": str(d["whoop_auth"]),
        "data_dir": str(d["runtime"]),
        "timezone": old.get("timezone") or local_timezone(),
        "dsh_web": f"http://127.0.0.1:{dsh_port}",
        "api_port": api_port,
        "follow_enabled": False,
        "app_key": old.get("app_key") or secrets.token_urlsafe(24),   # 已有就沿用：手机不用重新配对
    }
    for k in ("fixed_wake_time", "morning_time", "apns", "insight_push"):
        if k in old:
            cfg[k] = old[k]
    _write_private(path, json.dumps(cfg, ensure_ascii=False, indent=1))
    return cfg


def env_for(home: Path, d: dict, cfg: dict, nickname: str, session_prefix: str = "") -> dict:
    env = {
        "PYTHONPATH": str(CODE),
        "PIVIS_HEALTH_CONFIG": str(home / "config.json"),
        "PIVIS_DSH_CWD": str(d["workspace"]),
        "PIVIS_DSH_LOG": str(d["logs"] / "dshweb.log"),
        "PIVIS_HEALTH_TZ": cfg["timezone"],
        "PHEALTH_HOME": str(home),
        "PHEALTH_CODE": str(CODE),
        "PHEALTH_NICK": nickname,
        "PHEALTH_PY": python_bin(),
    }
    if session_prefix:          # 同一个 DSH 里装第二套（测试）时，会话名加前缀，免得和第一套串到一起
        env["PIVIS_DSH_PREFIX"] = session_prefix
    return env


def write_wrapper(d: dict, env: dict) -> Path:
    """工作区里的 ./pivis-health：P-Health 在对话里跑的所有命令都经过它（带上这套环境的配置）。"""
    lines = ["#!/bin/sh", "# P-Health 命令入口（setup 生成，别手改；重跑 setup 会覆盖）"]
    lines += [f"export {k}={json.dumps(v, ensure_ascii=False)}" for k, v in env.items()]
    lines += [f'exec "$PHEALTH_PY" -m pivis_health.cli "$@"', ""]
    p = d["workspace"] / "pivis-health"
    p.write_text("\n".join(lines), encoding="utf-8")
    p.chmod(0o755)
    return p


def render_agents(nickname: str) -> str:
    """AGENTS.md：P-Health 规则（开源那份，不带任何个人附录），「老大」换成用户自己的称呼。"""
    text = (CODE / "agent/AGENTS-v3.md").read_text(encoding="utf-8")
    if nickname and nickname != "老大":
        text = text.replace("老大", nickname)
    # 规则里写死的开发机路径换成插件目录
    return text.replace("~/Tools/pivis-health", str(CODE))


def install_agents(d: dict, nickname: str, wrapper: Path) -> None:
    md = d["workspace"] / "AGENTS.md"
    if md.exists():
        shutil.copy2(md, md.with_name("AGENTS.md.bak-setup"))
    md.write_text(render_agents(nickname), encoding="utf-8")
    subprocess.run([str(wrapper), "prefs-sync"], cwd=str(d["workspace"]), capture_output=True, text=True)


# ---------------------------------------------------------------- DSH profile
PROFILE_MARK = "# phealth-setup-profile v1"


def default_model_row(dsh_home: Path) -> str:
    """用户平时那份 DSH profile 里「默认模型」那一行原样抄过来：他用账号登录就走账号，用 API Key 就走 API Key
    （凭证本身存在 DSH 主目录，各 profile 共用；只是每个 profile 要说明用哪个）。找不到就不写，用 DSH 的默认。"""
    for name in ("desktop", "web", "tui", "headless"):
        f = dsh_home / "profiles" / name / "cordis.patch.yml"
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"^- id: agent-default-model\n(?:(?:[ \t]+.*|)\n)*?(?=^- |^#|\Z)", text, re.M)
        if m and "provider:" in m.group(0):
            return f"# 默认模型：抄自你的「{name}」profile\n" + m.group(0).rstrip() + "\n"
    return ""


def profile_patch(home: Path, dsh_home: Path | None = None) -> str:
    """P-Health 专用 profile 自己的配置层：沙箱只能写 P-Health 的目录和缓存，不弹审批（App 里没法点审批）。
    只写在这个 profile 里，不影响用户平时用的 DSH。"""
    h = Path.home()
    return f"""{PROFILE_MARK}
# P-Health 专用 profile（phealth setup 生成；重跑 setup 不会覆盖带这行标记的文件，你的改动加在后面）。
# P-Health 在 App 里对话时没人能点审批，所以这个 profile 不弹审批；能写的只有工作区、P-Health 的目录和缓存。
- id: sandbox-policy
  name: '@deepseek-ai/dsh-sandbox-policy'
  config:
    mode: workspace-write
    workspaceRoot: !!js process.cwd()
    additionalWritableRoots:
      - {home}
      - {h / '.cache'}
      - {h / 'Library/Caches'}
- id: approval
  name: '@deepseek-ai/dsh-user-approval'
  config:
    policy: never
- id: permission
  name: '@deepseek-ai/dsh-permission-presets'
  config:
    presets:
      read-only:
        sandbox: read-only
        approval: ask
      workspace-write:
        sandbox: workspace-write
        approval: never
      danger-full-access:
        sandbox: danger-full-access
        approval: never
    defaultPreset: workspace-write
""" + (default_model_row(dsh_home) if dsh_home else "")
def installed_spec(name: str) -> str | None:
    """这份代码是装在别的 profile 里的（从插件市场装进你平时用的 DSH）：照那里记的来源（GitHub 地址 + 提交号）
    再装一份进 P-Health 专用 profile，不链接到别的 profile 的目录（那边删了这边就坏了）。"""
    parts = CODE.parts
    if "node_modules" not in parts:
        return None
    pdir = Path(*parts[:parts.index("node_modules")])
    try:
        deps = json.loads((pdir / "package.json").read_text(encoding="utf-8")).get("dependencies") or {}
    except (OSError, ValueError):
        return None
    src = deps.get(name)
    if not src or src.startswith(("link:", "file:")):
        return None
    return src if (":" in src or "/" in src) else f"{name}@{src}"


def ensure_profile(dsh_home: Path, profile: str, spec: str | None, home: Path) -> Path:
    """P-Health 专用的 DSH profile：web 界面 + 本插件。已经有就只确认插件在里面。"""
    pdir = dsh_home / "profiles" / profile
    pdir.mkdir(parents=True, exist_ok=True)
    pkg = pdir / "package.json"
    if not pkg.exists():
        pkg.write_text(json.dumps({"name": f"dsh-profile-{profile}", "private": True, "dependencies": {},
                                   "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]}}},
                                  indent=2) + "\n", encoding="utf-8")
        (pdir / "pnpm-workspace.yaml").write_text("packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n", encoding="utf-8")
        (pdir / "cordis.yml").write_text("# P-Health 专用 profile（setup 生成）：组合包见 package.json，改配置写 cordis.patch.yml\n[]\n", encoding="utf-8")
    patch = pdir / "cordis.patch.yml"
    if not patch.exists() or PROFILE_MARK not in patch.read_text(encoding="utf-8"):
        if patch.exists():
            shutil.copy2(patch, patch.with_name("cordis.patch.yml.bak-setup"))
        patch.write_text(profile_patch(home, dsh_home), encoding="utf-8")
    bundles = json.loads(pkg.read_text(encoding="utf-8"))["dsh"]["profile"]["bundles"]
    name = json.loads((CODE / "package.json").read_text(encoding="utf-8"))["name"]
    if name not in bundles:
        target = spec or installed_spec(name) or str(CODE)
        say(f"· 把 P-Health 插件装进 DSH profile「{profile}」…")
        env = {**os.environ, "DSH_HOME": str(dsh_home)}
        r = subprocess.run([dsh_bin(), "plugin", "--profile", profile, "add", target], env=env,
                           capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise SystemExit("装插件失败：\n" + (r.stdout + r.stderr)[-1500:])
    return pdir


# ---------------------------------------------------------------- launchd
def _plist(label: str, args: list[str], env: dict, log: Path, cwd: Path, interval: int | None = None,
           calendar: list[dict] | None = None, keepalive: bool = False) -> dict:
    p = {"Label": label, "ProgramArguments": args, "EnvironmentVariables": {**env, "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"},
         "WorkingDirectory": str(cwd), "StandardOutPath": str(log), "StandardErrorPath": str(log.with_suffix(".err.log")),
         "RunAtLoad": True}
    if keepalive:
        p["KeepAlive"] = True
        p["ThrottleInterval"] = 10
    if interval:
        p["StartInterval"] = interval
    if calendar:
        p["StartCalendarInterval"] = calendar
    return p


def jobs(home: Path, d: dict, env: dict, cfg: dict, profile: str, dsh_home: Path, prefix: str, whoop: bool) -> dict[str, dict]:
    py = env["PHEALTH_PY"]
    logs = d["logs"]
    cli = [py, "-m", "pivis_health.cli"]
    out = {
        f"{prefix}.server": _plist(f"{prefix}.server", cli + ["serve", "--host", "0.0.0.0", "--port", str(cfg["api_port"])],
                                   env, logs / "server.log", CODE, keepalive=True),
        # DSH web 只听本机（它能跑命令，DSH 自己也不许监听所有网卡）；手机经 P-Health 服务器的 /dshp 转发、凭设备密钥进来。
        # 它的输出里有登录 token（服务器从这份日志读），所以日志单独一份
        f"{prefix}.dshweb": _plist(f"{prefix}.dshweb", [dsh_bin(), profile, "--host", "127.0.0.1",
                                                        "--port", cfg["dsh_web"].rsplit(":", 1)[1], "--no-open"],
                                   {**env, "DSH_HOME": str(dsh_home)}, Path(env["PIVIS_DSH_LOG"]), d["workspace"], keepalive=True),
        f"{prefix}.notify": _plist(f"{prefix}.notify", cli + ["notify-tick"], env, logs / "notify.log", CODE, interval=60),
        f"{prefix}.events": _plist(f"{prefix}.events", cli + ["agent-events-dispatch", "--limit", "20"], env, logs / "events.log", CODE, interval=30),
        f"{prefix}.cycle": _plist(f"{prefix}.cycle", ["/bin/sh", str(CODE / "scripts/v3-cycle.sh")], env, logs / "cycle.log", CODE,
                                  calendar=[{"Minute": 0}]),
        f"{prefix}.insight": _plist(f"{prefix}.insight", ["/bin/sh", str(CODE / "scripts/insight-cycle.sh")], env, logs / "insight.log", CODE,
                                    calendar=[{"Minute": 30}]),
    }
    if whoop:
        out[f"{prefix}.whoop"] = _plist(f"{prefix}.whoop", cli + ["whoop-sync"], env, logs / "whoop.log", CODE, interval=900)
    return out


def install_jobs(plists: dict[str, dict]) -> list[str]:
    la = Path.home() / "Library/LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    uid = os.getuid()
    done = []
    for label, p in plists.items():
        path = la / f"{label}.plist"
        path.write_bytes(plistlib.dumps(p))
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
        for _ in range(5):          # 刚 bootout 的任务还没完全退出时 bootstrap 会报 5: Input/output error，等一下再试
            r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], capture_output=True, text=True)
            if r.returncode == 0:
                break
            time.sleep(1.5)
        done.append(f"{label}{'' if r.returncode == 0 else '（启动失败：' + r.stderr.strip()[:80] + '）'}")
    return done


def uninstall_jobs(prefix: str) -> list[str]:
    la = Path.home() / "Library/LaunchAgents"
    uid = os.getuid()
    gone = []
    for path in sorted(la.glob(f"{prefix}.*.plist")):
        label = path.stem
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
        path.unlink()
        gone.append(label)
    return gone


# ---------------------------------------------------------------- 检查
def wait_ready(api_port: int, key: str, log: Path, timeout: float = 90) -> dict:
    """等服务器和 DSH web 起来：服务器 /api/v3/hello 回话、DSH 日志里出现登录 token。"""
    deadline = time.time() + timeout
    state = {"server": False, "dsh": False}
    while time.time() < deadline and not all(state.values()):
        if not state["server"]:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{api_port}/api/v3/hello", headers={"X-Pivis-Key": key})
                with urllib.request.urlopen(req, timeout=3) as r:
                    state["server"] = json.loads(r.read()).get("ok") is True
            except Exception:  # noqa: BLE001
                pass
        if not state["dsh"]:
            try:
                state["dsh"] = "token=" in log.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
        if not all(state.values()):
            time.sleep(2)
    return state


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="phealth setup", description=__doc__.split("\n")[0])
    ap.add_argument("--home", default=os.environ.get("PHEALTH_HOME") or str(Path.home() / "PHealth"))
    ap.add_argument("--nickname", default=None, help="P-Health 怎么称呼你（默认「老大」，重跑时沿用上次的）")
    ap.add_argument("--api-port", type=int, default=8943)
    ap.add_argument("--dsh-port", type=int, default=8960)
    ap.add_argument("--profile", default="phealth", help="P-Health 专用的 DSH profile 名")
    ap.add_argument("--dsh-home", default=os.environ.get("DSH_HOME") or str(Path.home() / ".dsh"))
    ap.add_argument("--spec", default=None, help="装插件用的地址（默认就是当前这份代码）")
    ap.add_argument("--label-prefix", default="com.phealth")
    ap.add_argument("--session-prefix", default="", help="同一个 DSH 里装第二套时给会话名加前缀（测试用）")
    ap.add_argument("--whoop", action="store_true", help="已经用 whoop-auth 登录过 WHOOP：加上每 15 分钟同步")
    ap.add_argument("--no-launchd", action="store_true", help="只准备文件，不装后台任务（测试用）")
    ap.add_argument("--uninstall", action="store_true", help="停掉并删除 P-Health 的后台任务（数据和配置留着）")
    a = ap.parse_args(argv)
    if a.uninstall:
        gone = uninstall_jobs(a.label_prefix)
        say("已停掉：" + ("、".join(gone) if gone else "（没有 P-Health 后台任务）") + f"\n数据还在 {a.home}，要彻底删除就删掉那个文件夹。")
        return 0
    home = Path(a.home).expanduser()
    dsh_home = Path(a.dsh_home).expanduser()
    say(f"P-Health 安装到 {home}")
    d = make_dirs(home)
    if make_vault(d["vault"] / "health.sqlite3"):
        say("· 建好了空的健康数据库")
    cfg = write_config(home, d, a.api_port, a.dsh_port)
    nick_file = home / "nickname"
    nickname = a.nickname or (nick_file.read_text(encoding="utf-8").strip() if nick_file.exists() else "") or "老大"
    nick_file.write_text(nickname + "\n", encoding="utf-8")
    env = env_for(home, d, cfg, nickname, a.session_prefix)
    wrapper = write_wrapper(d, env)
    install_agents(d, nickname, wrapper)
    say(f"· 工作区和规则：{d['workspace']}（称呼：{nickname}）")
    ensure_profile(dsh_home, a.profile, a.spec, home)
    say(f"· DSH profile「{a.profile}」就绪")
    if a.no_launchd:
        say("· 跳过后台任务（--no-launchd）")
    else:
        started = install_jobs(jobs(home, d, env, cfg, a.profile, dsh_home, a.label_prefix, a.whoop))
        say("· 后台任务：" + "、".join(started))
        st = wait_ready(cfg["api_port"], cfg["app_key"], Path(env["PIVIS_DSH_LOG"]))
        say(f"· 服务器 {'已就绪' if st['server'] else '还没起来（看 ' + str(d['logs'] / 'server.err.log') + '）'}；"
            f"DSH {'已就绪' if st['dsh'] else '还没起来（看 ' + env['PIVIS_DSH_LOG'] + '）'}")
    from .config import load_config
    from . import pairing
    c = load_config(str(home / "config.json"))
    files = pairing.write_files(c)
    url = pairing.pair_url(c)
    say("\n用 iPhone 上的 P-Health 扫这个码配对（或用相机扫）：\n")
    say(pairing.terminal(url))
    say(f"\n也可以在这台电脑的浏览器里打开 http://127.0.0.1:{cfg['api_port']}/pair（或 {files['html']}）")
    say("App 还没装：在 iPhone 上打开 TestFlight 公开链接（见 README）。手机要和这台电脑在同一个 Wi-Fi，出门在外用 Tailscale。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
