"""工具编排层：把只读客观库 + WHOOP 快照 + 主观库组装成对 agent 友好的查询与写入能力。

dsh 的 P-Health bot 通过 CLI（推荐）或 HTTP 调用这里；每个方法返回可 JSON 化的 dict。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any
from zoneinfo import ZoneInfo

from . import content, insights, whoop as whoop_mod
from .baselines import Baseline, daily_aggregate, direction, rolling_baseline
from .config import Config
from .readonly import ReadOnlyObjectiveStore
from .report import (
    QUESTION_POOL,
    behavior_buckets,
    build_advice_inputs,
    correlation_candidates,
    morning_assemble,
    weekly_assemble,
)
from .rules import Finding, MetricSeries, dnd_allows, evaluate as rules_evaluate
from .sleep import asleep_minute_sets, night_durations, sleep_from_rows
from .subjective import SubjectiveStore

APPLE_SERIES: dict[str, tuple[str, str]] = {
    # 规范名 → (sample_type, 聚合)
    "hrv": ("heart_rate_variability_sdnn", "mean"),
    "resting_heart_rate": ("resting_heart_rate", "mean"),
    "respiratory_rate": ("respiratory_rate", "mean"),
    "oxygen_saturation": ("oxygen_saturation", "mean"),
    "steps": ("step_count", "sum"),
    "active_energy": ("active_energy_burned", "sum"),
    "weight": ("body_mass", "mean"),
    "workout": ("workout", "count"),
}
WHOOP_SERIES = ("whoop_recovery", "whoop_strain", "whoop_hrv_rmssd", "whoop_skin_temp",
                "whoop_resting_hr", "whoop_resp_rate")
# Psir 每晚戴的是 WHOOP；这两项 Apple 健康里早没新数（手表不戴了）。
# 取数时：这段时间里 WHOOP 有就整段用 WHOOP，没有才用 Apple —— 一条序列只来自一个设备，不混算
# （睡眠时测的静息心率和白天手表测的口径不同，混在一起会把常态范围搞乱）。
PREFER_WHOOP = {"resting_heart_rate": "whoop_resting_hr", "respiratory_rate": "whoop_resp_rate"}
UNITS = {
    "hrv": "ms", "resting_heart_rate": "count/min", "respiratory_rate": "count/min",
    "oxygen_saturation": "%", "steps": "count", "active_energy": "kcal", "weight": "kg",
    "whoop_recovery": "%", "whoop_strain": "strain", "whoop_hrv_rmssd": "ms", "whoop_skin_temp": "°C",
    "whoop_resting_hr": "count/min", "whoop_resp_rate": "count/min",
}


class HealthTools:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.tz = ZoneInfo(config.timezone)
        self.store = ReadOnlyObjectiveStore(config.vault_db, config.timezone)
        self.subj = SubjectiveStore(config.subjective_db, config.timezone)
        self._whoop_sig: object = object()  # 快照文件 (mtime, size)；变了就重读
        self._whoop_cache: dict | None = None
        self._rows_cache: dict[date, tuple] = {}
        self._rows_sig: object = object()   # 健康库 + WAL 的 (mtime, size)；有新数据进来就清缓存

    @property
    def _whoop(self) -> dict | None:
        """WHOOP 快照。serve 进程常驻，whoop-sync 每 15 分钟原子替换文件 → 按 mtime 重新加载。"""
        try:
            st = Path(self.cfg.whoop_snapshot).stat()
            sig: object = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        if sig != self._whoop_sig:
            self._whoop_cache = whoop_mod.load_snapshot(self.cfg.whoop_snapshot) if sig else None
            self._whoop_sig = sig
        return self._whoop_cache

    def _now(self) -> datetime:
        from .clock import now as clock_now
        return clock_now(self.cfg)

    def _today(self) -> date:
        """Psir 的「今天」（凌晨 6 点前还算前一天），见 clock.day_of。"""
        from .clock import day_of
        return day_of(self._now())

    def _vault_sig(self) -> object:
        sig = []
        for suffix in ("", "-wal"):
            try:
                st = Path(str(self.cfg.vault_db) + suffix).stat()
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        return tuple(sig)

    def _rows(self, day: date) -> tuple[dict, ...]:
        """按天缓存健康库的读数。serve 进程常驻：库或 WAL 变了（Apple 健康、设备数据刚写进来）就整体作废，
        以前缓存一次就不再更新，第二天早上上传的睡眠要等服务器重启才看得到。"""
        sig = self._vault_sig()
        if sig != self._rows_sig:
            self._rows_cache.clear()
            self._rows_sig = sig
        if day not in self._rows_cache:
            self._rows_cache[day] = self.store.projection_rows(day)
        return self._rows_cache[day]

    def _sleep_results(self, end_day: date, days: int) -> dict[date, dict]:
        out: dict[date, dict] = {}
        for i in range(days):
            day = end_day - timedelta(days=i)
            try:
                out[day] = sleep_from_rows(self._rows(day), day, self.cfg.timezone)
            except Exception as exc:  # 门禁拒绝输出的是这一天的数字，不是整个系统
                out[day] = {"error": str(exc), "night": {"hours": 0.0, "stages": {}}, "nap": {"hours": 0.0, "stages": {}}, "notes": [str(exc)], "source_count": 0}
        return out

    # -- WHOOP 视图 -------------------------------------------------------
    def _whoop_views(self) -> dict:
        snap = self._whoop or {}
        return {
            "recovery": whoop_mod.recovery_by_day(snap, self.cfg.timezone),   # 按醒来那天：今早的恢复 = 今天的
            "sleep": whoop_mod.sleep_by_night(snap, self.cfg.timezone),
            "strain": whoop_mod.strain_by_day(snap, self.cfg.timezone),
            "latest": whoop_mod.latest_timestamps(snap, self.cfg.timezone),
        }

    def _whoop_freshness(self) -> dict:
        """WHOOP 同步是否跟上（超过 1 小时没成功算 stale）。"""
        try:
            from .whoop_sync import freshness
            return freshness(self.cfg)
        except Exception as exc:  # noqa: BLE001 —— 自检不能因为这一项挂掉
            return {"error": f"{type(exc).__name__}: {exc}"}

    # -- 序列 -------------------------------------------------------------
    def _apple_daily(self, canonical: str, end_day: date, days: int) -> dict[date, float]:
        sample_type, agg = APPLE_SERIES[canonical]
        rows = self.store.rows_of_type(sample_type, end_day - timedelta(days=days), end_day)
        return daily_aggregate(rows, self.cfg.timezone, agg)

    def _whoop_daily(self, canonical: str, end_day: date, days: int) -> dict[date, float]:
        views = self._whoop_views()
        source = {
            "whoop_recovery": views["recovery"],
            "whoop_strain": views["strain"],
        }
        if canonical in source:
            raw = source[canonical]
            return {d: float(v[{"whoop_recovery": "recovery_score", "whoop_strain": "strain"}[canonical]]) for d, v in raw.items() if v.get({"whoop_recovery": "recovery_score", "whoop_strain": "strain"}[canonical]) is not None}
        if canonical == "whoop_resp_rate":      # 呼吸频率在 WHOOP 的睡眠评分里：和 HRV、静息心率一样算到醒来那天
            return {d + timedelta(days=1): float(v["respiratory_rate"]) for d, v in views["sleep"].items()
                    if v.get("respiratory_rate") is not None}
        key = {"whoop_hrv_rmssd": "hrv_rmssd", "whoop_skin_temp": "skin_temp_celsius",
               "whoop_resting_hr": "resting_heart_rate"}[canonical]
        return {d: float(v[key]) for d, v in views["recovery"].items() if v.get(key) is not None}

    def series_source(self, canonical: str, end_day: date, days: int) -> str:
        """这条序列这段时间取自哪个设备（whoop / apple），给页面和 Agent 说清口径。"""
        if canonical in PREFER_WHOOP and self._whoop_window(PREFER_WHOOP[canonical], end_day, days):
            return "whoop"
        return "whoop" if canonical in WHOOP_SERIES else "apple"

    def _whoop_window(self, canonical: str, end_day: date, days: int) -> dict[date, float]:
        start = end_day - timedelta(days=days)
        return {d: v for d, v in self._whoop_daily(canonical, end_day, days).items() if start <= d <= end_day}

    def daily_series(self, canonical: str, end_day: date, days: int) -> dict[date, float]:
        if canonical in PREFER_WHOOP:
            w = self._whoop_window(PREFER_WHOOP[canonical], end_day, days)
            if w:
                return w
        if canonical in APPLE_SERIES:
            return self._apple_daily(canonical, end_day, days)
        if canonical in WHOOP_SERIES:
            return self._whoop_daily(canonical, end_day, days)
        raise KeyError(f"没有 {canonical} 这条序列。能用的：{', '.join(list(APPLE_SERIES) + list(WHOOP_SERIES))}；"
                       f"睡眠时长看 ./pivis-health viz --metric sleep 或 facts 里的 sleep_nights")

    # =========================================================
    # 命令实现
    # =========================================================
    def doctor(self) -> dict:
        latest = {t: ts.isoformat() for t, ts in self.store.latest_sample_at_by_type().items()}
        views = self._whoop_views()
        return {
            "ok": True,
            "timezone": self.cfg.timezone,
            "vault_db": str(self.cfg.vault_db),
            "vault_latest_by_type": latest,
            "whoop_snapshot": {
                "present": self._whoop is not None,
                "window": [self._whoop.get("window_start"), self._whoop.get("window_end")] if self._whoop else None,
                **views["latest"],
            },
            "whoop_sync": self._whoop_freshness(),
            "subjective_db": str(self.cfg.subjective_db),
            "subjective_schema": 1,
        }

    def sleep_day(self, day: date | None = None) -> dict:
        day = day or (self._today() - timedelta(days=1))   # 不给日期就是昨晚（按入睡那天记日期）
        result = sleep_from_rows(self._rows(day), day, self.cfg.timezone)
        views = self._whoop_views()
        w_sleep = views["sleep"].get(day)
        return {
            "local_date": day.isoformat(),
            "apple_watch": result,
            "whoop": w_sleep,
            "notes": result.get("notes", []),
        }

    def series(self, canonical: str, days: int = 30, end_day: date | None = None) -> dict:
        end = end_day or self._today()
        daily = self.daily_series(canonical, end, days)
        return {
            "metric": canonical,
            "unit": UNITS.get(canonical, ""),
            "days": days,
            "values": [
                {"date": d.isoformat(), "value": round(v, 3)} for d, v in sorted(daily.items())
            ],
        }

    def baseline(self, canonical: str, end_day: date | None = None) -> dict:
        end = end_day or self._today()
        daily = self.daily_series(canonical, end, 46)
        b: Baseline | None = rolling_baseline(daily, end_exclusive=end, window=30, metric=canonical)
        today_val = daily.get(end)
        z = b.z(today_val) if (b and today_val is not None) else None
        return {
            "metric": canonical,
            "unit": UNITS.get(canonical, ""),
            "baseline": b.to_dict() if b else None,
            "latest": {"date": end.isoformat(), "value": round(today_val, 3) if today_val is not None else None},
            "z": round(z, 2) if z is not None else None,
            "direction": direction(today_val, b) if today_val is not None else "unknown",
            "note": "样本不足 7 天时不给基线（缺数据 ≠ 正常也 ≠ 异常）",
        }

    def _rules_context(self, day: date) -> tuple[dict, dict]:
        """组装规则引擎上下文。返回 (kwargs, 辅助视图)。"""
        hrv = MetricSeries(self.daily_series("hrv", day, 46), "ms")
        rhr = MetricSeries(self.daily_series("resting_heart_rate", day, 46), "count/min")
        resp = MetricSeries(self.daily_series("respiratory_rate", day, 46), "count/min")
        views = self._whoop_views()
        wtemp = MetricSeries({d: v["skin_temp_celsius"] for d, v in views["recovery"].items() if v.get("skin_temp_celsius") is not None}, "°C")
        wrec = MetricSeries({d: v["recovery_score"] for d, v in views["recovery"].items() if v.get("recovery_score") is not None}, "%")
        wstrain = MetricSeries({d: v["strain"] for d, v in views["strain"].items() if v.get("strain") is not None}, "strain")
        sleeps = self._sleep_results(day, 8)
        nights = night_durations(sleeps)
        debt = insights.sleep_debt(nights, day)
        kwargs = {
            "hrv": hrv,
            "resting_heart_rate": rhr,
            "respiratory_rate": resp,
            "whoop_skin_temp": wtemp,
            "whoop_recovery": wrec,
            "whoop_strain": wstrain,
            "sleep_debt_h": debt["debt_h"] if debt else None,
            "custom_rules": self.subj.list_rules(),
        }
        extras = {"hrv_series": hrv, "nights": nights, "debt": debt, "views": views}
        return kwargs, extras

    def monitor(self, day: date | None = None, now_hour: int | None = None) -> dict:
        d = day or self._today()
        hour = self._now().hour if now_hour is None else now_hour
        kwargs, _ = self._rules_context(d)
        findings = rules_evaluate(d, **kwargs)
        out = []
        for f in findings:
            item = f.to_dict()
            item["dnd_blocked"] = not dnd_allows(f.level, hour, self.cfg.dnd_hours)
            out.append(item)
        return {
            "local_date": d.isoformat(),
            "now_hour": hour,
            "dnd_hours": list(self.cfg.dnd_hours),
            "findings": out,
            "summary": {
                "see_doctor": sum(1 for f in findings if f.level == "see_doctor"),
                "alert": sum(1 for f in findings if f.level == "alert"),
                "notice": sum(1 for f in findings if f.level == "notice"),
            },
            "non_diagnostic": True,
        }

    def today(self, day: date | None = None) -> dict:
        d = day or self._today()
        kwargs, extras = self._rules_context(d)
        views = extras["views"]
        sleep = self._sleep_results(d, 1).get(d)
        hrv_daily = kwargs["hrv"].daily
        w_rec = views["recovery"].get(d)
        w_strain = views["strain"].get(d - timedelta(days=1))
        weight_series = self.daily_series("weight", d, 30)
        return {
            "local_date": d.isoformat(),
            "sleep": {
                "night_h": sleep["night"]["hours"] if sleep else None,
                "nap_h": sleep["nap"]["hours"] if sleep else None,
                "stages": sleep["night"]["stages"] if sleep else None,
                "notes": (sleep or {}).get("notes", []),
            },
            "hrv": {
                "today": round(hrv_daily.get(d), 1) if hrv_daily.get(d) is not None else None,
                "unit": "ms (SDNN)",
            },
            "whoop": {
                "recovery": w_rec,
                "yesterday_strain": w_strain,
            },
            "weight": {"latest": round(list(weight_series.values())[-1], 1) if weight_series else None,
                        "latest_date": max(weight_series).isoformat() if weight_series else None},
            "subjective_entries_today": [
                {"kind": e["kind"], "payload": e["payload"]}
                for e in self.subj.entries(since=d, until=d)
            ],
        }

    def morning_report(self, day: date | None = None) -> dict:
        d = day or self._today()
        kwargs, extras = self._rules_context(d)
        views = extras["views"]
        sleep = self._sleep_results(d, 1).get(d)
        sleep_arrived = bool(sleep and sleep.get("source_count", 0) > 0 and sleep["night"]["hours"] > 0)
        night_h = sleep["night"]["hours"] if sleep else None

        hrv_daily = kwargs["hrv"].daily
        hrv_b = rolling_baseline(hrv_daily, end_exclusive=d, window=30, metric="hrv")
        hrv_today = hrv_daily.get(d)
        hrv_z = hrv_b.z(hrv_today) if (hrv_b and hrv_today is not None) else None
        hrv_verdict = insights.hrv_verdict(hrv_z)

        rhr_daily = kwargs["resting_heart_rate"].daily
        resp_daily = kwargs["respiratory_rate"].daily
        spo2_daily = self.daily_series("oxygen_saturation", d, 2)
        steps_yesterday = self.daily_series("steps", d, 2).get(d - timedelta(days=1))
        energy_yesterday = self.daily_series("active_energy", d, 2).get(d - timedelta(days=1))

        w_rec = views["recovery"].get(d)
        w_sleep = views["sleep"].get(d)
        w_strain = views["strain"].get(d - timedelta(days=1))
        if w_sleep and w_sleep.get("sleep_needed_h"):
            need = w_sleep["sleep_needed_h"]
            need_h = round(sum(v for v in need.values() if v is not None), 2)
        else:
            need_h = insights.sleep_need_from_debt(extras["nights"], self.daily_series("steps", d, 3), d)
        bedtime = insights.suggested_bedtime(need_h, self.cfg.fixed_wake_time, self.cfg.buffer_minutes) if need_h else None

        findings = [f.to_dict() for f in rules_evaluate(d, **kwargs)]
        for f in findings:
            f["level_rank"] = {"notice": 1, "alert": 2, "see_doctor": 3}.get(f["level"], 0)

        trend14 = self.daily_series("hrv", d, 14)
        rec14 = self.daily_series("whoop_recovery", d, 14)

        questions = self.subj.rotation_pick(QUESTION_POOL, d.isoformat(), k=2)
        # 缺数据的夜不算"睡 0 小时"——建议素材只信真实到达的睡眠
        night_for_advice = night_h if sleep_arrived else None
        advice = build_advice_inputs(
            hrv_z=hrv_z, night_hours=night_for_advice,
            sleep_debt_h=extras["debt"]["debt_h"] if extras["debt"] else None,
            whoop_recovery=w_rec.get("recovery_score") if w_rec else None,
            suggested_bedtime=bedtime, sleep_need_h=need_h,
        )
        metrics_block = {
            "hrv": {"today": round(hrv_today, 1) if hrv_today is not None else None,
                     "baseline": round(hrv_b.center, 1) if hrv_b else None,
                     "z": round(hrv_z, 2) if hrv_z is not None else None,
                     "verdict": hrv_verdict, "unit": "ms (SDNN)"},
            "whoop_hrv_rmssd_last_night": (w_rec or {}).get("hrv_rmssd"),
            "resting_heart_rate": round(rhr_daily.get(d), 1) if rhr_daily.get(d) is not None else None,
            "respiratory_rate": round(resp_daily.get(d), 2) if resp_daily.get(d) is not None else None,
            "oxygen_saturation": round(spo2_daily.get(d), 1) if spo2_daily.get(d) is not None else None,
            "steps_yesterday": int(steps_yesterday) if steps_yesterday else None,
            "active_energy_yesterday": int(energy_yesterday) if energy_yesterday else None,
        }
        whoop_block = None
        if w_rec or w_sleep or w_strain:
            whoop_block = {
                "recovery": w_rec,
                "sleep": w_sleep,
                "yesterday_strain": w_strain,
                "sleep_need_h": need_h,
                "suggested_bedtime": bedtime,
            }
        charts = {
            "sleep_stages": sleep["night"]["stages"] if sleep else None,
            "hrv_trend_14d": {
                "dates": [x.isoformat() for x in sorted(trend14)],
                "values": [round(trend14[x], 1) for x in sorted(trend14)],
                "baseline": round(hrv_b.center, 1) if hrv_b else None,
            },
            "recovery_trend_14d": {
                "dates": [x.isoformat() for x in sorted(rec14)],
                "values": [round(rec14[x], 0) for x in sorted(rec14)],
            },
        }
        return morning_assemble(
            local_date=d.isoformat(),
            sleep=sleep,
            sleep_arrived=sleep_arrived,
            metrics=metrics_block,
            whoop=whoop_block,
            findings=findings,
            questions=questions,
            advice_inputs=advice,
            charts=charts,
            generated_at=self._now().isoformat(timespec="seconds"),
        )

    def weekly_report(self, week_start: date | None = None) -> dict:
        d = self._today()
        monday = week_start or (d - timedelta(days=d.weekday()))
        sunday = monday + timedelta(days=6)
        sleeps = self._sleep_results(monday + timedelta(days=6), 7)
        nights = night_durations(sleeps)
        week_nights = {k: v for k, v in nights.items() if monday <= k <= sunday}
        hrv_daily = self.daily_series("hrv", sunday, 46)
        week_hrv = [hrv_daily[k] for k in sorted(hrv_daily) if monday <= k <= sunday]
        steps = self.daily_series("steps", sunday, 7)
        week_steps = {k: v for k, v in steps.items() if monday <= k <= sunday}
        strain = self.daily_series("whoop_strain", sunday, 14)
        week_strain = [strain[k] for k in sorted(strain) if monday <= k <= sunday]
        prev_strain = [strain[k] for k in sorted(strain) if monday - timedelta(days=7) <= k < monday]
        weight = self.daily_series("weight", sunday, 21)
        w_vals = [(k, v) for k, v in sorted(weight.items()) if k <= sunday]
        weight_delta = round(w_vals[-1][1] - w_vals[0][1], 2) if len(w_vals) >= 2 else None

        rows_by_day = {k: list(self._rows(k)) for k in week_nights}
        sets = asleep_minute_sets(rows_by_day, self.cfg.timezone)
        all_rows = {dd: list(self._rows(dd)) for dd in [monday - timedelta(days=i) for i in range(28)]}
        sri = insights.sri_index(asleep_minute_sets(all_rows, self.cfg.timezone), monday + timedelta(days=7))
        jetlag = insights.social_jetlag(insights.night_intervals(all_rows))

        entries = self.subj.entries(kinds=["behavior_answer"], since=monday - timedelta(days=21), until=sunday)
        buckets = behavior_buckets(entries)
        outcomes = {
            "night_sleep_h": nights,
            "hrv": hrv_daily,
        }
        cands = correlation_candidates(buckets, outcomes)

        window = {
            "nights_n": len(week_nights),
            "night_avg_h": round(fmean(week_nights.values()), 2) if week_nights else None,
            "hrv_avg": round(fmean(week_hrv), 1) if week_hrv else None,
            "steps_total": int(sum(week_steps.values())),
            "strain_avg": round(fmean(week_strain), 1) if week_strain else None,
            "strain_prior_avg": round(fmean(prev_strain), 1) if prev_strain else None,
            "weight_delta_kg": weight_delta,
        }
        return weekly_assemble(
            week_of=monday.isoformat(),
            window=window,
            sri=sri,
            jetlag=jetlag,
            correlations=cands,
            generated_at=self._now().isoformat(timespec="seconds"),
        )

    # -- 主观写入 -----------------------------------------------------------
    def log_subjective(self, kind: str, payload: dict, day: date | None = None) -> dict:
        d = day or self._today()
        entry_id = self.subj.record(d.isoformat(), kind, payload)
        return {"ok": True, "id": entry_id, "local_date": d.isoformat(), "kind": kind, "payload": payload}

    def need_feedback(self, need_type: str, action: str) -> dict:
        payload = {"need_type": need_type, "action": action}
        result = self.log_subjective("need_feedback", payload)
        from .agent_context import AgentContextStore
        shared = AgentContextStore(self.cfg).record(
            f"need.feedback.{need_type}", payload, source_session="ios-client",
            reason="用户在客户端执行待办动作；只表示执行反馈，不代表健康效果")
        result["shared_revision"] = shared["revision"]
        return result

    def answer_question(self, question_id: str, answer: str, day: date | None = None) -> dict:
        pool = {q["id"]: q for q in QUESTION_POOL}
        q = pool.get(question_id)
        if q is None:
            raise KeyError(f"unknown question_id: {question_id}")
        payload = {"question_id": question_id, "answer": answer}
        if question_id == "subjective_sleep":
            try:
                payload["score"] = int(str(answer).strip()[0])
            except (ValueError, IndexError):
                pass
        return self.log_subjective(q["kind"], payload, day)

    # -- 规则管理 -----------------------------------------------------------
    def rules_add(self, metric: str, comparator: str, threshold: float, days: int, level: str, note: str = "") -> dict:
        allowed = set(APPLE_SERIES) | set(WHOOP_SERIES) | {"sleep_debt"}
        if metric not in allowed:
            raise KeyError(f"unknown metric: {metric}; allowed: {sorted(allowed)}")
        rid = self.subj.add_rule(metric, comparator, threshold, days, level, note, UNITS.get(metric, ""))
        return {"ok": True, "rule_id": rid, "rule": self.subj.list_rules() and [r for r in self.subj.list_rules() if r["id"] == rid][0]}

    def rules_list(self) -> dict:
        return {"rules": self.subj.list_rules()}

    def rules_remove(self, rule_id: int) -> dict:
        return {"ok": self.subj.remove_rule(rule_id)}

    # -- 推送配额与去重 -------------------------------------------------------
    def push_reserve(self, key: str, day: date | None = None) -> dict:
        """当日去重 + 配额：首次且未超配额返回 allowed=True（并记账）。"""
        d = (day or self._today()).isoformat()
        count = self.subj.push_count(d)
        if count >= self.cfg.daily_push_limit:
            return {"allowed": False, "reason": "daily_push_limit_reached", "count_today": count, "limit": self.cfg.daily_push_limit}
        first = self.subj.push_once(d, key)
        if not first:
            return {"allowed": False, "reason": "already_sent_today", "count_today": count + 1, "limit": self.cfg.daily_push_limit}
        return {"allowed": True, "count_today": count + 1, "limit": self.cfg.daily_push_limit}

    # -- 晨报事件触发（WHOOP 到达即出，最晚 09:00）----------------------------
    def morning_wait(self, deadline: str = "09:00", poll_sec: int = 60) -> dict:
        """轮询 WHOOP recovery 今日是否有值；有则返回晨报，无则等到 deadline 返回降级版。"""
        import time as _time
        from datetime import datetime, timedelta
        now = self._now()
        dl = now.replace(hour=int(deadline[:2]), minute=int(deadline[3:]), second=0)
        while now < dl:
            views = self._whoop_views()
            today_rec = views["recovery"].get(now.date())
            if today_rec and today_rec.get("recovery_score") is not None:
                return {"trigger": "whoop_arrived", **self.morning_report(now.date())}
            _time.sleep(poll_sec)
            now = self._now()
        return {"trigger": "deadline_fallback", **self.morning_report(self._today())}

    def nap_today(self) -> dict:
        """WHOOP nap 条目（今日小憩），午休自动识别。"""
        snap = self._whoop or {}
        tz = self.tz
        from .readonly import parse_ts as _pt
        from .whoop import _to_local
        naps = []
        for s in snap.get("sleep", []):
            if not s.get("nap"):
                continue
            try:
                start = _to_local(str(s["start"]), tz)
                if start.date() == self._today():
                    end = _to_local(str(s["end"]), tz)
                    naps.append({"start": start.isoformat(), "end": end.isoformat(),
                                 "hours": round((end - start).total_seconds() / 3600, 2)})
            except Exception:
                continue
        return {"naps": naps, "total_h": round(sum(n["hours"] for n in naps), 2) if naps else 0}

    # -- 放松页（F5）--------------------------------------------------------
    def relax_library(self) -> dict:
        entries = self.subj.entries(kinds=["content_rating"])
        scores = content.rating_scores(entries)
        items = []
        for it in content.LIBRARY:
            s = scores.get(it["id"], {"good": 0, "bad": 0})
            items.append({**{k: v for k, v in it.items() if k != "embed"}, "embed": it["embed"], "ratings": s})
        return {"categories": content.CATEGORY_ORDER, "items": items}

    def relax_suggest(self) -> dict:
        scores = content.rating_scores(self.subj.entries(kinds=["content_rating"]))
        return {"suggested": content.suggest(scores)}

    def relax_plan_save(self, item_ids: list[str]) -> dict:
        plan = content.tonight_plan(item_ids)
        if not plan:
            raise ValueError("no valid items")
        payload = {"items": [it["id"] for it in plan],
                   "titles": [it["title"] for it in plan]}
        self.subj.record(self._today().isoformat(), "relax_plan", payload)
        return {"ok": True, "plan": payload["titles"], "items": plan}

    def content_rate(self, item_id: str, rating: str) -> dict:
        if rating not in ("good", "bad"):
            raise ValueError("rating must be good|bad")
        if content.item_by_id(item_id) is None:
            raise KeyError(f"unknown item: {item_id}")
        return self.log_subjective("content_rating", {"item_id": item_id, "rating": rating})

    # -- 与P-Health对话（dsh web API 直连）------------------------------------------
    def chat_history(self, limit: int = 20, after_time: str | None = None, context: str = "") -> dict:
        from . import dsh_chat
        return dsh_chat.chat_history(limit, after_time, context)

    def chat_send(self, text: str, context: str = "") -> dict:
        from . import dsh_chat
        return dsh_chat.chat_send(text, context)

    # -- 覆盖核对（F3：分源、≥3 天才报、摘表豁免说明） ------------------------
    def coverage(self, now: datetime | None = None) -> dict:
        now = now or self._now()
        today = now.date()
        latest = self.store.latest_sample_at_by_type()
        core = {
            "sleep_analysis": "睡眠",
            "heart_rate": "心率（管道活性）",
            "heart_rate_variability_sdnn": "HRV",
            "resting_heart_rate": "静息心率",
        }
        sources = []
        for t, label in core.items():
            ts = latest.get(t)
            last_local_date = ts.astimezone(self.tz).date() if ts else None
            gap_days = (today - last_local_date).days if last_local_date else None
            sources.append({
                "source": "apple", "type": t, "label": label,
                "last_data_local": ts.astimezone(self.tz).isoformat() if ts else None,
                "gap_days": gap_days,
                "notify": bool(gap_days is not None and gap_days >= 3),
            })
        views = self._whoop_views()
        w_latest = views["latest"].get("whoop_latest_local")
        w_gap = None
        if w_latest:
            w_gap = (today - datetime.fromisoformat(w_latest).date()).days
        sources.append({
            "source": "whoop", "type": "snapshot", "label": "WHOOP 快照",
            "last_data_local": w_latest,
            "gap_days": w_gap,
            "notify": bool(w_gap is not None and w_gap >= 3),
        })
        shower = [
            e for e in self.subj.entries(kinds=["behavior_answer"], since=today, until=today)
            if (e.get("payload") or {}).get("question_id") == "shower_time"
        ]
        notify_any = any(s["notify"] for s in sources)
        return {
            "local_date": today.isoformat(),
            "sources": sources,
            "watch_off_note_today": bool(shower),
            "notify": notify_any,
            "rule": "单一来源断更 ≥3 天才提醒；缺数据 ≠ 身体异常；摘表时段已在覆盖核对时豁免说明",
        }
