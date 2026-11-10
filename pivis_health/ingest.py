"""设备数据接入：iPhone 原生上报 → vault samples 表（复用既有只读管道）。

- 样本按 (device_id, sample_id) 幂等写入（INSERT OR REPLACE），重传安全
- 类型与单位白名单和 readonly/baselines 的实际约定一致（对照 health.sqlite3 现存数据）
- 位置 / 蓝牙等非样本观测追加到 <data_dir>/device/observations.jsonl，不进样本表
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .event_ingest import EventStore

# type → 期望单位（对照 vault samples 表现存数据）
ALLOWED_TYPES: dict[str, str] = {
    "sleep_analysis": "category",
    "heart_rate": "count/min",
    "heart_rate_variability_sdnn": "ms",
    "resting_heart_rate": "count/min",
    "respiratory_rate": "count/min",
    "oxygen_saturation": "%",
    "step_count": "count",
    "active_energy_burned": "kcal",
    "body_mass": "kg",
    "workout": "workout",
}

# 收任何带时区的 ISO 时间（App 从 build 43 起发北京时间「+08:00」，以前只收「Z」，全被拒了），一律换成 UTC「Z」存：
# 库里按字符串比较时间，格式必须一致
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})$")


def utc_ts(value: Any) -> str | None:
    """'2026-11-07T21:45:12+08:00' → '2026-11-07T13:45:12Z'；小数秒原样保留；不是带时区的 ISO 时间就返回 None。"""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    day, hms, frac, zone = m.group(1), m.group(2), m.group(3) or "", m.group(4)
    if zone == "Z":
        return f"{day}T{hms}{frac}Z"
    try:
        local = datetime.fromisoformat(f"{day}T{hms}{zone[:3]}:{zone[-2:]}")
    except ValueError:
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + frac + "Z"


def _valid_ts(value: Any) -> bool:
    return utc_ts(value) is not None


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def ingest_samples(db_path: Path, rows: list[dict],
                   device_id: str = "iphone-native") -> dict:
    """白名单校验后写入 batches + samples。返回接受/拒绝计数与原因。"""
    accepted: list[tuple] = []
    rejected: list[dict] = []
    for r in rows[:5000]:
        t = str(r.get("type") or "")
        if t not in ALLOWED_TYPES:
            rejected.append({"sample_id": r.get("sample_id"), "reason": f"type_not_allowed:{t}"})
            continue
        if str(r.get("unit") or "") != ALLOWED_TYPES[t]:
            rejected.append({"sample_id": r.get("sample_id"), "reason": "unit_mismatch"})
            continue
        if not (_valid_ts(r.get("start_at")) and _valid_ts(r.get("end_at"))):
            rejected.append({"sample_id": r.get("sample_id"), "reason": "bad_timestamp"})
            continue
        if t == "sleep_analysis" and not r.get("category_value"):
            rejected.append({"sample_id": r.get("sample_id"), "reason": "sleep_needs_category"})
            continue
        sid = str(r.get("sample_id") or uuid.uuid4())
        accepted.append((
            device_id, sid, t, utc_ts(r["start_at"]), utc_ts(r["end_at"]), ALLOWED_TYPES[t],
            r.get("numeric_value"), r.get("category_value"),
        ))
    if not accepted:
        return {"accepted": 0, "rejected": len(rejected), "reject_reasons": rejected[:10]}

    batch_id = f"device-{uuid.uuid4()}"
    digest_src = json.dumps(accepted, sort_keys=True, default=str)
    digest = f"sha1:{uuid.uuid5(uuid.NAMESPACE_URL, digest_src)}"
    rows = [(d, s, batch_id, t, st, en, un, nv, cv) for (d, s, t, st, en, un, nv, cv) in accepted]
    con = _connect(db_path)
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO batches (batch_id, batch_digest, acknowledgement_json)"
                " VALUES (?, ?, ?)",
                (batch_id, digest, json.dumps({"source": "device-upload", "n": len(accepted)})),
            )
            con.executemany(
                "INSERT OR REPLACE INTO samples"
                " (device_id, sample_id, batch_id, type, start_at, end_at, unit,"
                "  numeric_value, category_value) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
    finally:
        con.close()
    return {"accepted": len(accepted), "rejected": len(rejected),
            "reject_reasons": rejected[:10], "batch_id": batch_id}


STATE_FILE = "ingest_state.json"


def note_result(data_dir: Path, sent: int, result: dict, health: dict | None = None) -> dict:
    """每次手机上报都记一笔：收到几条、收下几条、拒了几条和原因。数据状态 / 自检按它分清「手机没传」和「服务器没收」。
    health：App（build 53 起）报的这次查 HealthKit 的情况 {foreground, samples, error}——前台查到 0 条才可能是权限关了。"""
    path = Path(data_dir) / STATE_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["last_upload_at"] = now
    if isinstance(health, dict):
        state["health"] = {"at": now, "foreground": bool(health.get("foreground")),
                           "samples": int(health.get("samples") or 0), "error": str(health.get("error") or "")[:120]}
    if sent:
        state["last_samples_at"] = now
        state["last_sent"] = sent
        state["last_accepted"] = int(result.get("accepted") or 0)
        state["last_rejected"] = int(result.get("rejected") or 0)
        if state["last_accepted"]:
            state["last_accepted_at"] = now
        if state["last_rejected"]:
            state["last_reject_at"] = now
            state["last_reject_reasons"] = [r.get("reason") for r in (result.get("reject_reasons") or [])][:5]
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return state


def read_state(data_dir: Path) -> dict:
    try:
        return json.loads((Path(data_dir) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def log_observation(data_dir: Path, kind: str, payload: dict, *,
                    source: str = "iphone-native",
                    event_id: str | None = None,
                    occurred_at: str | None = None) -> dict:
    """位置 / 蓝牙等观测写可靠事件库与兼容 jsonl，不进样本表。"""
    occurred_at = occurred_at or payload.get("ts") or payload.get("occurred_at")
    if not occurred_at:
        occurred_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if event_id is None:
        canonical = json.dumps({"kind": kind, "occurred_at": occurred_at,
                                "source": source, "payload": payload},
                               sort_keys=True, ensure_ascii=False, default=str)
        if payload.get("ts") or payload.get("occurred_at"):
            event_id = "obs-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        else:
            event_id = f"obs-{uuid.uuid4()}"

    store = EventStore(Path(data_dir) / "events.sqlite3")
    try:
        result = store.append({"event_id": event_id, "type": kind,
                               "occurred_at": occurred_at, "source": source,
                               "payload": payload})
    finally:
        store.close()

    obs_dir = Path(data_dir) / "device"
    obs_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "event_id": event_id,
        "payload": payload,
    }, ensure_ascii=False)
    with (obs_dir / "observations.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return result
