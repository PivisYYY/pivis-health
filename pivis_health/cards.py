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
    "line_chart", "bandline", "list", "table", "datatable", "media", "mediacard", "viz", "layout", "sticker",
}
# 表情包：24 个 Q 版线条表情，和 ios/PivisHealth/Stickers.json 对齐（scripts/stickers 生成，名字改了两边一起改）
STICKERS = (
    "早安", "晒晒太阳", "歇一会", "该睡了", "晚安", "放下手机",           # 作息
    "又守住了", "干得漂亮", "太棒了", "比心", "好耶", "进步了",           # 夸夸
    "抱抱", "辛苦了", "摸摸头", "我在呢", "慢慢来", "加油",               # 陪伴
    "喝水", "动一动", "深呼吸", "好好吃饭", "收到", "记下了",             # 提醒
)
# 卡片外的 emoji：一条最多 2 个，只用这 8 个（Psir 11-11：回复要亲切、生动些）；不算进 60 字
EMOJI_OK = ("☀️", "🌙", "👏", "💪", "🫂", "✨", "💧", "🚶")
EMOJI_MAX = 2
_EMOJI = re.compile("(?:[\U0001F300-\U0001FAFF\u2600-\u26FF\u2702-\u2712\u2719-\u27BF\u2B50\u2B55"
                    "\u23F0-\u23FA\u231A\u231B](?:\uFE0F)?(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF](?:\uFE0F)?)*)")
# 说到就医、急救时不用 emoji 和表情包
_SERIOUS = re.compile(r"打\s*120|拨打\s*120|120\s*急救|急诊|马上就医|立刻就医|尽快就医|去医院")
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
        else:
            from .media import MediaError, check_url
            try:
                check_url(url)        # 和待办同一套：不用 YouTube、网盘、内网地址
            except MediaError as exc:
                probs.append(f"media 的 url 不能用：{exc}")
    elif t == "viz":
        if not card.get("metric"):
            probs.append("viz 卡缺 metric")
    elif t == "sticker":
        name = str(card.get("name") or "").strip()
        if name not in STICKERS:
            probs.append(f"表情包 name={name!r} 没有这个（只能用：{'、'.join(STICKERS)}）")
    elif t == "layout":
        from . import canvas
        try:
            canvas.validate(card, "chat")
        except canvas.CanvasError as e:
            probs.append(f"layout 不合规范：{e}")
    return probs


# 开头附和 / 夸问题（b60 导师立场：第一句直接给判断）
_OPENER = re.compile(r"\s*(你说得对|说得对|没错|你说的没错|问得对|问得好|抓得准|你抓对了)")
OUTSIDE_MAX = 60       # 卡片外最多 60 字（AGENTS 4.6：只说结论和下一步，其余放进卡里）
# 做 CBT-I 时不说的话：睡眠债一类（CBT-I 没有这个概念，前两周少睡是方案本身）；「不补觉」这种劝阻不算
_DEBT_WORDS = re.compile(r"睡眠债|欠觉|欠的觉|(?<!不)(?<!别)补觉|需要\s*\d+(?:\.\d+)?\s*(?:个)?(?:小时|h)|"
                         r"差\s*\d+(?:\.\d+)?\s*(?:个)?(?:小时|h)|比需要的?少|该睡\s*\d")


def outside_text(text: str) -> str:
    """卡片外的文字（去掉卡片代码块、Markdown 记号和 emoji：emoji 不算字数）"""
    t = _BLOCK.sub("", text or "")
    t = _EMOJI.sub("", t).replace("\ufe0f", "")
    t = re.sub(r"[*_`#>\-]+", "", t)
    return re.sub(r"\s+", "", t)


def _emoji_problems(text: str, cards: list[tuple[int, Any]], sticker_at: list[int], blocks: list) -> list[str]:
    """emoji 和表情包的分寸：emoji 最多 2 个、只用那 8 个、不进卡片；表情包最多 1 个、放最后；说到就医时都不用。"""
    probs: list[str] = []
    outside = _BLOCK.sub("", text or "")
    found = [m.group(0) for m in _EMOJI.finditer(outside)]
    if len(found) > EMOJI_MAX:
        probs.append(f"emoji 用了 {len(found)} 个（一条最多 {EMOJI_MAX} 个，放句尾）")
    ok = {e.replace("\ufe0f", "") for e in EMOJI_OK}
    bad = sorted({e for e in found if e.replace("\ufe0f", "") not in ok})
    if bad:
        probs.append(f"emoji 只用这 8 个：{' '.join(EMOJI_OK)}（这里用了 {' '.join(bad)}）")
    for idx, obj in cards:
        if isinstance(obj, dict) and str(obj.get("type") or "").lower() != "sticker" \
                and _EMOJI.search(json.dumps(obj, ensure_ascii=False)):
            probs.append(f"第 {idx} 张卡里有 emoji：卡片里面不放 emoji，要放就放卡片外的句尾")
    if len(sticker_at) > 1:
        probs.append(f"表情包用了 {len(sticker_at)} 个（一条最多 1 个）")
    if sticker_at:
        last = blocks[sticker_at[-1]]
        if sticker_at[-1] != len(blocks) - 1 or (text or "")[last.end():].strip():
            probs.append("表情包要放在这条回复的最后（文字、卡片和按钮的下面），后面不再接字或卡")
    hit = _SERIOUS.search(text or "")
    if hit and (found or sticker_at):
        probs.append(f"说到就医、急救（「{hit.group(0)}」）时不用 emoji 和表情包")
    return probs


def check_text(text: str, cbti_active: bool = False) -> dict:
    """检查一整条回复：每张卡片 + 卡片外的字数 + 做 CBT-I 时不提睡眠债。"""
    problems: list[str] = []
    out_len = len(outside_text(text))
    if out_len > OUTSIDE_MAX:
        problems.append(f"卡片外的文字有 {out_len} 字（最多 {OUTSIDE_MAX}）：只留结论和下一步，数字、依据、步骤放进卡里，能画就画；"
                        "说理用「为什么」卡，卡片后面不补段落")
    head = _OPENER.match(outside_text(text) or "")
    if head:
        problems.append(f"开头「{head.group(1)}」是附和或夸问题：第一句直接给判断（AGENTS 2.5 第 8 条）。"
                        "Psir 给了新信息才改，并说「因为…我改成…」")
    if cbti_active:
        hit = _DEBT_WORDS.search(text or "")
        if hit:
            problems.append(f"在做 CBT-I：不提睡眠债、需要睡多久、差几个小时（这里写了「{hit.group(0)}」）；"
                            "只看睡眠效率、守窗口、入睡和夜醒")
    cards = []
    parsed: list[tuple[int, Any]] = []
    sticker_at: list[int] = []
    blocks = list(_BLOCK.finditer(text or ""))
    for i, m in enumerate(blocks):
        src, closing = m.group(1), m.group(2)
        item: dict[str, Any] = {"index": i + 1}
        if closing != "```":
            item.update(ok=False, problems=["卡片代码块没有用 ``` 收尾"])
            cards.append(item)
            continue
        obj, err, fixed = parse(src.strip())
        if obj is not None:
            parsed.append((i + 1, obj))
            if isinstance(obj, dict) and str(obj.get("type") or "").lower() == "sticker":
                sticker_at.append(i)
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
    problems += _emoji_problems(text, parsed, sticker_at, blocks)
    return {"ok": all(c["ok"] for c in cards) and not problems, "cards": cards, "count": len(cards),
            "problems": problems, "outside_chars": out_len}


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
