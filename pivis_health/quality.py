"""睡眠专项（§5）：入睡难度（纯主观版）+ 高质量夜 Q1–Q5 + 难度换算 + 目标上床。

Eight Sleep 未接入期间的降级纪律（2026-11-01 确认）：
- 入睡难度只用晨报主观 1–5 分，客观换算表仅做展示备用（不参与计算）；
- Q4（深睡+REM ≥ 个人范围下限）在范围未就绪时"不计"，不判失败；
- Q5（醒来精神 ≥3）当天没评则"不计"。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any
from zoneinfo import ZoneInfo

from .ranges import Range, personal_range

HQ_MAP = {7: 1, 6: 1, 5: 2, 4: 3, 3: 3, 2: 4, 1: 4, 0: 5}


def subjective_scores(entries: list[dict], kind: str) -> dict[date, int]:
    """主观分（subj_latency / subj_energy）→ {local_date: score}。"""
    out: dict[date, int] = {}
    for e in entries:
        if e.get("kind") != kind:
            continue
        p = e.get("payload") or {}
        score = p.get("score")
        if score is None:
            continue
        try:
            out[date.fromisoformat(e["local_date"])] = int(score)
        except (KeyError, ValueError):
            continue
    return out


def latency_weekly(subj: dict[date, int], end: date, target: int = 2) -> dict:
    """入睡难度周均 + 目标 + 上周值。样本不足如实说明。"""
    this = [subj[d] for d in sorted(subj) if end - timedelta(days=7) <= d <= end]
    last = [subj[d] for d in sorted(subj) if end - timedelta(days=14) <= d < end - timedelta(days=7)]
    return {
        "mean": round(fmean(this), 1) if this else None,
        "n": len(this),
        "target": target,
        "last_week_mean": round(fmean(last), 1) if last else None,
        "note": None if this else "积累中：隔天评分，还没到本周样本",
    }


def night_need(whoop_night: dict | None) -> float | None:
    if not whoop_night:
        return None
    need = whoop_night.get("sleep_needed_h") or {}
    vals = [v for v in need.values() if v is not None]
    return round(sum(vals), 2) if vals else None


def hq_night(
    whoop_night: dict | None,
    energy_score: int | None,
    deep_rem_range: Range,
    params: dict,
) -> dict | None:
    """单晚 Q1–Q5 判定。数据缺失返回 None（缺数据 ≠ 失败 ≠ 正常）。

    Q1 睡够：asleep_h / need ≥ q1_sleep_ratio（0.9）
    Q2 连续：干扰次数 ≤1（WHOOP disturbance_count 代理；awake 分钟用 awake_h）
    Q3 效率：efficiency_pct ≥ 85
    Q4 结构：deep+rem ≥ 个人范围下限（范围未就绪 → 不计）
    Q5 精神：醒来精神 ≥ 3（没评 → 不计）
    """
    if not whoop_night or whoop_night.get("asleep_h") is None:
        return None
    asleep = float(whoop_night["asleep_h"])
    need = night_need(whoop_night) or 0.0
    stages = whoop_night.get("stages_h") or {}
    deep_rem = (stages.get("slow_wave") or 0) + (stages.get("rem") or 0)
    checks: list[dict] = []

    def add(qid: str, name: str, passed: bool | None, detail: str):
        checks.append({"qid": qid, "name": name, "pass": passed, "detail": detail})

    ratio = asleep / need if need > 0 else 0.0
    add("Q1", "睡够", ratio >= 0.9, f"{asleep:.1f}h / 需要 {need:.1f}h（{ratio:.0%}）")
    dist = whoop_night.get("disturbance_count")
    awake_h = stages.get("awake")
    q2_pass = None
    q2_detail = "干扰数据缺失"
    if dist is not None:
        awake_ok = True if awake_h is None else awake_h <= 20 / 60
        q2_pass = dist <= 1 and awake_ok
        q2_detail = f"干扰 {dist} 次" + (f"，清醒 {awake_h:.1f}h" if awake_h is not None else "")
    add("Q2", "睡得连续", q2_pass, q2_detail)
    eff = whoop_night.get("efficiency_pct")
    add("Q3", "睡得有效率", None if eff is None else eff >= 85,
        "效率数据缺失" if eff is None else f"效率 {eff:.0f}%")
    if deep_rem_range.ready:
        add("Q4", "结构健康", deep_rem >= deep_rem_range.low,
            f"深睡+REM {deep_rem:.1f}h vs 常见下限 {deep_rem_range.low:.1f}h")
    else:
        add("Q4", "结构健康", None, "还在学习你的范围，本项暂不计")
    if energy_score is None:
        add("Q5", "醒来有精神", None, "当天没评，本项不计")
    else:
        add("Q5", "醒来有精神", energy_score >= 3, f"醒来精神 {energy_score}/5")

    evaluated = [c for c in checks if c["pass"] is not None]
    passed = bool(evaluated) and all(c["pass"] for c in evaluated)
    fails = [c["qid"] for c in checks if c["pass"] is False]
    return {"pass": passed, "checks": checks, "fails": fails,
            "evaluated": [c["qid"] for c in evaluated] or "no_eval"}


def hq_difficulty(nights_pass: list[bool | None], window: int = 7) -> dict:
    """近 7 晚高质量夜 → 难度 1–5。无数据晚不计入分母。"""
    valid = [p for p in nights_pass if p is not None]
    n_pass = sum(1 for p in valid if p)
    n_nights = len(valid)
    score = HQ_MAP.get(n_pass, 5) if n_nights else None
    return {
        "score": score,
        "nights_pass": n_pass,
        "n_nights": n_nights,
        "label": f"{score} · 近 7 晚 {n_pass} 晚达标" if score is not None else "积累中",
        "note": None if n_nights else "WHOOP 睡眠数据未到",
    }


def target_bedtime(need_h: float | None, params: dict, night_of: date) -> dict:
    """目标上床 = 起床 − 需求 − 入睡缓冲 − 放松时长；周五/周六晚加周末宽限。"""
    wake = params.get("wake_target", "08:20")
    wh, wm = map(int, wake.split(":"))
    wake_min = wh * 60 + wm
    parts = []
    if not need_h:
        return {"bedtime": None, "wake": wake, "parts": [], "note": "今晚睡眠需求未知（数据未到）"}
    total = wake_min
    total -= int(round(need_h * 60))
    parts.append({"label": f"睡眠需求 {need_h:.1f}h", "minutes": -int(round(need_h * 60))})
    buf = int(params.get("latency_buffer_min", 20))
    total -= buf
    parts.append({"label": f"入睡缓冲 {buf}分", "minutes": -buf})
    lead = int(params.get("relax_lead_min", 30))
    total -= lead
    parts.append({"label": f"放松 {lead}分", "minutes": -lead})
    grace_applied = 0
    if night_of.weekday() in (4, 5):  # 周五/周六晚
        grace_applied = int(params.get("weekend_bed_grace_min", 60))
        total += grace_applied
        parts.append({"label": f"周末宽限 +{grace_applied}分", "minutes": grace_applied})
    total %= 24 * 60
    return {
        "bedtime": f"{total // 60:02d}:{total % 60:02d}",
        "wake": wake,
        "parts": parts,
        "grace_applied": grace_applied,
    }


def caffeine_cutoff(bedtime: str | None, params: dict) -> str | None:
    if not bedtime:
        return None
    bh, bm = map(int, bedtime.split(":"))
    cutoff = (bh * 60 + bm - int(params.get("caffeine_cutoff_h", 8)) * 60) % (24 * 60)
    return f"{cutoff // 60:02d}:{cutoff % 60:02d}"


def on_time_bed_stats(
    bed_times: dict[date, str], target_fn, end: date, grace_min: int, window: int = 7
) -> dict:
    """近 7 晚按时上床统计（实际上床 = WHOOP 在床起点）。"""
    n = on = 0
    for i in range(window):
        d = end - timedelta(days=i)
        actual = bed_times.get(d)
        if not actual:
            continue
        tgt = target_fn(d)
        if not tgt:
            continue
        ah, am = map(int, actual.split(":"))
        th, tm = map(int, tgt.split(":"))
        a = ah * 60 + am
        t = th * 60 + tm
        # 跨午夜：上床在 18:00–04:00 视为"晚间"，目标同段
        if a < 12 * 60:
            a += 24 * 60
        if t < 12 * 60:
            t += 24 * 60
        n += 1
        if a <= t + grace_min:
            on += 1
    return {"nights": n, "on_time": on, "label": f"按时上床 {on}/{n} 晚" if n else "上床数据积累中"}
