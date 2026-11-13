"""b60 动作库：中英文查动作、肌群中文名、膝盖提醒、动图路由（防穿越）、photo 零件放动作示意。"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from pivis_health import canvas, exercises, web
from pivis_health.canvas import CanvasError

CN = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 10, 28)
NOW = datetime(2026, 10, 28, 21, 10, tzinfo=CN)

ROWS = [
    {"id": "0710", "name": "side hip abduction", "body_part": "upper legs", "equipment": "body weight",
     "target": "abductors", "muscle_group": "glutes", "secondary_muscles": ["glutes", "quadriceps"],
     "instruction_steps": {"zh": ["侧躺。", "抬起上面的腿。", "慢慢放下。", "重复。"]},
     "image": "images/0710-abcDEF1.jpg", "gif_url": "videos/0710-abcDEF1.gif"},
    {"id": "3013", "name": "low glute bridge on floor", "body_part": "upper legs", "equipment": "body weight",
     "target": "glutes", "muscle_group": "glutes", "secondary_muscles": ["hamstrings", "core"],
     "instruction_steps": {"zh": ["平躺，膝盖弯曲。", "抬起臀部。"]},
     "image": "images/3013-u0cNiij.jpg", "gif_url": "videos/3013-u0cNiij.gif"},
    {"id": "0514", "name": "jump squat", "body_part": "upper legs", "equipment": "body weight",
     "target": "glutes", "muscle_group": "quadriceps", "secondary_muscles": ["quadriceps", "calves"],
     "instruction_steps": {"zh": ["下蹲后跳起。"]},
     "image": "images/0514-x1.jpg", "gif_url": "videos/0514-x1.gif"},
    {"id": "1511", "name": "hamstring stretch", "body_part": "upper legs", "equipment": "body weight",
     "target": "hamstrings", "muscle_group": "hamstrings", "secondary_muscles": ["glutes"],
     "instruction_steps": {"zh": ["坐姿，腿伸直。"]},
     "image": "images/1511-y2.jpg", "gif_url": "videos/1511-y2.gif"},
]


@pytest.fixture()
def tools(tools_env, tmp_path):
    root = tmp_path / "exdb"
    for sub in ("data", "images", "videos"):
        (root / sub).mkdir(parents=True)
    (root / "data/exercises.json").write_text(json.dumps(ROWS), encoding="utf-8")
    for r in ROWS:
        (root / r["image"]).write_bytes(b"\xff\xd8\xff" + b"0" * 10)
        (root / r["gif_url"]).write_bytes(b"GIF89a" + b"0" * 10)
    exercises._load.cache_clear()
    tools_env.cfg = replace(tools_env.cfg, exercise_db_dir=str(root))
    return tools_env


def test_search_chinese_muscle_and_names(tools):
    r = exercises.search(tools.cfg, muscle="臀中肌")
    assert [x["id"] for x in r["items"]] == ["0710"]
    assert r["items"][0]["主练"] == "髋外展肌（臀中肌）" and r["items"][0]["器械"] == "徒手"
    assert exercises.search(tools.cfg, "臀桥")["items"][0]["id"] == "3013"
    assert exercises.search(tools.cfg, "腘绳 拉伸")["items"][0]["id"] == "1511"
    assert exercises.search(tools.cfg, "hip abduction")["items"][0]["id"] == "0710"
    assert "Gym visual" in r["attribution"]


def test_knee_flags_and_safe_filter(tools):
    jump = exercises.get(tools.cfg, "0514")
    assert any("跳跃落地" in f for f in jump["膝盖留意"])
    assert exercises.get(tools.cfg, "3013")["膝盖留意"] == []
    ids = [x["id"] for x in exercises.search(tools.cfg, muscle="臀", no_knee_flags=True, limit=10)["items"]]
    assert "0514" not in ids and "3013" in ids


def test_get_full_steps_and_media_urls(tools):
    ex = exercises.get(tools.cfg, "0710")
    assert len(ex["步骤"]) == 4
    assert ex["动图"] == "/media/exercise/0710-abcDEF1.gif" and ex["图"] == "/media/exercise/0710-abcDEF1.jpg"
    assert exercises.get(tools.cfg, "9999") is None


def test_missing_db_says_so(tools_env, tmp_path):
    exercises._load.cache_clear()
    cfg = replace(tools_env.cfg, exercise_db_dir=str(tmp_path / "nope"))
    r = exercises.search(cfg, "臀桥")
    assert r["items"] == [] and "没装" in r["error"]


def test_media_path_rejects_traversal(tools):
    assert exercises.media_path(tools.cfg, "/media/exercise/0710-abcDEF1.gif").name == "0710-abcDEF1.gif"
    assert exercises.media_path(tools.cfg, "/media/exercise/../data/exercises.json") is None
    assert exercises.media_path(tools.cfg, "/media/exercise/0710-abcDEF1.png") is None
    assert exercises.media_path(tools.cfg, "/media/exercise/0711-nothere.gif") is None


def test_photo_part_shows_exercise_gif(tools):
    lay = canvas.validate({"t": "v", "children": [{"t": "photo", "exercise": "0710"}]}, "chat")
    out = canvas.resolve(tools, lay, DAY, NOW)["children"][0]
    assert out["url"] == "/media/exercise/0710-abcDEF1.gif" and out["kind"] == "exercise"
    assert "臀中肌" in out["caption"]
    with pytest.raises(CanvasError):
        canvas.validate({"t": "v", "children": [{"t": "photo", "exercise": "臀桥"}]}, "chat")


def test_media_route_serves_gif(tools):
    httpd = web.QuietServer(("127.0.0.1", 0), web.make_handler(tools.cfg, tools))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/media/exercise/0710-abcDEF1.gif", timeout=5) as r:
            assert r.status == 200 and r.headers["Content-Type"] == "image/gif" and r.read().startswith(b"GIF")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/media/exercise/..%2Fdata%2Fexercises.json", timeout=5)
        assert e.value.code == 404
    finally:
        httpd.shutdown()
