"""开屏的「反直觉、但是对的」健康观。

每条都有可查的依据，写法守 P-Health 的底线：讲清机制和适用范围，不诊断、不替代医生。
App 每次打开显示一条（共 100 条），点开看解释；和老大正在做的项目（CBT-I、训练、减重……）相关的更常出现，
最近看过的 12 条不重复。
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

# 内容在同目录的 truths.json：100 条，每条有标题、一句话、2–3 段解释、怎么做和出处
TRUTHS: list[dict[str, Any]] = json.loads((Path(__file__).with_name("truths.json")).read_text(encoding="utf-8"))

SEEN_FILE = "truths_seen.json"
KEEP_SEEN = 12


def _interests(cfg) -> set[str]:
    """从老大正在进行的项目推出他现在关心什么：休息板块 → sleep，项目 id 带 cbti → cbti，以此类推。"""
    tags: set[str] = set()
    try:
        from .todos import TodoStore
        for p in TodoStore(cfg).projects(active_only=True):
            text = f"{p.get('id', '')} {p.get('name', '')}".lower()
            tags.add({"sleep": "sleep", "sport": "sport", "stress": "stress", "life": "life"}.get(p.get("board"), ""))
            if "cbti" in text or "cbt-i" in text:
                tags.add("cbti")
            if "weigh" in text or "体重" in text or "减重" in text:
                tags.add("weight")
            if "咖啡" in text or "caffeine" in text:
                tags.add("caffeine")
    except Exception:  # noqa: BLE001 —— 开屏不能因为读项目出错而没有内容
        pass
    tags.discard("")
    return tags


def pick(cfg, rng: random.Random | None = None) -> dict:
    """挑一条：最近看过的 12 条不出；和老大正在做的事相关的权重 ×3。挑中的记进已看列表。"""
    rng = rng or random.Random()
    path = cfg.data_dir / SEEN_FILE
    try:
        seen = [str(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    except Exception:  # noqa: BLE001
        seen = []
    pool = [t for t in TRUTHS if t["id"] not in seen[-KEEP_SEEN:]] or TRUTHS
    interests = _interests(cfg)
    weights = [3 if interests & set(t["tags"]) else 1 for t in pool]
    item = rng.choices(pool, weights=weights, k=1)[0]
    seen = (seen + [item["id"]])[-KEEP_SEEN * 2:]
    try:
        path.write_text(json.dumps(seen), encoding="utf-8")
    except OSError:
        pass
    return {k: item[k] for k in ("id", "topic", "headline", "lead", "body", "do", "sources")}
