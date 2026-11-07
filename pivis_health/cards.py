"""对话里 ```phealth-ui 卡片的检查：JSON 能不能解析、App 认不认这个 type、每种卡该有的字段齐不齐。

P-Health 发卡片前跑 `./pivis-health card-check --text '<整条回复>'`；常见的笔误（比如 question 的选项字段
少写了 "options" 键、末尾多一个逗号）会给出改好的 JSON。服务器读对话时也会把坏卡片记进 card_errors.jsonl。"""
from __future__ import annotations

import json
import re
from typing import Any

# App 能画的卡片 type（和 iOS GenCardView 的分支对齐）
CARD_TYPES = {
    "question", "options", "decision", "decisioncard", "rating", "plan", "confirm", "receipt",
    "metric", "stat", "stat_tile", "stattile", "chart", "bar_chart", "groupcompare", "attributionbar",
    "line_chart", "bandline", "list", "table", "datatable", "media", "mediacard", "viz", "layout",
}
FIELD_TYPES = {"options", "multi", "scale", "number", "text", "time"}
CHART_TYPES = {"chart", "bar_chart", "groupcompare", "attributionbar", "line_chart", "bandline"}

_BLOCK = re.compile(r"```phealth-ui(.*?)(```|$)", re.S)
# 常见笔误："type":"options":[…]  → "type":"options","options":[…]
_MISSING_KEY = re.compile(r'"type"\s*:\s*"(options|multi)"\s*:\s*\[')
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def parse(src: str) -> tuple[Any, str | None, str | None]:
    """返回 (对象或 None, 解析错误或 None, 自动修好的 JSON 文本或 None)。"""
    try:
        return json.loads(src, strict=False), None, None
    except json.JSONDecodeError as e:
        err = f"JSON 写坏了：{e.msg}（第 {e.pos} 个字符附近）"
    fixed = _MISSING_KEY.sub(lambda m: f'"type":"{m.group(1)}","options":[', src)
    fixed = _TRAILING_COMMA.sub(r"\1", fixed)
    if fixed != src:
        try:
            obj = json.loads(fixed, strict=False)
            return obj, err, json.dumps(obj, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return None, err, None


def _nonempty_list(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0


def check(card: Any) -> list[str]:
    """一张卡（已解析的对象）有哪些问题；空列表 = 没问题。"""
    if not isinstance(card, dict):
        return ["卡片必须是一个 JSON 对象 {…}"]
    t = str(card.get("type") or "").lower()
    if not t:
        return ["缺 type"]
    if t not in CARD_TYPES:
        return [f"App 画不了 type={t!r}（能用的：question / plan / receipt / metric / chart / viz / list / media / layout …）"]
    probs: list[str] = []
    if t == "question":
        fields = card.get("fields")
        if not _nonempty_list(fields):
            probs.append("question 要有 fields（至少一题）")
        for i, f in enumerate(fields or []):
            if not isinstance(f, dict):
                probs.append(f"第 {i + 1} 题不是对象")
                continue
            ft = str(f.get("type") or "")
            if not f.get("id"):
                probs.append(f"第 {i + 1} 题缺 id")
            if ft not in FIELD_TYPES:
                probs.append(f"第 {i + 1} 题 type={ft!r} 不认识（只能是 {' / '.join(sorted(FIELD_TYPES))}）")
            if ft in ("options", "multi") and not _nonempty_list(f.get("options")):
                probs.append(f"第 {i + 1} 题是选择题，要写 \"options\":[…]（现在没有选项）")
            if ft == "scale" and (f.get("min") is None or f.get("max") is None):
                probs.append(f"第 {i + 1} 题是打分题，要写 min 和 max")
    elif t in ("options", "decision", "decisioncard", "rating"):
        if not _nonempty_list(card.get("options")):
            probs.append(f"{t} 卡要写 \"options\":[…]")
    elif t == "plan":
        if not card.get("title"):
            probs.append("plan 卡缺 title")
        if not _nonempty_list(card.get("items")):
            probs.append("plan 卡要有 items")
    elif t == "receipt":
        if not card.get("change"):
            probs.append("receipt 卡缺 change（改了什么）")
    elif t in ("metric", "stat", "stat_tile", "stattile"):
        if card.get("value") in (None, ""):
            probs.append(f"{t} 卡缺 value")
    elif t in CHART_TYPES:
        pts = card.get("points")
        if not _nonempty_list(pts):
            probs.append("chart 卡要有 points")
        elif any(not isinstance(p, dict) or not isinstance(p.get("value"), (int, float)) for p in pts):
            probs.append("points 里每个点要有数字 value")
    elif t == "list":
        if not _nonempty_list(card.get("items")):
            probs.append("list 卡要有 items")
    elif t in ("table", "datatable"):
        if not (_nonempty_list(card.get("rows")) or _nonempty_list(card.get("columns"))):
            probs.append("table 卡要有 rows / columns")
    elif t in ("media", "mediacard"):
        url = str(card.get("url") or "")
        if not url or url.startswith("<"):
            probs.append("media 卡的 url 还是空的 / 占位符：先在 media-library 里找到真的地址")
        elif not (url.startswith("http://") or url.startswith("https://") or url.startswith("/media/")):
            probs.append("media 的 url 要是 http(s):// 或 /media/ 开头")
    elif t == "viz":
        if not card.get("metric"):
            probs.append("viz 卡缺 metric")
    elif t == "layout":
        from . import canvas
        try:
            canvas.validate(card, "chat")
        except canvas.CanvasError as e:
            probs.append(f"layout 不合规范：{e}")
    return probs


def check_text(text: str) -> dict:
    """检查一整条回复里的所有卡片。"""
    cards = []
    for i, m in enumerate(_BLOCK.finditer(text or "")):
        src, closing = m.group(1), m.group(2)
        item: dict[str, Any] = {"index": i + 1}
        if closing != "```":
            item.update(ok=False, problems=["卡片代码块没有用 ``` 收尾"])
            cards.append(item)
            continue
        obj, err, fixed = parse(src.strip())
        if obj is None:
            item.update(ok=False, problems=[err or "JSON 写坏了"])
        else:
            probs = check(obj)
            item["type"] = str(obj.get("type") or "") if isinstance(obj, dict) else ""
            if err:      # 自动修好了：把修好的给回去，照着改
                probs = [err + "，已按常见笔误修好，用 fixed 里的 JSON 替换这张卡"] + probs
                item["fixed"] = fixed
            item.update(ok=not probs, problems=probs)
        cards.append(item)
    return {"ok": all(c["ok"] for c in cards), "cards": cards, "count": len(cards)}


_logged: set[str] = set()


def log_broken(data_dir, messages: list[dict]) -> int:
    """服务器读对话时：P-Health 回复里有坏卡片就记一笔（每条只记一次），方便看笔误还多不多。返回新记了几条。"""
    from datetime import datetime
    from pathlib import Path
    n = 0
    for m in messages or []:
        text = m.get("text") or ""
        if m.get("role") != "phealth" or "phealth-ui" not in text:
            continue
        key = f"{m.get('time')}|{hash(text)}"
        if key in _logged:
            continue
        _logged.add(key)
        res = check_text(text)
        bad = [c for c in res["cards"] if not c["ok"]]
        if not bad:
            continue
        rec = {"at": datetime.now().isoformat(timespec="seconds"), "message_time": m.get("time"),
               "problems": [{"index": c["index"], "type": c.get("type", ""), "problems": c["problems"],
                             "auto_fixable": bool(c.get("fixed"))} for c in bad]}
        try:
            with open(Path(data_dir) / "card_errors.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
        except OSError:
            pass
    return n
