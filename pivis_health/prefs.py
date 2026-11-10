"""老大定下的偏好（越用越懂）：展示形式、对比基线等。

- P-Health 用 context-record --scope pref.<主题> 记下偏好，payload 里必须有一句人话 rule。
- 记下后，这里把所有生效的 pref.* 渲染成 AGENTS.md 末尾的一段「老大定下的偏好」，
  DSH 发现 AGENTS.md 变了会自动把新内容带进每个会话（App 的四个板块、团队里的 P-Health Bot 都读同一份）。
- 页面编排通过 shared_context 也能看到；对比基线这类要算数的偏好，由 compare() 按偏好算好放进 facts。
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PREF_PREFIX = "pref."
START = "<!-- 老大的偏好：系统自动维护，不要手改 -->"
END = "<!-- 老大的偏好：结束 -->"

BASELINES = ("prev_week", "personal")
METRICS = {
    "sleep": ("睡眠时长", "小时"),
    "hrv": ("HRV", "ms"),
    "recovery": ("恢复", "%"),
    "strain": ("训练负荷", ""),
    "steps": ("步数", "步"),
    "resting_hr": ("静息心率", "次/分"),
    "resp_rate": ("呼吸频率", "次/分"),
    "weight": ("体重", "kg"),
}
SERIES = {"hrv": "whoop_hrv_rmssd", "recovery": "whoop_recovery", "strain": "whoop_strain", "steps": "steps",
          "resting_hr": "resting_heart_rate", "resp_rate": "respiratory_rate", "weight": "weight"}


def active_prefs(cfg) -> list[dict]:
    from .agent_context import AgentContextStore
    return [e for e in AgentContextStore(cfg).snapshot()["entries"] if str(e.get("scope", "")).startswith(PREF_PREFIX)]


def baseline_pref(cfg) -> str | None:
    for e in active_prefs(cfg):
        if e["scope"] == "pref.baseline":
            w = (e.get("payload") or {}).get("window")
            return w if w in BASELINES else None
    return None


# 位置这类敏感档案不写进每个会话的规则（DS Bot 群里的 P-Health 也读这份）；要用时 context-list 查
SENSITIVE_PROFILE = ("profile.home_place", "profile.travel", "profile.location", "profile.address")
MAX_PREFS = 30


MAX_CORRECTIONS = 40


def corrections(cfg) -> list[dict]:
    """老大纠正过的专业要点（correction.*），按记录时间排。"""
    from .agent_context import AgentContextStore
    return [e for e in AgentContextStore(cfg).snapshot()["entries"]
            if str(e.get("scope", "")).startswith("correction.")]


def check_correction(cfg, scope: str, payload: dict) -> dict:
    """纠正要写成「正确做法」一句话；同一主题被纠正第二次，标出来要求写进 skill。"""
    if not str(payload.get("rule") or "").strip():
        raise ValueError("correction.* 的 payload 要带 rule（正确做法，一句话），可选 wrong（之前错在哪）、why（依据）、"
                         "skill（应该写进哪个 skill），例如 {\"rule\":\"热水澡在最早上床前 1–2 小时洗完\",\"wrong\":\"说成睡前随便洗\"}")
    prev = next((e for e in corrections(cfg) if e.get("scope") == scope), None)
    times = int(((prev or {}).get("payload") or {}).get("times") or (1 if prev else 0)) + 1
    out = {**payload, "times": times}
    if times >= 2 and not out.get("folded"):
        out["needs_skill"] = True     # 同一件事纠正第二次：说明只记记忆不够，要写进 skill（request.tool）
    return out


def render_block(prefs: list[dict], known: list[dict] | None = None, fixes: list[dict] | None = None) -> str:
    lines = [START, "## 老大定下的偏好（要遵守；**红线优先**：和红线冲突时按红线做，并用 context-record 把这条偏好改成不冲突的说法；"
             "老大改口就覆盖同一个 scope）"]
    if not prefs:
        lines.append("- 暂无")
    for e in prefs[-MAX_PREFS:]:
        rule = str((e.get("payload") or {}).get("rule") or "").strip() or str(e.get("payload"))
        when = str(e.get("recorded_at") or "")[:10]
        lines.append(f"- {rule}（{e['scope']}，{when}）")
    if known:
        lines.append("")
        lines.append("## 你已经了解到的老大（profile.* / learn.*；回答专业问题、排计划前先对照，变了就覆盖同一个 scope）")
        for e in known[-30:]:
            rule = _fact_line(e.get("payload") or {})
            if not rule:
                continue
            when = str(e.get("recorded_at") or "")[:10]
            lines.append(f"- {rule[:120]}（{e['scope']}，{when}）")
    if fixes:
        lines.append("")
        lines.append("## 老大纠正过的专业要点（**照这些做，不要再犯**；回答同类问题前先对照。这里没有的，按 skill 的专业资料）")
        for e in fixes[-MAX_CORRECTIONS:]:
            p = e.get("payload") or {}
            rule = str(p.get("rule") or "").strip()
            if not rule:
                continue
            wrong = str(p.get("wrong") or "").strip()
            when = str(e.get("recorded_at") or "")[:10]
            tail = f"；之前错在：{wrong[:60]}" if wrong else ""
            lines.append(f"- {rule[:140]}{tail}（{e['scope']}，{when}）")
    lines.append(END)
    return "\n".join(lines)


def _fact_line(p: dict) -> str:
    """一条 profile./learn. 记忆的一句话：优先 rule / summary；实验列出还在试的；其余取前几个文字字段。"""
    if not isinstance(p, dict):
        return str(p or "").strip()
    rule = str(p.get("rule") or p.get("summary") or "").strip()
    if rule:
        return rule
    items = p.get("items")
    if isinstance(items, list):
        open_ = [str(i.get("change") or i.get("id") or "") for i in items
                 if isinstance(i, dict) and not i.get("result")]
        open_ = [x for x in open_ if x]
        return ("在试：" + "；".join(open_)) if open_ else ""
    parts = []
    for k, v in p.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            parts.append("、".join(v))
        if len("；".join(parts)) > 100:
            break
    return "；".join(parts)


def known_facts(cfg) -> list[dict]:
    from .agent_context import AgentContextStore
    return [e for e in AgentContextStore(cfg).snapshot()["entries"]
            if str(e.get("scope", "")).startswith(("profile.", "learn."))
            and not str(e.get("scope", "")).startswith(SENSITIVE_PROFILE)]


def agents_md_path() -> Path:
    from . import dsh_chat
    return Path(dsh_chat.DSH_CWD) / "AGENTS.md"


LOCAL_NAME = "AGENTS.local.md"   # 和 AGENTS.md 同目录；DSH 默认会读，而且按文件单独刷新


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".agents-", suffix=".md", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def sync_agents_md(cfg, path: Path | None = None) -> dict:
    """把生效的偏好 / 了解到的老大 / 纠正过的要点写进工作区的 AGENTS.local.md（整份由这里生成）。

    build 51 起不再写进 AGENTS.md：DSH 每轮会检查指令文件，哪个文件变了就把它整份补进每个对话。
    偏好段写在 45 KB 的 AGENTS.md 里时，记一条偏好所有对话都要再收一份全文（主对话堆了 34 份）；
    拆出来以后，记偏好只补这几 KB，AGENTS.md 只在发版时变。AGENTS.md 里旧的偏好段顺手删掉。"""
    path = path or agents_md_path()
    if not path.is_file() or path.is_symlink():
        return {"ok": False, "reason": f"{path} 不是普通文件"}
    local = path.with_name(LOCAL_NAME)
    if local.is_symlink() or (local.exists() and not local.is_file()):
        return {"ok": False, "reason": f"{local} 不是普通文件"}
    text = path.read_text(encoding="utf-8")
    migrated = False
    if START in text and END in text:
        head, rest = text.split(START, 1)
        tail = rest.split(END, 1)[1]
        _atomic_write(path, head.rstrip("\n") + ("\n" + tail.lstrip("\n") if tail.strip() else "\n"))
        migrated = True
    block = render_block(active_prefs(cfg), known_facts(cfg), corrections(cfg)) + "\n"
    old = local.read_text(encoding="utf-8") if local.exists() else None
    if block != old:
        _atomic_write(local, block)
    return {"ok": True, "path": str(local), "prefs": len(active_prefs(cfg)), "changed": block != old,
            **({"moved_from_agents_md": True} if migrated else {})}


# ---------------------------------------------------------------- 对比（数字都由这里算，P-Health 只抄）
def _round(v: float | None, nd: int = 1):
    return None if v is None else (int(round(v)) if nd == 0 else round(v, nd))


def _values(tools, metric: str, day: date, days: int) -> list[tuple[str, float]]:
    """按日期升序的 (日期, 值)。睡眠按「入睡那晚」记，今天能看到的最近一晚是昨晚。"""
    if metric == "sleep":
        from .pages import V2Pages
        sp = V2Pages(tools).sleep(day)
        yday = (day - timedelta(days=1)).isoformat()
        return [(n["date"], float(n["actual"])) for n in sp.get("chart14") or []
                if n.get("actual") is not None and n["date"] <= yday][-days:]
    daily = tools.daily_series(SERIES[metric], day, days)
    return [(d.isoformat(), float(v)) for d, v in sorted(daily.items()) if d <= day]


def compare(tools, metric: str, day: date, recent: int = 7, baseline: str = "prev_week") -> dict:
    if metric not in METRICS:
        raise ValueError(f"metric 只能是 {list(METRICS)}")
    if baseline not in BASELINES:
        raise ValueError(f"baseline 只能是 {BASELINES}")
    label, unit = METRICS[metric]
    nd = 0 if metric in ("steps", "recovery", "resting_hr") else 1
    vals = _values(tools, metric, day, 28)
    if not vals:
        return {"metric": metric, "label": label, "unit": unit, "ok": False, "reason": "这项最近没有数据"}
    last_date = date.fromisoformat(vals[-1][0])
    r_start = last_date - timedelta(days=recent - 1)
    rec = [(d, v) for d, v in vals if d >= r_start.isoformat()]
    out: dict[str, Any] = {"metric": metric, "label": label, "unit": unit, "ok": True,
                           "recent": {"from": r_start.isoformat(), "to": last_date.isoformat(), "n": len(rec),
                                      "avg": _round(sum(v for _, v in rec) / len(rec), nd)}}
    if baseline == "prev_week":
        b_end = r_start - timedelta(days=1)
        b_start = b_end - timedelta(days=6)
        base = [(d, v) for d, v in vals if b_start.isoformat() <= d <= b_end.isoformat()]
        out["baseline"] = {"kind": "prev_week", "label": "上一周", "from": b_start.isoformat(), "to": b_end.isoformat(),
                           "n": len(base), "avg": _round(sum(v for _, v in base) / len(base), nd) if base else None}
    else:
        b = tools.baseline(SERIES.get(metric, "whoop_hrv_rmssd")) if metric != "sleep" else {}
        center = ((b or {}).get("baseline") or {}).get("center")
        out["baseline"] = {"kind": "personal", "label": "个人基线（30 天）", "avg": _round(center, nd) if center else None}
    a, bavg = out["recent"]["avg"], out["baseline"].get("avg")
    if a is not None and bavg:
        out["change"] = _round(a - bavg, nd)
        out["change_pct"] = _round((a - bavg) / bavg * 100, 0)
    if out["baseline"].get("n", 1) < 3 or out["recent"]["n"] < 3:
        out["note"] = "样本少于 3 天，只能当参考"
    return out
