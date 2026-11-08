"""开放画布新零件：校验（收好的、拒坏的）、估算高度、内核现算（合成客观库 + 合成 WHOOP + 临时待办 / 记忆）。"""
from __future__ import annotations

import io
import json
import math
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from clips import make_clip
from pivis_health import canvas, canvas_parts, v3
from pivis_health.canvas import CanvasError

CN = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 10, 28)                    # conftest 的「今天」（周三）
NOW = datetime(2026, 10, 28, 21, 10, tzinfo=CN)
GOAL = 8000


def _steps(back: int) -> int:                # conftest 合成步数
    return 8000 + int(math.sin(back) * 3000)


def _utc(local: datetime) -> str:
    return local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def _zones(*mins: int) -> dict:
    return {k: m * 60_000 for k, m in zip(canvas_parts.ZONE_KEYS, mins)}


# ---------------------------------------------------------------- 夹具：合成数据 + 一个 CBT-I 项目
@pytest.fixture()
def env(tools_env, whoop_snapshot, tmp_path):
    from pivis_health.agent_context import AgentContextStore
    from pivis_health.todos import TodoStore
    snap = json.loads(whoop_snapshot.read_text(encoding="utf-8"))
    for d, mins in ((DAY, (5, 20, 30, 20, 12, 3)), (DAY - timedelta(days=1), (10, 30, 30, 15, 4, 1)),
                    (DAY - timedelta(days=12), (0, 10, 10, 10, 0, 0))):
        start = datetime.combine(d, time(19, 0), tzinfo=CN)
        snap["collections"]["workout"].append({"id": f"w-{d}", "start": _utc(start), "end": _utc(start + timedelta(minutes=90)),
                                               "sport_name": "tennis", "score_state": "SCORED",
                                               "score": {"strain": 12.0, "zone_durations": _zones(*mins)}})
    path = tmp_path / "whoop-with-workouts.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    tools = tools_env
    tools.cfg = replace(tools.cfg, whoop_snapshot=path)
    store = TodoStore(tools.cfg)
    start = DAY - timedelta(days=9)
    store.project_set({"id": "cbti", "name": "CBT-I · 42 天", "board": "sleep", "start": start.isoformat(), "days": 42,
                       "goal": "固定起床、压缩在床时间", "rules": ["每天 08:30 起床，周末也一样"],
                       "reviews": [{"date": "2026-10-25", "title": "第 1 次复盘：按效率调窗口"},
                                   {"date": "2026-11-01", "title": "第 2 次复盘"}],
                       "daily": [{"key": "scan", "when": "00:30", "title": "床外身体扫描", "kind": "follow",
                                  "media": make_clip(tools.cfg.data_dir, "scan", 12, "身体扫描")},
                                 {"key": "bed", "when": "01:30", "title": "01:30 后再上床", "kind": "done"}]}, start)
    for i in range(10):
        d = start + timedelta(days=i)
        store.materialize(d)
        for t in store.for_date(d, "sleep"):
            if d < DAY and (t["title"] == "01:30 后再上床" or i % 3):      # 上床天天做到，身体扫描每 3 天漏一次
                store.user_submit(t["id"], "done", {}, None, None, NOW)
    AgentContextStore(tools.cfg).record("sleep.cbti", {"rule": "08:30 起床，01:30 后上床", "wake": "08:30",
                                                       "earliest_bed": "01:30", "window_h": 7.0, "week": 2})
    photos = tools.cfg.data_dir / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    (photos / "lunch-1.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 20)
    lunch = store.add({"board": "life", "when": "12:00", "title": "午饭拍一张", "kind": "fields",
                       "inputs": [{"id": "photo", "label": "", "type": "photo", "submit": "agent"}]}, DAY)
    store.user_submit(lunch["id"], "agent", {"photo": str(photos / "lunch-1.jpg")}, "", None, NOW)
    store.update(lunch["id"], {"status": "done", "summary": "主食偏多，蛋白质够"})
    return tools


def run(tools, part: dict) -> dict:
    lay = canvas.validate({"t": "v", "children": [part]}, "chat")
    return canvas.resolve(tools, lay, DAY, NOW)["children"][0]


# ---------------------------------------------------------------- 注册表：每个零件都有说明、校验、高度、现算
def test_registry_covers_every_part():
    names = [p["name"] for p in canvas.PARTS]
    assert len(names) == len(set(names)) == 15 + len(canvas_parts.NORMALIZERS)
    for t in canvas_parts.NORMALIZERS:
        assert t in names and t in canvas_parts.ESTIMATES and t in canvas_parts.RESOLVERS
    for p in canvas.PARTS:
        assert p["group"] in canvas.PART_GROUPS and p["cn"] and p["when"] and p["example"]["t"] == p["name"]
        for b in p.get("binds") or []:
            assert b in canvas.BIND_KINDS


def test_registry_examples_validate():
    for p in canvas.PARTS:
        if p["name"] in ("v", "h"):
            continue
        ex = json.loads(json.dumps(p["example"]).replace("<项目id>", "cbti"))
        canvas.validate(ex, "chat")


def test_unknown_part_lists_new_parts_and_binds_help_has_radar_rule():
    with pytest.raises(CanvasError, match="不认识的零件.*radar.*photo"):
        canvas.validate({"t": "pace"})
    assert "压力 = 100 − clamp" in canvas.binds_help()["radar"]


def test_parts_cli_compact_and_full():
    from pivis_health import cli
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert cli.main(["parts", "--group", "趋势"]) == 0
    out = json.loads(buf.getvalue())
    assert {p["name"] for p in out["parts"]} >= {"sparkline", "scatter", "bullet"}
    assert set(out["parts"][0]) == {"name", "cn", "when", "example"}
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert cli.main(["parts", "--name", "radar"]) == 0
    full = json.loads(buf.getvalue())
    assert full["cn"] == "雷达" and "习惯" in full["binds"]["radar"]


# ---------------------------------------------------------------- 校验：收好的
@pytest.mark.parametrize("node,expect", [
    ({"t": "pie", "bind": "sleep.stages"}, {"t": "pie", "bind": "sleep.stages"}),
    ({"t": "donut", "bind": "training.zones", "center": "轻松"}, {"center": "轻松"}),
    ({"t": "pie", "items": [{"label": "工作", "value": 8}, {"label": "睡觉", "value": "7.5"}]},
     {"items": [{"label": "工作", "value": 8.0, "text": "8"}, {"label": "睡觉", "value": 7.5, "text": "7.5"}]}),
    ({"t": "stack", "bind": "sleep.stages"}, {"bind": "sleep.stages"}),
    ({"t": "stack_columns", "days": 40, "height": "xl"}, {"bind": "sleep.stages", "days": 14, "height": "s"}),
    ({"t": "waffle", "bind": "project:cbti", "days": 3}, {"days": 7}),
    ({"t": "zones"}, {"bind": "workout.last"}),
    ({"t": "radar", "bind": "whatever"}, {"t": "radar"}),
    ({"t": "sleep_window", "days": 30, "band": "project:cbti"}, {"days": 14, "band": "project:cbti"}),
    ({"t": "calendar", "bind": "steps.week", "month": "2026-09"}, {"month": "2026-09"}),
    ({"t": "calendar", "bind": "sleep.nights"}, {"month": "current"}),
    ({"t": "weekgrid", "bind": "project:cbti"}, {"bind": "project:cbti"}),
    ({"t": "streak", "bind": "wake:8:30"}, {"bind": "wake:08:30"}),
    ({"t": "countdown", "to": "1:30"}, {"to": "01:30", "label": "还有"}),
    ({"t": "countdown", "to": "project:cbti:bed", "label": "离上床还有"}, {"to": "project:cbti:bed"}),
    ({"t": "time_range", "from": "13:30", "to": "14:00", "label": "午睡"}, {"from": "13:30", "label": "午睡"}),
    ({"t": "milestones", "items": [{"title": "定窗口"}, {"title": "调窗口", "sub": "看效率"}], "current": 9},
     {"current": 1, "items": [{"title": "定窗口", "sub": ""}, {"title": "调窗口", "sub": "看效率"}]}),
    ({"t": "sparkline", "bind": "steps", "days": 99}, {"days": 30}),
    ({"t": "stat_spark", "bind": "resting_hr"}, {"label": "静息心率"}),
    ({"t": "delta", "bind": "hrv"}, {"baseline": "prev3"}),
    ({"t": "compare", "bind": "recovery"}, {"bind": "recovery"}),
    ({"t": "dual_line", "a": "hrv", "b": "resting_hr"}, {"days": 14}),
    ({"t": "diverging", "bind": "steps.goal"}, {"days": 7}),
    ({"t": "lollipop", "bind": "project:cbti", "target": 12}, {"target": 12.0}),
    ({"t": "scatter", "x": "sleep", "y": "hrv"}, {"days": 30, "lag": 1}),
    ({"t": "histogram", "bind": "bedtime"}, {"days": 30}),
    ({"t": "spread", "bind": "hrv", "days": 2}, {"days": 7}),
    ({"t": "bullet", "bind": "sleep.efficiency"}, {"bind": "sleep.efficiency"}),
    ({"t": "segments", "bind": "project:cbti"}, {"bind": "project:cbti"}),
    ({"t": "stepper", "items": ["适应", "加量"], "current": 5}, {"subs": [], "current": 1}),
    ({"t": "progress_list", "bind": "projects"}, {"days": 7}),
    ({"t": "checklist", "n": 10}, {"n": 6}),
    ({"t": "kv", "items": [{"label": "起床", "value": "08:30"}, {"label": "窗口", "value": "7 小时"}]}, {}),
    ({"t": "table", "bind": "sleep.week", "n": 9}, {"n": 6}),
    ({"t": "table", "columns": ["日期", "睡了"], "rows": [["11/1", "7.0"]]}, {"rows": [["11/1", "7.0"]]}),
    ({"t": "tag", "items": ["CBT-I · 第 1 周", "需要处理"], "strong": 7}, {"strong": None}),
    ({"t": "quote", "text": "固定起床，是整个计划里最不能动的一条。"}, {"source": None}),
    ({"t": "media", "id": "cbti-body-scan"}, {"id": "cbti-body-scan"}),
    ({"t": "media", "url": "/media/follow/s1/out.mp4", "title": "拉伸", "duration_min": 10},
     {"duration_min": 10.0}),
    ({"t": "photo", "latest": "life", "caption": "晚饭"}, {"latest": "life", "caption": "晚饭"}),
])
def test_accepts_and_normalizes(node, expect):
    out = canvas.validate(node, "chat")
    for k, v in expect.items():
        assert out[k] == v, (k, out)


# ---------------------------------------------------------------- 校验：拒坏的（中文说怎么改）
@pytest.mark.parametrize("node,msg", [
    ({"t": "pie"}, "要么写 bind"),
    ({"t": "pie", "bind": "steps"}, "bind 'steps' 不认识"),
    ({"t": "pie", "items": [{"label": "一", "value": 1}]}, "2–5 项"),
    ({"t": "pie", "items": [{"label": "一", "value": "很多"}, {"label": "二", "value": 1}]}, "要是数字"),
    ({"t": "donut", "bind": "sleep.stages", "center": "x" * 15}, "最多 14 个字"),
    ({"t": "stack", "items": [{"label": "a", "value": 1}, {"label": "b", "value": 2}], "title": "x" * 19}, "最多 18 个字"),
    ({"t": "stack_columns", "bind": "steps"}, "只能是 sleep.stages"),
    ({"t": "waffle", "bind": "hrv"}, "不认识"),
    ({"t": "zones", "bind": "workout.month"}, "workout.last"),
    ({"t": "sleep_window", "band": "01:30-08:30"}, "project:"),
    ({"t": "calendar", "bind": "sleep.nights", "month": "next"}, "current / prev / YYYY-MM"),
    ({"t": "weekgrid", "bind": "hrv"}, "不认识"),
    ({"t": "streak", "bind": "wake:25:00"}, "HH:MM"),
    ({"t": "countdown", "to": "tonight"}, "HH:MM"),
    ({"t": "countdown", "to": "project:cbti"}, "project:<项目 id>:<待办 key>"),
    ({"t": "time_range", "from": "01:30"}, "to 要写成 HH:MM"),
    ({"t": "time_range", "bind": "sleep.cbti"}, "不认识"),
    ({"t": "milestones", "items": [{"title": "x"}] * 6}, "1–5 项"),
    ({"t": "milestones", "items": [{"title": "x" * 21}]}, "最多 20 个字"),
    ({"t": "sparkline", "bind": "sleep_debt"}, "不认识"),
    ({"t": "delta", "bind": "hrv", "baseline": "last_year"}, "prev3"),
    ({"t": "compare", "bind": "weight"}, "compare 的 bind 只能是"),
    ({"t": "dual_line", "a": "hrv", "b": "hrv"}, "两项不同"),
    ({"t": "dual_line", "a": "hrv", "b": "mood"}, "b 只能是"),
    ({"t": "diverging", "bind": "hrv.warn"}, "不认识"),
    ({"t": "lollipop", "bind": "steps", "target": "很多"}, "要是数字"),
    ({"t": "scatter", "x": "sleep", "y": "hrv", "lag": 3}, "lag 只能是 0"),
    ({"t": "histogram", "bind": "waketime"}, "不认识"),
    ({"t": "bullet", "bind": "weight"}, "不认识"),
    ({"t": "segments", "bind": "cbti"}, "不认识"),
    ({"t": "stepper", "items": ["一"]}, "2–5 个"),
    ({"t": "stepper", "items": ["适应期第一阶段", "加量"]}, "每格最多 6 个字"),
    ({"t": "stepper", "items": ["适应", "加量"], "subs": ["1 周"]}, "一样多"),
    ({"t": "progress_list", "bind": "project"}, "不认识"),
    ({"t": "checklist", "board": "work"}, "board 只能是"),
    ({"t": "kv", "items": [{"label": "起床", "value": "08:30"}]}, "2–6 行"),
    ({"t": "kv", "items": [{"label": "最早可以上床的时间", "value": "1"}, {"label": "a", "value": "b"}]}, "最多 8 个字"),
    ({"t": "table", "columns": ["a", "b", "c", "d", "e"], "rows": [["1"] * 5]}, "1–4 列"),
    ({"t": "table", "columns": ["a"], "rows": [["1"]] * 7}, "1–6 行"),
    ({"t": "table", "columns": ["a", "b"], "rows": [["1"]]}, "格数要和 columns 一样"),
    ({"t": "table", "columns": ["日期"], "rows": [["二零二六年十一月"]]}, "每格最多 6 个字"),
    ({"t": "table", "bind": "steps.week"}, "sleep.week"),
    ({"t": "tag", "items": []}, "1–4 个"),
    ({"t": "tag", "items": ["这是一个特别特别长的标签"]}, "每格最多 10 个字"),
    ({"t": "quote", "text": "x" * 31}, "最多 30 个字"),
    ({"t": "quote"}, "要有 text"),
    ({"t": "media"}, "media 要写"),
    ({"t": "media", "url": "https://www.bilibili.com/video/BV1x", "title": "拉伸"}, "只放 follow 出的片"),
    ({"t": "media", "url": "/media/sleep-audio/a.m4a", "title": "呼吸"}, "只放 follow 出的片"),
    ({"t": "media", "url": "https://www.youtube.com/watch?v=1", "title": "x"}, "YouTube"),
    ({"t": "media", "url": "http://192.168.1.2/a.mp3", "title": "x"}, "内网"),
    ({"t": "media", "url": "/media/follow/s1/out.mp4"}, "要有 title"),
    ({"t": "photo"}, "photo 要写 todo"),
    ({"t": "photo", "latest": "work"}, "latest 只能是"),
    ({"t": "photo", "latest": "life", "caption": "x" * 31}, "最多 30 个字"),
])
def test_rejects_with_reason(node, msg):
    with pytest.raises(CanvasError, match=msg):
        canvas.validate(node, "chat")


def test_handwritten_numbers_in_new_parts_must_come_from_evidence():
    pool = [8, 30, 1, 7.5, 12]
    ok = [{"t": "kv", "items": [{"label": "起床", "value": "08:30"}, {"label": "窗口", "value": "7.5 小时"}]},
          {"t": "time_range", "from": "01:30", "to": "08:30", "label": "睡眠窗口"},
          {"t": "tag", "items": ["第 1 周"]}, {"t": "lollipop", "bind": "steps", "target": 12},
          {"t": "table", "columns": ["日期", "睡了"], "rows": [["11/4", "7.5"]]}]       # 第一列日期不查
    for node in ok:
        canvas.validate(node, "hero", pool, v3._has_number)
    bad = [({"t": "kv", "items": [{"label": "起床", "value": "08:15"}, {"label": "a", "value": "b"}]}, "15"),
           ({"t": "pie", "items": [{"label": "a", "value": 3}, {"label": "b", "value": 8}]}, "3"),
           ({"t": "quote", "text": "睡够 9 小时再说"}, "9"),
           ({"t": "countdown", "to": "23:45"}, "23"),
           ({"t": "stepper", "items": ["适应", "加量"], "subs": ["1 周", "6 周"]}, "6"),
           ({"t": "table", "columns": ["日期", "睡了"], "rows": [["11/4", "6.2"]]}, "6.2"),
           ({"t": "lollipop", "bind": "steps", "target": 15}, "15")]
    for node, num in bad:
        with pytest.raises(CanvasError, match=f"{num} 在 facts 里找不到"):
            canvas.validate(node, "hero", pool, v3._has_number)


# ---------------------------------------------------------------- 估算高度（和规格一致）
@pytest.mark.parametrize("node,h", [
    ({"t": "pie", "bind": "sleep.stages"}, 140), ({"t": "donut", "bind": "sleep.stages"}, 140),
    ({"t": "stack", "bind": "sleep.stages"}, 72),
    ({"t": "stack_columns", "height": "s"}, 150), ({"t": "stack_columns", "height": "m"}, 190),
    ({"t": "waffle", "bind": "sleep.nights", "days": 30}, 96), ({"t": "waffle", "bind": "sleep.nights", "days": 7}, 48),
    ({"t": "zones"}, 130), ({"t": "radar"}, 200), ({"t": "hypnogram"}, 110),
    ({"t": "sleep_window", "days": 7}, 138), ({"t": "clock24"}, 160),
    ({"t": "calendar", "bind": "sleep.nights"}, 200), ({"t": "weekgrid", "bind": "sleep"}, 80),
    ({"t": "streak", "bind": "sleep.nights"}, 130), ({"t": "countdown", "to": "01:30"}, 120),
    ({"t": "time_range", "from": "01:30", "to": "08:30"}, 110),
    ({"t": "milestones", "items": [{"title": "a"}, {"title": "b"}, {"title": "c"}]}, 162),
    ({"t": "milestones", "bind": "project:cbti"}, 254),
    ({"t": "sparkline", "bind": "hrv"}, 56), ({"t": "stat_spark", "bind": "hrv"}, 74), ({"t": "delta", "bind": "hrv"}, 110),
    ({"t": "compare", "bind": "sleep"}, 140), ({"t": "dual_line", "a": "hrv", "b": "steps"}, 140),
    ({"t": "diverging", "bind": "sleep.need"}, 120), ({"t": "lollipop", "bind": "steps"}, 120),
    ({"t": "scatter", "x": "sleep", "y": "hrv"}, 160), ({"t": "histogram", "bind": "bedtime"}, 130),
    ({"t": "spread", "bind": "hrv"}, 80), ({"t": "bullet", "bind": "recovery"}, 110),
    ({"t": "segments", "bind": "project:cbti"}, 90), ({"t": "stepper", "items": ["a", "b"]}, 76),
    ({"t": "progress_list", "bind": "projects"}, 136), ({"t": "checklist", "n": 3}, 84),
    ({"t": "kv", "items": [{"label": "a", "value": "b"}] * 3}, 114), ({"t": "kv", "bind": "project:cbti"}, 152),
    ({"t": "table", "columns": ["a"], "rows": [["1"]] * 4}, 130), ({"t": "table", "bind": "sleep.week", "n": 3}, 104),
    ({"t": "tag", "items": ["a"]}, 32), ({"t": "quote", "text": "x" * 15}, 94),
    ({"t": "media", "id": "x"}, 64), ({"t": "photo", "latest": "life"}, 170),
])
def test_estimate_heights(node, h):
    assert canvas.estimate(canvas.validate(node, "chat")) == h


def test_too_tall_layout_rejected():
    with pytest.raises(CanvasError, match="超过画布"):
        canvas.validate({"t": "v", "children": [{"t": "radar"}, {"t": "calendar", "bind": "sleep.nights"},
                                                {"t": "photo", "latest": "life"}]}, "chat")


# ---------------------------------------------------------------- 现算：占比与构成
def test_pie_stack_and_stack_columns_from_whoop_stages(env):
    pie = run(env, {"t": "pie", "bind": "sleep.stages"})
    assert [(i["label"], i["value"], i["pct"]) for i in pie["items"]] == [
        ("深睡", 1.4, 20), ("快速眼动", 1.8, 26), ("浅睡", 3.2, 47), ("清醒", 0.5, 7)]
    assert pie["items"][0]["text"] == "1.4 小时" and pie["caption"] == "昨晚 6.4 小时" and pie["center_text"] is None
    st = run(env, {"t": "stack", "bind": "sleep.stages"})
    assert st["title"] == "昨晚 6.4 小时" and st["items"][2]["text"] == "3.2" and st["items"][0]["frac"] == round(1.4 / 6.9, 3)
    sc = run(env, {"t": "stack_columns", "bind": "sleep.stages", "days": 7})
    assert sc["keys"] == ["深睡", "快速眼动", "浅睡"] and len(sc["columns"]) == 7
    assert sc["columns"][-1] == {"label": "10/27", "parts": [1.4, 1.8, 3.2], "ref": 8.3, "now": True}
    assert sc["max"] == 8.3 and sc["caption"] == "短横线 = 当晚需要"


def test_manual_pie_and_donut_center(env):
    out = run(env, {"t": "donut", "items": [{"label": "a", "value": 1}, {"label": "b", "value": 2}], "center": "a"})
    assert [i["pct"] for i in out["items"]] == [33, 67] and (out["center_text"], out["center_sub"]) == ("33%", "a")


def test_training_zones_and_zones_rows(env):
    d = run(env, {"t": "donut", "bind": "training.zones"})
    # 近 7 天两次：Z0–2 = 55 + 70，Z3 = 20 + 15，Z4–5 = 15 + 5
    assert [(i["label"], i["value"]) for i in d["items"]] == [("轻松", 125), ("中等", 35), ("高强度", 20)]
    assert d["center_sub"] == "轻松" and d["caption"] == "近 7 天 2 次训练 · 3 小时"
    z = run(env, {"t": "zones", "bind": "workout.last"})
    assert z["title"] == "今天 网球 · 90 分钟"
    assert [(r["label"], r["minutes"], r["text"]) for r in z["rows"]][:2] == [("Z1 很轻松", 25, "25′"), ("Z2 轻松", 30, "30′")]
    assert z["max"] == 30
    wk = run(env, {"t": "zones", "bind": "workout.week"})
    assert wk["title"] == "近 7 天 2 次训练 · 180 分钟" and wk["rows"][0]["minutes"] == 65


def test_waffle_counts_only_decided_days(env):
    w = run(env, {"t": "waffle", "bind": "sleep.nights", "days": 14})
    assert w["items"] == [False] * 10 and w["caption"] == "近 10 晚，0 晚睡够"      # Apple 补的晚上没有「需要」，不算格
    s = run(env, {"t": "waffle", "bind": "steps.week", "days": 7})
    assert s["items"] == [_steps(b) >= GOAL for b in range(6, -1, -1)]
    p = run(env, {"t": "waffle", "bind": "project:cbti", "days": 14})
    assert len(p["items"]) == 9 and p["caption"].startswith("CBT-I · 近 9 天，")       # 今天还没做完，不算


def test_radar_scores(env):
    r = run(env, {"t": "radar"})
    assert r["axes"] == ["睡眠", "恢复", "运动", "压力", "习惯"]
    assert r["now"][0] == round(6.4 / 8.3 * 100) and r["now"][1] == round((66 * 4 + 25 * 3) / 7)
    assert r["now"][2] == round(sum(min(100, _steps(b) / GOAL * 100) for b in range(7, 0, -1)) / 7)
    assert r["now"][3] == 100 and r["prev"][1] == 66                 # HRV 一直 45，和基线一样
    # 习惯：上床天天做到、身体扫描每 3 天漏一次；上周只有项目头两天（10/19、10/20）
    assert (r["now"][4], r["prev"][4]) == (round(12 / 14 * 100), 75)


# ---------------------------------------------------------------- 现算：时间与作息
def test_hypnogram_from_apple_segments(env):
    h = run(env, {"t": "hypnogram"})
    assert (h["start"], h["end"], h["total_min"]) == ("23:30", "07:00", 450)
    assert [s["stage"] for s in h["segments"]] == ["light", "deep", "rem", "wake"]
    assert h["segments"][0]["from"] == 0 and h["segments"][-1]["to"] == 450


def test_hypnogram_falls_back_without_apple_night(env):
    lay = canvas.validate({"t": "hypnogram"}, "chat")
    out = canvas.resolve(env, lay, DAY - timedelta(days=4), NOW - timedelta(days=4))   # 10/23 那晚 Apple 没记
    assert out["t"] == "text" and "只有 Apple Watch" in out["text"]


def test_sleep_window_with_cbti_band(env):
    s = run(env, {"t": "sleep_window", "days": 7})
    assert s["axis_start"] == 22 and s["axis_hours"] == 12 and len(s["rows"]) == 7
    assert s["rows"][-1] == {"label": "10/27", "start": "23:20", "end": "06:20", "from": 1.33, "to": 8.33, "now": True}
    assert s["band"] == {"from": 3.5, "to": 10.5, "label": "CBT-I 窗口 01:30–08:30"}
    assert [t["label"] for t in s["ticks"]] == ["22:00", "02:00", "06:00", "10:00"]


def test_clock24(env):
    c = run(env, {"t": "clock24"})
    assert c["arcs"][0] == {"kind": "sleep", "from": 23.33, "to": 6.33, "label": "睡眠 23:20–06:20"}
    assert c["arcs"][1]["kind"] == "workout" and c["arcs"][1]["from"] == 19.0 and c["arcs"][1]["to"] == 20.5
    assert c["now"] == 21.17 and "01:30 后再上床" in [d["label"] for d in c["dots"]]


def test_calendar_levels(env):
    c = run(env, {"t": "calendar", "bind": "sleep.nights"})
    assert c["title"] == "10 月 · 每晚睡够没" and c["first_weekday"] == 4 and len(c["days"]) == 31
    lv = {d["d"]: d["level"] for d in c["days"]}
    assert lv[27] == 1 and lv[10] is None and lv[28] is None        # 每晚差 1.9 小时 → 差 1–2；Apple 补的没有需要；今晚还没睡
    assert next(d for d in c["days"] if d["d"] == 28)["today"] is True
    s = run(env, {"t": "calendar", "bind": "steps.week"})
    assert {d["d"]: d["level"] for d in s["days"]}[26] == 3 and {d["d"]: d["level"] for d in s["days"]}[29] is None
    p = run(env, {"t": "calendar", "bind": "project:cbti"})
    assert {d["d"]: d["level"] for d in p["days"]}[19] in (2, 3) and {d["d"]: d["level"] for d in p["days"]}[18] is None


def test_weekgrid(env):
    s = run(env, {"t": "weekgrid", "bind": "steps"})
    assert [(d["label"], d["state"]) for d in s["days"]][:4] == [("一", "done"), ("二", "done"), ("三", "done"), ("四", "future")]
    p = run(env, {"t": "weekgrid", "bind": "project:cbti"})
    assert p["days"][2]["state"] == "today" and p["days"][3] == {"label": "四", "text": "2件", "state": "future"}
    assert p["days"][0]["text"] in ("2/2", "1/2")


def test_streak_wake_and_project(env):
    s = run(env, {"t": "streak", "bind": "wake:06:30"})
    # WHOOP 的 10 晚 06:20 起；更早 Apple 的晚上 07:00 起
    assert (s["count"], s["best"], s["label"]) == (10, 10, "连续 06:30 起床")
    assert s["caption"] == "10 天前断过一次 · 最长 10 天" and len(s["marks"]) == 14 and s["marks"][-1] is True
    p = run(env, {"t": "streak", "bind": "project:cbti"})
    assert p["unit"] == "天" and p["count"] <= 9


def test_countdown(env):
    c = run(env, {"t": "countdown", "to": "23:30", "label": "离上床还有"})
    assert c["text"] == "2:20" and c["sub"] == "到 23:30" and c["fraction"] == round(770 / 910, 3)   # 起床目标 08:20 起算
    p = run(env, {"t": "countdown", "to": "project:cbti:bed", "label": "离上床还有"})
    assert p["text"] == "4:20" and p["sub"] == "01:30 后再上床" and p["to"] == "01:30"
    late = run(env, {"t": "countdown", "to": "20:00"})
    assert late["text"] == "0:00" and late["fraction"] == 1.0


def test_time_range(env):
    b = run(env, {"t": "time_range", "bind": "project:cbti"})
    assert b == {"t": "time_range", "label": "睡眠窗口 · 第 2 周", "text": "01:30 — 08:30", "sub": "7 小时", "from": 1.5, "to": 8.5}
    m = run(env, {"t": "time_range", "from": "13:30", "to": "14:00", "label": "午睡", "note": "闹钟定好"})
    assert m["sub"] == "30 分钟 · 闹钟定好"


def test_milestones(env):
    m = run(env, {"t": "milestones", "bind": "project:cbti"})
    assert m["title"] == "CBT-I · 6 周"
    assert [(i["title"], i["state"]) for i in m["items"]] == [
        ("10/19 · 开始", "done"), ("10/25 · 第 1 次复盘", "now"), ("11/1 · 第 2 次复盘", "next"), ("11/29 · 结束", "next")]
    assert m["items"][0]["sub"] == "每天 08:30 起床，周末也一样" and m["items"][1]["sub"] == "按效率调窗口"
    h = run(env, {"t": "milestones", "items": [{"title": "a"}, {"title": "b"}, {"title": "c"}], "current": 1})
    assert [i["state"] for i in h["items"]] == ["done", "now", "next"]


# ---------------------------------------------------------------- 现算：趋势与对比
def test_sparkline_stat_spark_delta(env):
    sp = run(env, {"t": "sparkline", "bind": "steps", "days": 14})
    vals = [_steps(b) for b in range(14, 0, -1)]                    # 步数不含今天
    assert sp["points"] == vals and sp["text"] == f"{vals[-1]:,}" and sp["asof"] == "10/27"
    assert run(env, {"t": "sparkline", "bind": "hrv"})["direction"] == "flat"
    ss = run(env, {"t": "stat_spark", "bind": "steps", "label": "步数"})
    a, b = sum(vals[-3:]) / 3, sum(vals[-6:-3]) / 3
    assert ss["moved"] is (abs(a - b) / b * 100 > 3) and len(ss["points"]) == 14
    d = run(env, {"t": "delta", "bind": "steps", "baseline": "prev3"})
    pct = round((a - b) / b * 100)
    assert d["text"] == f"{'↑' if pct > 0 else '↓'} {abs(pct)}%" and d["label"] == "步数 · 近 3 天和前 3 天比"
    assert d["from"] == f"{round(b):,}" and d["good"] is (pct > 0)
    assert run(env, {"t": "delta", "bind": "hrv", "baseline": "prev_week"})["text"] == "→ 持平"


def test_compare_and_dual_line(env):
    c = run(env, {"t": "compare", "bind": "sleep"})
    assert c["title"] == "每晚睡了多久：这周 vs 上周" and c["unit"] == "小时" and c["max"] == 8
    assert c["pairs"][0] == {"label": "一", "now": 6.4, "prev": 6.4, "today": False}
    assert c["pairs"][2]["today"] is True and c["pairs"][2]["now"] is None and c["pairs"][4]["now"] is None
    d = run(env, {"t": "dual_line", "a": "hrv", "b": "steps", "days": 7})
    assert d["a"]["label"] == "HRV" and len(d["a"]["points"]) == len(d["b"]["points"]) and d["a"]["text"] == "45.0–45.0"


def test_diverging_and_lollipop(env):
    dv = run(env, {"t": "diverging", "bind": "sleep.need", "days": 7})
    assert dv["items"][-1] == {"label": "10/27", "value": -1.9, "text": "−1.9"} and dv["max_abs"] == 1.9
    sg = run(env, {"t": "diverging", "bind": "steps.goal", "days": 3})
    assert [i["value"] for i in sg["items"]] == [_steps(b) - GOAL for b in (3, 2, 1)] and sg["items"][0]["text"].startswith("+")
    lp = run(env, {"t": "lollipop", "bind": "project:cbti", "days": 7})
    assert lp["target"] == 12 and lp["target_label"] == "目标 12 分钟" and lp["max"] == 12
    assert {i["text"] for i in lp["items"]} <= {"12′", "0′"} and any(not i["done"] for i in lp["items"])
    ls = run(env, {"t": "lollipop", "bind": "steps", "days": 3})
    assert ls["target"] == GOAL and ls["target_label"] == "目标 8,000 步"


def test_scatter_needs_14_samples(env):
    small = run(env, {"t": "scatter", "x": "sleep", "y": "hrv", "days": 30})
    assert small["t"] == "text" and "样本太少" in small["text"]          # WHOOP HRV 只有 11 晚
    s = run(env, {"t": "scatter", "x": "sleep", "y": "steps", "days": 30, "lag": 1})
    assert len(s["points"]) >= 14 and s["x_label"] == "睡了几小时" and s["y_label"] == "第二天 步数"
    assert s["x_range"][0] <= min(p[0] for p in s["points"]) and s["caption"].endswith("只说明相关，不代表因果")
    assert s["last"] == s["points"][-1] and len(s["fit"]) == 2


def test_histogram_and_spread(env):
    h = run(env, {"t": "histogram", "bind": "bedtime", "days": 30})
    assert [(b["label"], b["count"], b["peak"]) for b in h["bins"]] == [("23:00", 10, False), ("23:30", 11, True)]
    assert h["caption"] == "最常在 23:30 前后睡着（11 晚）"
    hs = run(env, {"t": "histogram", "bind": "steps", "days": 30})
    assert 1 < len(hs["bins"]) <= 8 and sum(b["count"] for b in hs["bins"]) == 30
    sp = run(env, {"t": "spread", "bind": "steps", "days": 30})
    vals = sorted(_steps(b) for b in range(30, 0, -1))
    assert sp["min"] == vals[0] and sp["max"] == vals[-1] and sp["label"] == "近 30 天步数的范围"
    assert sp["today_text"] == f"昨天 {_steps(1):,}" and sp["min"] <= sp["q1"] <= sp["median"] <= sp["q3"] <= sp["max"]


def test_bullet(env):
    e = run(env, {"t": "bullet", "bind": "sleep.efficiency"})
    assert e == {"t": "bullet", "label": "昨晚睡眠效率", "text": "93", "unit": "%", "value": 93, "min": 70, "max": 100,
                 "bands": [85, 90], "target": 90, "direction": "low_bad", "caption": "到目标了"}
    s = run(env, {"t": "bullet", "bind": "steps", "label": "步数"})
    assert s["label"] == "步数" and s["target"] == GOAL and s["bands"] == [4000, 6000] and s["caption"] == "走够了"
    r = run(env, {"t": "bullet", "bind": "recovery"})
    assert r["bands"] == [33, 66] and r["caption"].startswith("在红区")


# ---------------------------------------------------------------- 现算：进度与信息
def test_segments_progress_checklist(env):
    s = run(env, {"t": "segments", "bind": "project:cbti"})
    assert s == {"t": "segments", "text": "第 2 周", "sub": "/ 6 周", "label": "CBT-I", "total": 6, "done": round(9 / 7, 2)}
    p = run(env, {"t": "progress_list", "bind": "projects", "days": 7})
    assert p["rows"][0]["label"] == "CBT-I" and p["rows"][0]["text"].endswith("/ 6")
    one = run(env, {"t": "progress_list", "bind": "project:cbti", "days": 7})
    assert {r["label"] for r in one["rows"]} == {"床外身体扫描", "01:30 后再上床"}
    assert next(r for r in one["rows"] if r["label"] == "01:30 后再上床")["fraction"] == 1.0
    c = run(env, {"t": "checklist", "board": "sleep", "n": 4})
    assert [i["text"] for i in c["items"]] == ["00:30 床外身体扫描", "01:30 后再上床"]     # 标题已带时间的不重复
    assert run(env, {"t": "checklist", "board": "life"})["items"][0] == {"text": "12:00 午饭拍一张", "done": True, "state": "done"}


def test_kv_table_tag_quote_stepper(env):
    kv = run(env, {"t": "kv", "bind": "project:cbti"})
    assert kv["items"] == [{"label": "起床", "value": "08:30"}, {"label": "最早上床", "value": "01:30"},
                           {"label": "睡眠窗口", "value": "7 小时"}, {"label": "第几周", "value": "第 2 周"}]
    tb = run(env, {"t": "table", "bind": "sleep.week", "n": 3})
    assert tb["columns"] == ["日期", "睡了", "效率", "入睡"] and tb["rows"][-1] == ["10/27", "6.4", "93%", "23:20"]
    assert run(env, {"t": "tag", "items": ["CBT-I · 第 1 周", "需要处理"], "strong": 1}) == \
        {"t": "tag", "items": ["CBT-I · 第 1 周", "需要处理"], "strong": 1}
    assert run(env, {"t": "quote", "text": "固定起床", "source": "规则 1"})["source"] == "规则 1"
    st = run(env, {"t": "stepper", "items": ["适应", "加量"], "subs": ["1–2 周", "3 周"], "current": 1})
    assert st == {"t": "stepper", "items": ["适应", "加量"], "subs": ["1–2 周", "3 周"], "current": 1}


def test_media_and_photo(env):
    m = run(env, {"t": "media", "id": "cbti-body-scan"})
    assert m["kind"] == "audio" and m["sub"] == "12 分钟 · 素材库" and m["url"].startswith("/media/")
    missing = run(env, {"t": "media", "id": "nope"})
    assert missing["t"] == "text" and "算不出来" in missing["text"]
    u = run(env, {"t": "media", "url": "/media/follow/s1/out.mp4", "title": "拉伸", "duration_min": 10})
    assert u == {"t": "media", "title": "拉伸", "sub": "10 分钟", "url": "/media/follow/s1/out.mp4", "kind": "video"}
    ph = run(env, {"t": "photo", "latest": "life"})
    assert ph == {"t": "photo", "url": "/api/v3/photo/lunch-1.jpg", "caption": "主食偏多，蛋白质够"}
    assert run(env, {"t": "photo", "latest": "sleep"})["t"] == "text"


def test_project_parts_fall_back_for_unknown_project(env):
    for part in ({"t": "segments", "bind": "project:nope"}, {"t": "kv", "bind": "project:nope"},
                 {"t": "weekgrid", "bind": "project:nope"}, {"t": "milestones", "bind": "project:nope"}):
        out = run(env, part)
        assert out["t"] == "text" and "算不出来" in out["text"], part


def test_every_part_degrades_without_data(tmp_path, monkeypatch):
    """空客观库、没有 WHOOP、没有项目：每个零件要么照常画（手写的），要么换成一行说明，整张卡不挂。"""
    import sqlite3
    from tests.conftest import SCHEMA
    vault = tmp_path / "empty.sqlite3"
    con = sqlite3.connect(vault)
    con.executescript(SCHEMA)
    con.close()
    monkeypatch.setenv("PIVIS_HEALTH_VAULT_DB", str(vault))
    monkeypatch.setenv("PIVIS_HEALTH_WHOOP_SNAPSHOT", str(tmp_path / "none.json"))
    monkeypatch.setenv("PIVIS_HEALTH_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("PIVIS_HEALTH_CONFIG", raising=False)
    from pivis_health.config import load_config
    from pivis_health.tools import HealthTools
    tools = HealthTools(load_config())
    for p in canvas.PARTS:
        if p["name"] in ("v", "h"):
            continue
        ex = json.loads(json.dumps(p["example"]).replace("<项目id>", "cbti"))
        out = run(tools, ex)
        assert out["t"] in (p["name"], "text"), (p["name"], out)
