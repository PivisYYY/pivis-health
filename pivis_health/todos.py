"""v3 待办与项目：P-Health 生成的“生成式待办卡”和长期项目（CBT-I、训练计划…）。

- 待办由 Agent 通过 CLI（todo-add / todo-update）或项目模板生成；客户端只渲染和回传输入。
- 项目只存 Agent 写的模板；服务端按日期把模板展开成当天待办（像日历重复事件），
  模板改了，当天还没开始的实例跟着更新，从而“今晚起生效”。
- 原始健康数据不在这里；这里只存计划、待办状态和用户的主观记录。
"""
from __future__ import annotations

import fcntl
import ipaddress
import json
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from .config import Config

BOARDS = ("sleep", "sport", "stress", "life")   # life＝日常（饭、试纸这类记录），只出待办，不单独成页
BOARD_LABEL = {"sleep": "休息", "sport": "运动", "stress": "压力", "life": "日常"}
KINDS = ("done", "follow", "options", "scale", "number", "fields", "proposal")
STATUSES = ("proposed", "scheduled", "in_progress", "processing", "done", "skipped", "expired")
PENDING = ("proposed", "scheduled", "in_progress", "processing")
VERBS = ("start", "done", "later", "skip")
INPUT_TYPES = ("options", "multi", "scale", "number", "text", "time", "photo")
SUBMIT_MODES = ("local", "agent", "chat")
MEDIA_KINDS = ("audio", "video", "embed")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _sort_when(when: str) -> str:
    """00:00–05:59 属于当晚，排在晚上之后。"""
    if not when:
        return "99:99"
    h = int(when[:2])
    return f"{h + 24:02d}{when[2:]}" if h < 6 else when


def sort_key(t: dict) -> tuple:
    """等老大拍板/回答的卡排最前：提议，以及没有时间点、等着填的卡（P-Health 追问时会把提议改成这种）。其余按时间。"""
    waiting = t["status"] in ("proposed", "processing", "scheduled")
    asks = t["kind"] == "proposal" or (not t["when"] and t["kind"] in ("fields", "options", "scale", "number"))
    return (0 if waiting and asks else 1, _sort_when(t["when"]), t.get("created_at") or "")


class TodoError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _check_url(url: str) -> None:
    if url.startswith("/media/"):
        return
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise TodoError(f"媒体链接必须是公网 http(s) 地址或 /media/ 下的文件: {url}")
    host = p.hostname
    if host in ("localhost",) or host.endswith(".local"):
        raise TodoError(f"媒体链接不能用本地地址: {url}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:  # 域名，不是 IP
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")):
        raise TodoError(f"媒体链接不能用内网地址: {url}")
    if "youtube.com" in host or "youtu.be" in host:
        raise TodoError("不使用 YouTube，国内平台优先 B 站")


def _norm_media(m: Any) -> dict | None:
    if m in (None, {}, ""):
        return None
    if not isinstance(m, dict) or not m.get("url"):
        raise TodoError("media 需要 {kind, url, title}")
    kind = m.get("kind") or m.get("media_type") or "audio"
    if kind not in MEDIA_KINDS:
        raise TodoError(f"media.kind 只能是 {MEDIA_KINDS}")
    _check_url(str(m["url"]))
    out = {"kind": kind, "url": str(m["url"]), "title": str(m.get("title") or "")}
    if m.get("duration_min") is not None:
        out["duration_min"] = float(m["duration_min"])
    return out


def _norm_input(i: Any, idx: int) -> dict:
    if not isinstance(i, dict):
        raise TodoError("inputs 每项必须是对象")
    typ = i.get("type")
    if typ not in INPUT_TYPES:
        raise TodoError(f"input.type 只能是 {INPUT_TYPES}")
    out = {"id": str(i.get("id") or f"q{idx + 1}"), "type": typ, "label": str(i.get("label") or "")}
    if typ in ("options", "multi"):
        opts = i.get("options") or []
        norm = []
        for o in opts:
            if isinstance(o, dict):
                norm.append({"id": str(o.get("id") or o.get("label")), "label": str(o.get("label") or o.get("id"))})
            else:
                norm.append({"id": str(o), "label": str(o)})
        if not 2 <= len(norm) <= 6:
            raise TodoError("选项需要 2–6 个")
        out["options"] = norm
    if typ == "scale":
        out["min"] = int(i.get("min", 1))
        out["max"] = int(i.get("max", 5))
        if out["max"] - out["min"] > 10 or out["max"] <= out["min"]:
            raise TodoError("scale 范围不合理")
        if i.get("min_label"):
            out["min_label"] = str(i["min_label"])
        if i.get("max_label"):
            out["max_label"] = str(i["max_label"])
    if typ == "number":
        out["unit"] = str(i.get("unit") or "")
    if typ in ("text", "number", "time") and i.get("placeholder"):
        out["placeholder"] = str(i["placeholder"])
    submit = i.get("submit") or ("agent" if typ in ("text", "time") else "local")
    if submit not in SUBMIT_MODES:
        raise TodoError(f"submit 只能是 {SUBMIT_MODES}")
    out["submit"] = submit
    return out


def normalize(t: dict, existing: dict | None = None) -> dict:
    base = dict(existing or {})
    base.update({k: v for k, v in t.items() if v is not None})
    board = base.get("board")
    if board not in BOARDS:
        raise TodoError(f"board 只能是 {BOARDS}")
    if not str(base.get("title") or "").strip():
        raise TodoError("title 必填")
    kind = base.get("kind") or "done"
    if kind not in KINDS:
        raise TodoError(f"kind 只能是 {KINDS}")
    when = str(base.get("when") or "")
    if when and not _HHMM.match(when):
        raise TodoError("when 必须是 HH:MM")
    status = base.get("status") or ("proposed" if kind == "proposal" else "scheduled")
    if status not in STATUSES:
        raise TodoError(f"status 只能是 {STATUSES}")
    verbs = base.get("verbs") or (["start", "later", "skip"] if kind == "follow" else ["done", "later", "skip"]
                                  if kind == "done" else ["later", "skip"])
    for v in verbs:
        if v not in VERBS:
            raise TodoError(f"verbs 只能从 {VERBS} 里选")
    out = {
        "id": str(base.get("id") or f"t{int(time.time() * 1000)}"),
        "board": board,
        "project": base.get("project") or None,
        "date": str(base.get("date")),
        "when": when,
        "title": str(base["title"]).strip(),
        "note": str(base.get("note") or ""),
        "kind": kind,
        "status": status,
        "verbs": list(verbs),
        "inputs": [_norm_input(i, n) for n, i in enumerate(base.get("inputs") or [])],
        "media": _norm_media(base.get("media")),
        "steps": [],
        "duration_min": float(base["duration_min"]) if base.get("duration_min") not in (None, "") else None,
        "alarm": str(base.get("alarm") or "") or None,
        "until": str(base.get("until") or "") or None,   # 过了这个点还没处理就自动收起（比如午睡提议 14:30）
        "auto": base.get("auto") or None,
        "submit_label": str(base.get("submit_label") or ""),
        "record": base.get("record") or None,
        "summary": str(base.get("summary") or ""),
        "escalate": base.get("escalate") or None,
        "request": base.get("request") or None,
        "source": base.get("source") or "agent",
        "template_rev": base.get("template_rev"),
        "created_at": base.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
    }
    if out["alarm"] and not _HHMM.match(out["alarm"]):
        raise TodoError("alarm 必须是 HH:MM")
    if out["until"] and not _HHMM.match(out["until"]):
        raise TodoError("until 必须是 HH:MM")
    for s in base.get("steps") or []:
        if not isinstance(s, dict) or not s.get("title"):
            raise TodoError("steps 每项需要 title")
        step = {"title": str(s["title"]), "note": str(s.get("note") or ""),
                "duration_min": float(s["duration_min"]) if s.get("duration_min") else None,
                "media": _norm_media(s.get("media"))}
        out["steps"].append(step)
    if out["kind"] in ("options", "scale", "number", "fields") and not out["inputs"]:
        raise TodoError(f"kind={kind} 需要 inputs")
    date.fromisoformat(out["date"])
    return out


class TodoStore:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.path = cfg.data_dir / "todos_v3.json"
        self.lock_path = cfg.data_dir / "todos_v3.lock"

    @contextmanager
    def _locked(self):
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            data = self._read()
            yield data
            self._write(data)
            fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("todos", {})
        data.setdefault("projects", {})
        data.setdefault("log", [])
        return data

    def _write(self, data: dict) -> None:
        data["log"] = data["log"][-500:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self) -> dict:
        return self._read()

    # ---- 待办 ----
    def add(self, todo: dict, today: date) -> dict:
        todo = dict(todo)
        todo.setdefault("date", today.isoformat())
        with self._locked() as data:
            t = normalize(todo)
            if t["id"] in data["todos"]:
                raise TodoError(f"id 已存在: {t['id']}")
            data["todos"][t["id"]] = t
            data["log"].append({"at": _now_iso(), "op": "add", "id": t["id"]})
            return t

    def update(self, todo_id: str, patch: dict, by: str = "agent") -> dict:
        with self._locked() as data:
            cur = data["todos"].get(todo_id)
            if not cur:
                raise TodoError(f"没有这条待办: {todo_id}")
            patch = dict(patch)
            if by == "agent" and cur.get("status") == "processing" and "status" not in patch:
                patch["status"] = "proposed" if (patch.get("kind") or cur["kind"]) == "proposal" else "scheduled"
            if by == "agent" and "escalate" not in patch and patch.get("status") != "processing":
                patch["escalate"] = None
            t = normalize(patch, cur)
            t["id"] = todo_id
            if by == "agent" and cur.get("status") == "processing":
                t["request"] = None
            # P-Health 重写 record 时，老大提交过的历史（submitted）保留
            kept = (cur.get("record") or {}).get("submitted")
            if kept:
                t["record"] = {**(t.get("record") or {}), "submitted": (t.get("record") or {}).get("submitted") or kept}
            data["todos"][todo_id] = t
            data["log"].append({"at": _now_iso(), "op": "update", "id": todo_id, "by": by})
            return t

    def remove(self, todo_id: str) -> dict:
        with self._locked() as data:
            t = data["todos"].pop(todo_id, None)
            if not t:
                raise TodoError(f"没有这条待办: {todo_id}")
            data["log"].append({"at": _now_iso(), "op": "remove", "id": todo_id})
            return {"removed": todo_id}

    def get(self, todo_id: str) -> dict | None:
        return self._read()["todos"].get(todo_id)

    def for_date(self, day: date, board: str | None = None) -> list[dict]:
        items = [t for t in self._read()["todos"].values()
                 if t["date"] == day.isoformat() and (board is None or t["board"] == board)]
        return sorted(items, key=sort_key)

    # ---- 项目 ----
    def project_set(self, project: dict, today: date, now: datetime | None = None) -> dict:
        if not project.get("id"):
            raise TodoError("project 需要 id")
        with self._locked() as data:
            cur = data["projects"].get(project["id"]) or {}
            merged = {**cur, **project}      # 已有的项目可以只传要改的字段（比如 {"id":"strength","status":"paused"}）
            if not merged.get("name"):
                raise TodoError("新项目需要 name")
            if merged.get("board") not in BOARDS:
                raise TodoError(f"project.board 只能是 {BOARDS}")
            if merged.get("status") not in (None, "active", "paused", "done"):
                raise TodoError("project.status 只能是 active / paused / done")
            merged.setdefault("start", today.isoformat())
            date.fromisoformat(merged["start"])
            merged["days"] = int(merged.get("days") or 30)
            merged["status"] = merged.get("status") or "active"
            merged["rules"] = [str(r) for r in merged.get("rules") or []]
            daily = []
            for n, tpl in enumerate(merged.get("daily") or []):
                tpl = dict(tpl)
                tpl.setdefault("key", f"k{n + 1}")
                tpl["board"] = merged["board"]
                tpl["date"] = merged["start"]
                wd = tpl.get("weekdays")
                if wd is not None and (not isinstance(wd, list) or not wd or any(d not in range(1, 8) for d in wd)):
                    raise TodoError("weekdays 是 1–7 的列表（1=周一，7=周日）")
                normalize(tpl)  # 校验模板
                daily.append(tpl)
            merged["daily"] = daily
            merged["reviews"] = merged.get("reviews") or []
            merged["revision"] = int(cur.get("revision") or 0) + 1
            merged["updated_at"] = _now_iso()
            history = cur.get("history") or []
            if cur:
                history.append({"revision": cur.get("revision"), "daily": cur.get("daily"),
                                "rules": cur.get("rules"), "replaced_at": _now_iso()})
            merged["history"] = history[-20:]
            data["projects"][merged["id"]] = merged
            data["log"].append({"at": _now_iso(), "op": "project_set", "id": merged["id"],
                                "revision": merged["revision"]})
            # 已经展开到今天及以后的实例：项目暂停或结束就撤掉还没开始的；模板改了就在那几天重新展开
            later = sorted({t["date"] for t in data["todos"].values()
                            if t.get("project") == merged["id"] and t.get("source") == "project"
                            and t["date"] >= today.isoformat()})
            if merged["status"] != "active":
                for tid, t in list(data["todos"].items()):
                    if (t.get("project") == merged["id"] and t.get("source") == "project"
                            and t["date"] >= today.isoformat() and t["status"] in ("scheduled", "proposed")):
                        data["todos"].pop(tid)
                later = []
        self.materialize(today, now)
        for d in later:
            if d > today.isoformat():
                self._refresh_day(merged["id"], date.fromisoformat(d))
        return self._read()["projects"][project["id"]]

    def _refresh_day(self, project_id: str, day: date) -> None:
        """项目模板改了以后，以后某天已经展开的实例跟着改：不在项目日期范围内或模板里删掉的项撤掉，其余按新模板重新展开。"""
        with self._locked() as data:
            p = data["projects"].get(project_id)
            start = date.fromisoformat(p["start"])
            inside = start <= day < start + timedelta(days=p["days"])
            if not inside:
                for tid, t in list(data["todos"].items()):
                    if (t.get("project") == project_id and t["date"] == day.isoformat()
                            and t.get("source") == "project" and t["status"] in ("scheduled", "proposed")):
                        data["todos"].pop(tid)
        if inside:
            self.materialize(day)

    def projects(self, active_only: bool = False) -> list[dict]:
        ps = list(self._read()["projects"].values())
        return [p for p in ps if p.get("status") == "active"] if active_only else ps

    def project_for_board(self, board: str, day: date) -> dict | None:
        for p in self.projects(active_only=True):
            start = date.fromisoformat(p["start"])
            if p["board"] == board and start <= day < start + timedelta(days=p["days"]):
                return p
        return None

    def materialize(self, day: date, now: datetime | None = None) -> list[str]:
        """把有效项目的每日模板展开成当天待办；模板更新后，当天未开始的实例同步更新。
        当天第一次展开时，已经过去的时间点不再补出来（比如晚上才开始的项目，不出当天早上的日记）。"""
        created = []
        with self._locked() as data:
            for p in data["projects"].values():
                if p.get("status") != "active":
                    continue
                start = date.fromisoformat(p["start"])
                if not (start <= day < start + timedelta(days=p["days"])):
                    continue
                keys = set()
                for tpl in p.get("daily") or []:
                    keys.add(tpl["key"])
                    wd = tpl.get("weekdays")   # 只在某几天出现（1=周一 … 7=周日），比如周末尿检
                    if wd and day.isoweekday() not in wd:
                        keys.discard(tpl["key"])
                        continue
                    tid = f"{p['id']}-{day.isoformat()}-{tpl['key']}"
                    cur = data["todos"].get(tid)
                    if cur and (cur["status"] not in ("scheduled", "proposed")
                                or cur.get("template_rev") == p["revision"]):
                        continue
                    if not cur and now is not None and tpl.get("when") and day == start:
                        due = datetime.combine(day, datetime.strptime(tpl["when"], "%H:%M").time())
                        if due.hour < 6:
                            due += timedelta(days=1)
                        if due < now.replace(tzinfo=None) - timedelta(minutes=30):
                            continue
                    body = {k: v for k, v in tpl.items() if k != "key"}
                    body.update({"id": tid, "date": day.isoformat(), "project": p["id"],
                                 "source": "project", "template_rev": p["revision"]})
                    if cur:
                        body["created_at"] = cur["created_at"]
                    data["todos"][tid] = normalize(body)
                    created.append(tid)
                # 模板里删掉的项：当天还没开始的实例一并移除
                for tid, t in list(data["todos"].items()):
                    if (t.get("project") == p["id"] and t["date"] == day.isoformat()
                            and t.get("source") == "project" and t["status"] in ("scheduled", "proposed")
                            and tid[len(f"{p['id']}-{day.isoformat()}-"):] not in keys):
                        data["todos"].pop(tid)
        return created

    # ---- 用户提交 ----
    def user_submit(self, todo_id: str, action: str, values: dict | None, text: str | None,
                    summary: str | None, now: datetime) -> dict:
        with self._locked() as data:
            t = data["todos"].get(todo_id)
            if not t:
                raise TodoError(f"没有这条待办: {todo_id}")
            values = values or {}
            if action == "start":
                t["status"] = "in_progress"
            elif action == "done":
                t["status"] = "done"
                t["record"] = {"values": values, "text": text or "", "at": now.isoformat(timespec="seconds")}
                t["summary"] = summary or t.get("summary") or ""
            elif action == "later":
                minutes = int(values.get("minutes") or 10)
                base = now if not t["when"] else datetime.combine(now.date(), datetime.strptime(t["when"], "%H:%M").time())
                base = max(base.replace(tzinfo=None), now.replace(tzinfo=None))
                t["when"] = (base + timedelta(minutes=minutes)).strftime("%H:%M")
                t["status"] = "scheduled" if t["kind"] != "proposal" else "proposed"
            elif action == "skip":
                t["status"] = "skipped"
                t["record"] = {"values": values, "text": text or "", "at": now.isoformat(timespec="seconds")}
                t["summary"] = summary or ("已跳过" + (f" · {text}" if text else ""))
            elif action == "agent":
                t["request"] = {"values": values, "text": text or "", "at": now.isoformat(timespec="seconds"),
                                "previous_status": t["status"]}
                t["status"] = "processing"
                # 老大提交的内容同时存进 record（带最近 10 次的历史）：P-Health 改完这条时 request 会清掉，答案不能跟着丢
                rec = dict(t.get("record") or {})
                subs = list(rec.get("submitted") or [])[-9:]
                subs.append({"values": values, "text": text or "", "at": now.isoformat(timespec="seconds")})
                rec.update({"values": values, "text": text or "", "at": now.isoformat(timespec="seconds"), "submitted": subs})
                t["record"] = rec
            elif action == "correct":
                t["record"] = {**(t.get("record") or {}), "corrected": values, "text": text or ""}
                t["summary"] = summary or t["summary"]
            else:
                raise TodoError(f"未知动作: {action}")
            t["updated_at"] = _now_iso()
            data["log"].append({"at": _now_iso(), "op": f"user_{action}", "id": todo_id})
            return t

    def auto_complete(self, todo_id: str, summary: str, record: dict) -> None:
        with self._locked() as data:
            t = data["todos"].get(todo_id)
            if t and t["status"] in ("scheduled", "proposed", "in_progress", "expired"):
                t["status"] = "done"
                t["summary"] = summary
                t["record"] = {**record, "auto": True}
                t["updated_at"] = _now_iso()


def board_of_context(context: str) -> str | None:
    return {"休息": "sleep", "运动": "sport", "压力": "stress"}.get(context)
