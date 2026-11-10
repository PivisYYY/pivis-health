"""康复（build 53，老大 11-10：P-Health 要有专业康复师的能力）。

- 伤病档案：哪里、哪边、什么时候、怎么伤的、医生说了什么（只抄老大说的）、现在哪个阶段、限制、目标。
- 疼痛记录：0–10 分，休息时 / 活动时（练的时候或之后）/ 第二天早上。按「疼痛监控模型」亮灯：
  绿 活动时 ≤ 2；黄 3–5 且第二天早上回到平时；红 > 5，或第二天早上比平时更疼、更僵。
- 进阶 / 退一步由这里算（连续一周绿灯、晨起稳定才进阶；近 3 天有红灯就退一步），P-Health 照这个说，不凭感觉。
数据：data_dir/rehab.json（伤病档案）、data_dir/pain_log.jsonl（只追加）。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

FILE = "rehab.json"
PAIN = "pain_log.jsonl"
AREAS = {"knee": "膝", "lower_back": "腰背", "shoulder": "肩", "elbow": "肘", "ankle": "踝", "neck": "颈",
         "hip": "髋", "wrist": "腕", "hamstring": "腘绳肌", "achilles": "跟腱", "other": "其他"}
SIDES = ("left", "right", "both", "none")
PHASES = {"protect": "保护期", "load": "恢复负荷", "strength": "力量", "return": "回归运动", "maintain": "维持预防"}
NEXT = {"protect": "load", "load": "strength", "strength": "return", "return": "maintain"}
PREV = {v: k for k, v in NEXT.items()}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class RehabError(ValueError):
    pass


def _path(cfg) -> Path:
    return Path(cfg.data_dir) / FILE


def _load(cfg) -> dict:
    try:
        return json.loads(_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"injuries": {}}


def _save(cfg, data: dict) -> None:
    p = _path(cfg)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def injury_set(cfg, body: dict) -> dict:
    data = _load(cfg)
    iid = str(body.get("id") or "").strip()
    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,30}$", iid):
        raise RehabError("id 要写小写字母、数字、- 组成的短 id，比如 knee-r、back")
    cur = dict(data["injuries"].get(iid) or {})
    cur.update({k: v for k, v in body.items() if v is not None})
    if cur.get("area") not in AREAS:
        raise RehabError(f"area 只能是 {tuple(AREAS)}")
    if cur.get("side", "none") not in SIDES:
        raise RehabError(f"side 只能是 {SIDES}")
    cur.setdefault("side", "none")
    if cur.get("phase", "load") not in PHASES:
        raise RehabError(f"phase 只能是 {tuple(PHASES)}（{'/'.join(PHASES.values())}）")
    cur.setdefault("phase", "load")
    if cur.get("status", "active") not in ("active", "resolved"):
        raise RehabError("status 只能是 active / resolved")
    cur.setdefault("status", "active")
    if not str(cur.get("name") or "").strip():
        raise RehabError("name 必填（一句话：右膝半月板损伤、腰肌劳损反复）")
    if cur.get("onset"):
        try:
            date.fromisoformat(str(cur["onset"]))
        except ValueError:
            raise RehabError("onset 要写 YYYY-MM-DD") from None
    for k in ("limits", "aggravating", "easing"):
        cur[k] = [str(x)[:30] for x in cur.get(k) or []][:10]
    prev_phase = (data["injuries"].get(iid) or {}).get("phase")
    hist = list(cur.get("phase_history") or [])
    if prev_phase != cur["phase"]:
        hist.append({"phase": cur["phase"], "at": datetime.now().date().isoformat()})
    cur["phase_history"] = hist[-20:]
    cur["id"] = iid
    cur["updated_at"] = datetime.now().isoformat(timespec="seconds")
    data["injuries"][iid] = cur
    _save(cfg, data)
    return cur


def injuries(cfg, include_resolved: bool = False) -> list[dict]:
    return [i for i in _load(cfg)["injuries"].values() if include_resolved or i.get("status") == "active"]


def active(cfg) -> list[dict]:
    return injuries(cfg)


def _score(v, name: str) -> int | None:
    if v is None or v == "":
        return None
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        raise RehabError(f"{name} 要写 0–10 的数") from None
    if not 0 <= n <= 10:
        raise RehabError(f"{name} 要写 0–10 的数")
    return n


def pain_log(cfg, body: dict, today: date | None = None) -> dict:
    iid = str(body.get("injury") or "")
    if iid not in _load(cfg)["injuries"]:
        raise RehabError(f"没有这个伤病档案：{iid}。先 injury-set")
    day = str(body.get("date") or (today or date.today()).isoformat())
    try:
        date.fromisoformat(day)
    except ValueError:
        raise RehabError("date 要写 YYYY-MM-DD") from None
    at = str(body.get("at") or "")
    if at and not _HHMM.match(at):
        raise RehabError("at 要写 HH:MM")
    row = {"injury": iid, "date": day, "at": at,
           "rest": _score(body.get("rest"), "rest"), "activity": _score(body.get("activity"), "activity"),
           "morning_after": _score(body.get("morning_after"), "morning_after"),
           "stiffness_min": int(body["stiffness_min"]) if str(body.get("stiffness_min") or "").isdigit() else None,
           "note": str(body.get("note") or "")[:80], "source": body.get("source") or "agent",
           "logged_at": datetime.now().isoformat(timespec="seconds")}
    if all(row[k] is None for k in ("rest", "activity", "morning_after")):
        raise RehabError("rest / activity / morning_after 至少写一个")
    with (Path(cfg.data_dir) / PAIN).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def log_from_card(cfg, todo: dict, values: dict, now: datetime) -> dict | None:
    """疼痛打卡卡（todo.log = {"type":"pain","injury":…}）提交时自动记，不用 P-Health 再跑一轮。"""
    spec = todo.get("log") or {}
    if spec.get("type") != "pain":
        return None
    body = {"injury": spec.get("injury"), "date": todo.get("date"), "at": now.strftime("%H:%M"), "source": "card"}
    for inp in todo.get("inputs") or []:
        if inp.get("id") in ("rest", "activity", "morning_after", "stiffness_min", "note") and inp["id"] in values:
            body[inp["id"]] = values[inp["id"]]
    return pain_log(cfg, body)


def logs(cfg, injury: str | None = None, since: str | None = None) -> list[dict]:
    out = []
    try:
        with (Path(cfg.data_dir) / PAIN).open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if (injury is None or r.get("injury") == injury) and (since is None or r.get("date", "") >= since):
                    out.append(r)
    except OSError:
        pass
    return sorted(out, key=lambda r: (r.get("date", ""), r.get("at") or ""))


def light(r: dict, baseline_morning: float | None) -> str:
    """一条记录的灯：疼痛监控模型（Silbernagel 2007 的做法，阈值按常用的 0–10 分）。"""
    act, morn = r.get("activity"), r.get("morning_after")
    if act is not None and act > 5:
        return "red"
    if morn is not None and (morn >= 5 or (baseline_morning is not None and morn > baseline_morning + 1)):
        return "red"
    if act is not None and act >= 3:
        return "amber"
    if act is None and morn is None:
        return "amber" if (r.get("rest") or 0) >= 4 else "green"
    return "green"


def _avg(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def status(cfg, injury: str | None = None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    out = []
    for inj in injuries(cfg):
        if injury and inj["id"] != injury:
            continue
        rows = logs(cfg, inj["id"], (today - timedelta(days=27)).isoformat())
        last7 = [r for r in rows if r["date"] >= (today - timedelta(days=6)).isoformat()]
        prev7 = [r for r in rows if (today - timedelta(days=13)).isoformat() <= r["date"] < (today - timedelta(days=6)).isoformat()]
        earlier = [r.get("morning_after") for r in rows if r["date"] < (today - timedelta(days=2)).isoformat()]
        base = sorted(x for x in earlier if x is not None)
        baseline = base[len(base) // 2] if base else None
        lights = [light(r, baseline) for r in last7]
        a7, a_prev = _avg([r.get("activity") for r in last7]), _avg([r.get("activity") for r in prev7])
        trend = None
        if a7 is not None and a_prev is not None and len(last7) >= 3 and len(prev7) >= 3:
            trend = "改善" if a7 <= a_prev - 1 else "变差" if a7 >= a_prev + 1 else "平稳"
        recent_red = any(light(r, baseline) == "red" for r in rows if r["date"] >= (today - timedelta(days=2)).isoformat())
        days_logged = len({r["date"] for r in last7})
        if recent_red:
            advice = "退一步：这几天的量减 30–50%（或回到" + PHASES.get(PREV.get(inj["phase"], inj["phase"]), "上一阶段") + "的动作），48 小时后再看"
        elif days_logged >= 5 and lights and all(x == "green" for x in lights) and inj["phase"] in NEXT:
            advice = f"可以进阶：连续 {days_logged} 天绿灯，晨起稳定 → 进入「{PHASES[NEXT[inj['phase']]]}」，按 rehab-coach 的进阶标准核对一遍再改"
        elif days_logged < 3:
            advice = "记录太少（近 7 天不到 3 天），先把每天的疼痛打卡做起来再判断进阶"
        else:
            advice = "保持现在的量：还没到进阶标准（要连续 5 天以上绿灯、第二天早上不加重）"
        onset = inj.get("onset")
        out.append({
            "id": inj["id"], "name": inj.get("name"), "area": AREAS.get(inj["area"], inj["area"]), "side": inj.get("side"),
            "phase": inj["phase"], "phase_label": PHASES[inj["phase"]],
            "days_since_onset": (today - date.fromisoformat(onset)).days if onset else None,
            "limits": inj.get("limits") or [], "goal": inj.get("goal"),
            "last7": {"days_logged": days_logged, "activity_avg": a7, "activity_max": max((r["activity"] for r in last7 if r.get("activity") is not None), default=None),
                      "rest_avg": _avg([r.get("rest") for r in last7]), "morning_avg": _avg([r.get("morning_after") for r in last7]),
                      "lights": {k: lights.count(k) for k in ("green", "amber", "red")}},
            "baseline_morning": baseline, "trend": trend,
            "last": rows[-1] if rows else None,
            "light_today": light(rows[-1], baseline) if rows and rows[-1]["date"] >= (today - timedelta(days=1)).isoformat() else None,
            "advice": advice,
        })
    return out


def brief_lines(cfg, today: date) -> list[str]:
    out = []
    try:
        st = status(cfg, None, today)
    except Exception:  # noqa: BLE001
        return []
    lights_cn = {"green": "绿灯", "amber": "黄灯", "red": "红灯"}
    for s in st:
        l7 = s["last7"]
        pain = (f"近 7 天记了 {l7['days_logged']} 天，活动时疼平均 {l7['activity_avg']}/10、最高 {l7['activity_max']}"
                if l7["activity_avg"] is not None else "近 7 天没有疼痛记录")
        tail = []
        if s.get("light_today"):
            tail.append(f"最近一次{lights_cn[s['light_today']]}")
        if s.get("trend"):
            tail.append(f"比上周{s['trend']}")
        line = (f"{s['name']}（{s['phase_label']}" + (f"，第 {s['days_since_onset']} 天" if s.get("days_since_onset") is not None else "")
                + f"）：{pain}" + ("，" + "，".join(tail) if tail else "") + f" → {s['advice']}")
        if s["limits"]:
            line += "；限制：" + "、".join(s["limits"][:4])
        out.append(line)
    return out
