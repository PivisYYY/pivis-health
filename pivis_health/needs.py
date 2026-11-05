"""今日 3 件事（§10）：候选池 + 四因子打分 + 反馈链。

打分 = 严重度 × 可行动性 × 时间窗 × 新鲜度（各 0–1）。
规则：最多 3 张、同专项 ≤2、生病卡置顶且运动类下线、"今天算了"同类 24h 冷却、
按建议时刻先后排（得分只决定入选）。0 张时结论句写"今天状态不错，照常就好"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

SCORE_GATE = 0.15
MAX_NEEDS = 3
PER_SPECIALTY_MAX = 2
COOLDOWN_H = 24


@dataclass
class Need:
    type: str
    title: str
    specialty: str
    evidence: str
    evidence_fields: dict
    action: str
    alt_action: str = ""
    window: str = "当天"          # 今晚 / 午间 / 当天空档 / 运动后 / 现在
    severity: float = 0.5
    actionability: float = 0.7
    time_factor: float = 0.6
    freshness: float = 1.0
    top: bool = False             # 置顶（生病早期）
    kills_sport: bool = False

    @property
    def score(self) -> float:
        return round(self.severity * self.actionability * self.time_factor * self.freshness, 4)

    def to_dict(self) -> dict:
        return {
            "need_type": self.type, "title": self.title, "specialty": self.specialty,
            "evidence": self.evidence, "evidence_fields": self.evidence_fields,
            "action": self.action, "alt_action": self.alt_action, "window": self.window,
            "score": self.score, "top": self.top,
            "actions": ["做了", "不做"],
        }


_WINDOW_ORDER = {"现在": 0, "当天空档": 1, "午间": 2, "运动后": 3, "今晚": 4, "当天": 5}


def _feedback_state(entries: list[dict], need_type: str, now: datetime) -> dict:
    """同类卡的近期反馈：算了(24h 冷却)、做了(新鲜度加成)。时间统一按本地 naive 比较。"""
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    out = {"cooldown": False, "done_recent": 0, "skipped_streak": 0}
    recent = []
    for e in entries:
        if e.get("kind") != "need_feedback":
            continue
        p = e.get("payload") or {}
        if p.get("need_type") != need_type:
            continue
        try:
            raw = e["created_at"]
            at = datetime.fromisoformat(raw.split("+")[0] if "+" in raw else raw)
            # 负时区（如 -04:00）不含 "+"，fromisoformat 会返回带时区对象；统一转本地 naive
            if at.tzinfo is not None:
                at = at.astimezone().replace(tzinfo=None)
        except (KeyError, ValueError):
            continue
        recent.append((at, p.get("action")))
    recent.sort(reverse=True)
    for at, action in recent:
        if now - at <= timedelta(hours=COOLDOWN_H) and action in ("今天算了", "不做"):
            out["cooldown"] = True
        if now - at <= timedelta(days=3) and action == "做了":
            out["done_recent"] += 1
    for _, action in recent:
        if action in ("今天算了", "不做"):
            out["skipped_streak"] += 1
        else:
            break
    return out


def build_needs(ctx: dict, feedback_entries: list[dict], now: datetime) -> list[dict]:
    """ctx 由 pages 层装配；返回按规则筛选排序后的 0–3 张卡。"""
    day: date = ctx["date"]
    pool: list[Need] = []

    debt = ctx.get("debt") or {}
    params = ctx.get("params") or {}
    illness = bool(ctx.get("illness"))
    coverage = ctx.get("coverage") or []
    play = ctx.get("play") or {}
    sessions = ctx.get("weekly_sessions") or {}
    y_strain = ctx.get("yesterday_strain")
    strain_ref = ctx.get("strain_median_30d") or 0.0
    has_workout_today = bool(ctx.get("has_workout_today"))
    free_slots = ctx.get("free_slots")
    nap_total_h = ctx.get("nap_total_h", 0) or 0

    # 睡眠专项（午休 ≥30 分钟自动打勾补觉卡）
    if debt.get("debt_h") and nap_total_h < 0.5:
        d = debt["debt_h"]
        sev = 0.9 if d > params.get("debt_high_h", 3.0) else 0.7 if d > params.get("debt_alert_h", 1.0) else 0.0
        if sev > 0:
            pool.append(Need(
                "catch_up_sleep", f"急需补觉（{debt.get('n_nights', 7)} 晚欠 {d:.1f}h）", "睡眠",
                f"近 {debt.get('n_nights', 7)} 晚平均 {debt.get('avg_h')}h，需求约 {debt.get('target_h', '?')}h，累计欠 {d:.1f} 小时",
                {"sleep_debt_h": d, "avg_h": debt.get("avg_h"), "n_nights": debt.get("n_nights")},
                "今晚提前上床；或午间 20 分钟小憩",
                alt_action="午间 20 分钟小憩", window="今晚", severity=sev,
            ))
    latency3 = ctx.get("latency_last3") or []
    if len(latency3) >= 3 and sum(latency3) / 3 >= 4:
        pool.append(Need(
            "lower_latency", "降低入睡难度", "睡眠",
            f"近 3 晚入睡难度均分 {sum(latency3)/3:.1f}（目标 ≤{params.get('latency_target', 2)}）",
            {"latency_mean_3d": round(sum(latency3)/3, 1)},
            "调整今晚放松计划（优先你评过『好用』的内容）", window="今晚", severity=0.7,
        ))

    # 压力专项（HRV 连续偏出）
    if ctx.get("hrv_streak_out", 0) >= 3:
        pool.append(Need(
            "ease_off", "需要缓一缓", "压力",
            f"HRV 连续 {ctx['hrv_streak_out']} 天低于你的常见范围",
            {"hrv_streak_out": ctx["hrv_streak_out"]},
            "空档里走动 20 分钟 / 5 分钟呼吸练习",
            alt_action="5 分钟呼吸练习", window="当天空档", severity=0.65,
        ))
    if free_slots and ctx.get("daylight_low"):
        pool.append(Need(
            "daylight", "晒太阳", "压力",
            "今天户外光照还不到 20 分钟且有空档", {},
            "白天户外 20 分钟", window="当天空档", severity=0.35,
        ))

    # 运动专项
    done = sessions.get("done", 0)
    quota = sessions.get("quota", 3)
    if illness:
        pool.append(Need(
            "rest_first", "先休息", "身体",
            "心率/呼吸/皮温多项同时偏离，可能在累积疲劳或要生病（不诊断）",
            {"illness_flags": ctx.get("illness_flags", [])},
            "今天减量，早睡", window="当天", severity=1.0, top=True, kills_sport=True,
        ))
    if y_strain is not None and strain_ref > 0 and y_strain >= max(12.0, strain_ref * 2):
        pool.append(Need(
            "big_load_rest", "昨天负荷很高，今天彻底休息", "身体",
            f"昨日负荷 {y_strain:.1f}，是你 30 天中位数的 {y_strain/strain_ref:.1f} 倍",
            {"yesterday_strain": round(y_strain, 1), "strain_median_30d": round(strain_ref, 1)},
            "今天不安排强度，散步即可", window="当天", severity=0.8,
        ))
    if play.get("verdict") == "不宜" and ctx.get("sport_planned"):
        pool.append(Need(
            "skip_sport", "今天不宜运动", "运动",
            play.get("reason", ""), {"checks": play.get("checks", [])},
            "改日；替代：15 分钟拉伸或力量", window="当天", severity=0.7, kills_sport=True,
        ))
    if has_workout_today:
        pool.append(Need(
            "post_stretch", "练后修复", "运动",
            "今天有运动记录，还差 10 分钟拉伸", {"workout": True},
            "10 分钟拉伸", window="运动后", severity=0.6,
        ))
    elif done == 0 and day.weekday() >= 2:
        pool.append(Need(
            "move_more", "动一动 / 增强", "运动",
            f"本周 {done}/{quota} 场，力量 2 次也未开始", {"weekly_sessions": done, "quota": quota},
            "15 分钟力量 / 拉伸", window="当天空档", severity=0.4,
        ))

    # 数据专项（关注级，不推送、只进页面）
    for s in coverage:
        if s.get("notify"):
            pool.append(Need(
                "data_sync", f"同步 {s.get('label', '数据源')}", "数据",
                f"{s.get('label')} 已断更 {s.get('gap_days')} 天（最后 {str(s.get('last_data_local'))[:16]}）",
                {"source": s.get("source"), "gap_days": s.get("gap_days")},
                "打开对应 App 手动同步 / 检查设备充电", window="当天", severity=0.55,
            ))

    # 反馈链：冷却 + 新鲜度
    kept: list[Need] = []
    for nd in pool:
        fb = _feedback_state(feedback_entries, nd.type, now)
        if fb["cooldown"]:
            continue
        nd.freshness = min(1.0, 0.8 + 0.1 * fb["done_recent"]) if fb["done_recent"] else (
            0.5 if fb["skipped_streak"] >= 2 else 1.0)
        kept.append(nd)

    # 生病卡置顶且运动类下线
    if any(n.top for n in kept):
        kept = [n for n in kept if n.specialty != "运动" or not n.kills_sport]

    kept = [n for n in kept if n.score >= SCORE_GATE]
    kept.sort(key=lambda n: (-int(n.top), n.score), reverse=False)
    kept.sort(key=lambda n: (0 if n.top else 1, -n.score))
    # 入选后按时间先后展示
    selected = kept[:MAX_NEEDS]
    seen_types: set[str] = set()
    per_specialty: dict[str, int] = {}
    final: list[Need] = []
    for n in selected:
        if n.type in seen_types:  # 同一类型只保留分数最高的一条（如多个数据源断更）
            continue
        seen_types.add(n.type)
        c = per_specialty.get(n.specialty, 0)
        if c >= PER_SPECIALTY_MAX:
            continue
        per_specialty[n.specialty] = c + 1
        final.append(n)
    if not any(n.top for n in final):
        for n in kept[MAX_NEEDS:]:
            if n.top and len(final) < MAX_NEEDS:
                final.insert(0, n)
                break
    final.sort(key=lambda n: (0 if n.top else 1, _WINDOW_ORDER.get(n.window, 9)))
    return [n.to_dict() for n in final]
