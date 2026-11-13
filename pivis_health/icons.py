"""长期项目 / 待办的线条图标（build 53，Psir 11-10：「腰背放松」显示成网球拍是错的）。

P-Health 建项目时可以写 icon（只能从 ICONS 里挑，都是 iOS 17 自带的 SF Symbols）；没写就按名字配，再不行按板块。
App 用细线圆框画，和板块图标一个样子。
"""
from __future__ import annotations

# 图标 → 什么时候用（写进 AGENTS，P-Health 按这个挑）
ICONS: dict[str, str] = {
    "figure.flexibility": "拉伸、腰背放松、柔韧",
    "figure.core.training": "核心、腰背力量",
    "figure.step.training": "膝盖康复、下肢稳定",
    "figure.strengthtraining.traditional": "力量、哑铃、深蹲",
    "figure.strengthtraining.functional": "功能训练、其他训练",
    "figure.cooldown": "运动后放松",
    "figure.walk": "走路、散步、步数",
    "figure.run": "跑步",
    "figure.tennis": "网球",
    "figure.pool.swim": "游泳",
    "figure.outdoor.cycle": "骑车",
    "figure.hiking": "爬山、徒步",
    "figure.yoga": "瑜伽",
    "figure.mind.and.body": "冥想、身心练习",
    "lungs": "呼吸练习",
    "moon": "睡眠、CBT-I",
    "bed.double": "上床、作息",
    "sun.max": "早上见光、晒太阳",
    "lightbulb": "调暗灯光",
    "iphone.slash": "放下手机、少看屏幕",
    "shower": "洗澡、泡脚",
    "cup.and.saucer": "咖啡因、饮品",
    "drop": "喝水",
    "fork.knife": "饮食、三餐",
    "camera": "拍照记录",
    "square.and.pencil": "日记、记录",
    "scalemass": "称体重",
    "pills": "吃药、补剂",
    "book": "阅读",
    "brain.head.profile": "压力、情绪",
    "heart": "心率、心脏相关",
}

# 名字里的词 → 图标（先长后短，先具体后笼统）
_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("腰背放松", "拉伸", "柔韧", "放松操"), "figure.flexibility"),
    (("腰", "背", "核心"), "figure.core.training"),
    (("膝",), "figure.step.training"),
    (("深蹲", "哑铃", "力量", "增肌"), "figure.strengthtraining.traditional"),
    (("网球",), "figure.tennis"),
    (("跑",), "figure.run"),
    (("游泳",), "figure.pool.swim"),
    (("骑",), "figure.outdoor.cycle"),
    (("爬山", "徒步"), "figure.hiking"),
    (("瑜伽",), "figure.yoga"),
    (("冥想", "正念"), "figure.mind.and.body"),
    (("呼吸",), "lungs"),
    (("走", "散步", "步数"), "figure.walk"),
    (("CBT", "睡眠", "睡"), "moon"),
    (("上床", "作息"), "bed.double"),
    (("见光", "晒", "阳光"), "sun.max"),
    (("灯",), "lightbulb"),
    (("手机", "屏幕"), "iphone.slash"),
    (("澡", "泡脚"), "shower"),
    (("咖啡", "茶"), "cup.and.saucer"),
    (("喝水", "补水"), "drop"),
    (("拍", "照"), "camera"),
    (("饮食", "吃", "饭", "餐"), "fork.knife"),
    (("日记", "记录", "记"), "square.and.pencil"),
    (("体重", "称"), "scalemass"),
    (("药", "补剂"), "pills"),
    (("阅读", "书"), "book"),
    (("压力", "情绪", "焦虑"), "brain.head.profile"),
    (("心",), "heart"),
    (("训练", "练", "运动"), "figure.strengthtraining.functional"),
]
BOARD_ICON = {"sleep": "moon", "sport": "figure.strengthtraining.functional", "stress": "lungs", "life": "square.and.pencil"}


def check(icon: str | None) -> None:
    if icon and icon not in ICONS:
        from .todos import TodoError
        raise TodoError(f"icon「{icon}」不在可选图标里，从这些里挑：" + "、".join(f"{k}（{v}）" for k, v in ICONS.items()))


def guess(name: str, board: str | None = None) -> str:
    n = str(name or "")
    for words, icon in _WORDS:
        if any(w in n for w in words):
            return icon
    return BOARD_ICON.get(board or "", "square.and.pencil")


def for_project(p: dict) -> str:
    icon = p.get("icon")
    return icon if icon in ICONS else guess(p.get("name", ""), p.get("board"))
