"""P-Health Agent 业务组件发布器。

规则层只提供原始证据；Agent 生成组件 JSON；校验通过后原子发布。
客户端只读最新发布版，发布失败保留上一版，不回退成规则拼装的伪 Agent 页面。
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from . import content, dsh_chat
from .agent_context import AgentContextStore
from .config import Config
from .experience import Experience
from .tools import HealthTools

COMPOSER_CONTEXT = "组件编排"
PAGE_TYPES = {
    "now": {"headline", "hero_status", "quiet_note", "need_section"},
    "sleep": {"headline", "hero_risk", "media", "tiles", "need_section", "relax_entry", "whoop_confirm", "evidence"},
    "sport": {"headline", "hero_risk", "media", "tiles", "need_section", "evidence"},
    "stress": {"headline", "hero_risk", "media", "tiles", "need_section", "evidence"},
    "relax": {"relax_plan", "relax_library"},
}
PAGE_SESSION = {"sleep": "休息", "sport": "运动", "stress": "压力"}
MAX_COMPONENTS = {"headline": 1, "hero_status": 1, "hero_risk": 1, "media": 1, "quiet_note": 1,
                  "tiles": 1, "need_section": 1, "relax_entry": 1, "whoop_confirm": 1,
                  "evidence": 1, "relax_plan": 1, "relax_library": 1}
# 槽位媒体：类型枚举与禁用域名（隐私纪律：只外链不转存；境外平台不可控，国内优先 B 站）
MEDIA_TYPES = ("embed", "video", "audio")
_BLOCKED_MEDIA_HOSTS = ("youtube.com", "youtu.be")


def relax_document(tools: HealthTools) -> dict:
    lib = tools.relax_library()
    lib["suggested"] = tools.relax_suggest()["suggested"]
    entries = tools.subj.entries(kinds=["relax_plan"], since=tools._now().date(),
                                 until=tools._now().date())
    plan = entries[-1].get("payload") if entries else None
    if plan:
        lib["plan_today"] = {
            "items": [content.item_by_id(i) or {"id": i, "title": t}
                      for i, t in zip(plan.get("items") or [], plan.get("titles") or [])],
            "titles": plan.get("titles") or [],
        }
    return lib


def raw_document(tools: HealthTools, page: str) -> dict:
    if page == "relax":
        doc = relax_document(tools)
    else:
        from .pages import V2Pages
        v2 = V2Pages(tools)
        fn = {"now": v2.today, "sleep": v2.sleep, "sport": v2.sport, "stress": v2.stress}.get(page)
        if not fn:
            raise ValueError(f"unknown publication page: {page}")
        doc = fn(tools._now().date())
        doc.pop("components", None)
    today = tools._now().date()
    doc["interaction_history"] = tools.subj.entries(
        kinds=["need_feedback", "relax_plan", "content_rating"], since=today - timedelta(days=14), until=today)
    # 媒体槽位的真实链接池（固定槽位、自由表现：素材只找不改，Agent 只能从这里选）
    doc["media_library"] = [{"id": it["id"], "title": it["title"],
                             "duration_min": it["duration_min"], "url": it["url"]}
                            for it in content.LIBRARY]
    # 共享上下文一并交给 Agent：主 Session 的干涉（含展示覆盖）在下一次编排生效，
    # 而不是仅靠发布后覆盖（目标架构 §12）
    doc["shared_context"] = AgentContextStore(tools.cfg).snapshot()
    return doc


def _get_path(doc: dict, path: str) -> Any:
    cur: Any = doc
    for part in re.sub(r"\[(\d+)\]", r".\1", path).split("."):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _numeric_match(raw: Any, displayed: str) -> bool:
    if isinstance(raw, bool) or raw is None:
        return False
    if isinstance(raw, str):
        tokens = re.findall(r"\d+(?:\.\d+)?(?:/\d+)?", raw)
        return any(re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.])", displayed)
                   for v in tokens)
    if not isinstance(raw, (int, float)):
        return False
    value = float(raw)
    candidates = {str(int(round(value))), f"{value:.1f}", f"{value:.2f}", f"{value:.3f}"}
    return any(re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.])", displayed) for v in candidates)


def _check_style(style: Any) -> None:
    if style is not None:
        Experience._style(style)


def _media_pool(doc: dict) -> set[str]:
    """证据文档中出现过的全部 http(s) 链接：槽位媒体只能从中选取，防止编造。"""
    urls: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and node.startswith(("http://", "https://")):
            urls.add(node)

    walk(doc)
    return urls


def _validate_media(holder: dict, pool: set[str]) -> None:
    """槽位带媒体（media_type/url 任一出现）时的统一校验：配对、类型、协议、域名、证据池。"""
    mtype, url = holder.get("media_type"), holder.get("url")
    if mtype is None and url is None:
        return
    if mtype not in MEDIA_TYPES or not isinstance(url, str) or not url:
        raise ValueError("media requires media_type (embed|video|audio) and url")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"media url must be http/https: {url}")
    host = parts.netloc.rsplit("@", 1)[-1].split(":", 1)[0].lower()
    if host in _BLOCKED_MEDIA_HOSTS or any(host.endswith(f".{h}") for h in _BLOCKED_MEDIA_HOSTS):
        raise ValueError(f"media url cannot use YouTube: {url}")
    if url not in pool:
        raise ValueError(f"media url not in evidence: {url}")


def _validate_common(c: dict, allowed: set[str]) -> None:
    if not isinstance(c, dict) or c.get("type") not in allowed:
        raise ValueError(f"unknown component: {c.get('type') if isinstance(c, dict) else type(c)}")
    _check_style(c.get("style"))


def _validate_data_card(c: dict, doc: dict) -> None:
    value = "" if c.get("value") is None else str(c["value"])
    c["value"] = value
    if c.get("tone") not in (None, "risk", "amber", "good", "accent"):
        raise ValueError("tone must be risk/amber/good/accent")
    source = c.get("source")
    if re.search(r"\d", value):
        if not isinstance(source, str) or not source:
            raise ValueError(f"numeric {c.get('type')} requires source")
        raw = _get_path(doc, source)
        if raw is None:
            raise ValueError(f"source not found: {source}")
        if not _numeric_match(raw, value):
            raise ValueError(f"value does not match source {source}: {value!r} != {raw!r}")
    if c.get("viz"):
        viz = c["viz"]
        if viz.get("type") not in ("gap_bar", "verdict_dial", "mini_bars"):
            raise ValueError("unknown hero visualization")
        for key in ("avg", "need", "values"):
            if key in viz and key != "values" and not isinstance(viz[key], (int, float)):
                raise ValueError(f"viz.{key} must be numeric")


def _validate_needs(c: dict, pool: set[str]) -> None:
    needs = c.get("needs") or []
    if not isinstance(needs, list) or len(needs) > 3:
        raise ValueError("need_section supports at most 3 cards")
    seen = set()
    clean = []
    aliases = {"sleep": "睡眠", "sport": "运动", "exercise": "运动", "stress": "压力",
               "body": "身体", "data": "数据"}
    for n in needs:
        if not isinstance(n, dict) or not n.get("need_type") or not n.get("action"):
            raise ValueError("each need requires need_type/action")
        if n["need_type"] in seen:
            continue
        seen.add(n["need_type"])
        n["specialty"] = aliases.get(str(n.get("specialty") or "").lower(), n.get("specialty"))
        if n.get("specialty") not in ("睡眠", "运动", "压力", "身体", "数据"):
            raise ValueError("invalid need specialty")
        if not isinstance(n.get("title") or "", str) or not isinstance(n.get("evidence") or "", str):
            raise ValueError("need title/evidence must be text")
        _check_style(n.get("style"))
        _validate_media(n, pool)  # 待办可为视频/音频，但 action 语义保留、链接必须真实
        clean.append(n)
    c["needs"] = clean


def _validate_chart(c: dict, doc: dict) -> None:
    chart = c.get("chart")
    if not isinstance(chart, dict) or chart.get("type") not in ("night_bars", "strain_bars", "hrv_line", "table"):
        raise ValueError("evidence requires a supported chart")
    rows = chart.get("nights") or chart.get("points") or []
    if not isinstance(rows, list) or len(rows) > 31:
        raise ValueError("chart rows invalid")
    source_rows = (doc.get("chart14") or (doc.get("play") or {}).get("strain14")
                   or (doc.get("band") or {}).get("series") or [])
    source_values = {
        (str(r.get("date")), round(float(v), 3))
        for r in source_rows if isinstance(r, dict)
        for v in (r.get("actual"), r.get("value"), r.get("strain"), r.get("need")) if isinstance(v, (int, float))
    }
    for row in rows:
        if not isinstance(row, dict) or not row.get("date"):
            raise ValueError("chart row requires date")
        for key in ("actual", "value", "strain", "need"):
            value = row.get(key)
            if isinstance(value, (int, float)) and (str(row["date"]), round(float(value), 3)) not in source_values:
                raise ValueError(f"chart value not in evidence: {row['date']} {value}")


def _validate_relax(c: dict, doc: dict) -> None:
    items = c.get("relax_items") or c.get("items") or []
    c["relax_items"] = items
    c.pop("items", None)
    if not isinstance(items, list) or len(items) > 8:
        raise ValueError("relax items must be an array of at most 8")
    library = {i["id"]: i for i in doc.get("items") or []}
    seen = set()
    for item in items:
        iid = item.get("id") if isinstance(item, dict) else None
        if iid not in library or iid in seen:
            raise ValueError(f"invalid or duplicate relax item: {iid}")
        seen.add(iid)
        source = library[iid]
        for key in ("title", "category", "duration_min", "url"):
            if key in item and item[key] != source.get(key):
                raise ValueError(f"relax metadata cannot change: {iid}.{key}")
        item.update({k: source.get(k) for k in ("title", "category", "duration_min", "url")})
        if not isinstance(item.get("reason") or "", str):
            raise ValueError("relax reason must be text")


def validate_components(page: str, components: Any, doc: dict) -> list[dict]:
    if not isinstance(components, list) or not components:
        raise ValueError("components must be a non-empty array")
    allowed = PAGE_TYPES[page]
    media_pool = _media_pool(doc)
    counts: dict[str, int] = {}
    out = []
    for original in components:
        c = dict(original)
        if isinstance(c.get("style"), str):
            c["style"] = {"material": c["style"]}
        for key in ("items", "needs"):
            for item in c.get(key) or []:
                if isinstance(item, dict) and isinstance(item.get("style"), str):
                    item["style"] = {"material": item["style"]}
        _validate_common(c, allowed)
        typ = c["type"]
        counts[typ] = counts.get(typ, 0) + 1
        if counts[typ] > MAX_COMPONENTS[typ]:
            raise ValueError(f"too many {typ} components")
        if typ == "headline":
            expected = PAGE_SESSION.get(page)
            if expected and c.get("session") != expected:
                raise ValueError("headline session is fixed")
            if not c.get("text"):
                raise ValueError("headline text required")
        elif typ in ("hero_status", "hero_risk"):
            _validate_data_card(c, doc)
        elif typ == "media":
            if not isinstance(c.get("title"), str) or not c.get("title"):
                raise ValueError("media requires title")
            if c.get("description") is not None and not isinstance(c.get("description"), str):
                raise ValueError("media description must be text")
            if c.get("media_type") is None or c.get("url") is None:
                raise ValueError("media requires media_type (embed|video|audio) and url")
            _validate_media(c, media_pool)
        elif typ == "tiles":
            items = c.get("items") or []
            if not isinstance(items, list) or len(items) != 3:
                raise ValueError("tiles requires exactly 3 cards")
            for item in items:
                if item.get("media_type") is not None or item.get("url") is not None:
                    _validate_media(item, media_pool)  # 媒体小卡：不要求 value/source
                else:
                    _validate_data_card(item, doc)
                _check_style(item.get("style"))
        elif typ == "need_section":
            _validate_needs(c, media_pool)
        elif typ == "evidence":
            _validate_chart(c, doc)
        elif typ == "whoop_confirm":
            if not (doc.get("whoopConfirm") or doc.get("whoop_confirm") or {}).get("pending"):
                raise ValueError("cannot publish WHOOP confirmation without pending evidence")
        elif typ == "relax_entry":
            if not (doc.get("tonight") or {}).get("planSetToday"):
                raise ValueError("relax_entry requires a real plan")
        elif typ in ("relax_plan", "relax_library"):
            _validate_relax(c, doc)
        out.append(c)
    if page != "relax":
        if out[0].get("type") != "headline" or counts.get("headline") != 1:
            raise ValueError("page requires one leading headline")
        if page == "now" and counts.get("hero_status") != 1:
            raise ValueError("now requires exactly one hero_status big card")
        if page != "now":
            if counts.get("hero_risk", 0) + counts.get("media", 0) != 1:
                raise ValueError("specialty page requires exactly one hero_risk or media big card")
            if counts.get("tiles") != 1:
                raise ValueError("specialty page requires exactly one tiles component")
    elif counts.get("relax_library") != 1:
        raise ValueError("relax requires one relax_library")
    return out


class PublicationStore:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.path = cfg.data_dir / "component_publications.json"
        self.lock_path = cfg.data_dir / "component-composer.lock"

    def all(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "pages": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "pages": {}}

    def get(self, page: str) -> dict | None:
        record = self.all()["pages"].get(page)
        return record if isinstance(record, dict) and isinstance(record.get("components"), list) else None

    def save(self, page: str, components: list[dict], session: str,
             shared_revision: int | None = None) -> dict:
        if shared_revision is None:
            shared_revision = AgentContextStore(self.cfg).revision()
        raw = self.all()
        record = {"components": components, "published_at": datetime.now().isoformat(timespec="seconds"),
                  "producer": "P-Health Agent", "session": session,
                  "shared_revision": int(shared_revision)}
        raw["pages"][page] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="components-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return record

    @contextmanager
    def lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _schema_instruction(page: str) -> str:
    if page == "now":
        return """输出 {\"components\":[...]}，只许 headline、hero_status、quiet_note、need_section。
- headline 必须且只能一个，session 按首要行动 owner 或空字符串。
- hero_status 必须且只能一个；quiet_note 可选，放在 hero_status 之后。hero_status 数值必须带证据点路径 source。
- now 页面没有小卡，严禁输出 tiles/tile/hero_risk/media/evidence。
- need_section 用 needs 数组，0–3 项，由 Agent 决定行动，不照抄规则候选。
- need 每项可带 media_type/url 表示视频/音频待办；action 仍必填；url 只能取证据中的真实链接（如 media_library），仅 http/https，禁止 YouTube，国内平台优先 B 站。
- tone 只能 risk/amber/good/accent。不得虚构数字或改 Session。
示例：{\"components\":[{\"type\":\"headline\",\"kicker\":\"P-Health · 当前判断\",\"text\":\"一句话\",\"session\":\"\"},{\"type\":\"hero_status\",\"kicker\":\"当前最异常\",\"label\":\"睡眠债\",\"value\":\"16.3h\",\"source\":\"hero.value\",\"status\":\"需要关注\",\"tone\":\"amber\"}]}"""
    if page == "relax":
        return """输出一个 JSON 对象 {\"components\":[...]}。只能用 relax_plan、relax_library。
- relax_library 恰好一个，relax_items 从证据 items 中选择，每项字段 id/reason/selected；Agent 决定推荐与理由。
- relax_plan 仅在 plan_today 真实存在时输出，relax_items 字段 id/reason。
- 素材 id、标题、分类、时长、URL 由校验器从证据补齐，不得编造。
- 不加 headline，不改客户端结构。"""
    return """输出一个 JSON 对象 {\"components\":[...]}。这是最终给 iOS 渲染的唯一业务文档。
- 第一块且仅一块 headline：{type,kicker,text,session}；sleep=休息、sport=运动、stress=压力，now 按任务 owner 或空字符串。
- 专项页大卡有且只有一个：hero_risk 或 media 二选一，两者同时出现或缺席都非法；数值型 value 必须带 source，source 是证据 JSON 的点路径。
- media 大卡：{type:"media",title,description,media_type,url,style}；media_type 只能 embed/video/audio；url 只能取证据中的真实链接（如 media_library），仅 http/https，禁止 youtube.com/youtu.be，国内平台优先 B 站。
- tiles 必须且只能一个，items 恰好 3 项；每项 label/value/note/tone/source/style，只能取证据中真实值。缺数据的小卡用“暂无数据/—”如实表达，不得减少数量或虚构数值。小卡也可带 media_type/url 用媒体表现，带媒体时不要求数值 source，链接规则同上。
- need_section 的数组字段名必须是 needs（不是 items），最多 3 项。每项 need_type/title/specialty/evidence/action/window/top，可带 media_type/url 表示视频/音频待办（action 仍必填，链接规则同上）。由你判断是否需要、如何生成和排序，不要照抄规则候选；0 项就不输出该组件。
- evidence 必须是 {type:\"evidence\",title:\"...\",chart:{...}}；chart.type 为 night_bars/strain_bars/hrv_line/table。夜间数据放 chart.nights，其他点放 chart.points，不能改成对话组件格式。
- tone 只能是 risk/amber/good/accent。style 仅 glass/solid/plain、合法 #RRGGBB、合理字号/圆角/透明度。
- 缺数据如实说明，不把缺失当正常或异常，不诊断，不虚构数字，不调用 ask_user_question。
- 页面结构固定：1 大卡 + 3 小卡，不得增加导航、改 Session 或改变卡片数量。
结构示例（只示范字段形状，数值必须换成当前证据）：
{\"components\":[
 {\"type\":\"headline\",\"kicker\":\"休息专项\",\"text\":\"一句当前判断\",\"session\":\"休息\"},
 {\"type\":\"hero_risk\",\"kicker\":\"主风险\",\"value\":\"16.3\",\"unit\":\"h\",\"source\":\"tiles.debt.debt_h\",\"status\":\"显著偏高\",\"tone\":\"risk\"},
 {\"type\":\"tiles\",\"items\":[{\"label\":\"Recovery\",\"value\":\"42%\",\"source\":\"recovery\",\"note\":\"当前恢复\"},{\"label\":\"入睡难度\",\"value\":\"暂无数据\",\"note\":\"样本积累中\"},{\"label\":\"今晚安排\",\"value\":\"按计划\",\"note\":\"当前有效决定\"}]}, 
 {\"type\":\"need_section\",\"needs\":[{\"need_type\":\"custom_action\",\"title\":\"当前行动\",\"specialty\":\"睡眠\",\"evidence\":\"真实依据\",\"action\":\"可执行动作\",\"window\":\"今晚\",\"top\":true}]},
 {\"type\":\"evidence\",\"title\":\"依据\",\"chart\":{\"type\":\"night_bars\",\"nights\":[{\"date\":\"2026-10-31\",\"actual\":7.12,\"need\":10.31}]}}
]}"""


def _rpc(method: str, request: dict) -> dict:
    return dsh_chat.dsh_api(method, request, timeout=35)


def _ensure_composer(page: str, suffix: str) -> str:
    """页面编排会话：单独的工作目录和轻量预设（phealth-composer）。DSH 还没有这个预设时退回 P-Health 预设。"""
    context = f"{COMPOSER_CONTEXT}:{page}:{suffix}"
    session = dsh_chat._session_id(context)
    if not dsh_chat._session_dir(context).exists():
        cwd = dsh_chat.ensure_composer_cwd()
        try:
            _rpc("session/create", {"sessionId": session, "cwd": cwd, "agentPreset": dsh_chat.COMPOSER_PRESET})
        except Exception:  # noqa: BLE001
            _rpc("session/create", {"sessionId": session, "cwd": cwd, "agentPreset": dsh_chat.AGENT_PRESET})
    return session


def _new_assistant_text(events: list[dict]) -> str:
    """这一轮最后一条助手消息（以前把整轮所有文字拼起来，前面多一句话就解析失败）。"""
    last = ""
    for d in events:
        if d.get("type") != "assistant/message":
            continue
        data = d.get("data", d)
        message = data.get("message", data)
        texts = [c["text"] for c in message.get("content") or []
                 if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
        if texts:
            last = "\n".join(texts)
    return last.strip()


def _parse_json(text: str) -> dict:
    """取出回复里的那个 JSON 对象：允许前后有代码块标记或一两句多余的话。"""
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        try:
            value = json.loads(raw[start:end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError as exc:
            raise ValueError(f"Agent did not return valid JSON: {exc}; prefix={text[:160]!r}") from exc
        if value is None:
            raise ValueError(f"Agent did not return valid JSON; prefix={text[:160]!r}")
    if not isinstance(value, dict):
        raise ValueError("Agent publication must be a JSON object")
    return value


