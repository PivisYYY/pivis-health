"""放松内容库（F5 今晚放松页）。

纪律（继承产品方案）：素材**只找不改**——这里只存外链与元数据，不存/不转存内容本体。
视频条目使用已核实的 B 站具体视频，iOS 转换为官方播放器嵌入；不用搜索结果页冒充播放内容。
评分闭环：好用/不好用影响下次挑选。
"""
from __future__ import annotations

from datetime import date
from typing import Any

# category → 建议顺序（a-b-c 顺序执行）
LIBRARY: list[dict[str, Any]] = [
    {
        "id": "cbti-stretch-stand",
        "category": "拉伸",
        "title": "床外站立全身拉伸（10:52）",
        "duration_min": 11,
        "source": "B 站 · MIZI · 站姿拉伸",
        "url": "/media/sleep-audio/00_%E5%BA%8A%E5%A4%96%E6%8B%89%E4%BC%B8.m4a",
        "embed": None,
        "status": "verified",
    },
    {
        "id": "cbti-breath-478",
        "category": "呼吸",
        "title": "4-7-8 呼吸跟练（6:00）",
        "duration_min": 6,
        "source": "B 站 · 呼吸引导第1期",
        "url": "/media/sleep-audio/04_%E5%91%BC%E5%90%B8478.m4a",
        "embed": None,
        "status": "verified",
    },
    {
        "id": "cbti-body-scan",
        "category": "冥想",
        "title": "身体扫描（12:02）",
        "duration_min": 12,
        "source": "B 站 · 三三说一说",
        "url": "/media/sleep-audio/02_%E8%BA%AB%E4%BD%93%E6%89%AB%E6%8F%8F.m4a",
        "embed": None,
        "status": "verified",
    },
    {
        "id": "cbti-meditation",
        "category": "冥想",
        "title": "睡前冥想（10:03）",
        "duration_min": 10,
        "source": "B 站 · 悠雅-Yoya",
        "url": "/media/sleep-audio/03_%E7%9D%A1%E5%89%8D%E5%86%A5%E6%83%B3.m4a",
        "embed": None,
        "status": "verified",
    },
    {
        "id": "stretch-bedtime",
        "category": "拉伸",
        "title": "15 分钟睡前舒缓拉伸好梦瑜伽",
        "duration_min": 15,
        "source": "B 站 · 王立鑫 Tony",
        "url": "https://www.bilibili.com/video/BV1U34y1R7pz/",
        "embed": "https://player.bilibili.com/player.html?bvid=BV1U34y1R7pz&autoplay=0",
        "status": "verified",
    },
    {
        "id": "breathing-478",
        "category": "呼吸",
        "title": "4-7-8 呼吸法（跟练说明）",
        "duration_min": 6,
        "source": "Sleep Foundation · breathing exercises",
        "url": "https://www.sleepfoundation.org/sleep-hygiene/healthy-sleep-tips",
        "embed": None,
        "status": "seed",
    },
    {
        "id": "cbt-worry-time",
        "category": "CBT-I",
        "title": "睡前忧虑清空练习（写下来再上床）",
        "duration_min": 10,
        "source": "CBT-I 通用做法",
        "url": "https://www.sleepfoundation.org/insomnia/treatment/cognitive-behavioral-therapy-insomnia",
        "embed": None,
        "status": "seed",
    },
    {
        "id": "meditation-body-scan",
        "category": "冥想",
        "title": "15 分钟助眠冥想与渐进式放松",
        "duration_min": 15,
        "source": "B 站 · 范李猿",
        "url": "https://www.bilibili.com/video/BV1Sw41187j4/",
        "embed": "https://player.bilibili.com/player.html?bvid=BV1Sw41187j4&autoplay=0",
        "status": "verified",
    },
    {
        "id": "music-ambient",
        "category": "音频",
        "title": "8 小时瀑布流水白噪音",
        "duration_min": 480,
        "source": "B 站 · 白噪音",
        "url": "https://www.bilibili.com/video/BV1oa4y1h7sk/",
        "embed": "https://player.bilibili.com/player.html?bvid=BV1oa4y1h7sk&autoplay=0",
        "status": "verified",
        "note": "适合作为流程最后一段环境音",
    },
]

CATEGORY_ORDER = ["拉伸", "呼吸", "CBT-I", "冥想", "音频"]


def item_by_id(item_id: str) -> dict | None:
    for it in LIBRARY:
        if it["id"] == item_id:
            return it
    return None


def rating_scores(entries: list[dict]) -> dict[str, dict[str, int]]:
    """item_id → {good: n, bad: n}（来自 content_rating 主观记录）。"""
    out: dict[str, dict[str, int]] = {}
    for e in entries:
        p = e.get("payload") or {}
        iid = str(p.get("item_id") or "")
        rating = str(p.get("rating") or "")
        if iid and rating in ("good", "bad"):
            slot = out.setdefault(iid, {"good": 0, "bad": 0})
            slot[rating] += 1
    return out


def suggest(scores: dict[str, dict[str, int]], limit_per_category: int = 1) -> list[dict]:
    """每个类别挑一条：好评分 > 未评过 > 差评靠后；同分取靠前（稳定）。"""
    picked: list[dict] = []
    for cat in CATEGORY_ORDER:
        items = [it for it in LIBRARY if it["category"] == cat]
        if not items:
            continue

        def rank(it: dict) -> tuple:
            s = scores.get(it["id"], {})
            return (-(s.get("good", 0) - s.get("bad", 0)), s.get("bad", 0))

        for it in sorted(items, key=rank)[:limit_per_category]:
            picked.append(it)
    return picked


def tonight_plan(item_ids: list[str]) -> list[dict]:
    """按类别固定顺序组成今晚流程；未知 id 忽略。"""
    by_cat: dict[str, list[dict]] = {}
    for iid in item_ids:
        it = item_by_id(iid)
        if it:
            by_cat.setdefault(it["category"], []).append(it)
    plan: list[dict] = []
    for cat in CATEGORY_ORDER:
        plan.extend(by_cat.get(cat, []))
    return plan
