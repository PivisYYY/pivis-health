"""数据连接状态（build 53）：先分清原因，再决定说不说、对谁说。

老大的要求：不能再出现「WHOOP / Apple 健康连不上」的提示，除非真要他动手。
- 原因在服务器 / 开发（比如样本被拒、WHOOP 接口慢在重试）→ 不告诉老大去改设置，记进 dev_alerts.jsonl；
- 手机只是没打开 App（后台上报没有健康样本）→ 不算问题，打开就补上；
- 真要老大动手的只有两种：WHOOP 登录真的失效（刷新令牌被拒）、Apple 健康权限确认关了（App 在前台查到 0 条并报了上来）。

状态只读本地文件和库，不联网。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ingest

DEV_ALERTS = "dev_alerts.jsonl"
APPLE_FRESH_H = 12          # 12 小时内收下过样本 = 新鲜
WHOOP_LATE_H = 3            # WHOOP 连续失败 3 小时以上才算晚到（每 15 分钟拉一次，偶尔一两次失败不算）
PERMISSION_ACTION = "Apple 健康读不到：设置 › 健康 › 数据访问与设备 › P-Health，全部打开"
WHOOP_LOGIN_ACTION = "WHOOP 登录失效了：在 App 里点「重新登录 WHOOP」"


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hours(now: datetime, ts) -> float | None:
    dt = _parse(ts)
    return None if dt is None else round((now - dt).total_seconds() / 3600, 1)


def _latest_sample(cfg) -> str | None:
    """库里最近一条手机样本的开始时间（UTC 字符串）。"""
    db = Path(cfg.vault_db)
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("SELECT MAX(start_at) FROM samples WHERE type IN ('step_count','sleep_analysis')"
                              " AND device_id LIKE 'iphone-%'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def whoop(cfg, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if getattr(cfg, "sim_mode", False):
        return {"state": "fresh", "age_min": 0, "sim": True}
    from . import whoop_sync
    try:
        f = whoop_sync.freshness(cfg, now)
    except Exception:  # noqa: BLE001
        return {"state": "unknown"}
    age_h = f.get("age_hours")
    out = {"age_min": None if age_h is None else int(age_h * 60), "last_success_utc": f.get("last_success_utc")}
    last = f.get("last_attempt") or {}
    if (f.get("present") or f.get("authorised")) and (not f.get("authorised") or last.get("error_code") == "not_authorised"):
        return {**out, "state": "needs_login", "action": WHOOP_LOGIN_ACTION}
    fail_h = _hours(now, f.get("last_success_utc"))
    if f.get("stale") and last.get("ok") is False and (fail_h is None or fail_h >= WHOOP_LATE_H):
        return {**out, "state": "late", "cause": last.get("error_code") or "unknown", "late_h": fail_h}
    return {**out, "state": "fresh"}


def apple(cfg, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if getattr(cfg, "sim_mode", False):
        return {"state": "fresh", "sim": True}
    st = ingest.read_state(Path(cfg.data_dir))
    latest = _latest_sample(cfg)
    acc_h = _hours(now, st.get("last_accepted_at"))
    out = {"latest_sample_utc": latest, "age_h": _hours(now, latest), "last_upload_h": _hours(now, st.get("last_upload_at"))}
    if acc_h is not None and acc_h <= APPLE_FRESH_H:
        return {**out, "state": "fresh"}
    rej = _parse(st.get("last_reject_at"))
    if rej and (not _parse(st.get("last_accepted_at")) or rej > _parse(st.get("last_accepted_at"))):
        # 手机发了、服务器拒了：是我们的 bug，不是老大的设置
        return {**out, "state": "server", "cause": ",".join(x for x in (st.get("last_reject_reasons") or []) if x)}
    hk = st.get("health") or {}
    hk_h = _hours(now, hk.get("at"))
    if hk.get("foreground") and hk.get("samples") == 0 and hk_h is not None and hk_h <= 24 and (acc_h is None or acc_h > 24):
        # App 在前台查过 HealthKit，一条都没有，而且一天多没收到过：权限关了（HealthKit 不告诉读权限，只能这样判断）
        return {**out, "state": "blocked", "action": PERMISSION_ACTION}
    up_h = out["last_upload_h"]
    if up_h is None or up_h > 24:
        return {**out, "state": "quiet"}          # 手机一天没开 App / 没网：打开就补上，不算问题
    if out["age_h"] is not None and out["age_h"] <= 36:
        return {**out, "state": "fresh"}
    return {**out, "state": "late"}               # 手机在线但样本旧：原因不明，进开发排查，不打扰老大


def status(cfg, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    w, a = whoop(cfg, now), apple(cfg, now)
    actions = [x["action"] for x in (w, a) if x.get("action")]
    return {"whoop": w, "apple": a, "actions": actions}


def brief_lines(cfg, now: datetime | None = None) -> list[str]:
    """给 P-Health 的简报：每条都写清原因和该怎么说。"""
    s = status(cfg, now)
    w, a = s["whoop"], s["apple"]
    out = []
    if w.get("state") == "needs_login":
        out.append("WHOOP 登录失效，要老大在 App 里点「重新登录 WHOOP」（这是唯一要他做的事）")
    elif w.get("state") == "late":
        out.append(f"WHOOP 数据晚到约 {int(w.get('late_h') or 0)} 小时，服务器在自动重试，不用老大做什么；别说他没连上，用最近的数就说明是哪天的")
    if a.get("state") == "blocked":
        out.append("Apple 健康权限关了：" + PERMISSION_ACTION.split("：", 1)[1])
    elif a.get("state") == "server":
        out.append("Apple 健康的数据卡在服务器这边（开发在修），不用老大做什么；不要让他去改设置，也不要说他没连上")
    elif a.get("state") == "late":
        out.append("Apple 健康最近的数据有点旧，原因在排查，不用老大做什么；不要说他没连上")
    return out


def notices(cfg, now: datetime | None = None) -> list[dict]:
    """页面上的提示：只放要老大动手的。"""
    return [{"text": t, "source": "server", "action": True} for t in status(cfg, now)["actions"]]


def _alert(cfg, kind: str, detail: str, now: datetime) -> bool:
    """记一条给开发看的警报；同一类一天只记一次。"""
    path = Path(cfg.data_dir) / DEV_ALERTS
    day = now.date().isoformat()
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
            r = json.loads(line)
            if r.get("kind") == kind and str(r.get("at", ""))[:10] == day:
                return False
    except (OSError, ValueError):
        pass
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now.isoformat(timespec="seconds"), "kind": kind, "detail": detail[:300]},
                           ensure_ascii=False) + "\n")
    return True


def self_check(cfg, now: datetime | None = None) -> list[str]:
    """每小时巡一次：手机在线但数据没进库、WHOOP 一直失败——当 bug 记下来，不等老大发现。"""
    now = now or datetime.now(timezone.utc)
    s = status(cfg, now)
    raised = []
    a, w = s["apple"], s["whoop"]
    if a.get("state") == "server" and _alert(cfg, "apple_rejected", f"样本被拒：{a.get('cause')}", now):
        raised.append("apple_rejected")
    if a.get("state") == "late" and _alert(cfg, "apple_stale", f"手机在线但最新样本 {a.get('latest_sample_utc')}", now):
        raised.append("apple_stale")
    if w.get("state") == "late" and _alert(cfg, "whoop_late", f"WHOOP {w.get('late_h')} 小时没成功：{w.get('cause')}", now):
        raised.append("whoop_late")
    if w.get("state") == "needs_login" and _alert(cfg, "whoop_login", "WHOOP 刷新令牌失效", now):
        raised.append("whoop_login")
    return raised


def read_alerts(cfg, days: int = 7) -> list[dict]:
    path = Path(cfg.data_dir) / DEV_ALERTS
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []
    return [r for r in rows if str(r.get("at", "")) >= since[:19]]
