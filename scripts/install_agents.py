#!/usr/bin/env python3
"""把 P-Health 的工作规则装进各个工作区（一条命令做完，免得漏步骤）：

1. 拼出 agent/AGENTS-real.md = agent/AGENTS-v3.md + agent/AGENTS-appendix.local.md（附录含个人信息，不进 git）
2. 每个工作区的 AGENTS.md 先备份成 AGENTS.md.bak-<标签>，再换成新的
3. 在那个工作区跑一次 prefs-sync，把偏好 / 了解到的老大重新写进去（不跑的话，下次记新东西之前所有会话都看不到偏好）

用法：scripts/install_agents.py <备份标签> [--only real,sim,demo,qa] [--dry-run]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
# 工作区：AGENTS.md 位置 + 这个工作区自己的 pivis-health 入口（prefs-sync 要用它自己的配置）
WORKSPACES = {
    "real": (HOME / ".dsh/bot/workspace/p-health/AGENTS.md", HOME / ".dsh/bot/workspace/pivis-health"),
    "sim": (HOME / ".dsh/bot/workspace-sim/AGENTS.md", HOME / ".dsh/bot/workspace-sim/pivis-health"),
    "demo": (HOME / ".dsh/bot/workspace-demo/AGENTS.md", HOME / ".dsh/bot/workspace-demo/pivis-health"),
    "qa": (HOME / ".dsh/bot/workspace-qa/p-health/AGENTS.md", HOME / ".dsh/bot/workspace-qa/p-health/pivis-health"),
}


def build() -> str:
    v3 = (REPO / "agent/AGENTS-v3.md").read_text(encoding="utf-8").rstrip()
    appendix_path = REPO / "agent/AGENTS-appendix.local.md"
    appendix = appendix_path.read_text(encoding="utf-8").strip() if appendix_path.exists() else ""
    text = v3 + ("\n\n---\n\n" + appendix if appendix else "") + "\n"
    (REPO / "agent/AGENTS-real.md").write_text(text, encoding="utf-8")
    return text


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print(__doc__)
        return 2
    tag = sys.argv[1]
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    dry = "--dry-run" in sys.argv
    text = build()
    print(f"AGENTS-real.md: {len(text.encode())} bytes")
    for name, (agents, cli) in WORKSPACES.items():
        if only and name not in only:
            continue
        if not agents.parent.exists():
            print(f"- {name}: 工作区不存在，跳过")
            continue
        backup = agents.with_name(f"AGENTS.md.bak-{tag}")
        if dry:
            print(f"- {name}: 会备份到 {backup.name} 并安装")
            continue
        if agents.exists() and not backup.exists():
            shutil.copy2(agents, backup)
        agents.write_text(text, encoding="utf-8")
        out = subprocess.run([str(cli), "prefs-sync"], capture_output=True, text=True, cwd=str(cli.parent))
        ok = out.returncode == 0 and '"ok": true' in out.stdout
        print(f"- {name}: 已安装（备份 {backup.name}），prefs-sync {'OK' if ok else '失败：' + (out.stdout + out.stderr)[-200:]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
