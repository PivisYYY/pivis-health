#!/usr/bin/env python3
"""生成 DeepSeek Harness 插件市场索引（格式 1）：dsh/market-index.json。

每发一个版本跑一次（提交并推送之后，用推送上去的提交号）：
    scripts/market_index.py [--commit <40 位提交号>]   # 默认用 HEAD
已有的版本保留，新版本追加在最前面。索引地址（用户在 DSH「发现 › 添加索引源」里填）：
    https://raw.githubusercontent.com/PivisYYY/pivis-health/main/dsh/market-index.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "dsh" / "market-index.json"
GIT_URL = "https://github.com/PivisYYY/pivis-health"


def main() -> int:
    commit = sys.argv[sys.argv.index("--commit") + 1] if "--commit" in sys.argv else \
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    assert len(commit) == 40, "提交号要 40 位"
    pkg = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    versions = [v for v in ((old.get("plugins") or [{}])[0].get("versions") or []) if v.get("version") != pkg["version"]]
    versions.insert(0, {"version": pkg["version"], "publishTimestamp": int(time.time()),
                        "source": {"type": "git", "url": GIT_URL, "commit": commit}})
    index = {
        "format": 1,
        "title": "P-Health",
        "description": "P-Health 的 DeepSeek Harness 插件索引：跑在你自己电脑上的私人健康管家。",
        "plugins": [{
            "name": pkg["name"],
            "title": "P-Health 私人健康管家",
            "description": pkg["description"],
            "icon": "icon.png",
            "author": "PivisYYY",
            "homepage": GIT_URL,
            "repository": {"url": GIT_URL},
            "versions": versions,
        }],
    }
    OUT.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写好了 {OUT.relative_to(REPO)}：{pkg['name']} {pkg['version']} @ {commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
