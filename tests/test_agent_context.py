"""共享上下文（P0-1）：递增 revision、append-only 历史、替代、持久化与编排联动。"""
from __future__ import annotations

import json

from pivis_health.agent_context import AgentContextStore
from pivis_health.config import Config
from pivis_health.experience import Experience
from pivis_health.publications import PublicationStore, raw_document


def test_record_increments_global_revision_across_scopes(tmp_path):
    ctx = AgentContextStore(Config(data_dir=tmp_path))
    first = ctx.record("plan.sleep", {"bedtime": "22:40"}, source_session="main")
    second = ctx.record("ui.sleep.hero_risk", {"source": "recovery"}, source_session="休息")
    assert first["revision"] == 1 and second["revision"] == 2
    assert ctx.revision() == 2
    third = ctx.record("plan.sleep", {"bedtime": "23:00"}, source_session="主 Session 干预")
    assert third["revision"] == 3


def test_new_decision_supersedes_old_but_keeps_history(tmp_path):
    ctx = AgentContextStore(Config(data_dir=tmp_path))
    ctx.record("plan.sleep", {"bedtime": "22:40"}, source_session="main", reason="初版")
    entry = ctx.record("plan.sleep", {"bedtime": "23:00"}, source_session="main", reason="用户推迟")
    assert entry["supersedes"] == 1

    snapshot = ctx.snapshot()
    assert snapshot["revision"] == 2
    assert [e["revision"] for e in snapshot["entries"]] == [2]
    assert snapshot["entries"][0]["payload"] == {"bedtime": "23:00"}

    history = ctx.history("plan.sleep")
    assert [e["status"] for e in history] == ["superseded", "active"]
    assert history[0]["superseded_by"] == 2
    assert history[0]["payload"] == {"bedtime": "22:40"}  # 旧决定与原因保留


def test_history_filters_by_scope_and_keeps_order(tmp_path):
    ctx = AgentContextStore(Config(data_dir=tmp_path))
    ctx.record("ui.sleep.hero_risk", {"source": "recovery"}, source_session="main")
    ctx.record("ui.sleep.tiles", {"sources": ["debt"]}, source_session="休息")
    ctx.record("plan.sport", {"quota": 3}, source_session="运动")
    all_entries = ctx.history()
    assert [e["revision"] for e in all_entries] == [1, 2, 3]
    assert [e["scope"] for e in ctx.history("ui.sleep.tiles")] == ["ui.sleep.tiles"]


def test_persists_atomically_and_is_readable_by_new_store(tmp_path):
    cfg = Config(data_dir=tmp_path)
    ctx = AgentContextStore(cfg)
    ctx.record("plan.sleep", {"bedtime": "22:40"}, source_session="main")
    ctx.record("plan.sleep", {"bedtime": "23:00"}, source_session="main")

    reloaded = AgentContextStore(cfg)
    assert reloaded.revision() == 2
    assert reloaded.snapshot()["entries"][0]["payload"] == {"bedtime": "23:00"}

    raw = json.loads((tmp_path / "agent_context.json").read_text(encoding="utf-8"))
    assert raw["revision"] == 2 and len(raw["entries"]) == 2
    assert not list(tmp_path.glob("agent-context-*.json"))  # 无残留临时文件


def test_record_rejects_invalid_scope_and_payload(tmp_path):
    ctx = AgentContextStore(Config(data_dir=tmp_path))
    for bad_scope in ("", "   ", 42):
        try:
            ctx.record(bad_scope, {"x": 1})
        except ValueError:
            pass
        else:
            raise AssertionError(f"scope {bad_scope!r} should be rejected")
    try:
        ctx.record("plan.sleep", ["not", "an", "object"])
    except ValueError:
        pass
    else:
        raise AssertionError("non-object payload should be rejected")
    assert ctx.revision() == 0  # 失败写入不产生 revision


def test_ui_set_writes_shared_decision_with_source_session(tmp_path):
    cfg = Config(data_dir=tmp_path)
    exp = Experience(cfg)
    out = exp.ui_set("sleep", "hero_risk", {"source": "recovery"}, "客户端对话调整")
    assert out["shared_revision"] == 1

    ctx = AgentContextStore(cfg)
    entry = ctx.history("ui.sleep.hero_risk")[0]
    assert entry["source_session"] == "unknown"  # 默认来源
    assert entry["reason"] == "客户端对话调整"
    assert entry["payload"] == {"page": "sleep", "component": "hero_risk",
                                "patch": {"source": "recovery"}}

    exp.ui_set("sleep", "hero_risk", {"source": "debt"}, "再次调整", source_session="main")
    history = ctx.history("ui.sleep.hero_risk")
    assert [e["status"] for e in history] == ["superseded", "active"]
    assert ctx.snapshot()["entries"][0]["source_session"] == "main"
    assert ctx.revision() == 2


def test_ui_set_invalid_patch_leaves_no_shared_entry(tmp_path):
    cfg = Config(data_dir=tmp_path)
    exp = Experience(cfg)
    try:
        exp.ui_set("sleep", "hero_risk", {"fields": {"value": "100"}})
    except ValueError:
        pass
    else:
        raise AssertionError("fake value should be rejected")
    assert AgentContextStore(cfg).revision() == 0


def test_raw_document_carries_shared_snapshot(tools_env):
    ctx = AgentContextStore(tools_env.cfg)
    ctx.record("ui.sleep.hero_risk", {"source": "recovery"}, source_session="main")

    doc = raw_document(tools_env, "sleep")
    assert doc["shared_context"]["revision"] == 1
    assert doc["shared_context"]["entries"][0]["scope"] == "ui.sleep.hero_risk"
    # 证据与共享上下文一起 JSON 序列化给编排 Agent
    json.dumps(doc, ensure_ascii=False, default=str)


def test_publication_records_shared_revision(tools_env):
    ctx = AgentContextStore(tools_env.cfg)
    ctx.record("ui.sleep.hero_risk", {"source": "recovery"}, source_session="main")

    store = PublicationStore(tools_env.cfg)
    components = [{"type": "headline", "kicker": "休息专项", "text": "今晚先补觉",
                   "session": "休息"}]
    record = store.save("sleep", components, "composer-session")
    assert record["shared_revision"] == 1  # 未显式声明时取当前 revision

    ctx.record("plan.sleep", {"bedtime": "23:00"}, source_session="main")
    explicit = store.save("sleep", components, "composer-session", shared_revision=1)
    assert explicit["shared_revision"] == 1  # 声明基于哪个 revision 就记哪个
    assert store.get("sleep")["shared_revision"] == 1


def test_ui_reset_supersedes_previous_shared_decision(tmp_path):
    cfg = Config(data_dir=tmp_path)
    exp = Experience(cfg)
    exp.ui_set("sleep", "hero_risk", {"source": "recovery"}, source_session="main")
    out = exp.ui_reset("sleep", "hero_risk", source_session="main")

    ctx = AgentContextStore(cfg)
    history = ctx.history("ui.sleep.hero_risk")
    assert out["shared_revision"] == 2
    assert [e["status"] for e in history] == ["superseded", "active"]
    assert history[-1]["payload"]["reset"] is True
    assert history[-1]["source_session"] == "main"


def test_ui_reset_page_supersedes_each_previous_component(tmp_path):
    cfg = Config(data_dir=tmp_path)
    exp = Experience(cfg)
    exp.ui_set("sleep", "hero_risk", {"source": "recovery"})
    exp.ui_set("sleep", "tiles", {"sources": ["debt"]})
    exp.ui_reset("sleep")

    ctx = AgentContextStore(cfg)
    assert ctx.revision() == 4
    for scope in ("ui.sleep.hero_risk", "ui.sleep.tiles"):
        history = ctx.history(scope)
        assert [e["status"] for e in history] == ["superseded", "active"]
        assert history[-1]["payload"]["reset"] is True


def test_each_publication_uses_a_fresh_stateless_composer_session():
    from pivis_health import dsh_chat
    a = dsh_chat._session_id("组件编排:sleep:r1")
    b = dsh_chat._session_id("组件编排:sleep:r2")
    c = dsh_chat._session_id("组件编排:sport:r1")
    assert a.startswith("phealth-component-composer-v3-sleep-")
    assert b.startswith("phealth-component-composer-v3-sleep-")
    assert a != b
    assert c.startswith("phealth-component-composer-v3-sport-")


def test_need_feedback_is_visible_to_future_agent_executions(tools_env):
    result = tools_env.need_feedback("media-video-1", "做了")
    assert result["shared_revision"] == 1
    snapshot = AgentContextStore(tools_env.cfg).snapshot()
    assert snapshot["entries"][0]["payload"] == {"need_type": "media-video-1", "action": "做了"}
    assert snapshot["entries"][0]["source_session"] == "ios-client"
    assert tools_env.subj.entries(kinds=["need_feedback"])[-1]["payload"]["action"] == "做了"
