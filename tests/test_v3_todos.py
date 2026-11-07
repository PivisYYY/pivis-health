"""v3 待办与项目：校验、每日展开、模板更新、提交流程、排序、模拟时钟。

只用临时目录，不碰真实数据、不发消息。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest

from clips import make_clip

from pivis_health.config import Config
from pivis_health.todos import TodoError, TodoStore, normalize, sort_key
from pivis_health import clock

D1 = date(2026, 10, 27)


@pytest.fixture()
def store(tmp_path) -> TodoStore:
    make_clip(tmp_path, "flow", 11, "拉伸")
    make_clip(tmp_path, "med", 10, "冥想")
    return TodoStore(replace(Config(), data_dir=tmp_path))


FLOW = {"kind": "video", "title": "拉伸", "url": "/media/follow/flow/out.mp4", "duration_min": 11}
MED = {"kind": "video", "title": "冥想", "url": "/media/follow/med/out.mp4", "duration_min": 10}


def _project(**over):
    p = {"id": "cbti", "name": "CBT-I 温和版", "board": "sleep", "start": D1.isoformat(), "days": 30,
         "daily": [
             {"key": "diary", "when": "08:40", "title": "记一下昨晚", "kind": "fields",
              "inputs": [{"id": "latency", "label": "多久睡着", "type": "options", "options": ["15 分内", "30+"]}]},
             {"key": "flow", "when": "22:30", "title": "床外拉伸 + 呼吸", "kind": "follow", "media": FLOW},
             {"key": "bed", "when": "00:00", "title": "上床", "kind": "done", "auto": "bedtime"},
         ]}
    p.update(over)
    return p


# ---- 校验 ----
def test_normalize_rejects_bad_board_kind_time_and_private_media():
    with pytest.raises(TodoError):
        normalize({"board": "food", "title": "x", "date": "2026-10-27"})
    with pytest.raises(TodoError):
        normalize({"board": "sleep", "title": "x", "kind": "wizard", "date": "2026-10-27"})
    with pytest.raises(TodoError):
        normalize({"board": "sleep", "title": "x", "when": "25:00", "date": "2026-10-27"})
    with pytest.raises(TodoError):
        normalize({"board": "sleep", "title": "x", "kind": "follow", "date": "2026-10-27",
                   "media": {"kind": "audio", "url": "http://192.168.1.5/a.m4a"}})


def test_normalize_accepts_server_media_path():
    t = normalize({"board": "sleep", "title": "呼吸", "kind": "follow", "date": "2026-10-27", "media": FLOW})
    assert t["steps"][0]["media"]["url"].startswith("/media/follow/")


# ---- 项目展开 ----
def test_start_day_skips_items_already_past(store):
    """晚上 21:30 才开始的项目，当天不补出早上的日记，但留下今晚的流程和上床。"""
    store.project_set(_project(), D1, datetime(2026, 10, 27, 21, 30))
    titles = [t["title"] for t in store.for_date(D1)]
    assert "记一下昨晚" not in titles
    assert titles == ["床外拉伸 + 呼吸", "上床"]


def test_later_days_materialize_full_template(store):
    store.project_set(_project(), D1, datetime(2026, 10, 27, 21, 30))
    d3 = date(2026, 10, 29)
    store.materialize(d3, datetime(2026, 10, 29, 22, 10))
    assert [t["title"] for t in store.for_date(d3)] == ["记一下昨晚", "床外拉伸 + 呼吸", "上床"]


def test_template_change_updates_not_started_instance_only(store):
    """「以后都换成冥想」：今天还没开始的那张跟着换，已完成的不动，之后每天用新的。"""
    d3 = date(2026, 10, 29)
    store.project_set(_project(), D1, datetime(2026, 10, 27, 21, 30))
    store.materialize(d3, datetime(2026, 10, 29, 8, 0))
    store.user_submit(f"cbti-{d3}-diary", "done", {"latency": "30+"}, None, "多久睡着 30+",
                      datetime(2026, 10, 29, 8, 45))
    new = _project()
    new["daily"][1] = {"key": "flow", "when": "22:30", "title": "睡前冥想", "kind": "follow", "media": MED}
    p = store.project_set(new, d3, datetime(2026, 10, 29, 22, 10))
    assert p["revision"] == 2 and len(p["history"]) == 1
    flow = store.get(f"cbti-{d3}-flow")
    assert flow["title"] == "睡前冥想" and flow["template_rev"] == 2
    assert store.get(f"cbti-{d3}-diary")["status"] == "done"
    d4 = date(2026, 10, 30)
    store.materialize(d4, datetime(2026, 10, 30, 7, 0))
    assert store.get(f"cbti-{d4}-flow")["title"] == "睡前冥想"


def test_removed_template_key_drops_pending_instance(store):
    d3 = date(2026, 10, 29)
    store.project_set(_project(), D1, datetime(2026, 10, 27, 21, 30))
    store.materialize(d3, datetime(2026, 10, 29, 8, 0))
    p = _project()
    p["daily"] = [x for x in p["daily"] if x["key"] != "flow"]
    store.project_set(p, d3, datetime(2026, 10, 29, 9, 0))
    assert store.get(f"cbti-{d3}-flow") is None


# ---- 提交流程 ----
def test_agent_submit_goes_processing_and_agent_update_releases(store):
    t = store.add({"board": "sleep", "title": "今天补一下？", "kind": "proposal",
                   "inputs": [{"id": "c", "label": "", "type": "options", "options": ["午睡", "不补"],
                               "submit": "agent"}]}, D1)
    now = datetime(2026, 10, 27, 8, 0)
    s = store.user_submit(t["id"], "agent", {"c": "午睡"}, None, None, now)
    assert s["status"] == "processing" and s["request"]["values"] == {"c": "午睡"}
    u = store.update(t["id"], {"title": "几点睡、睡多久？", "kind": "fields"})
    assert u["status"] == "scheduled" and u["request"] is None and u["escalate"] is None


def test_escalate_kept_when_agent_sets_it(store):
    t = store.add({"board": "sleep", "title": "流程", "kind": "follow", "media": FLOW}, D1)
    store.user_submit(t["id"], "agent", {}, "换一套", None, datetime(2026, 10, 27, 22, 0))
    u = store.update(t["id"], {"escalate": "chat"})
    assert u["escalate"] == "chat" and u["status"] == "scheduled"


def test_old_app_later_and_skip_still_work(store):
    """build 42 及更早的 App 还会发「晚点」「算了」：服务器照样处理（新卡上已经没有这两个按钮）。"""
    t = store.add({"board": "sleep", "title": "拉伸", "kind": "follow", "when": "22:30", "media": FLOW}, D1)
    s = store.user_submit(t["id"], "later", {"minutes": 10}, None, None, datetime(2026, 10, 27, 22, 31))
    assert s["when"] == "22:41"
    s = store.user_submit(t["id"], "skip", {}, "太累了", None, datetime(2026, 10, 27, 22, 50))
    assert s["status"] == "skipped"


def test_auto_complete_accepts_expired(store):
    t = store.add({"board": "sleep", "title": "上床", "kind": "done", "when": "00:00", "auto": "bedtime"}, D1)
    store.update(t["id"], {"status": "expired"}, by="system")
    store.auto_complete(t["id"], "00:40 入睡", {"source": "whoop"})
    assert store.get(t["id"])["status"] == "done"


# ---- 排序 ----
def test_waiting_cards_first_then_time_with_overnight_last():
    rows = [
        {"kind": "done", "status": "scheduled", "when": "00:00", "created_at": "1"},
        {"kind": "follow", "status": "scheduled", "when": "22:30", "created_at": "2"},
        {"kind": "fields", "status": "scheduled", "when": "", "created_at": "3"},     # 追问卡
        {"kind": "proposal", "status": "processing", "when": "", "created_at": "4"},  # 处理中的提议不跳走
        {"kind": "fields", "status": "scheduled", "when": "08:40", "created_at": "5"},
    ]
    order = [r["created_at"] for r in sorted(rows, key=sort_key)]
    assert order == ["3", "4", "5", "2", "1"]


# ---- 模拟时钟 ----
def test_sim_clock_only_in_sim_mode(tmp_path):
    real = replace(Config(), data_dir=tmp_path)
    with pytest.raises(Exception):
        clock.set_now(real, "2026-10-29T22:10")
    sim = replace(Config(), data_dir=tmp_path, sim_mode=True)
    clock.set_now(sim, "2026-10-29T22:10")
    assert clock.now(sim).strftime("%Y-%m-%d %H:%M") == "2026-10-29 22:10"
    assert abs((clock.now(real).replace(tzinfo=None) - datetime.now()).total_seconds()) < 24 * 3600  # 正式环境不受模拟时钟影响
