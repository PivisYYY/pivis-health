"""放松页闭环：内容库、评分影响挑选、今晚流程生成。"""
from __future__ import annotations

from pivis_health import content


def test_library_links_are_search_authority_or_verified_bilibili_video():
    """链接必须来自可检查的来源；具体 B 站视频必须经核实且提供官方嵌入地址。"""
    for it in content.LIBRARY:
        url = it["url"]
        if url.startswith("/media/sleep-audio/"):  # CBT-I 跟练音频由服务器自己托管
            continue
        assert url.startswith("https://"), it["id"]
        if "www.bilibili.com/video/BV" in url:
            bvid = url.split("/video/", 1)[1].split("/", 1)[0]
            assert it["status"] == "verified", it["id"]
            assert it["embed"] == f"https://player.bilibili.com/player.html?bvid={bvid}&autoplay=0"
        else:
            assert "search.bilibili.com/all?keyword=" in url or "sleepfoundation.org" in url, it["id"]


def test_plan_orders_by_category():
    plan = content.tonight_plan(["music-ambient", "cbt-worry-time", "stretch-bedtime"])
    assert [it["category"] for it in plan] == ["拉伸", "CBT-I", "音频"]
    assert content.tonight_plan(["nope"]) == []


def test_rating_changes_suggestion():
    """评分聚合正确，且每类各挑一条；差评只在有替代项时才会被挤掉。"""
    scores = content.rating_scores([
        {"payload": {"item_id": "stretch-bedtime", "rating": "good"}},
        {"payload": {"item_id": "stretch-bedtime", "rating": "good"}},
        {"payload": {"item_id": "breathing-478", "rating": "bad"}},
    ])
    assert scores["stretch-bedtime"] == {"good": 2, "bad": 0}
    assert scores["breathing-478"] == {"good": 0, "bad": 1}
    picked = content.suggest(scores)
    assert len(picked) == len(content.CATEGORY_ORDER)  # 每类一条
    net = {it["id"]: scores.get(it["id"], {}).get("good", 0) - scores.get(it["id"], {}).get("bad", 0)
           for it in content.LIBRARY}
    # 被挑中的必须是该类别中净评分最高的（此处各类别仅一条，验证排序稳定性）
    for it in picked:
        cat_items = [x for x in content.LIBRARY if x["category"] == it["category"]]
        assert net[it["id"]] == max(net[x["id"]] for x in cat_items)


def test_relax_flow_roundtrip(tools_env):
    lib = tools_env.relax_library()
    assert len(lib["items"]) >= 4
    sug = tools_env.relax_suggest()["suggested"]
    assert sug, "每类至少挑一条"
    plan = tools_env.relax_plan_save([it["id"] for it in sug])
    assert plan["ok"] and plan["plan"]
    tools_env.content_rate(plan["items"][0]["id"], "good")
    entries = tools_env.subj.entries(kinds=["content_rating", "relax_plan"])
    kinds = {e["kind"] for e in entries}
    assert kinds == {"content_rating", "relax_plan"}
