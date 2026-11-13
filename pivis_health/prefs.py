"""Psir 定下的偏好（越用越懂）：展示形式、对比基线等。

- P-Health 用 context-record --scope pref.<主题> 记下偏好，payload 里必须有一句人话 rule。
- 记下后，这里把所有生效的 pref.* 渲染成 AGENTS.md 末尾的一段「Psir 定下的偏好」，
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
START = "<!-- Psir 的偏好：系统自动维护，不要手改 -->"
END = "<!-- Psir 的偏好：结束 -->"

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
    """Psir 纠正过的专业要点（correction.*），按记录时间排。"""
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


def check_stance(cfg, scope: str, payload: dict) -> dict:
    """立场（stance.*）：要带 rule（立场）和 why（理由：机制 + Psir 的数据 + 证据等级）。
    同一个 scope 换了说法，必须写 changed_because（Psir 给了什么新信息 / 新数据）——
    没有新信息就不改立场（11-11 午睡：Psir 一句「我以前午休也没事」就退了一半）。"""
    from .agent_context import AgentContextStore
    rule, why = str(payload.get("rule") or "").strip(), str(payload.get("why") or "").strip()
    if not rule or not why:
        raise ValueError("stance.* 的 payload 要带 rule（你的立场，一句话）和 why（理由：机制 + Psir 自己的数据 + 证据等级），"
                         "例如 {\"rule\":\"窗口期不午睡\",\"why\":\"午睡会消耗睡眠压力（A）；你近 7 晚有 4 晚很晚才睡着\"}")
    prev = next((e for e in reversed(AgentContextStore(cfg).snapshot()["entries"]) if e.get("scope") == scope), None)
    old = str(((prev or {}).get("payload") or {}).get("rule") or "").strip()
    if prev and old and old != rule and not str(payload.get("changed_because") or "").strip():
        raise ValueError(f"这个立场之前是「{old}」。要改，payload 里写 changed_because：Psir 给了什么新信息或新数据；"
                         "只是 Psir 不同意、没有新信息，就别改立场：讲清理由，给一个能验证的小试验")
    out = dict(payload)
    if prev and old and old != rule:
        out["was"] = old
    return out


def check_protocol(payload: dict) -> dict:
    """方案书（protocol.<项目 id>）：rule 一句话总述 + steps[{rule, why}]，可选 expect / adjust / evidence。"""
    steps = payload.get("steps")
    if not str(payload.get("rule") or "").strip() or not isinstance(steps, list) or not steps:
        raise ValueError("protocol.<项目 id> 的 payload 要有 rule（这个方案一句话）和 steps（[{\"rule\":\"…\",\"why\":\"…\"}]），"
                         "可选 expect（这个阶段 Psir 会经历什么）、adjust（什么数据出现就怎么调）、evidence（证据等级和出处）")
    for st in steps:
        if not isinstance(st, dict) or not str(st.get("rule") or "").strip() or not str(st.get("why") or "").strip():
            raise ValueError("steps 里每一条都要有 rule 和 why（为什么要这样做，Psir 问起来你要讲得出）")
    return payload


def stances(cfg) -> list[dict]:
    from .agent_context import AgentContextStore
    return [e for e in AgentContextStore(cfg).snapshot()["entries"] if str(e.get("scope", "")).startswith("stance.")]


def protocols(cfg) -> list[dict]:
    """进行中项目的方案书（项目结束了就不再放进每个对话）。"""
    from .agent_context import AgentContextStore
    from .todos import TodoStore
    try:
        active = {p["id"] for p in TodoStore(cfg).projects() if p.get("status", "active") == "active"}
    except Exception:  # noqa: BLE001
        active = set()
    return [e for e in AgentContextStore(cfg).snapshot()["entries"]
            if str(e.get("scope", "")).startswith("protocol.") and e["scope"].split(".", 1)[1] in active]


SKILLS_DIR = Path(__file__).resolve().parent.parent / "agent" / "skills"
# 专业要点（常驻）：哪种情况放哪一份 core.md。每份 ≤ 1.5 KB，只放判断最常用到的硬规矩，细节仍在 skill 里
CORES = [
    ("cbti", "睡眠 / CBT-I"),
    ("rehab-coach", "康复（有伤病时）"),
    ("training-coach", "训练"),
]


def cores(cfg) -> list[tuple[str, str]]:
    """按 Psir 现在的情况挑常驻的专业要点：在做 CBT-I → 睡眠；有伤病档案或 profile.safety → 康复；有运动项目 → 训练。"""
    from .agent_context import AgentContextStore
    from .todos import TodoStore
    try:
        projects = [p for p in TodoStore(cfg).projects() if p.get("status", "active") == "active"]
    except Exception:  # noqa: BLE001
        projects = []
    scopes = {str(e.get("scope", "")) for e in AgentContextStore(cfg).snapshot()["entries"]}
    want = {
        "cbti": any(p["id"] == "cbti" or "cbt" in str(p.get("name", "")).lower() for p in projects) or "sleep.cbti" in scopes,
        "rehab-coach": any(sc.startswith(("profile.safety", "profile.injury")) for sc in scopes),
        "training-coach": any(p.get("board") == "sport" for p in projects),
    }
    out = []
    for skill, title in CORES:
        f = SKILLS_DIR / skill / "references" / "core.md"
        if want.get(skill) and f.is_file():
            out.append((title, f.read_text(encoding="utf-8").strip()))
    return out


def render_block(prefs: list[dict], known: list[dict] | None = None, fixes: list[dict] | None = None,
                 stance: list[dict] | None = None, protos: list[dict] | None = None,
                 core: list[tuple[str, str]] | None = None) -> str:
    lines = [START]
    if protos:
        lines.append("## 进行中的方案书（你按这个带 Psir：每条规则都有理由，Psir 问「为什么」就讲这里的 why；"
                     "改方案只在复盘时按 adjust 的条件改，周中 Psir 想改先讲理由）")
        for e in protos:
            p = e.get("payload") or {}
            lines.append(f"### {e['scope'].split('.', 1)[1]}：{str(p.get('rule') or '').strip()[:120]}")
            for st in (p.get("steps") or [])[:10]:
                if isinstance(st, dict):
                    lines.append(f"- {str(st.get('rule') or '').strip()[:100]} —— 为什么：{str(st.get('why') or '').strip()[:140]}")
            for k, label in (("expect", "这个阶段会怎样"), ("adjust", "什么时候调"), ("evidence", "证据")):
                if str(p.get(k) or "").strip():
                    lines.append(f"- {label}：{str(p[k]).strip()[:200]}")
        lines.append("")
    if stance:
        lines.append("## 你已经表过的态（所有对话都按这个说，前后一致；Psir 不同意时：没有新信息就坚持并讲理由，"
                     "有新信息才改，改了用同一个 scope 重记并写 changed_because）")
        for e in stance[-30:]:
            p = e.get("payload") or {}
            when = str(e.get("recorded_at") or "")[:10]
            lines.append(f"- {str(p.get('rule') or '').strip()[:120]} —— 理由：{str(p.get('why') or '').strip()[:140]}（{e['scope']}，{when}）")
        lines.append("")
    if core:
        lines.append("## 专业要点（常驻；回答这几类问题时这些是底线，细节再读对应 skill 的 references）")
        for title, text in core:
            lines.append(f"### {title}")
            lines.append(text)
        lines.append("")
    lines.append("## Psir 定下的偏好（要遵守；**红线优先**：和红线冲突时按红线做，并用 context-record 把这条偏好改成不冲突的说法；"
             "Psir 改口就覆盖同一个 scope）")
    if not prefs:
        lines.append("- 暂无")
    for e in prefs[-MAX_PREFS:]:
        rule = str((e.get("payload") or {}).get("rule") or "").strip() or str(e.get("payload"))
        when = str(e.get("recorded_at") or "")[:10]
        lines.append(f"- {rule}（{e['scope']}，{when}）")
    if known:
        lines.append("")
        lines.append("## 你已经了解到的 Psir（profile.* / learn.*；回答专业问题、排计划前先对照，变了就覆盖同一个 scope）")
        for e in known[-30:]:
            rule = _fact_line(e.get("payload") or {})
            if not rule:
                continue
            when = str(e.get("recorded_at") or "")[:10]
            lines.append(f"- {rule[:120]}（{e['scope']}，{when}）")
    if fixes:
        lines.append("")
        lines.append("## Psir 纠正过的专业要点（**照这些做，不要再犯**；回答同类问题前先对照。这里没有的，按 skill 的专业资料）")
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


def own_workspace(cfg) -> bool:
    """这份配置的数据目录是不是 DSH 工作区自己的（真实 / 模拟 / 演示 / 测试环境都是 <工作区>/pivis-runtime）。
    不是就别往工作区写指令文件：单元测试用临时数据目录，以前会把测试数据写进真实工作区的偏好段。"""
    from . import dsh_chat
    data_parent = Path(cfg.data_dir).resolve().parent
    cwd = Path(dsh_chat.DSH_CWD).resolve()
    return data_parent in (cwd, cwd.parent)


LOCAL_NAME = "AGENTS.local.md"   # 和 AGENTS.md 同目录；DSH 默认会读，而且按文件单独刷新


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".agents-", suffix=".md", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def sync_agents_md(cfg, path: Path | None = None) -> dict:
    """把生效的偏好 / 了解到的 Psir / 纠正过的要点写进工作区的 AGENTS.local.md（整份由这里生成）。

    build 51 起不再写进 AGENTS.md：DSH 每轮会检查指令文件，哪个文件变了就把它整份补进每个对话。
    偏好段写在 45 KB 的 AGENTS.md 里时，记一条偏好所有对话都要再收一份全文（主对话堆了 34 份）；
    拆出来以后，记偏好只补这几 KB，AGENTS.md 只在发版时变。AGENTS.md 里旧的偏好段顺手删掉。"""
    if path is None:
        if not own_workspace(cfg):
            return {"ok": False, "reason": "数据目录不属于当前 DSH 工作区，不写指令文件"}
        path = agents_md_path()
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
    block = render_block(active_prefs(cfg), known_facts(cfg), corrections(cfg),
                         stances(cfg), protocols(cfg), cores(cfg)) + "\n"
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
