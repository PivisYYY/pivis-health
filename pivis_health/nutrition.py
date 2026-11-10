"""营养（build 53，老大 11-10：P-Health 要有专业营养师的能力）。

- 目标：Mifflin-St Jeor 算基础代谢，按近 7 天步数和训练定活动系数，有减重目标就打 15–25% 缺口（有伤在养就最多 15%）；
  蛋白质按体重（减重 + 训练 1.6–2.2 g/kg，有伤 ≥ 1.6，其他 1.2–1.6），换算成手掌份量。
- 饭：P-Health 从照片估「手掌份量」（掌心蛋白、一捧主食、一拳蔬菜、一拇指油脂），服务器换成蛋白质克数和热量的**范围**。
  P-Health 自己不编克数和热量，回复里的数都来自这里，而且都是范围（照片估不准，范围就是诚实的说法）。
数据：data_dir/nutrition_log.jsonl（只追加；同一个 id 再写一行就是改，deleted=true 是删）。
"""
from __future__ import annotations

import json
import re
import secrets
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

FILE = "nutrition_log.jsonl"
MEALS = {"breakfast": "早饭", "lunch": "午饭", "dinner": "晚饭", "snack": "加餐"}
PORTION_KEYS = ("protein_palms", "carb_hands", "veg_fists", "fat_thumbs")
CONFIDENCE = ("low", "mid", "high")
# 一份手掌份量（熟重）大约对应多少：Precision Nutrition 手掌份量法，按中式做法放宽成范围
HAND = {
    "protein_palms": {"protein_g": (20, 30), "kcal": (100, 150), "fat_g": (2, 8)},     # 掌心大小、厚度的肉鱼蛋豆腐
    "carb_hands": {"carbs_g": (20, 30), "kcal": (90, 130), "protein_g": (2, 4)},      # 一捧熟米饭 / 面 / 薯类
    "veg_fists": {"kcal": (15, 40), "fiber_g": (1.5, 3.5), "carbs_g": (3, 7), "protein_g": (1, 2)},   # 一拳蔬菜
    "fat_thumbs": {"fat_g": (7, 12), "kcal": (65, 110)},                               # 一拇指油、酱、坚果
}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class NutritionError(ValueError):
    pass


# ---------------------------------------------------------------- 目标
def _profile(cfg) -> dict:
    from .agent_context import AgentContextStore
    out: dict[str, Any] = {}
    for e in AgentContextStore(cfg).snapshot()["entries"]:
        if str(e.get("scope", "")).startswith("profile.body"):
            out.update({k: v for k, v in (e.get("payload") or {}).items() if v not in (None, "")})
    return out


def _activity(tools, today: date) -> tuple[float, str]:
    """活动系数：近 7 天平均步数 + 训练次数（WHOOP）。"""
    steps = []
    try:
        steps = [v for v in tools.daily_series("steps", today, 7).values() if v]
    except Exception:  # noqa: BLE001
        pass
    sessions = 0
    try:
        from . import whoop as whoop_mod
        start = (today - timedelta(days=6)).isoformat()
        sessions = sum(1 for w in whoop_mod.workouts(tools._whoop or {}, tools.cfg.timezone) if start <= w["date"] <= today.isoformat())
    except Exception:  # noqa: BLE001
        pass
    avg = sum(steps) / len(steps) if steps else None
    if avg is None:
        f, why = 1.375, "没有步数，按轻度活动"
    elif avg < 5000:
        f, why = 1.25, f"近 7 天平均 {int(avg)} 步"
    elif avg < 7500:
        f, why = 1.375, f"近 7 天平均 {int(avg)} 步"
    elif avg < 10000:
        f, why = 1.5, f"近 7 天平均 {int(avg)} 步"
    else:
        f, why = 1.6, f"近 7 天平均 {int(avg)} 步"
    if sessions >= 3:
        f += 0.1
        why += f"，训练 {sessions} 次"
    elif sessions:
        why += f"，训练 {sessions} 次"
    return round(f, 3), why


def _weight(tools, today: date) -> tuple[float | None, str | None]:
    try:
        w = tools.daily_series("weight", today, 90)
    except Exception:  # noqa: BLE001
        return None, None
    if not w:
        return None, None
    last = max(w)
    return round(float(w[last]), 1), last.isoformat()


def targets(tools, today: date | None = None) -> dict:
    from . import goals as goals_mod
    from . import rehab
    cfg = tools.cfg
    today = today or tools._today()
    prof = _profile(cfg)
    kg, kg_date = _weight(tools, today)
    missing = [label for key, label in (("sex", "性别"), ("age", "年龄"), ("height_cm", "身高")) if not prof.get(key)]
    if kg is None:
        missing.append("最近的体重")
    goal = next((g for g in goals_mod.load(cfg) if g.get("metric") == "weight"), None)
    losing = bool(goal and kg and float(goal.get("target") or 0) < kg)
    injured = bool(rehab.active(cfg))
    training = False
    factor, act_why = _activity(tools, today)
    training = "训练" in act_why
    out: dict[str, Any] = {"profile": {**{k: prof.get(k) for k in ("sex", "age", "height_cm")}, "weight_kg": kg, "weight_date": kg_date},
                           "missing": missing, "goal": "减重" if losing else "维持", "injured": injured,
                           "activity_factor": factor, "activity_basis": act_why}
    # 蛋白质（按体重，BMI ≥ 30 用 BMI 25 时的体重算，免得高估）
    if kg:
        ref = kg
        h = float(prof.get("height_cm") or 0) / 100
        if h and kg / (h * h) >= 30:
            ref = round(25 * h * h, 1)
            out["protein_ref_kg"] = ref
        lo, hi = (1.6, 2.2) if (losing and training) else (1.6, 2.0) if (losing or injured) else (1.2, 1.6)
        if injured:
            lo = max(lo, 1.6)
        out["protein_g"] = [round(lo * ref), round(hi * ref)]
        out["protein_basis"] = f"{lo}–{hi} g/kg × {ref} kg" + ("（有伤在养，不低于 1.6）" if injured else "")
        out["fat_g_min"] = round(0.6 * kg)
        out["water_ml"] = [round(30 * kg / 50) * 50, round(35 * kg / 50) * 50]
    out["fiber_g"] = [25, 30]
    # 热量
    if not missing:
        w, hcm, age = kg, float(prof["height_cm"]), float(prof["age"])
        bmr = 10 * w + 6.25 * hcm - 5 * age + (5 if str(prof["sex"]).lower() in ("male", "m", "男") else -161)
        tdee = bmr * factor
        if losing:
            lo_f, hi_f = (0.85, 0.9) if injured else (0.75, 0.85)
        else:
            lo_f, hi_f = 0.95, 1.05
        lo_k, hi_k = max(tdee * lo_f, bmr), max(tdee * hi_f, bmr)
        out.update({"bmr": round(bmr), "tdee": round(tdee), "kcal_target": [round(lo_k, -1), round(hi_k, -1)],
                    "kcal_basis": f"Mifflin-St Jeor 基础代谢 {round(bmr)} × 活动 {factor}（{act_why}）"
                                  + (f"，减重缺口 {round((1 - hi_f) * 100)}–{round((1 - lo_f) * 100)}%" if losing else "")
                                  + ("，有伤在养缺口不超过 15%" if losing and injured else "")})
    # 手掌份量（一天 / 一餐，按 3 餐）
    if out.get("protein_g"):
        p_mid = sum(out["protein_g"]) / 2
        palms = round(p_mid / 25 * 2) / 2
        hands: dict[str, Any] = {"protein_palms": palms, "veg_fists": [4, 6]}
        if out.get("kcal_target"):
            # 按每份热量的中间值配平：先放蛋白质和蔬菜，油脂补到总脂肪约 25%（蛋白质食物里自带的脂肪先扣掉），剩下的给主食
            mid = {k: sum(v["kcal"]) / 2 for k, v in HAND.items()}
            k_mid = sum(out["kcal_target"]) / 2
            veg = 5
            fat_g = max(out["fat_g_min"], 0.25 * k_mid / 9)
            thumbs = round(max(0.0, fat_g - palms * sum(HAND["protein_palms"]["fat_g"]) / 2) / 9.5 * 2) / 2
            used = palms * mid["protein_palms"] + veg * mid["veg_fists"] + thumbs * mid["fat_thumbs"]
            hands["carb_hands"] = round(max(0.0, k_mid - used) / mid["carb_hands"] * 2) / 2
            hands["fat_thumbs"] = thumbs
        out["hands_per_day"] = hands
        out["per_meal"] = {k: (round(v / 3 * 2) / 2 if isinstance(v, (int, float)) else [1, 2]) for k, v in hands.items()}
    return out


# ---------------------------------------------------------------- 饭
def _path(cfg) -> Path:
    return Path(cfg.data_dir) / FILE


def estimate(portions: dict) -> dict:
    """手掌份量 → 蛋白质、碳水、脂肪、膳食纤维、热量的范围。"""
    tot = {k: [0.0, 0.0] for k in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")}
    for key, n in portions.items():
        for nut, (lo, hi) in HAND.get(key, {}).items():
            tot[nut][0] += lo * n
            tot[nut][1] += hi * n
    return {k: [round(lo), round(hi)] for k, (lo, hi) in tot.items()}


def _check(entry: dict) -> dict:
    meal = entry.get("meal")
    if meal not in MEALS:
        raise NutritionError(f"meal 只能是 {tuple(MEALS)}")
    day = str(entry.get("date") or "")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise NutritionError("date 要写 YYYY-MM-DD") from None
    at = str(entry.get("at") or "")
    if at and not _HHMM.match(at):
        raise NutritionError("at 要写 HH:MM")
    raw = entry.get("portions") or {}
    if not isinstance(raw, dict) or set(raw) - set(PORTION_KEYS):
        raise NutritionError(f"portions 只能写 {PORTION_KEYS}（手掌份量，可以写 0.5）")
    portions = {}
    for k in PORTION_KEYS:
        v = float(raw.get(k) or 0)
        if not 0 <= v <= 10 or round(v * 2) != v * 2:
            raise NutritionError(f"portions.{k} 要在 0–10 之间，按 0.5 递增")
        portions[k] = v
    if not any(portions.values()):
        raise NutritionError("portions 至少写一项：照片里看到多少掌心蛋白、几捧主食、几拳蔬菜、几拇指油")
    conf = entry.get("confidence") or "mid"
    if conf not in CONFIDENCE:
        raise NutritionError(f"confidence 只能是 {CONFIDENCE}")
    dishes = [str(x).strip()[:20] for x in entry.get("dishes") or [] if str(x).strip()][:8]
    return {"date": day, "meal": meal, "at": at, "dishes": dishes, "portions": portions, "confidence": conf,
            "note": str(entry.get("note") or "")[:80], "todo": entry.get("todo") or None, "photo": entry.get("photo") or None}


def log(cfg, entry: dict) -> dict:
    """记一餐；同一个 id 再记就是改；{"id": …, "deleted": true} 是删（记错了）。"""
    if entry.get("deleted"):
        if not entry.get("id"):
            raise NutritionError("删要写 id")
        row = {"id": str(entry["id"]), "deleted": True, "at_logged": datetime.now().isoformat(timespec="seconds")}
        with _path(cfg).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
    row = _check(entry)
    row["id"] = str(entry.get("id") or f"m{int(time.time() * 1000)}{secrets.token_hex(2)}")
    row["est"] = estimate(row["portions"])
    row["at_logged"] = datetime.now().isoformat(timespec="seconds")
    with _path(cfg).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def entries(cfg, day: str | None = None, since: str | None = None) -> list[dict]:
    """每个 id 的最后一版（删掉的不要），按日期和时间排。"""
    last: dict[str, dict] = {}
    try:
        with _path(cfg).open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                last[r.get("id")] = r
    except OSError:
        return []
    rows = [r for r in last.values() if not r.get("deleted")
            and (day is None or r.get("date") == day) and (since is None or str(r.get("date")) >= since)]
    return sorted(rows, key=lambda r: (r.get("date", ""), r.get("at") or "99:99"))


def _sum(rows: list[dict]) -> dict:
    tot = {k: [0, 0] for k in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")}
    hands = {k: 0.0 for k in PORTION_KEYS}
    for r in rows:
        for k, (lo, hi) in r["est"].items():
            tot[k][0] += lo
            tot[k][1] += hi
        for k in PORTION_KEYS:
            hands[k] += r["portions"].get(k, 0)
    return {"est": tot, "hands": hands}


def _night(hhmm: str) -> int:
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return (h + 24 if h < 6 else h) * 60 + m


def day_summary(tools, day: date | None = None, tg: dict | None = None) -> dict:
    from . import timedraft
    day = day or tools._today()
    tg = tg if tg is not None else targets(tools, day)
    rows = entries(tools.cfg, day.isoformat())
    s = _sum(rows)
    flags = []
    p_mid = sum(s["est"]["protein_g"]) / 2
    if rows and tg.get("protein_g") and p_mid < tg["protein_g"][0]:
        flags.append(f"蛋白质约 {s['est']['protein_g'][0]}–{s['est']['protein_g'][1]} g，比目标下限 {tg['protein_g'][0]} g 少")
    low_meals = [MEALS[r["meal"]] for r in rows if r["meal"] != "snack" and sum(r["est"]["protein_g"]) / 2 < 25]
    if low_meals:
        flags.append("、".join(low_meals) + " 蛋白质不到 25 g（每餐 1–1.5 掌心更好）")
    if rows and s["hands"]["veg_fists"] < 3 and len([r for r in rows if r["meal"] != "snack"]) >= 2:
        flags.append(f"蔬菜只有约 {s['hands']['veg_fists']:g} 拳（一天 4–6 拳）")
    bed, _wake = timedraft.bed_wake(tools.cfg)
    last = max((r for r in rows if r.get("at")), key=lambda r: _night(r["at"]), default=None)
    gap = None
    if last:
        gap = round((_night(bed) - _night(last["at"])) / 60, 1)
        if gap < 3:
            flags.append(f"最后一餐 {last['at']}，离 {bed} 上床只有 {gap} 小时（至少 3 小时）")
    k = tg.get("kcal_target")
    if rows and k and sum(s["est"]["kcal"]) / 2 > k[1] * 1.1:
        flags.append(f"热量约 {s['est']['kcal'][0]}–{s['est']['kcal'][1]}，超过目标 {k[0]}–{k[1]}")
    return {"date": day.isoformat(), "meals": [{"id": r["id"], "meal": MEALS[r["meal"]], "at": r.get("at"), "dishes": r["dishes"],
                                                "portions": r["portions"], "est": r["est"], "confidence": r["confidence"]} for r in rows],
            "total": s["est"], "hands": s["hands"], "targets": {k2: tg.get(k2) for k2 in ("protein_g", "kcal_target", "fiber_g", "hands_per_day")},
            "last_meal": last.get("at") if last else None, "bed": bed, "hours_before_bed": gap, "flags": flags}


def week_summary(tools, end: date | None = None) -> dict:
    end = end or tools._today()
    tg = targets(tools, end)
    days = []
    for i in range(6, -1, -1):
        d = end - timedelta(days=i)
        s = day_summary(tools, d, tg)
        if s["meals"]:
            days.append(s)
    n = len(days)
    out: dict[str, Any] = {"end": end.isoformat(), "days_logged": n, "of": 7}
    if n:
        p_mid = [sum(d["total"]["protein_g"]) / 2 for d in days]
        k_mid = [sum(d["total"]["kcal"]) / 2 for d in days]
        out["protein_avg_g"] = round(sum(p_mid) / n)
        out["kcal_avg"] = round(sum(k_mid) / n, -1)
        out["veg_fists_avg"] = round(sum(d["hands"]["veg_fists"] for d in days) / n, 1)
        if tg.get("protein_g"):
            out["protein_hit_days"] = sum(1 for p in p_mid if p >= tg["protein_g"][0])
        out["late_dinner_days"] = sum(1 for d in days if d["hours_before_bed"] is not None and d["hours_before_bed"] < 3)
        out["note"] = "只算记了的天；照片估的是范围，取中间值算平均"
    out["targets"] = {k: tg.get(k) for k in ("protein_g", "kcal_target")}
    return out


def brief_lines(tools, day: date) -> list[str]:
    """全盘简报的「营养」段。"""
    try:
        tg = targets(tools, day)
    except Exception:  # noqa: BLE001
        return []
    out = []
    parts = []
    if tg.get("protein_g"):
        parts.append(f"蛋白质 {tg['protein_g'][0]}–{tg['protein_g'][1]} g/天（约 {tg['hands_per_day']['protein_palms']:g} 掌心）")
    if tg.get("kcal_target"):
        parts.append(f"热量 {tg['kcal_target'][0]:g}–{tg['kcal_target'][1]:g} kcal（{tg['goal']}）")
    elif tg.get("missing"):
        parts.append("热量目标还缺" + "、".join(tg["missing"]) + "（问到了记 profile.body）")
    if parts:
        out.append("营养目标：" + "；".join(parts))
    try:
        d = day_summary(tools, day, tg)
        w = week_summary(tools, day)
    except Exception:  # noqa: BLE001
        return out
    if d["meals"]:
        out.append(f"今天记了 {len(d['meals'])} 餐：蛋白质约 {d['total']['protein_g'][0]}–{d['total']['protein_g'][1]} g，"
                   f"热量约 {d['total']['kcal'][0]}–{d['total']['kcal'][1]}" + (f"；{d['flags'][0]}" if d["flags"] else ""))
    else:
        out.append("今天还没记饭")
    if w["days_logged"]:
        out.append(f"近 7 天记了 {w['days_logged']} 天：蛋白质平均约 {w['protein_avg_g']} g"
                   + (f"，达标 {w['protein_hit_days']} 天" if "protein_hit_days" in w else "")
                   + (f"，晚饭离上床不到 3 小时 {w['late_dinner_days']} 天" if w.get("late_dinner_days") else ""))
    return out
