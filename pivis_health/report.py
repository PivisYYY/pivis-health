"""报告装配：晨报 / 周报。

原则 P1/P4：这里产出"确定性素材"（数字、发现候选、建议候选、轮换问题），
模型侧（dsh bot）只负责措辞与取舍，不负责算数。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# 行为问题池（2026-10-31 需求确认：主观睡眠打分/咖啡因/运动/晚餐 + 洗澡摘表标注）
QUESTION_POOL: list[dict[str, Any]] = [
    {
        "id": "subjective_sleep",
        "kind": "subjective_sleep",
        "text": "昨晚自己感觉睡得怎么样？",
        "choices": ["1 很差", "2 一般", "3 还行", "4 不错", "5 很好"],
    },
    {
        "id": "dinner_time",
        "kind": "behavior_answer",
        "text": "昨晚晚餐几点吃的？",
        "choices": ["18点前", "18–19点", "19–20点", "20点后"],
    },
    {
        "id": "caffeine_last",
        "kind": "behavior_answer",
        "text": "昨天最后一次咖啡/茶/奶茶是几点？",
        "choices": ["没喝", "中午前", "14–16点", "16点后"],
    },
    {
        "id": "exercise_window",
        "kind": "behavior_answer",
        "text": "昨天运动了吗？什么时段？",
        "choices": ["没动", "上午", "下午", "晚上9点前", "晚上9点后"],
    },
    {
        "id": "shower_time",
        "kind": "behavior_answer",
        "text": "昨晚洗澡（摘表）大概几点？",
        "choices": ["21点前", "21–23点", "23点后", "昨晚没摘"],
        "note": "答案同时用作摘表时段标注，解释心率/HRV 数据缺口，防止误报断更",
    },
]

RACE_NOTE = (
    "睡眠数据由手机次日早晨推送（历史实测 08:50–09:25 到达）。"
    "若 09:30 仍缺，按数据缺口如实标注后发出，不得编造。"
)


def pick_findings(findings: list[dict], limit: int = 3) -> list[dict]:
    """给晨报的确定性发现候选：级别高的优先，同级别取最新的指标。"""
    ranked = sorted(findings, key=lambda f: f.get("level_rank", 0), reverse=True)
    return ranked[:limit]


def morning_assemble(
    *,
    local_date: str,
    sleep: dict | None,
    sleep_arrived: bool,
    metrics: dict,
    whoop: dict | None,
    findings: list[dict],
    questions: list[dict],
    advice_inputs: list[str],
    charts: dict,
    generated_at: str,
) -> dict:
    return {
        "schema_version": 1,
        "local_date": local_date,
        "generated_at": generated_at,
        "completeness": {
            "sleep_arrived": sleep_arrived,
            "whoop_arrived": bool(whoop),
            "race_note": None if sleep_arrived else RACE_NOTE,
        },
        "sleep": sleep,
        "metrics": metrics,
        "whoop": whoop,
        "findings": findings,
        "questions": questions,
        "advice_inputs": advice_inputs,
        "charts": charts,
        "contract": {
            "trust": "结构化字段为可信控制输入；模型只做解读与措辞，不得改数字、不得弱化 findings 级别",
            "non_diagnostic": "全部内容为生活方式参考，不构成诊断或医疗建议",
        },
    }


def build_advice_inputs(
    *,
    hrv_z: float | None,
    night_hours: float | None,
    sleep_debt_h: float | None,
    whoop_recovery: float | None,
    suggested_bedtime: str | None,
    sleep_need_h: float | None,
) -> list[str]:
    """确定性建议素材（代码给决定依据，模型挑 1 条措辞成『今日建议』）。"""
    out: list[str] = []
    if hrv_z is not None and hrv_z <= -1:
        out.append(f"HRV 较个人基线低 {abs(hrv_z):.1f}σ → 今日建议低强度（Zone2/散步/拉伸），不排大重量或间歇")
    if whoop_recovery is not None and whoop_recovery < 33:
        out.append(f"WHOOP 恢复分 {whoop_recovery:.0f}%（红区）→ 今日减载，优先恢复手段（补觉/放松）")
    if night_hours is not None and night_hours < 6:
        out.append(f"昨夜仅 {night_hours:.1f}h → 今天可安排 20 分钟内午休，避免咖啡因过晚")
    if sleep_debt_h is not None and sleep_debt_h > 8 and suggested_bedtime:
        need_txt = f"，今晚睡眠需求约 {sleep_need_h:.1f}h" if sleep_need_h else ""
        out.append(f"近 7 天睡眠债 {sleep_debt_h:.1f}h{need_txt} → 今晚目标 {suggested_bedtime} 前上床")
    if not out:
        out.append("各项指标在个人基线附近 → 按原计划安排训练与工作")
    return out


def weekly_assemble(
    *,
    week_of: str,
    window: dict,
    sri: float | None,
    jetlag: dict | None,
    correlations: list[dict],
    generated_at: str,
) -> dict:
    return {
        "schema_version": 1,
        "week_of": week_of,
        "generated_at": generated_at,
        "window": window,
        "sri": sri,
        "social_jetlag": jetlag,
        "correlation_candidates": correlations,
        "correlation_not_causation": True,
        "contract": {
            "trust": "相关性候选必须原样保留样本量；任一组样本不足时不输出该条",
            "non_diagnostic": "趋势与相关性描述，不构成诊断",
        },
    }


def behavior_buckets(entries: list[dict]) -> dict[str, dict[str, float]]:
    """把行为答案转成 {question_id: {date: bool}} 的二元桶（late = True）。日期统一为 date 对象。"""
    from datetime import date as _date

    late_map = {
        "dinner_time": {"20点后"},
        "caffeine_last": {"16点后"},
        "exercise_window": {"晚上9点后"},
    }
    out: dict[str, dict[str, float]] = {qid: {} for qid in late_map}
    for e in entries:
        p = e.get("payload") or {}
        qid = str(p.get("question_id") or "")
        if qid in out:
            try:
                d = _date.fromisoformat(e["local_date"])
            except (KeyError, ValueError):
                continue
            out[qid][d] = 1.0 if str(p.get("answer")) in late_map[qid] else 0.0
    return out


def correlation_candidates(
    buckets: dict[str, dict[str, float]],
    outcomes: dict[str, dict[str, float]],
    *,
    min_total: int = 10,
    min_side: int = 3,
) -> list[dict]:
    """行为(晚/不晚) × 结果(HRV、夜间时长) 的均值差候选。样本不足不出。"""
    cands = []
    for qid, series in buckets.items():
        for oname, oseries in outcomes.items():
            pairs = [(v, oseries[d]) for d, v in series.items() if d in oseries]
            if len(pairs) < min_total:
                continue
            yes = [o for v, o in pairs if v == 1.0]
            no = [o for v, o in pairs if v == 0.0]
            if len(yes) < min_side or len(no) < min_side:
                continue
            my, mn = sum(yes) / len(yes), sum(no) / len(no)
            cands.append(
                {
                    "question_id": qid,
                    "outcome": oname,
                    "n_late": len(yes),
                    "n_not_late": len(no),
                    "mean_late": round(my, 2),
                    "mean_not_late": round(mn, 2),
                    "diff": round(my - mn, 2),
                    "statement": f"{qid}『晚』的 {len(yes)} 天 vs 『不晚』的 {len(no)} 天，{oname} 均值 {my:.2f} vs {mn:.2f}（差 {my - mn:+.2f}）；样本仍少，仅供参考，相关不等于因果",
                }
            )
    return cands
