"""日常板块、照片输入、只在某几天出现的模板（周末尿检）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest

from pivis_health.config import Config
from pivis_health.todos import TodoError, TodoStore
from pivis_health.v3 import validate_page


@pytest.fixture()
def store(tmp_path) -> TodoStore:
    return TodoStore(replace(Config(), data_dir=tmp_path))


def _project(**over):
    p = {"id": "life", "name": "饮食和身体记录", "board": "life", "start": "2026-11-02", "days": 365,
         "daily": [
             {"key": "lunch", "when": "11:55", "title": "午饭拍一张", "kind": "fields",
              "inputs": [{"id": "photo", "label": "", "type": "photo", "submit": "agent"}]},
             {"key": "urine", "when": "10:00", "title": "尿检试纸拍一张", "kind": "fields", "weekdays": [6, 7],
              "inputs": [{"id": "photo", "label": "", "type": "photo", "submit": "agent"}]},
         ]}
    p.update(over)
    return p


def test_weekday_template_only_on_weekend(store):
    store.project_set(_project(), date(2026, 11, 2), datetime(2026, 11, 2, 8, 0))
    wed, sat = date(2026, 11, 4), date(2026, 11, 7)
    store.materialize(wed, datetime(2026, 11, 4, 8, 0))
    store.materialize(sat, datetime(2026, 11, 7, 8, 0))
    assert [t["title"] for t in store.for_date(wed)] == ["午饭拍一张"]
    assert sorted(t["title"] for t in store.for_date(sat)) == ["午饭拍一张", "尿检试纸拍一张"]
    assert store.for_date(sat)[0]["inputs"][0]["type"] == "photo"


def test_bad_weekdays_rejected(store):
    p = _project()
    p["daily"][1]["weekdays"] = [0, 8]
    with pytest.raises(TodoError):
        store.project_set(p, date(2026, 11, 2), datetime(2026, 11, 2, 8, 0))


def test_life_board_cannot_be_hero():
    doc = {"headline": {"text": "今天记得拍饭"}, "hero": {"level": "watch", "board": "life", "label": "饮食", "value": ""}}
    with pytest.raises(ValueError):
        validate_page("now", doc, {})


def test_chat_hides_photo_path():
    from pivis_health.dsh_chat import _PHOTO_REF
    text = "用户在待办卡里提交：照片 /some/dir/pivis-runtime/photos/daily-log-lunch-1.jpg（用 read_image 看这张图）"
    assert _PHOTO_REF.sub("照片", text) == "用户在待办卡里提交：照片"
