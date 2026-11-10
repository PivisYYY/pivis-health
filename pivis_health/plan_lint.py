"""计划冲突检查（build 52）：P-Health 加卡、改卡、改项目模板时，对照今晚的上床时间查明显冲突，有就退回。

只查有证据、判得准的几条（依据见 cbti/references/sleep-science.md 第 2 节）：
- 洗澡 / 泡脚：要在上床前 1 小时以前洗完，开始时间离上床不到 1 小时 → 退回
- 剧烈运动（力量、网球、跑步……；拉伸、散步、呼吸、康复动作不算）：离上床不到 2 小时 → 退回
- 在做 CBT-I：上床卡早于最早上床时间、午睡超过 20 分钟或在 15:00 以后 → 退回
以前出过的事：CBT-I 把上床时间往后挪了，当天傍晚排的洗澡没跟着改，离上床不到 1 小时。
"""
from __future__ import annotations

from typing import Any

BATH = ("澡", "泡脚")          # 洗澡、洗完澡、泡澡、冲澡都算
HARD = ("力量", "网球", "跑步", "慢跑", "HIIT", "间歇", "跳绳", "冲刺", "健身", "撸铁", "球赛", "打球", "游泳")
EASY = ("拉伸", "放松", "呼吸", "瑜伽", "散步", "走", "扫描", "冥想", "康复", "膝", "腰背", "热身")
NAP = ("午睡", "小睡", "补觉")


def _m(hm: Any) -> int | None:
    try:
        h, m = (int(x) for x in str(hm).split(":")[:2])
        return h * 60 + m
    except (TypeError, ValueError):
        return None


def _night(hm: Any) -> int | None:
    """从傍晚算起的分钟数：00:00–05:59 记成 24:00 以后，跨零点也能比。"""
    m = _m(hm)
    return None if m is None else (m + 24 * 60 if m < 6 * 60 else m)


def sleep_plan(cfg) -> dict:
    """在做的睡眠安排（CBT-I 记忆里的最早上床和起床）。"""
    try:
        from .agent_context import AgentContextStore
        for e in AgentContextStore(cfg).snapshot()["entries"]:
            if e.get("scope") == "sleep.cbti":
                p = e.get("payload") or {}
                return {"bed": p.get("earliest_bed"), "wake": p.get("wake"), "cbti": True}
    except Exception:  # noqa: BLE001
        pass
    return {}


def problems(t: dict, plan: dict) -> list[str]:
    """这张卡（或模板）和睡眠安排的冲突，一条一句，写清怎么改。"""
    bed = _night(plan.get("bed"))
    title = f"{t.get('title') or ''} {t.get('note') or ''}"
    when = t.get("when") or ""
    w = _night(when)
    out = []
    if bed is None or w is None:
        return out
    evening = w >= 17 * 60
    if evening and any(k in title for k in BATH) and bed - w < 60:
        out.append(f"「{t.get('title')}」{when} 开始，离上床（{plan['bed']}）不到 1 小时：热水澡要在上床前 1–2 小时洗完，"
                   f"改到 {_fmt(bed - 120)}–{_fmt(bed - 75)} 之间开始")
    if evening and any(k in title for k in HARD) and not any(k in title for k in EASY) and bed - w < 120:
        out.append(f"「{t.get('title')}」{when} 开始，离上床（{plan['bed']}）不到 2 小时：剧烈运动要在上床前 2 小时结束，"
                   f"改早，或换成拉伸 / 放松")
    if plan.get("cbti"):
        if t.get("title", "").startswith("上床") and w < bed:
            out.append(f"在做 CBT-I：最早上床是 {plan['bed']}，上床卡不能早于它（{when}）")
        if any(k in title for k in NAP):
            dur, m = t.get("duration_min"), _m(when)
            if (dur and float(dur) > 20) or (m is not None and m >= 15 * 60):
                out.append(f"在做 CBT-I：午睡最多 20 分钟、15:00 前结束（「{t.get('title')}」{when}"
                           + (f"，{dur} 分钟" if dur else "") + "）")
    return out


def _fmt(n: int) -> str:
    n %= 24 * 60
    return f"{n // 60:02d}:{n % 60:02d}"


def check(cfg, t: dict) -> list[str]:
    try:
        return problems(t, sleep_plan(cfg))
    except Exception:  # noqa: BLE001  检查本身出错不挡写卡
        return []
