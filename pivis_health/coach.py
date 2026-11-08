"""教练用的统计（数字都由这里算，P-Health 只抄）：项目执行情况、一周睡眠、素材库扩充、周复盘。"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from .todos import TodoStore


def project_stats(tools, project_id: str, days: int = 7, day: date | None = None) -> dict:
    """近 N 天某个项目每天的待办做了没：按模板 key 分别数，给出执行率。今天还没结束的不算进分母。"""
    day = day or tools._now().date()
    store = TodoStore(tools.cfg)
    proj = next((p for p in store.projects() if p["id"] == project_id), None)
    if not proj:
        raise ValueError(f"没有项目 {project_id}；用 project-list 看有哪些")
    start = date.fromisoformat(proj["start"])
    per_key: dict[str, dict[str, Any]] = {}
    days_out = []
    for i in range(days, -1, -1):
        d = day - timedelta(days=i)
        if d < start:
            continue
        ts = [t for t in store.for_date(d, proj["board"]) if t.get("project") == project_id]
        row = {"date": d.isoformat(), "today": d == day, "items": []}
        for t in ts:
            key = t.get("template_key") or t.get("key") or t["title"]
            st = t["status"]
            row["items"].append({"title": t["title"], "status": st, "summary": t.get("summary") or ""})
            if d == day:
                continue
            k = per_key.setdefault(t["title"], {"title": t["title"], "done": 0, "skipped": 0, "missed": 0, "total": 0})
            k["total"] += 1
            if st == "done":
                k["done"] += 1
            elif st == "skipped":
                k["skipped"] += 1
            else:
                k["missed"] += 1
        days_out.append(row)
    items = list(per_key.values())
    for k in items:
        k["rate_pct"] = round(100 * k["done"] / k["total"]) if k["total"] else None
    total = sum(k["total"] for k in items)
    done = sum(k["done"] for k in items)
    return {"project": {"id": proj["id"], "name": proj["name"], "day": (day - start).days + 1, "days": proj["days"]},
            "window_days": days, "items": items, "overall_pct": round(100 * done / total) if total else None,
            "by_day": days_out,
            "note": "只算已经过去的天；今天的在 by_day 里标了 today。数字直接抄，不要自己再算。"}


def sleep_week(tools, nights: int = 7, day: date | None = None) -> dict:
    """近 N 晚的睡眠：每晚睡了多久、需要多久、效率、入睡和起床时间（WHOOP 优先，断了用 Apple），以及分档计数。
    给 CBT-I 周复盘调窗口用。"""
    from . import whoop as whoop_mod
    from .pages import V2Pages
    day = day or tools._now().date()
    pages = V2Pages(tools)
    ns = pages._nights(day, nights + 2)
    wsleep = whoop_mod.sleep_by_night(tools._whoop or {}, tools.cfg.timezone) if tools._whoop else {}
    rows = []
    for i in range(nights, 0, -1):
        d = day - timedelta(days=i)
        n = ns.get(d) or {}
        w = wsleep.get(d) or {}
        need = None
        if w.get("sleep_needed_h"):
            vals = [v for v in w["sleep_needed_h"].values() if v is not None]
            need = round(sum(vals), 2) if vals else None
        rows.append({"night_of": d.isoformat(), "asleep_h": n.get("asleep_h"), "need_h": need,
                     "efficiency_pct": w.get("efficiency_pct"),
                     "in_bed_h": (w.get("stages_h") or {}).get("in_bed"),
                     "start": (w.get("start_local") or "")[11:16] or None, "end": (w.get("end_local") or "")[11:16] or None,
                     "source": n.get("source") or ("whoop" if w else None)})
    have = [r for r in rows if r["asleep_h"] is not None]
    eff = [r["efficiency_pct"] for r in rows if r["efficiency_pct"] is not None]
    bands = {"ge90": sum(1 for e in eff if e >= 90), "85_89": sum(1 for e in eff if 85 <= e < 90),
             "lt85": sum(1 for e in eff if e < 85), "no_data": nights - len(eff)}
    return {"nights": rows,
            "avg_asleep_h": round(sum(r["asleep_h"] for r in have) / len(have), 2) if have else None,
            "avg_efficiency_pct": round(sum(eff) / len(eff), 1) if eff else None,
            "efficiency_bands": bands,
            "note": "效率来自设备（WHOOP），通常比日记算的偏高；日记里入睡很慢的晚上要一起看。"}


def _user_media_path(tools):
    return tools.cfg.data_dir / "media_user.json"


def user_media(tools) -> list[dict]:
    try:
        return json.loads(_user_media_path(tools).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def media_add(tools, item: dict) -> dict:
    """把核对过的公开素材收进老大的素材库（之后 media-library 能直接用，不用每次重新搜）。"""
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    if not url.startswith("https://") or not title:
        raise ValueError("要有 title 和 https 开头的公开链接")
    url = re.sub(r"\?.*$", "", url) if "bilibili.com/video/" in url else url
    kind = item.get("kind") or ("video" if "bilibili.com/video/" in url else ("audio" if url.endswith((".m4a", ".mp3")) else "embed"))
    if kind not in ("audio", "video", "embed"):
        raise ValueError("kind 只能是 audio / video / embed")
    lib = user_media(tools)
    lib = [m for m in lib if m["url"] != url]
    entry = {"id": item.get("id") or f"user-{len(lib) + 1}", "title": title, "url": url, "kind": kind,
             "duration_min": item.get("duration_min"), "type": item.get("type") or "",
             "added_at": tools._now().isoformat(timespec="minutes"), "source": item.get("source") or "web"}
    lib.append(entry)
    _user_media_path(tools).write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    return entry


def project_status(p: dict, day: date) -> str:
    """一个项目此刻的真实状态（开始日以项目数据为准）：还没开始 / 第几天 / 已结束。"""
    start = date.fromisoformat(p["start"])
    days = int(p.get("days") or 0)
    if day < start:
        left = (start - day).days
        when = "明天" if left == 1 else f"{left} 天后"
        return f"{p['name']}（{p['id']}）：{start.isoformat()} 开始，{when}，今天还没开始"
    n = (day - start).days + 1
    if days and n > days:
        return f"{p['name']}（{p['id']}）：{start.isoformat()} 开始的 {days} 天已经结束"
    return f"{p['name']}（{p['id']}）：第 {n} 天 / 共 {days} 天（{start.isoformat()} 开始）"


def projects_truth(tools, day: date, board: str | None = None) -> str:
    """推荐、复盘提示里带上的项目真实状态：计划改过的话以这里为准，不按对话里早先说过的。"""
    ps = [p for p in TodoStore(tools.cfg).projects(active_only=True) if board is None or p["board"] == board]
    if not ps:
        return ""
    return ("\n进行中的项目（以这里的开始日为准；计划改过的话，对话里早先说的「明天开始」之类作废）：\n"
            + "\n".join("- " + project_status(p, day) for p in ps))


def weekly_review_note(tools, day: date, board: str | None = None) -> str:
    """周日早上那次【每日推荐】里加一段：每个进行中的项目（所有板块，含日常）做一次周复盘。"""
    if day.isoweekday() != 7:
        return ""
    store = TodoStore(tools.cfg)
    ps = [p for p in store.projects(active_only=True) if board is None or p["board"] == board]
    if not ps:
        return ""
    names = "、".join(f"{p['name']}（{p['id']}）" for p in ps)
    return ("\n今天是周日，做周复盘：" + names + "。每个项目先跑 ./pivis-health project-stats --id <id> --days 7"
            "（睡眠类再跑 ./pivis-health sleep-week），按 habit-coach / 对应专业 skill 的复盘规则判断；"
            "每个项目加一张 kind=proposal 的待办「本周复盘」：数据和建议写清楚，给 2–3 个选项（不用改也给「保持不变」），"
            "老大选了再 project-set。学到的规律用 context-record --scope learn.<主题> 记下。"
            "说某个项目哪天开始、第几天，只按这条消息里「进行中的项目」的状态说。")
