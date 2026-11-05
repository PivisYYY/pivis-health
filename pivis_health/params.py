"""参数表（§7）：所有阈值初始值 + 对话修改留痕。

已确认决策（2026-11-01）：wake_target 08:20、推送 ≤5/天、免打扰=上床→起床、
放松缓冲 30 分钟、入睡缓冲 20 分钟（攒出个人中位数后由 agent 建议替换）。
"""
from __future__ import annotations

from typing import Any

from .subjective import SubjectiveStore

DEFAULTS: dict[str, Any] = {
    "wake_target": "08:20",
    "on_time_grace_min": 15,
    "weekend_bed_grace_min": 60,      # 周五/周六晚宽限（Day3 对话调整留痕的初始形态）
    "latency_buffer_min": 20,
    "relax_lead_min": 30,
    "relax_plan_cutoff": "21:30",
    "morning_deadline": "09:00",
    "push_daily_cap": 5,
    "dnd_mode": "bed_to_wake",
    "caffeine_cutoff_h": 8,
    "sport_name": "网球",
    "weekly_quota": 3,
    "weekly_load_budget": 45.0,
    "latency_target": 2,
    "hq_target": 2,
    "debt_alert_h": 1.0,
    "debt_high_h": 3.0,
    "evening_workout_cutoff_h": 3,
    "illness_alert_items": 3,
    "strength_freq_week": 2,
}


class Params:
    def __init__(self, store: SubjectiveStore) -> None:
        self.store = store
        self._cache: dict[str, Any] | None = None

    def all(self) -> dict[str, Any]:
        if self._cache is None:
            over = {r["key"]: r["value"] for r in self.store.params_list()}
            merged = dict(DEFAULTS)
            for k, v in over.items():
                merged[k] = self._coerce(k, v)
            self._cache = merged
        return dict(self._cache)

    def get(self, key: str) -> Any:
        return self.all().get(key)

    def set(self, key: str, value: Any, reason: str = "") -> dict:
        if key not in DEFAULTS:
            raise KeyError(f"unknown param: {key}")
        old = self.get(key)
        self.store.param_set(key, str(value), str(old), reason)
        self._cache = None
        return {"key": key, "old": old, "new": self._coerce(key, str(value)), "reason": reason}

    def changes(self) -> list[dict]:
        return self.store.params_history()

    @staticmethod
    def _coerce(key: str, raw: str) -> Any:
        default = DEFAULTS[key]
        try:
            if isinstance(default, bool):
                return raw.lower() in ("1", "true", "yes")
            if isinstance(default, int):
                return int(float(raw))
            if isinstance(default, float):
                return float(raw)
        except (TypeError, ValueError):
            return default
        return raw
