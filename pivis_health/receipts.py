"""回执兜底（b61）：「记好了 / 改好了」只能说这一轮真的写成功了的事。

以前靠模型自觉：报的体重它说「记下了」，其实只写进了待办；也发过「已记住」回执，那轮一条命令都没跑。
现在：
1. 每个写入命令（context-record、todo-*、project-set、goal-set、meal-log、pain-log、remind-add……）成功后，
   服务器发一个回执编号（receipt_id），记进 receipts.jsonl。
2. 回执卡必须带 `ref`（这一轮写入命令返回的 receipt_id）。card-check 查得到才算 ok。
3. 每轮说完，服务器再对一遍：回执卡没有 ref、或 ref 对不上，记一条开发告警，并让 P-Health 在这个对话里自己更正
   （补做那一步，或者说清楚没做成）。转给它的那句话以【反馈 开头，Psir 的对话记录里不显示。
"""
from __future__ import annotations

import json
import os
import random
import string
import time
from pathlib import Path
from typing import Any

FILE = "receipts.jsonl"
KEEP = 500
FRESH_S = 6 * 3600            # 回执编号多久内有效（一轮对话再长也够）
WRITE_CMDS = {
    "context-record", "todo-add", "todo-update", "todo-remove", "project-set", "goal-set",
    "meal-log", "pain-log", "injury-set", "remind-add", "media-add", "weight-log",
}
AUDIT_PREFIX = "【反馈 · 回执核对】"


def _path(cfg) -> Path:
    return Path(cfg.data_dir) / FILE


def new_id() -> str:
    return "r" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def record(cfg, cmd: str, summary: str = "") -> str:
    rid = new_id()
    row = {"id": rid, "cmd": cmd, "summary": summary[:120], "at": time.time()}
    p = _path(cfg)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if p.stat().st_size > 200_000:
            lines = p.read_text(encoding="utf-8").splitlines()[-KEEP:]
            tmp = p.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            tmp.replace(p)
    except OSError:
        pass
    return rid


def lookup(cfg, rid: str, within_s: float = FRESH_S) -> dict | None:
    if not rid:
        return None
    try:
        lines = _path(cfg).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    now = time.time()
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("id") == rid:
            return row if now - float(row.get("at") or 0) <= within_s else None
    return None


def receipt_problems(cfg, cards: list[tuple[int, Any]]) -> list[str]:
    """回执卡要带 ref，而且 ref 是这几个小时里真的写成功过的回执编号。"""
    probs = []
    for idx, obj in cards:
        if not isinstance(obj, dict) or str(obj.get("type") or "").lower() != "receipt":
            continue
        ref = str(obj.get("ref") or "").strip()
        refs = [r.strip() for r in ref.replace("，", ",").split(",") if r.strip()]
        if not refs:
            probs.append(f"第 {idx} 张回执卡没有 ref：回执只能写这一轮写入命令成功返回的改动，"
                         "把命令输出里的 receipt_id 填进 \"ref\"（几条就用逗号隔开）；没跑写入命令就不发回执，也不说「记下了」")
            continue
        bad = [r for r in refs if lookup(cfg, r) is None]
        if bad:
            probs.append(f"第 {idx} 张回执卡的 ref {'、'.join(bad)} 对不上任何写成功的命令：先把那一步真的做了，"
                         "用命令返回的 receipt_id")
    return probs


def audit_turn(cfg, ctx: str, texts: list[str], send_prompt=None) -> list[str]:
    """一轮说完后核对回执；有问题记告警，并让 P-Health 在这个对话里自己更正。返回问题列表。"""
    from . import cards
    found: list[tuple[int, Any]] = []
    i = 0
    for text in texts:
        for m in cards._BLOCK.finditer(text or ""):
            i += 1
            obj, _err, _fixed = cards.parse(m.group(1).strip())
            found.append((i, obj))
    probs = receipt_problems(cfg, found)
    if not probs:
        return []
    try:
        from . import datastatus
        from datetime import datetime
        datastatus._alert(cfg, f"receipt_unbacked:{ctx or 'main'}:{int(time.time() // 60)}",
                          "P-Health 发了没有写入撑着的回执：" + "；".join(probs)[:200], datetime.now())
    except Exception:  # noqa: BLE001
        pass
    if send_prompt is not None:
        try:
            send_prompt(AUDIT_PREFIX + "你刚才那条回复里的回执，服务器核对不上真的写成功的命令（" + "；".join(probs)[:300]
                        + "）。现在就补做那一步（跑对应命令，用返回的 receipt_id 再发一张回执），"
                          "做不了就直接跟 Psir 说清楚刚才哪件事其实没记上。只回这件事，一两句话。", ctx)
        except Exception:  # noqa: BLE001
            pass
    return probs
