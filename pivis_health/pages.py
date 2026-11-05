"""v2 四页装配（§8）：今日 / 睡眠 / 运动 / 压力与恢复。

装配层只做字段组合与确定性计算；结论句给素材（agent 可润色但不改数字）。
WHOOP 为主源（§6.1）：夜间睡眠/入睡/需求全部用 WHOOP，Apple 只做补位与断更核对。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import fmean, median
from typing import Any

from . import insights, layout, needs as needs_mod, quality, work_signals
from .params import Params
from .ranges import personal_range, deviation, streak_out
from .tools import HealthTools
from .whoop import sleep_by_night, strain_by_day

_Q_NAMES = {"Q1": "睡够", "Q2": "睡得连续", "Q3": "睡得有效率",
            "Q4": "结构健康", "Q5": "醒来有精神"}


class V2Pages:
    def __init__(self, tools: HealthTools) -> None:
        self.t = tools
        self.params = Params(tools.subj)

    # ---------- 公共数据 ----------
    def _nights(self, end: date, days: int = 16) -> dict[date, dict]:
        """每晚睡眠：有 WHOOP 记录用 WHOOP（带「需要睡多久」）；WHOOP 断更的晚上用 Apple 健康的睡眠补上，
        只有时长、没有「需要」（不编）。"""
        snap = self.t._whoop or {}
        out = sleep_by_night(snap, self.t.cfg.timezone) if snap else {}
        for i in range(days):
            nd = end - timedelta(days=i)
            if nd in out or nd >= self.t._now().date():
                continue
            try:
                r = self.t._sleep_results(nd, 1)[nd]
            except Exception:
                continue
            hours = (r.get("night") or {}).get("hours") or 0.0
            if r.get("error") or hours < 1.0:
                continue
            out[nd] = {"asleep_h": round(float(hours), 2), "source": "apple_health"}
        return out

    def _recovery_daily(self, end: date, days: int = 30) -> dict[date, float]:
        return self.t.daily_series("whoop_recovery", end, days)

    def _hrv_daily(self, end: date, days: int = 30) -> dict[date, float]:
        return self.t.daily_series("whoop_hrv_rmssd", end, days)

    def _strain_daily(self, end: date, days: int = 30) -> dict[date, float]:
        return self.t.daily_series("whoop_strain", end, days)

    def _week_workouts(self, end: date) -> list[dict]:
        snap = self.t._whoop or {}
        monday = end - timedelta(days=end.weekday())
        out = []
        for w in snap.get("workout", []):
            try:
                from .readonly import parse_ts
                from zoneinfo import ZoneInfo
                s = parse_ts(str(w["start"])).astimezone(ZoneInfo(self.t.cfg.timezone))
            except Exception:
                continue
            if monday <= s.date() <= end:
                out.append({"date": s.date(), "sport": w.get("sport_name"),
                            "strain": (w.get("score") or {}).get("strain")})
        return out

    def _debt(self, end: date) -> dict | None:
        nights = self._nights(end)
        dur = {d: n["asleep_h"] for d, n in nights.items() if n.get("asleep_h")}
        need = {d: quality.night_need(n) for d, n in nights.items()}
        days = [d for d in sorted(dur) if end - timedelta(days=7) <= d < end]
        if len(days) < 5:
            return None
        debt = sum(max(0.0, (need.get(d) or 0) - dur[d]) for d in days)
        avg_need = fmean([need.get(d) or 0 for d in days]) or None
        return {
            "debt_h": round(debt, 1), "n_nights": len(days),
            "avg_h": round(fmean(dur[d] for d in days), 1),
            "target_h": round(avg_need, 1) if avg_need else None,
        }

    def _play_ok(self, end: date) -> dict:
        rec = self._recovery_daily(end).get(end)
        strain = self._strain_daily(end)
        y = strain.get(end - timedelta(days=1))
        med = median([v for v in strain.values()]) if strain else 0.0
        week = [v for d, v in strain.items() if end - timedelta(days=end.weekday()) <= d <= end]
        load = sum(week)
        p = self.params.all()
        budget = float(p.get("weekly_load_budget", 45))
        # 条件1：恢复（范围未就绪时按 WHOOP 分区：≥66 绿 / 33–66 黄 / <33 红）
        rng = personal_range(self._recovery_daily(end), end)
        checks: list[dict] = []
        if rec is not None:
            if rng.ready:
                dv = deviation(rec, rng)
                checks.append({"name": "恢复", "pass": dv["state"] != "below",
                               "value": f"{rec:.0f}%（{dv['state']}，距边界 {dv['distance']}）"})
            else:
                zone = "绿" if rec >= 66 else ("黄" if rec >= 33 else "红")
                checks.append({"name": "恢复", "pass": zone != "红",
                               "value": f"{rec:.0f}%（WHOOP {zone}区，个人范围还在学习）"})
        # 昨日负荷：恢复缺失时它是第一判断依据，始终展示（有数据时）
        if y is not None and med > 0:
            checks.append({"name": "昨日负荷", "pass": not (y >= med * 2),
                           "value": f"{y:.1f} / 中位 {med:.1f}"})
        else:
            checks.append({"name": "昨日负荷", "pass": None, "value": "本周尚无记录"})
        # 睡眠债只在异常时上位提示（>3h）；它是降级依据而非运动否决项
        debt = self._debt(end)
        if debt is not None and (debt.get("debt_h") or 0) > 3:
            checks.append({"name": "睡眠债", "pass": None,
                           "value": f"{debt['debt_h']:.1f}h / 近 {debt.get('n_nights', 7)} 晚"})
        checks.append({"name": "周负荷 < 预算", "pass": load <= budget,
                       "value": f"{load:.1f} / {budget:.0f}"})
        hard_fail = any(c["pass"] is False for c in checks)
        unknown = any(c["pass"] is None for c in checks)
        if hard_fail:
            verdict = "不宜"
        elif unknown or (checks and "黄" in str(checks[0].get("value", ""))):
            verdict = "可以但轻一点"
        else:
            verdict = "宜"
        out = {"verdict": verdict, "checks": checks, "weekly_load": round(load, 1), "budget": budget}
        days14 = sorted(strain)[-14:]
        if days14:
            out["strain14"] = [{"date": str(d), "strain": round(strain[d], 1)} for d in days14]
        return out

    def _days_to_range(self, end: date) -> dict:
        """历史上跌出范围后平均几天回来（R3 同款口径，比斜率外推稳）。"""
        rec = self._recovery_daily(end)
        rng = personal_range(rec, end)
        if not rng.ready:
            return {"value": None, "label": "范围学习中"}
        days = sorted(rec)
        recoveries: list[float] = []
        i = 0
        while i < len(days):
            if rec[days[i]] < rng.low:
                j = i
                while j < len(days) and rec[days[j]] < rng.low:
                    j += 1
                if j < len(days):  # 后面回到了范围 → 该次跌出用了 (j - 跌出首日) 天
                    recoveries.append(float(j - i))
                i = j
            else:
                i += 1
        if len(recoveries) < 2:
            return {"value": None, "label": "还在积累恢复经验"}
        avg = fmean(recoveries)
        return {"value": round(avg, 1), "label": f"历史上跌出后平均 {avg:.1f} 天回范围"}

    def _hq_context(self, end: date, nights: dict, energy: dict) -> tuple[list, dict]:
        deep_rem = {}
        for d, n in nights.items():
            st = n.get("stages_h") or {}
            if st.get("slow_wave") is not None and st.get("rem") is not None:
                deep_rem[d] = st["slow_wave"] + st["rem"]
        rng = personal_range(deep_rem, end)
        hq_days = {}
        for d in sorted(nights):
            if end - timedelta(days=7) <= d < end:
                hq_days[d] = quality.hq_night(nights.get(d), energy.get(d), rng, self.params.all())
        diff = quality.hq_difficulty([None if h is None else h["pass"] for h in hq_days.values()])
        fail_counts: dict[str, int] = {}
        for h in hq_days.values():
            if h and h["fails"]:
                for q in h["fails"]:
                    fail_counts[q] = fail_counts.get(q, 0) + 1
        return hq_days, {"difficulty": diff, "fail_counts": fail_counts, "deep_rem_range": rng.to_dict()}

    def _needs_ctx(self, d: date) -> dict:
        """组装 needs 判断上下文的唯一入口（四页共用，规则不变）。

        原来是 today() 的内联块；抽出来是为了让三个专项页也能拿到同一份
        「你需要做」做服务端过滤——iOS 客户端不再自己按板块筛 needs。
        """
        p = self.params.all()
        rec_series = self._recovery_daily(d)
        debt = self._debt(d)
        hrv = self._hrv_daily(d)
        hrv_rng = personal_range(hrv, d)
        mon = self.t.monitor(d, now_hour=12)
        illness = any(f["level"] == "see_doctor" for f in mon["findings"])
        cov = self.t.coverage(now=datetime.combine(d, datetime.min.time().replace(hour=20), tzinfo=self.t.tz))
        play = self._play_ok(d)
        sessions = {"done": len(self._week_workouts(d)), "quota": int(p.get("weekly_quota", 3))}
        strain = self._strain_daily(d)
        y_strain = strain.get(d - timedelta(days=1))
        subj = self.t.subj.entries(kinds=["subj_latency"], since=d - timedelta(days=4), until=d)
        latency3 = [int((e["payload"] or {}).get("score", 0)) for e in subj
                    if (e["payload"] or {}).get("score")]
        ws = work_signals.load(day=d)
        return {
            "date": d, "params": p, "debt": debt, "illness": illness,
            "illness_flags": [f["metric"] for f in mon["findings"] if f["level"] in ("alert", "see_doctor")],
            "coverage": cov["sources"], "play": play, "weekly_sessions": sessions,
            "yesterday_strain": y_strain,
            "strain_median_30d": median([v for v in strain.values()]) if strain else 0,
            "has_workout_today": any(w["date"] == d for w in self._week_workouts(d)),
            "latency_last3": latency3[-3:],
            "hrv_streak_out": streak_out(hrv, hrv_rng, d),
            "free_slots": (ws or {}).get("free_slots"),
            "nap_total_h": self.t.nap_today()["total_h"],
            "daylight_low": False,
        }

    def _needs_for(self, d: date, session: str) -> list[dict]:
        """某个专项的「你需要做」：与 iOS 客户端同一过滤规则（specialty → session）。"""
        ctx = self._needs_ctx(d)
        all_needs = needs_mod.build_needs(ctx, self.t.subj.entries(kinds=["need_feedback"]), self.t._now())
        return [n for n in all_needs
                if layout.SESSION_OF_SPECIALTY.get(n.get("specialty")) == session]

    # ---------- D1 今日 ----------
    def today(self, day: date | None = None) -> dict:
        d = day or self.t._now().date()
        p = self.params.all()
        rec_series = self._recovery_daily(d)
        rng = personal_range(rec_series, d)
        rec = rec_series.get(d)
        spark = [(k, rec_series[k]) for k in sorted(rec_series) if d - timedelta(days=14) <= k <= d]
        debt = self._debt(d)
        hrv = self._hrv_daily(d)
        hrv_rng = personal_range(hrv, d)
        mon = self.t.monitor(d, now_hour=12)
        illness = any(f["level"] == "see_doctor" for f in mon["findings"])
        cov = self.t.coverage(now=datetime.combine(d, datetime.min.time().replace(hour=20), tzinfo=self.t.tz))
        play = self._play_ok(d)
        sessions = {"done": len(self._week_workouts(d)), "quota": int(p.get("weekly_quota", 3))}
        strain = self._strain_daily(d)
        y_strain = strain.get(d - timedelta(days=1))
        ctx = self._needs_ctx(d)
        needs_list = needs_mod.build_needs(ctx, self.t.subj.entries(kinds=["need_feedback"]), self.t._now())
        top = next((n for n in needs_list if n.get("top")), needs_list[0] if needs_list else None)
        headline = f"{top['title']}——{top['action']}" if top else "今天状态不错，照常就好"
        answered = {e["kind"] for e in self.t.subj.entries(
            kinds=["subj_energy", "subj_latency"], since=d, until=d)}
        # hero 候选池：恢复 / 睡眠债 / HRV；用户说「换一个」后 24h 内跳过该指标
        now_dt = self.t._now()
        skips = set()
        for e in self.t.subj.entries(kinds=["hero_skip"], since=now_dt.date() - timedelta(days=1)):
            raw = e.get("created_at") or ""
            try:
                at = datetime.fromisoformat(raw.split("+")[0] if "+" in raw else raw)
            except ValueError:
                continue
            if now_dt.replace(tzinfo=None) - at <= timedelta(hours=24):
                h = (e.get("payload") or {}).get("hero")
                if h:
                    skips.add(h)
        hrv_latest_date = max((k for k, v in hrv.items() if v is not None and k <= d), default=None)
        hrv_latest = hrv.get(hrv_latest_date) if hrv_latest_date else None
        hrv_spark = [{"date": k.isoformat(), "value": hrv[k]} for k in sorted(hrv)
                     if d - timedelta(days=14) <= k <= d]
        cands = []
        if rec is not None:
            cands.append({"value": rec, "unit": "%", "label": "恢复",
                          "deviation": deviation(rec, rng), "range": rng.to_dict(),
                          "spark": [{"date": k.isoformat(), "value": v} for k, v in spark]})
        if debt and (debt.get("debt_h") or 0) > 0.5:
            cands.append({"value": round(debt["debt_h"], 1), "unit": "h", "label": "睡眠债",
                          "deviation": {"state": "high", "distance": round(debt["debt_h"], 1)},
                          "range": {"low": None, "high": None, "n": 0, "ready": False,
                                    "learning_days": 0,
                                    "label": f"近 {debt.get('n_nights', 7)} 晚累计缺口"},
                          "spark": []})
        if hrv_latest is not None:
            cands.append({"value": hrv_latest, "unit": "ms", "label": "HRV",
                          "deviation": deviation(hrv_latest, hrv_rng),
                          "range": hrv_rng.to_dict(), "spark": hrv_spark})
        hero = next((c for c in cands if c["label"] not in skips),
                    cands[0] if cands else {
                        "value": None, "unit": "%", "label": "恢复",
                        "deviation": {"state": "no_data", "distance": None},
                        "range": rng.to_dict(), "spark": []})
        out = {
            "page": "today", "date": d.isoformat(), "params": p,
            "headline": headline,
            "hero": hero,
            "needs": needs_list,
            "push_count_today": self.t.subj.push_count(d.isoformat()),
            "push_cap": p.get("push_daily_cap", 5),
            "rating_card": {
                "energy_done": "subj_energy" in answered,
                "latency_done": "subj_latency" in answered,
                "ask_latency_today": d.day % 2 == 1,   # 隔天问（逢单日）
            },
            "chat_context": {"page": "今日", "date": d.isoformat(),
                             "fields": {"recovery": rec, "sleep_debt_h": (debt or {}).get("debt_h"),
                                        "needs": [n["need_type"] for n in needs_list]}},
            "contract": "数字全部来自字段层；结论句由 agent 在不改数字前提下润色",
        }
        out["components"] = layout.today_components(out)
        return out

    # ---------- D2 睡眠 ----------
    def sleep(self, day: date | None = None) -> dict:
        d = day or self.t._now().date()
        p = self.params.all()
        rec = self._recovery_daily(d).get(d)
        nights = self._nights(d)
        energy = quality.subjective_scores(self.t.subj.entries(kinds=["subj_energy"]), "subj_energy")
        latency = quality.subjective_scores(self.t.subj.entries(kinds=["subj_latency"]), "subj_latency")
        hq_days, hq = self._hq_context(d, nights, energy)
        debt = self._debt(d)
        chart = []
        for nd in sorted(nights):
            if d - timedelta(days=14) <= nd <= d:
                n = nights[nd]
                need = quality.night_need(n)
                hqp = hq_days.get(nd)
                chart.append({
                    "date": nd.isoformat(),
                    "actual": n.get("asleep_h"), "need": need,
                    "short": (need is not None and n.get("asleep_h") is not None
                              and need - n["asleep_h"] > 1.0),
                    "hq": None if hqp is None else hqp["pass"],
                    "fails": hqp["fails"] if hqp else [],
                    "checks": {c["qid"]: c["pass"] for c in hqp["checks"]} if hqp else {},
                })
        bed_times = {nd: ((n.get("start_local") or "")[11:16]) for nd, n in nights.items()
                     if n.get("start_local")}
        tgt_cache: dict[date, str | None] = {}

        def tgt(nd: date):
            if nd not in tgt_cache:
                tb = quality.target_bedtime(quality.night_need(nights.get(nd)), p, nd)
                tgt_cache[nd] = tb.get("bedtime")
            return tgt_cache[nd]

        on_time = quality.on_time_bed_stats(bed_times, tgt, d, int(p.get("on_time_grace_min", 15)))
        latest_need = quality.night_need(nights.get(max(nights))) if nights else None
        tonight = quality.target_bedtime(latest_need, p, d)
        caf = quality.caffeine_cutoff(tonight.get("bedtime"), p)
        confirm_pending = bool(hq_days) and not any(
            e["kind"] == "whoop_confirm" and e["local_date"] == d.isoformat()
            for e in self.t.subj.entries(kinds=["whoop_confirm"], since=d, until=d))
        last_hq = next((hq_days[k] for k in sorted(hq_days, reverse=True) if hq_days[k]), None)
        out = {
            "page": "sleep", "date": d.isoformat(),
            "recovery": rec,
            "needs": self._needs_for(d, "休息"),
            "goal": f"入睡难度 ≤{p.get('latency_target', 2)}，高质量睡眠难度 ≤{p.get('hq_target', 2)}",
            "headline": (f"高质量睡眠难度 {hq['difficulty']['score'] or '—'}，近 7 晚 {hq['difficulty']['nights_pass']} 晚达标"
                         + (f"，主要卡在 {_Q_NAMES.get(max(hq['fail_counts'], key=hq['fail_counts'].get), '')}"
                            if hq.get("fail_counts") else "")),
            "tiles": {
                "latency": quality.latency_weekly(latency, d, int(p.get("latency_target", 2))),
                "hq": hq["difficulty"], "debt": debt,
            },
            "hq_fail_counts": hq["fail_counts"],
            "chart14": chart,
            "on_time": on_time,
            "tonight": {
                "target": tonight,
                "caffeine_cutoff": caf,
                "plan_cutoff": p.get("relax_plan_cutoff", "21:30"),
                "plan_set_today": any(
                    e["kind"] == "relax_plan" and e["local_date"] == d.isoformat()
                    for e in self.t.subj.entries(kinds=["relax_plan"], since=d, until=d)),
            },
            "rating_card": {
                "energy_done": d in energy, "latency_done": d in latency,
                "ask_latency_today": d.day % 2 == 1,
            },
            "whoop_confirm": {
                "pending": confirm_pending,
                "claim": (f"WHOOP 判定昨晚{'高质量夜' if last_hq and last_hq['pass'] else '非高质量夜'}"
                          + (f"，卡在 {'、'.join(_Q_NAMES.get(f, f) for f in last_hq['fails'])}"
                             if last_hq and last_hq["fails"] else ""))
                if last_hq else None,
            },
            "deep_rem_range": hq["deep_rem_range"],
            "chat_context": {"page": "睡眠", "date": d.isoformat()},
        }
        out["components"] = layout.sleep_components(out)
        return out

    # ---------- E3 运动 ----------
    def sport(self, day: date | None = None) -> dict:
        d = day or self.t._now().date()
        p = self.params.all()
        rec = self._recovery_daily(d, 28)
        rng = personal_range(rec, d)
        strain = self._strain_daily(d)
        week = [v for k, v in strain.items() if d - timedelta(days=d.weekday()) <= k <= d]
        load = sum(week)
        workouts = self.t._whoop.get("workout", []) if self.t._whoop else []
        markers = []
        from .readonly import parse_ts
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(self.t.cfg.timezone)
        med = median([v for v in strain.values()]) if strain else 0
        for w in workouts:
            try:
                s = parse_ts(str(w["start"])).astimezone(tz)
            except Exception:
                continue
            if d - timedelta(days=28) <= s.date() <= d:
                markers.append({"date": s.date().isoformat(), "label": w.get("sport_name") or "运动",
                                "heavy": bool(med and ((w.get("score") or {}).get("strain") or 0) >= med * 2)})
        play = self._play_ok(d)
        out = {
            "page": "sport", "date": d.isoformat(),
            "needs": self._needs_for(d, "运动"),
            "goal": f"每周稳定 {p.get('weekly_quota', 3)} 场{p.get('sport_name', '')}，肩肘无伤",
            "band": {
                "series": [{"date": k.isoformat(), "value": v} for k, v in sorted(rec.items())],
                "range": rng.to_dict(),
                "markers": markers,
            },
            "tiles": {
                "sessions": {"done": len(self._week_workouts(d)),
                             "quota": int(p.get("weekly_quota", 3))},
                "load": {"used": round(load, 1), "budget": float(p.get("weekly_load_budget", 45))},
                "days_to_range": self._days_to_range(d),
            },
            "play": play,
            "modules": {
                "strength": {"freq": int(p.get("strength_freq_week", 2)), "done": 0,
                             "note": "力量完成次数由执行记录回填"},
                "post_stretch": {"minutes": 10, "note": "每场运动后"},
            },
            "chat_context": {"page": "运动", "date": d.isoformat()},
        }
        out["components"] = layout.sport_components(out)
        return out

    # ---------- E4 压力与恢复 ----------
    def stress(self, day: date | None = None) -> dict:
        d = day or self.t._now().date()
        rec = self._recovery_daily(d).get(d)
        hrv = self._hrv_daily(d, 14)
        rng = personal_range(self._hrv_daily(d, 30), d)
        out_points = []
        if rng.ready:
            out_points = [k.isoformat() for k, v in sorted(hrv.items()) if v < rng.low]
        ws = work_signals.status(d)
        tiles = {"available": ws["available"]}
        if ws["available"]:
            data = ws["data"]
            tiles.update({
                "meeting_hours": data.get("meeting_hours"),
                "late_online_nights": data.get("late_online"),
                "meeting_blocks": data.get("meeting_blocks_2h"),
            })
        suggestion = None
        if out_points:
            suggestion = {"title": "空档里走动 / 呼吸练习", "window": "当天空档",
                          "reason": f"HRV 有 {len(out_points)} 天低于你的常见范围"}
        elif not ws["available"]:
            suggestion = {"title": None, "note": "工作信号接入后给出个性化建议；当前只展示 HRV 走势"}
        out = {
            "page": "stress", "date": d.isoformat(),
            "recovery": rec,
            "needs": self._needs_for(d, "压力"),
            "goal": "高压周也守住 HRV",
            "band": {
                "series": [{"date": k.isoformat(), "value": v} for k, v in sorted(hrv.items())],
                "range": rng.to_dict(), "out_points": out_points,
            },
            "work_signals": ws,
            "tiles": tiles,
            "suggestion": suggestion,
            "correlation_note": "会议×HRV 等洞察待样本 ≥14 且工作信号接入后开启；相关不等于因果",
            "chat_context": {"page": "压力与恢复", "date": d.isoformat()},
        }
        out["components"] = layout.stress_components(out)
        return out
