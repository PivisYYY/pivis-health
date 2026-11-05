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

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _valid_ts(value: Any) -> bool:
    return isinstance(value, str) and bool(_TS_RE.match(value))


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
            device_id, sid, t, r["start_at"], r["end_at"], ALLOWED_TYPES[t],
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
