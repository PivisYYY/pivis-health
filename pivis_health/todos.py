"""v3 待办与项目：P-Health 生成的“生成式待办卡”和长期项目（CBT-I、训练计划…）。

- 待办由 Agent 通过 CLI（todo-add / todo-update）或项目模板生成；客户端只渲染和回传输入。
- 项目只存 Agent 写的模板；服务端按日期把模板展开成当天待办（像日历重复事件），
  模板改了，当天还没开始的实例跟着更新，从而“今晚起生效”。
- 原始健康数据不在这里；这里只存计划、待办状态和用户的主观记录。
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

from . import journal
from .config import Config
from .media import MediaError
from .media import check_url as _media_check_url

BOARDS = ("sleep", "sport", "stress", "life")   # life＝日常（饭、试纸这类记录），只出待办，不单独成页
BOARD_LABEL = {"sleep": "休息", "sport": "运动", "stress": "压力", "life": "日常"}
KINDS = ("done", "follow", "options", "scale", "number", "fields", "proposal",
         "counter", "timer", "checklist", "confirm")
# counter：一天点好几次（喝水 3/6 杯）；timer：有时长、开始后倒计时（午睡 20 分钟）；
# checklist：一件事拆几小步、每步单独勾；confirm：要留下完成时间的事（按医嘱打针 08:05）
STATUSES = ("proposed", "scheduled", "in_progress", "processing", "done", "skipped", "expired")
ARCHIVE_AFTER_DAYS = 60
PENDING = ("proposed", "scheduled", "in_progress", "processing")
VERBS = ("start", "done", "later", "skip")
INPUT_TYPES = ("options", "multi", "scale", "number", "text", "time", "photo")
SUBMIT_MODES = ("local", "agent", "chat")
MEDIA_KINDS = ("audio", "video", "embed")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# 待办的 13 种形式（todo-cards skill 和 `./pivis-health todo-forms` 都从这里读，别在提示词里抄一份）
TODO_FORMS: list[dict] = [
    {"form": "check", "name": "打勾", "kind": "done", "use": "做了点一下就行的事",
     "template": {"board": "sleep", "when": "23:00", "title": "放下手机", "kind": "done", "note": "开勿扰，放远"}},
    {"form": "options", "name": "单选", "kind": "options", "use": "一个问题 2–4 个选项，点了就交",
     "template": {"board": "sleep", "when": "13:20", "title": "现在困吗", "kind": "options",
                  "inputs": [{"id": "sleepy", "label": "", "type": "options", "options": ["很困", "有点", "不困"], "submit": "agent"}]}},
    {"form": "number", "name": "数值", "kind": "number", "use": "记一个数（体重、血压读数），默认填上次的值",
     "template": {"board": "life", "when": "07:40", "title": "称体重", "kind": "number", "note": "空腹，上完厕所",
                  "inputs": [{"id": "kg", "label": "", "type": "number", "unit": "kg", "step": 0.1, "default": "last", "submit": "agent"}]}},
    {"form": "fields", "name": "多字段日记", "kind": "fields", "use": "一次记好几样（睡眠日记）：时间、选项、加减、打分、文字",
     "template": {"board": "sleep", "when": "08:50", "title": "记一下昨晚", "kind": "fields", "submit_label": "记好了",
                  "inputs": [{"id": "bed", "label": "几点上床", "type": "time"},
                             {"id": "latency", "label": "多久睡着", "type": "options", "options": ["15 分内", "15–30", "30–60", "1 小时+"]},
                             {"id": "wakes", "label": "醒了几次", "type": "number", "step": 1, "unit": "次"},
                             {"id": "energy", "label": "早上精神", "type": "scale", "min": 1, "max": 5},
                             {"id": "more", "label": "还想说的", "type": "text", "submit": "agent"}]}},
    {"form": "counter", "name": "计数", "kind": "counter", "use": "一天点好几次的事，点一下加一格（喝水、站起来）",
     "template": {"board": "life", "title": "喝水", "kind": "counter", "target": 6, "unit": "杯"}},
    {"form": "timer", "name": "计时", "kind": "timer", "use": "只用于午睡、闭眼歇这类休息：开始后倒计时、到点响。任何练习都不用它（练习用「练习视频」）",
     "template": {"board": "sleep", "when": "13:30", "title": "午睡 20 分钟", "kind": "timer", "duration_min": 20, "alarm": "13:50"}},
    {"form": "follow", "name": "练习视频", "kind": "follow",
     "use": "所有练习（拉伸、力量、呼吸、身体扫描、睡前流程、入眠练习）：这个项目 + 一个视频（只认 follow 出的片），点开就播；老大点对勾才算做完",
     "template": {"board": "sleep", "when": "22:40", "title": "睡前拉伸", "kind": "follow",
                  "steps": [{"title": "睡前拉伸", "media": {"kind": "video", "title": "睡前拉伸 · 8 分钟",
                                                            "url": "<follow 出片给的 /media/follow/<ssid>/out.mp4>",
                                                            "duration_min": 8}}]}},
    {"form": "photo", "name": "拍照", "kind": "fields", "use": "拍饭、试纸；交上来你看图、写一句点评到 summary",
     "template": {"board": "life", "when": "19:30", "title": "晚饭拍一张", "kind": "fields",
                  "inputs": [{"id": "photo", "label": "", "type": "photo", "submit": "agent"}]}},
    {"form": "rating", "name": "打分", "kind": "options", "use": "用完素材 / 新做法之后评价，按分数换或留",
     "template": {"board": "sleep", "title": "昨晚的放松有用吗", "kind": "options", "note": "身体扫描 · 12 分钟",
                  "inputs": [{"id": "rate", "label": "", "type": "options", "options": ["有用", "一般", "没用，换一个"], "submit": "agent"}]}},
    {"form": "proposal", "name": "提议", "kind": "proposal", "use": "你想改计划时先问：原因写进 note，2–3 个方案让老大选；一定写 until",
     "template": {"board": "sleep", "title": "本周复盘：睡前流程", "kind": "proposal", "until": "21:30",
                  "note": "身体扫描 3 次都跳了，理由都是太晚太困",
                  "inputs": [{"id": "fix", "label": "", "type": "options",
                              "options": ["提前到 23:10，换 6 分钟呼吸", "只换 6 分钟短版", "先不动，再跑一周"], "submit": "agent"}]}},
    {"form": "ask", "name": "追问", "kind": "options", "use": "破了规则后的追问：选一个原因（想多说的，老大会点卡上的图标进对话说）",
     "template": {"board": "sleep", "title": "起晚了，是什么原因", "kind": "options",
                  "inputs": [{"id": "why", "label": "", "type": "options", "options": ["没听到闹钟", "太困起不来", "想多睡会", "别的原因"],
                              "submit": "agent"}]}},
    {"form": "auto", "name": "设备自动完成", "kind": "done", "use": "设备能识别的事（入睡），不用老大点",
     "template": {"board": "sleep", "when": "01:30", "title": "01:30 后再上床", "kind": "done", "auto": "bedtime"}},
    {"form": "confirm", "name": "确认 + 时间", "kind": "confirm", "use": "要留下完成时间的事（按医嘱用药），卡上不写剂量",
     "template": {"board": "life", "when": "08:00", "title": "按医嘱打针", "kind": "confirm", "note": "每周一"}},
]


from .clock import NIGHT_END_HOUR  # noqa: E402  00:00–05:59 的事属于前一天的「当晚」


def due_at(day: date | str, hhmm: str) -> datetime | None:
    """这张卡真正到点的时刻（不带时区）：date 那天的 hh:mm；00:00–05:59 算当晚，即第二天凌晨。"""
    if not hhmm:
        return None
    d = date.fromisoformat(day) if isinstance(day, str) else day
    h, m = (int(x) for x in hhmm.split(":"))
    at = datetime(d.year, d.month, d.day, h, m)
    return at + timedelta(days=1) if h < NIGHT_END_HOUR else at


def _sort_when(when: str) -> str:
    """00:00–05:59 属于当晚，排在晚上之后。"""
    if not when:
        return "99:99"
    h = int(when[:2])
    return f"{h + 24:02d}{when[2:]}" if h < NIGHT_END_HOUR else when


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
    """媒体链接规则在 media.py（唯一来源），这里换成待办的错误类型。"""
    try:
        _media_check_url(url)
    except MediaError as exc:
        raise TodoError(str(exc)) from exc


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
        # build 43 起卡上不再有「自己写一句」（allow_text 忽略）：想多说的，老大点卡上的图标带着这张卡进对话
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
        if i.get("step") not in (None, ""):
            step = float(i["step"])
            if not 0 < step <= 100:
                raise TodoError("number.step 要在 0–100 之间")
            out["step"] = step             # App 画 − / + 按钮，一次加减这么多
        d = i.get("default")
        if d not in (None, ""):
            if d != "last":
                float(d)
            out["default"] = d             # "last" = 先填上次的值（体重这类）
    if typ in ("text", "number", "time") and i.get("placeholder"):
        out["placeholder"] = str(i["placeholder"])
    submit = i.get("submit") or ("agent" if typ in ("text", "time") else "local")
    if submit not in SUBMIT_MODES:
        raise TodoError(f"submit 只能是 {SUBMIT_MODES}")
    out["submit"] = submit
    return out


PRACTICE_RULE = ("练习（拉伸、力量、呼吸、身体扫描、睡前流程、入眠练习……）一律是「这个项目 + 一个视频」："
                 "kind=follow，steps 只放一项、带一个 video，url 是 follow 出片给的 /media/follow/<ssid>/out.mp4。"
                 "B 站等公开链接、音频、文字步骤、计时、子清单都不能当练习；还没有视频就先请老大发一个博主视频，用 follow 命令出片")


def check_practice(t: dict, cfg: Config | None = None) -> None:
    """2026-11-07 起的产品约束：练习只用视频，只认 follow 出的片。只在新建 / 修改时检查，旧数据照常能读。"""
    kind = t.get("kind")
    if kind == "checklist":
        raise TodoError("子清单不再用于练习。" + PRACTICE_RULE)
    if kind != "follow":
        return
    steps = t.get("steps") or []
    media = (steps[0].get("media") if len(steps) == 1 else None) or {}
    url = str(media.get("url") or "")
    if len(steps) != 1 or media.get("kind") != "video" or not url.startswith("/media/follow/"):
        raise TodoError(PRACTICE_RULE)
    if cfg is not None:
        from .follow import media_path
        if media_path(cfg, url) is None:
            raise TodoError(f"这个视频还不在素材库里：{url}。先用 follow 出片，用它给的地址（follow session list 能查已出的片）")


_TITLE_TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3])[:：]([0-5]\d)(?![\d])")


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
    if not when:
        # 每条待办都该有时间（老大 11-08：不统一很乱）：标题里写了钟点（「23:15 前洗完澡」）就拿它当时间
        m = _TITLE_TIME.search(str(base.get("title") or ""))
        if m:
            when = f"{int(m.group(1)):02d}:{m.group(2)}"
    status = base.get("status") or ("proposed" if kind == "proposal" else "scheduled")
    if status not in STATUSES:
        raise TodoError(f"status 只能是 {STATUSES}")
    # 卡上只有一个主动作（build 43 起没有「晚点」「算了」：要改时间、今天不做，老大点卡上的图标进对话说）
    verbs = base.get("verbs") or {"follow": ["start", "done"], "timer": ["start"], "done": ["done"]}.get(kind, [])
    verbs = [v for v in verbs if v not in ("later", "skip")]   # 老卡里的「晚点」「算了」不再显示
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
        "ops": list(base.get("ops") or [])[-30:],
        "edited": bool(base.get("edited")),
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
    if kind == "follow" and not out["steps"] and out["media"]:
        out["steps"] = [{"title": out["title"], "note": "", "duration_min": out["media"].get("duration_min"),
                         "media": out["media"]}]
        out["media"] = None
    if kind == "follow" and out["duration_min"] is None and len(out["steps"]) == 1:
        d = out["steps"][0].get("duration_min") or (out["steps"][0].get("media") or {}).get("duration_min")
        out["duration_min"] = float(d) if d else None
    if out["kind"] in ("options", "scale", "number", "fields") and not out["inputs"]:
        raise TodoError(f"kind={kind} 需要 inputs")
    if kind == "counter":
        target = int(base.get("target") or 0)
        if not 1 <= target <= 20:
            raise TodoError("counter 要写 target（1–20，比如一天 6 杯水）")
        out["target"] = target
        out["unit"] = str(base.get("unit") or "次")[:4]
    if kind == "timer" and not out["duration_min"]:
        raise TodoError("timer 要写 duration_min（比如午睡 20）")
    if kind == "checklist":
        items = [str(x).strip() for x in base.get("items") or [] if str(x).strip()]
        if not 2 <= len(items) <= 8 or any(len(x) > 20 for x in items):
            raise TodoError("checklist 要写 items：2–8 小步，每步最多 20 个字")
        out["items"] = items
    date.fromisoformat(out["date"])
    return out


def _same_content(a: dict, b: dict) -> bool:
    """练习内容没变（只挪了时间、改了哪几天）：不用重新校验视频（洞察先改后说只改时间）。"""
    skip = {"board", "date", "duration_min", "when", "weekdays", "alarm"}
    return {k: v for k, v in a.items() if k not in skip} == {k: v for k, v in b.items() if k not in skip}


TITLE_MAX = 12        # 待办标题（老大 11-10：卡上字太多）。写的时候 ≤ 8 字最好
NOTE_MAX = 20         # note 只在卡展开后显示
PROJECT_NAME_MAX = 10 # 项目名（去掉「· 56 天」后）不带括号、频率（第几天 App 自己显示）


def check_lengths(t: dict, fields: tuple[str, ...] = ("title", "note")) -> None:
    """P-Health 写卡时的字数上限；超了退回让它改短（老卡、项目展开时不查）。"""
    title = str(t.get("title") or "")
    if "title" in fields and len(title) > TITLE_MAX:
        raise TodoError(f"标题「{title}」{len(title)} 个字，最多 {TITLE_MAX} 个（≤ 8 个最好）：只写做什么，时间写进 when，细节写进 note")
    note = str(t.get("note") or "")
    if "note" in fields and len(note) > NOTE_MAX:
        raise TodoError(f"note「{note}」{len(note)} 个字，最多 {NOTE_MAX} 个：只留一句有信息量的")


def clean_project_name(name: str) -> str:
    """项目名只留名字：去掉「· 56 天」「（每周三次）」「一个月」这类（第几天 App 另外显示）。"""
    n = re.sub(r"\s*[（(【\[][^）)】\]]*[）)】\]]\s*", "", str(name or ""))
    n = re.sub(r"\s*[·・]?\s*(\d+|[一二两三四五六七八九十]+)\s*(个月|天|周|星期)$", "", n)
    return n.strip() or str(name or "").strip()


def _check_plan(cfg, t: dict) -> None:
    """和今晚睡眠安排的明显冲突（洗澡太晚、剧烈运动太晚、CBT-I 上床 / 午睡）：退回让 P-Health 改。"""
    from . import plan_lint
    bad = plan_lint.check(cfg, t)
    if bad:
        raise TodoError("和睡眠安排冲突：" + "；".join(bad) + "。改好再写（同一件事今天其他卡有冲突的也一起改）")


def check_project_name(name: str) -> None:
    n = str(name or "")
    if re.search(r"[（(【\[]", n):
        raise TodoError(f"项目名「{n}」不要带括号：频率、天数写进模板和 days，App 自己显示第几天")
    short = clean_project_name(n)
    if len(short) > PROJECT_NAME_MAX:
        raise TodoError(f"项目名「{short}」{len(short)} 个字，最多 {PROJECT_NAME_MAX} 个（≤ 6 个最好）")


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
            before = json.dumps(data, ensure_ascii=False, sort_keys=True)
            yield data
            if json.dumps(data, ensure_ascii=False, sort_keys=True) != before:
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
        cutoff = (date.today() - timedelta(days=ARCHIVE_AFTER_DAYS)).isoformat()
        old = {k: t for k, t in data["todos"].items() if str(t.get("date") or "9999") < cutoff}
        if old:
            with open(self.path.with_name("todos_archive.jsonl"), "a", encoding="utf-8") as f:
                for t in old.values():
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
            for k in old:
                data["todos"].pop(k, None)
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self) -> dict:
        return self._read()

    # ---- 待办 ----
    def add(self, todo: dict, today: date) -> dict:
        todo = dict(todo)
        todo.setdefault("date", today.isoformat())
        check_lengths(todo)
        _check_plan(self.cfg, todo)
        with self._locked() as data:
            t = normalize(todo)
            check_practice(t, self.cfg)
            if t["id"] in data["todos"]:
                raise TodoError(f"id 已存在: {t['id']}")
            data["todos"][t["id"]] = t
            data["log"].append({"at": _now_iso(), "op": "add", "id": t["id"]})
            journal.todo(self.cfg, "add", t, t["id"], by=t.get("source") or "agent")
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
            if patch.get("media") and "steps" not in patch and (patch.get("kind") or cur.get("kind")) == "follow":
                patch = {**patch, "steps": []}      # 换视频只给了 media：替换掉卡上原来的那一段，不是叠在旁边
            if by == "agent":
                check_lengths(patch, tuple(k for k in ("title", "note") if k in patch))
            t = normalize(patch, cur)
            if by == "agent" and any(k in patch for k in ("when", "title", "note", "duration_min")) \
                    and t.get("status") in ("scheduled", "proposed", "processing"):
                _check_plan(self.cfg, t)
            if any(k in patch for k in ("kind", "steps", "media", "items")):
                check_practice(t, self.cfg)
            t["id"] = todo_id
            if by == "agent" and cur.get("source") == "project" and set(patch) - {"status", "escalate", "summary", "record"}:
                t["edited"] = True
            if by == "agent" and cur.get("status") == "processing":
                t["request"] = None
            # P-Health 重写 record 时，老大提交过的历史（submitted）保留
            kept = (cur.get("record") or {}).get("submitted")
            if kept:
                t["record"] = {**(t.get("record") or {}), "submitted": (t.get("record") or {}).get("submitted") or kept}
            data["todos"][todo_id] = t
            data["log"].append({"at": _now_iso(), "op": "update", "id": todo_id, "by": by})
            journal.todo(self.cfg, "update", t, todo_id, by=by,
                         changed=sorted(k for k in patch if k not in ("record",)),
                         prev_when=cur.get("when") if cur.get("when") != t.get("when") else None)
            return t

    def remove(self, todo_id: str) -> dict:
        with self._locked() as data:
            t = data["todos"].pop(todo_id, None)
            if not t:
                raise TodoError(f"没有这条待办: {todo_id}")
            data["log"].append({"at": _now_iso(), "op": "remove", "id": todo_id})
            journal.todo(self.cfg, "remove", t, todo_id)
            return {"removed": todo_id}

    def last_record(self, t: dict, back_days: int = 14) -> dict | None:
        """同一个项目里同一项（id 是 项目-日期-key）上一次的结果：跟做卡显示「上次：有用（11/3）」，数值卡先填上次的数。"""
        pid = t.get("project")
        if not pid or t.get("source") != "project":
            return None
        prefix = f"{pid}-{t['date']}-"
        if not t["id"].startswith(prefix):
            return None
        key = t["id"][len(prefix):]
        day = date.fromisoformat(t["date"])
        todos = self._read()["todos"]
        for i in range(1, back_days + 1):
            d = day - timedelta(days=i)
            prev = todos.get(f"{pid}-{d.isoformat()}-{key}")
            if prev and prev["status"] in ("done", "skipped"):
                rec = prev.get("record") or {}
                return {"date": f"{d.month}/{d.day}", "summary": prev.get("summary") or "",
                        "status": prev["status"], "values": rec.get("values") or {}}
        return None

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
            if "name" in project and project["name"] != cur.get("name"):
                check_project_name(project["name"])
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
            changed = "daily" in project      # 只有传了 daily 才校验模板
            for n, tpl in enumerate(merged.get("daily") or []):
                tpl = dict(tpl)
                tpl.setdefault("key", f"k{n + 1}")
                tpl["board"] = merged["board"]
                tpl["date"] = merged["start"]
                wd = tpl.get("weekdays")
                if wd is not None and (not isinstance(wd, list) or not wd or any(d not in range(1, 8) for d in wd)):
                    raise TodoError("weekdays 是 1–7 的列表（1=周一，7=周日）")
                norm = normalize(tpl)
                if changed and not any(_same_content(tpl, old) for old in cur.get("daily") or []):
                    check_practice(norm, self.cfg)  # 新加 / 改过的模板才校验（练习只用视频），老模板照常能读
                if changed and not any(str(o.get("title")) == str(tpl.get("title")) and str(o.get("note") or "") == str(tpl.get("note") or "")
                                       for o in cur.get("daily") or []):
                    check_lengths(tpl)              # 改过标题 / note 的模板才查字数
                if changed and not any(_same_content(tpl, old) and str(old.get("when")) == str(tpl.get("when"))
                                       for old in cur.get("daily") or []):
                    _check_plan(self.cfg, tpl)      # 新加 / 改过的模板才查和睡眠安排的冲突
                if tpl.get("duration_min") in (None, "") and norm["duration_min"]:
                    tpl = {**tpl, "duration_min": norm["duration_min"]}   # 时长写在视频里的，模板上也带一份（复盘、习惯卡要用）
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
            journal.append(self.cfg, journal.TODOS, {
                "at": journal.now_iso(self.cfg), "op": "project_set", "id": merged["id"], "revision": merged["revision"],
                "board": merged.get("board"), "status": merged.get("status"),
                "daily": [{"key": d.get("key"), "when": d.get("when"), "kind": d.get("kind"), "title": d.get("title")}
                          for d in merged.get("daily") or []]})
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
                                or cur.get("template_rev") == p["revision"] or cur.get("edited")
                                or (cur.get("record") or {}).get("count")):
                        continue
                    if not cur and now is not None and tpl.get("when") and day == start:
                        if due_at(day, tpl["when"]) < now.replace(tzinfo=None) - timedelta(minutes=30):
                            continue
                    body = {k: v for k, v in tpl.items() if k != "key"}
                    body.update({"id": tid, "date": day.isoformat(), "project": p["id"],
                                 "source": "project", "template_rev": p["revision"]})
                    if cur:
                        body["created_at"] = cur["created_at"]
                    data["todos"][tid] = normalize(body)
                    created.append(tid)
                    journal.todo(self.cfg, "materialize" if not cur else "rematerialize", data["todos"][tid], tid,
                                 by="project")
                # 模板里删掉的项：当天还没开始的实例一并移除
                for tid, t in list(data["todos"].items()):
                    if (t.get("project") == p["id"] and t["date"] == day.isoformat()
                            and t.get("source") == "project" and t["status"] in ("scheduled", "proposed")
                            and tid[len(f"{p['id']}-{day.isoformat()}-"):] not in keys):
                        data["todos"].pop(tid)
        return created

    # ---- 用户提交 ----
    def user_submit(self, todo_id: str, action: str, values: dict | None, text: str | None,
                    summary: str | None, now: datetime, op_id: str | None = None) -> dict:
        with self._locked() as data:
            t = data["todos"].get(todo_id)
            if not t:
                raise TodoError(f"没有这条待办: {todo_id}")
            # App 的发送队列断网后会重发：同一个 op_id 只算一次（计数不会多加、计时不会重开）
            op_id = str(op_id or "")[:64]
            if op_id and op_id in (t.get("ops") or []):
                return t
            values = values or {}
            if action == "start":
                t["status"] = "in_progress"
                if t["kind"] == "timer":       # 计时：记下开始时间，App 按它倒计时
                    t["record"] = {**(t.get("record") or {}), "started_at": now.isoformat(timespec="seconds")}
            elif action == "inc":
                # 计数：点一下加一格；到 target 就算做完
                rec = dict(t.get("record") or {})
                rec["count"] = max(0, int(rec.get("count") or 0) + int(values.get("n") or 1))
                rec["at"] = now.isoformat(timespec="seconds")
                t["record"] = rec
                target = int(t.get("target") or 1)
                t["summary"] = f"{rec['count']} / {target} {t.get('unit') or ''}".strip()
                if rec["count"] >= target:
                    t["status"] = "done"
            elif action == "check":
                # 子清单：勾 / 取消一小步；全部勾完就算做完
                items = t.get("items") or []
                idx = int(values.get("index", -1))
                if not 0 <= idx < len(items):
                    raise TodoError("没有这一步")
                rec = dict(t.get("record") or {})
                checked = set(rec.get("checked") or [])
                checked.add(idx) if values.get("on", True) else checked.discard(idx)
                rec["checked"] = sorted(checked)
                t["record"] = rec
                t["summary"] = f"{len(checked)} / {len(items)}"
                t["status"] = "done" if len(checked) == len(items) else "in_progress" if checked else "scheduled"
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
            if op_id:
                t["ops"] = (list(t.get("ops") or []) + [op_id])[-30:]
            t["updated_at"] = _now_iso()
            data["log"].append({"at": _now_iso(), "op": f"user_{action}", "id": todo_id})
            journal.todo(self.cfg, f"user_{action}", t, todo_id, by="user", at=now.isoformat(timespec="seconds")[:19])
            return t

    def auto_complete(self, todo_id: str, summary: str, record: dict) -> None:
        with self._locked() as data:
            t = data["todos"].get(todo_id)
            if t and t["status"] in ("scheduled", "proposed", "in_progress", "expired"):
                t["status"] = "done"
                t["summary"] = summary
                t["record"] = {**record, "auto": True}
                t["updated_at"] = _now_iso()
                journal.todo(self.cfg, "auto_done", t, todo_id, by="system")


def board_of_context(context: str) -> str | None:
    return {"休息": "sleep", "运动": "sport", "压力": "stress"}.get(context)
