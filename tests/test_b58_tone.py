"""build 58：回复更亲切（先接住人 → 结论 → 主动一步）、少量 emoji、表情包卡（老大 11-11 / 11-12）。"""
import json
from pathlib import Path

from pivis_health import cards, notify

REPO = Path(__file__).resolve().parent.parent
STICKER = '```phealth-ui\n{"type":"sticker","name":"又守住了"}\n```'


def test_sticker_names_match_app():
    data = json.loads((REPO / "ios/PivisHealth/Stickers.json").read_text(encoding="utf-8"))
    assert tuple(s["name"] for s in data["stickers"]) == cards.STICKERS
    assert len(cards.STICKERS) == 24
    # 每个表情的动画种类都有关键帧
    kinds = set()

    def walk(n):
        if "an" in n:
            kinds.add(n["an"]["k"])
        for c in n.get("c", []):
            walk(c)
    for s in data["stickers"]:
        walk(s["root"])
    assert kinds <= set(data["anims"])


def test_sticker_card_and_name():
    assert cards.check({"type": "sticker", "name": "抱抱"}) == []
    probs = cards.check({"type": "sticker", "name": "哈哈"})
    assert probs and "没有这个" in probs[0]


def test_sticker_goes_last():
    ok = cards.check_text("早安老大 ☀️ 又守住一晚！\n" + STICKER + "\n")
    assert ok["ok"], ok
    after_text = cards.check_text(STICKER + "\n再补一句")
    assert any("最后" in p for p in after_text["problems"])
    after_card = cards.check_text(STICKER + '\n```phealth-ui\n{"type":"receipt","change":"记下了"}\n```')
    assert any("最后" in p for p in after_card["problems"])
    two = cards.check_text("好\n" + STICKER.replace("又守住了", "抱抱") + "\n" + STICKER)
    assert any("最多 1 个" in p for p in two["problems"])


def test_emoji_not_counted_and_limited():
    # 58 个字 + 2 个 emoji：emoji 不算字数
    text = "老" * 58 + " ☀️ 💪"
    res = cards.check_text(text)
    assert res["outside_chars"] == 58 and res["ok"], res
    three = cards.check_text("好的 ☀️ 💪 ✨")
    assert any("最多 2 个" in p for p in three["problems"])
    other = cards.check_text("好的 😀")
    assert any("只用这 8 个" in p for p in other["problems"])


def test_no_emoji_in_cards():
    res = cards.check_text('记好了\n```phealth-ui\n{"type":"receipt","change":"今晚起早点睡 🌙"}\n```')
    assert any("卡里有 emoji" in p for p in res["problems"])


def test_serious_replies_stay_plain():
    res = cards.check_text("老大先坐下，闷得厉害马上打 120 🫂")
    assert any("就医" in p for p in res["problems"])
    res = cards.check_text("这几条有一条就去医院。\n" + STICKER.replace("又守住了", "抱抱"))
    assert any("就医" in p for p in res["problems"])
    assert cards.check_text("老大先坐下，慢慢呼吸，闷得厉害马上打 120。")["ok"]


def test_notify_summary_for_stickers():
    assert notify.summarize(STICKER) == "发来一个表情：又守住了"
    assert notify.summarize("晚安老大 🌙\n" + STICKER) == "晚安老大 🌙"
    card = '```phealth-ui\n{"type":"plan","title":"睡前放松","items":[{"title":"拉伸"}]}\n```'
    assert notify.summarize(card + "\n" + STICKER) == "发来一张卡：睡前放松"


def test_rules_teach_the_new_tone():
    role = (REPO / "agent/skills/phealth-role/SKILL.md").read_text(encoding="utf-8")
    assert "不用表情符号" not in role
    assert "先接住人" in role and "主动一步" in role and '"type":"sticker"' in role
    for name in cards.STICKERS:
        assert name in role
    agents = (REPO / "agent/AGENTS-v3.md").read_text(encoding="utf-8")
    assert "| sticker |" in agents and "emoji 不算" in agents
    rec = (REPO / "agent/skills/daily-recommend/SKILL.md").read_text(encoding="utf-8")
    assert "「午后推荐：闭眼歇" not in rec and "写成「今日判断」" not in rec
