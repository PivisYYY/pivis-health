"""客户端对话驱动的体验配置：对话规则 + 页面内容/表现覆盖。

配置只改变既有组件的字段、数据源和视觉参数；页面、Session、组件种类与数量上限
仍由 layout.py 和 iOS 渲染器固定。所有写入原子落盘并进入主观库审计记录。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date
from typing import Any

from .agent_context import AgentContextStore
from .config import Config
from .subjective import SubjectiveStore

PAGES = ("now", "today", "sleep", "sport", "stress", "relax")
SESSIONS = ("main", "休息", "运动", "压力")
COMPONENTS = (
    "headline", "hero_status", "hero_risk", "quiet_note", "tiles",
    "need_section", "relax_entry", "whoop_confirm", "evidence",
    "relax_plan", "relax_library",
)
CONTENT_FIELDS = {
    "headline": {"kicker", "text"},
    "hero_status": {"kicker", "label", "note", "status", "warning", "tone"},
    "hero_risk": {"kicker", "label", "note", "status", "warning", "tone"},
    "quiet_note": {"text"},
    "tiles": set(),
    "need_section": {"title"},
    "relax_entry": {"label"},
    "whoop_confirm": {"claim"},
    "evidence": {"title"},
    "relax_plan": {"title"},
    "relax_library": {"title"},
}
ITEM_FIELDS = {
    "tiles": {"label", "note", "warning", "tone"},
    "need_section": {"title", "evidence", "action", "window"},
}
STYLE_RANGES = {
    "corner": (8.0, 32.0),
    "tint_opacity": (0.0, 0.35),
    "border_opacity": (0.0, 0.6),
    "shadow_radius": (0.0, 24.0),
    "value_size": (12.0, 56.0),
    "label_size": (10.0, 22.0),
    "note_size": (10.0, 18.0),
    "padding": (8.0, 28.0),
}
STYLE_COLORS = {"tint_color", "accent_color", "text_color"}
TILE_SOURCES = {
    "sleep": {"recovery", "latency", "hq", "debt", "avg_sleep", "bedtime"},
    "sport": {"recovery", "load", "sessions"},
    "stress": {"recovery", "range", "work"},
}
HERO_SOURCES = {
    "sleep": {"debt", "recovery", "latency", "hq", "avg_sleep", "bedtime"},
    "sport": {"verdict", "recovery", "load"},
    "stress": {"hrv", "recovery"},
}


def _empty() -> dict:
    return {"schema_version": 1, "dialogue": {}, "pages": {}}


def _session(name: str) -> str:
    value = "main" if name in ("", "main", "现在") else name
    if value not in SESSIONS:
        raise ValueError(f"unknown session: {name}")
    return value


def _page(name: str) -> str:
    value = "now" if name == "today" else name
    if value not in ("now", "sleep", "sport", "stress", "relax"):
        raise ValueError(f"unknown page: {name}")
    return value


class Experience:
    def __init__(self, cfg: Config, store: SubjectiveStore | None = None) -> None:
        self.path = cfg.data_dir / "experience.json"
        self.store = store
        self.context = AgentContextStore(cfg)

    def all(self) -> dict:
        if not self.path.exists():
            return _empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"experience config unreadable: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("experience config must be an object")
        out = _empty()
        out["dialogue"] = raw.get("dialogue") if isinstance(raw.get("dialogue"), dict) else {}
        out["pages"] = raw.get("pages") if isinstance(raw.get("pages"), dict) else {}
        return out

    def _write(self, raw: dict, kind: str, detail: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="experience-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        if self.store is not None:
            self.store.record(date.today().isoformat(), "experience_change",
                              {"kind": kind, **detail})
        return raw

    def dialogue_list(self, session: str = "main") -> dict:
        key = _session(session)
        rules = self.all()["dialogue"].get(key) or []
        return {"session": key, "rules": rules}

    def dialogue_add(self, session: str, rule: str) -> dict:
        key = _session(session)
        text = rule.strip()
        if not text or len(text) > 1000:
            raise ValueError("rule must contain 1–1000 characters")
        raw = self.all()
        rules = list(raw["dialogue"].get(key) or [])
        if text not in rules:
            rules.append(text)
        raw["dialogue"][key] = rules
        self._write(raw, "dialogue_add", {"session": key, "rule": text})
        return {"session": key, "rules": rules, "index": rules.index(text)}

    def dialogue_remove(self, session: str, index: int) -> dict:
        key = _session(session)
        raw = self.all()
        rules = list(raw["dialogue"].get(key) or [])
        if index < 0 or index >= len(rules):
            raise IndexError("dialogue rule index out of range")
        removed = rules.pop(index)
        raw["dialogue"][key] = rules
        self._write(raw, "dialogue_remove", {"session": key, "index": index, "rule": removed})
        return {"session": key, "removed": removed, "rules": rules}

    def ui(self, page: str) -> dict:
        return self.all()["pages"].get(_page(page)) or {}

    def ui_set(self, page: str, component: str, patch: dict, reason: str = "",
               source_session: str = "unknown") -> dict:
        page_key = _page(page)
        if component not in COMPONENTS:
            raise ValueError(f"unknown component: {component}")
        clean = self._validate_patch(page_key, component, patch)
        raw = self.all()
        pages = raw["pages"]
        old = (pages.get(page_key) or {}).get(component) or {}
        pages.setdefault(page_key, {})[component] = clean
        self._write(raw, "ui_set", {"page": page_key, "component": component,
                                    "old": old, "new": clean, "reason": reason})
        # 展示覆盖同步进入共享上下文：主 Session 的干涉要让下一次页面编排读到，
        # 而不是仅作为事后覆盖（目标架构 §12）；同组件再调整时替代旧决定。
        entry = self.context.record(f"ui.{page_key}.{component}",
                                    {"page": page_key, "component": component, "patch": clean},
                                    source_session=source_session, reason=reason)
        return {"page": page_key, "component": component, "old": old, "new": clean,
                "reason": reason, "structure_changed": False,
                "shared_revision": entry["revision"]}

    def ui_reset(self, page: str, component: str | None = None,
                 source_session: str = "unknown") -> dict:
        page_key = _page(page)
        raw = self.all()
        if component is not None and component not in COMPONENTS:
            raise ValueError(f"unknown component: {component}")
        pages = raw["pages"]
        previous = pages.get(page_key) or {}
        if component:
            previous = {component: previous.get(component) or {}}
            (pages.get(page_key) or {}).pop(component, None)
        else:
            pages.pop(page_key, None)
        self._write(raw, "ui_reset", {"page": page_key, "component": component})
        entry = None
        if previous:
            for name in previous:
                entry = self.context.record(
                    f"ui.{page_key}.{name}",
                    {"page": page_key, "component": name, "reset": True},
                    source_session=source_session, reason="重置展示偏好")
        else:
            entry = self.context.record(
                f"ui.{page_key}", {"page": page_key, "reset": True},
                source_session=source_session, reason="重置展示偏好")
        return {"page": page_key, "component": component, "reset": True,
                "shared_revision": entry["revision"]}

    def _validate_patch(self, page: str, component: str, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise ValueError("patch must be a JSON object")
        allowed = {"fields", "style", "items", "source", "sources", "viz_type", "chart_type"}
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(f"unsupported patch keys: {sorted(unknown)}")
        out: dict[str, Any] = {}
        if "fields" in patch:
            fields = patch["fields"]
            if not isinstance(fields, dict) or set(fields) - CONTENT_FIELDS[component]:
                raise ValueError(f"unsupported fields for {component}; allowed={sorted(CONTENT_FIELDS[component])}")
            out["fields"] = fields
        if "style" in patch:
            out["style"] = self._style(patch["style"])
        if "items" in patch:
            items = patch["items"]
            if component not in ITEM_FIELDS or not isinstance(items, dict):
                raise ValueError("items overrides require a tiles/need_section object keyed by index")
            clean_items = {}
            for raw_index, item in items.items():
                if not str(raw_index).isdigit() or not 0 <= int(raw_index) < 3 or not isinstance(item, dict):
                    raise ValueError("item index must be 0, 1 or 2")
                if set(item) - {"fields", "style"}:
                    raise ValueError("item override supports fields/style only")
                clean: dict[str, Any] = {}
                fields = item.get("fields") or {}
                if set(fields) - ITEM_FIELDS[component]:
                    raise ValueError(f"unsupported item fields; allowed={sorted(ITEM_FIELDS[component])}")
                if fields:
                    clean["fields"] = fields
                if "style" in item:
                    clean["style"] = self._style(item["style"])
                clean_items[str(int(raw_index))] = clean
            out["items"] = clean_items
        if "source" in patch:
            source = patch["source"]
            if component not in ("hero_status", "hero_risk") or source not in HERO_SOURCES.get(page, set()):
                raise ValueError(f"unsupported hero source for {page}: {source}")
            out["source"] = source
        if "sources" in patch:
            sources = patch["sources"]
            if component != "tiles" or not isinstance(sources, list) or not sources:
                raise ValueError("sources must be a non-empty array on tiles")
            if len(sources) > 3 or len(set(sources)) != len(sources) or set(sources) - TILE_SOURCES.get(page, set()):
                raise ValueError(f"tile sources must be 1–3 unique values from {sorted(TILE_SOURCES.get(page, set()))}")
            out["sources"] = sources
        if "viz_type" in patch:
            if component not in ("hero_status", "hero_risk") or patch["viz_type"] not in ("gap_bar", "verdict_dial", "mini_bars", "none"):
                raise ValueError("viz_type must be gap_bar/verdict_dial/mini_bars/none on a hero")
            out["viz_type"] = patch["viz_type"]
        if "chart_type" in patch:
            if component != "evidence" or patch["chart_type"] not in ("night_bars", "strain_bars", "hrv_line", "table"):
                raise ValueError("chart_type must be night_bars/strain_bars/hrv_line/table on evidence")
            out["chart_type"] = patch["chart_type"]
        if not out:
            raise ValueError("empty patch")
        return out

    @staticmethod
    def _style(raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise ValueError("style must be an object")
        allowed = set(STYLE_RANGES) | STYLE_COLORS | {"material"}
        if set(raw) - allowed:
            raise ValueError(f"unsupported style keys: {sorted(set(raw) - allowed)}")
        out = {}
        for key, value in raw.items():
            if key in STYLE_RANGES:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{key} must be numeric")
                lo, hi = STYLE_RANGES[key]
                if not lo <= float(value) <= hi:
                    raise ValueError(f"{key} must be {lo}–{hi}")
                out[key] = float(value)
            elif key in STYLE_COLORS:
                if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                    raise ValueError(f"{key} must be #RRGGBB")
                out[key] = value.upper()
            elif value not in ("glass", "solid", "plain"):
                raise ValueError("material must be glass/solid/plain")
            else:
                out[key] = value
        return out
