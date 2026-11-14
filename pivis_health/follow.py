"""跟练视频：./pivis-health follow … → pivis-follow（本机 ~/Tools/pivis-follow，Vision + LaMa + Qwen3-TTS）。
素材库按环境分开：<data_dir>/follow（真实 / 模拟 / 演示互不影响）。成片只经自己的服务器 /media/follow/ 给 App，绝不外传。"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .config import Config

PF = Path(os.environ.get("PIVIS_FOLLOW_HOME", str(Path.home() / "Tools/pivis-follow")))
SAFE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")


def pf_home(cfg: Config) -> Path:
    return cfg.data_dir / "follow"


def run_cli(cfg: Config, argv: list[str]) -> tuple[dict, int]:
    if not cfg.follow_enabled:
        return {"error": "not_enabled", "message": "跟练视频功能还在模拟环境验收，这个环境暂未开放。可以先把视频链接存进素材库（media-add）。"}, 2
    if argv and argv[0] == "wait":
        return wait_job(cfg, argv[1:])
    if not argv or argv[0] in ("-h", "--help", "help"):
        argv = ["--help"]
    env = dict(os.environ, PF_HOME=str(pf_home(cfg)))
    r = subprocess.run([str(PF / "pf.sh"), *argv], capture_output=True, text=True, env=env, timeout=3600)
    txt = r.stdout.strip()
    if argv == ["--help"]:
        return {"help": txt}, 0
    try:
        out = json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        out = {"output": txt[-3000:]}
    if r.returncode and not out:
        out = {"error": "follow_failed", "message": (r.stderr or txt)[-800:]}
    if isinstance(out, dict):
        _localize(out, cfg)
        jid = out.get("job")
        if r.returncode == 0 and isinstance(jid, str) and SAFE.fullmatch(jid):
            out["progress_card"] = progress_card(jid)
    return out, (0 if r.returncode == 0 else 1)


# 出片失败时给 Psir 的一句人话（b61：以前配音失败 6 次，P-Health 一次都没告诉他）
_STEP_SAY = (("下载", "下载原片"), ("看懂", "识别动作"), ("分析", "识别动作"), ("切动作", "剪动作"),
             ("配音", "配音"), ("出片", "合成视频"), ("验收", "验收"))


def wait_job(cfg: Config, argv: list[str]) -> tuple[dict, int]:
    """follow wait <job> [--timeout 秒]：一直等到出片结束（完成 / 失败）或超时，不用自己 sleep 轮询。
    失败时带 say（给 Psir 的一句话）和 dev（给开发看的错误），P-Health 要马上告诉 Psir。"""
    if not argv or not SAFE.fullmatch(argv[0]):
        return {"error": "bad_job", "message": "用法：follow wait <job id> [--timeout 秒]"}, 2
    jid = argv[0]
    timeout = 540
    if "--timeout" in argv:
        try:
            timeout = max(10, min(1800, int(argv[argv.index("--timeout") + 1])))
        except (ValueError, IndexError):
            pass
    path = pf_home(cfg) / "jobs" / f"{jid}.json"
    deadline = time.time() + timeout
    job: dict = {}
    while True:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"error": "no_job", "message": f"找不到任务 {jid}"}, 1
        except (OSError, ValueError):
            job = job or {}
        state = str(job.get("state") or "")
        if state in ("done", "failed") or time.time() >= deadline:
            break
        time.sleep(5)
    step = str(job.get("step") or "")
    out: dict = {"job": jid, "state": state or "unknown", "step": step, "progress_card": progress_card(jid)}
    if state == "done":
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        out["result"] = result
        out["say"] = "出好了，验收通过" if result.get("verify_ok") is True else "出好了，但验收没过，先别交给 Psir"
        return out, 0
    if state == "failed":
        where = next((label for k, label in _STEP_SAY if k in step), "出片")
        out["say"] = f"视频在「{where}」这一步失败了，这次没做成"
        out["dev"] = str(job.get("error") or "")[:300]
        out["next"] = ("马上告诉 Psir 没做成、卡在哪一步；能换个做法重试就说你打算怎么试（只重试一次），"
                       "同样的错第二次出现就用 context-record --scope request.tool 记给开发，不要反复重试")
        return out, 1
    out["say"] = "还在做，超过等待时间了"
    out["next"] = "告诉 Psir 还在做、进度卡会自己更新；之后再 follow wait 一次，别用 sleep 轮询"
    return out, 0


def _localize(obj, cfg):
    """本机文件路径里的素材库前缀换短，方便看"""
    return obj


def progress_card(jid: str) -> dict:
    """现有画布零件绑定后台任务；Agent 原样发卡，不猜进度或剩余分钟。"""
    if not SAFE.fullmatch(jid):
        raise ValueError("invalid follow job")
    return {"type": "layout", "layout": {"t": "v", "children": [
        {"t": "text", "text": "跟练视频", "role": "title"},
        {"t": "bar", "bind": f"follow:{jid}"},
    ]}}


def progress_node(cfg: Config, jid: str) -> dict:
    """只读当前环境任务状态，转成通用零件。绝不把 args、路径、trace 发给 App。"""
    def node(stage, fraction=0.0, elapsed="", caption="", live=False):
        children = [
            {"t": "text", "text": stage, "role": "body", "tone": 1},
            {"t": "bar", "fraction": fraction, "left": elapsed,
             "right": f"阶段进度 {int(fraction * 100)}%"},
            {"t": "text", "text": caption, "role": "caption", "tone": 3},
        ]
        out = {"t": "v", "gap": 8, "children": children}
        if live:
            out["refresh_after"] = 3
        return out

    if not cfg.follow_enabled or not SAFE.fullmatch(jid):
        return node("暂时读不到这个视频任务", caption="请让 P-Health 检查任务。")
    path = pf_home(cfg) / "jobs" / f"{jid}.json"
    # 不允许通过符号链接跨到另一环境。
    if path.is_symlink() or not path.resolve().is_relative_to(pf_home(cfg).resolve()):
        return node("暂时读不到这个视频任务", caption="请让 P-Health 检查任务。")
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(job, dict):
            raise ValueError("invalid job")
        modified = path.stat().st_mtime
    except FileNotFoundError:
        return node("找不到这个视频任务", caption="任务可能已清理，请让 P-Health 检查。")
    except (OSError, ValueError):
        # 生成器写 JSON 期间可能只读到半份，保留重试能力。
        return node("正在读取视频进度", caption="进度暂未取到，稍后自动重试。", live=True)

    state = str(job.get("state") or "")
    try:
        fraction = float(job.get("progress") or 0)
        fraction = min(0.99, max(0.0, fraction)) if math.isfinite(fraction) else 0.0
    except (ValueError, TypeError):
        fraction = 0.0
    try:
        # follow 写的是机器本地时间，不是健康数据的用户时区。
        started = datetime.strptime(str(job.get("started")), "%Y-%m-%d %H:%M:%S").timestamp()
        end = modified if state in ("done", "failed") else time.time()
        seconds = max(0, int(end - started))
        elapsed = f"已用时 {seconds // 60} 分 {seconds % 60} 秒"
    except (ValueError, TypeError, OverflowError):
        elapsed = ""
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    if state == "done" and result.get("verify_ok") is True:
        return node("视频已生成，验收通过", 1.0, elapsed, "可以在对话里查看成片。")
    if state == "done":
        return node("验收未通过", fraction, elapsed, "正在等 P-Health 检查，暂不交付。")
    if state == "failed":
        return node("视频生成中断", fraction, elapsed, "请让 P-Health 检查后重试。")
    if state not in ("queued", "running"):
        return node("视频任务状态待检查", fraction, elapsed, "请让 P-Health 检查任务。")
    step = str(job.get("step") or "")
    # 只显示已知阶段，外部工具的原始错误和自由文本不透出。
    stage = "正在准备视频"
    for keyword, label in (("排队", "等待开始"), ("下载", "正在下载原片"),
                           ("看懂", "正在识别动作和讲解"), ("分析", "正在识别动作和讲解"),
                           ("切动作", "正在剪辑动作"), ("配音", "正在制作报数和教练配音"),
                           ("出片", "正在合成跟练视频"), ("验收", "正在逐项验收视频")):
        if keyword in step:
            stage = label
            break
    if count := re.fullmatch(r"切动作\s+(\d{1,3})/(\d{1,3})", step):
        stage += f" {count[1]}/{count[2]}"
    caption = "按真实处理阶段更新，剩余时间暂不能准确估计。"
    if time.time() - modified > 600:
        caption = "这个阶段较久没有更新，仍在等候；尚未确认完成。"
    return node(stage, fraction, elapsed, caption, live=True)


def media_path(cfg: Config, path: str) -> Path | None:
    """/media/follow/<ssid>/<out.mp4|poster.jpg> → 文件（只认这两种，ssid 只能是字母数字）"""
    parts = path.split("?")[0].strip("/").split("/")
    if len(parts) != 4 or parts[0] != "media" or parts[1] != "follow":
        return None
    ssid, name = parts[2], parts[3]
    if not SAFE.match(ssid) or name not in ("out.mp4", "poster.jpg"):
        return None
    f = pf_home(cfg) / "sessions" / ssid / name
    return f if f.is_file() else None
