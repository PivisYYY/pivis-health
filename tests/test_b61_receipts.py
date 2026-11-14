"""b61：回执要有写成功的命令撑着；Psir 报的体重进体重数据。"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pivis_health import cli, receipts
from pivis_health.todos import TodoStore
from pivis_health.tools import log_weight, manual_weights

CN = ZoneInfo("Asia/Shanghai")


def _run(tools_env, *argv):
    buf = io.StringIO()
    cfgpath = tools_env.cfg_path if hasattr(tools_env, "cfg_path") else None
    with redirect_stdout(buf):
        cli.main([*(["--config", str(cfgpath)] if cfgpath else []), *argv])
    return json.loads(buf.getvalue())


def test_receipt_needs_backed_ref(tools_env):
    cfg = tools_env.cfg
    card = {"type": "receipt", "change": "记下体重 72.4", "effective": "今天", "remembered": True}
    probs = receipts.receipt_problems(cfg, [(1, card)])
    assert probs and "没有 ref" in probs[0]
    probs = receipts.receipt_problems(cfg, [(1, {**card, "ref": "rzzzzzz"})])
    assert probs and "对不上" in probs[0]
    rid = receipts.record(cfg, "weight-log", "72.4")
    assert receipts.receipt_problems(cfg, [(1, {**card, "ref": rid})]) == []


def test_audit_turn_asks_agent_to_correct(tools_env):
    sent = []
    text = '记下了。\n```phealth-ui\n{"type":"receipt","change":"体重 72.4","effective":"今天","remembered":true}\n```'
    probs = receipts.audit_turn(tools_env.cfg, "", [text], lambda m, c: sent.append((m, c)))
    assert probs and sent and sent[0][0].startswith("【反馈") and sent[0][1] == ""


def test_manual_weight_reaches_series(tools_env):
    cfg = tools_env.cfg
    log_weight(cfg, date(2026, 10, 28), 72.4)
    assert manual_weights(cfg)[date(2026, 10, 28)] == 72.4
    w = tools_env.daily_series("weight", date(2026, 10, 28), 30)
    assert w[max(w)] == 72.4


def test_weigh_todo_submit_logs_weight(tools_env):
    store = TodoStore(tools_env.cfg)
    t = store.add({"board": "life", "when": "08:30", "title": "空腹称体重", "kind": "number",
                   "inputs": [{"id": "kg", "label": "体重", "type": "number", "unit": "kg", "submit": "agent"}]},
                  date(2026, 10, 28))
    store.user_submit(t["id"], "agent", {"kg": 71.9}, None, None, datetime(2026, 10, 28, 8, 40, tzinfo=CN))
    assert manual_weights(tools_env.cfg)[date(2026, 10, 28)] == 71.9


def test_write_commands_print_receipt_id(tools_env, capsys):
    cli._STATE.update({"cmd": "context-record", "cfg": tools_env.cfg})
    try:
        cli._json({"scope": "pref.x"})
        out = json.loads(capsys.readouterr().out)
        assert receipts.lookup(tools_env.cfg, out["receipt_id"])["cmd"] == "context-record"
        cli._STATE["cmd"] = "facts"                      # 只读命令不发回执编号
        cli._json({"a": 1})
        assert "receipt_id" not in json.loads(capsys.readouterr().out)
        cli._STATE["cmd"] = "todo-add"
        cli._json({"error": "x"})                        # 失败不发
        assert "receipt_id" not in json.loads(capsys.readouterr().out)
    finally:
        cli._STATE.update({"cmd": None, "cfg": None})


def test_follow_wait_reports_failure_in_plain_words(tools_env, tmp_path):
    from dataclasses import replace
    from pivis_health import follow
    cfg = replace(tools_env.cfg, follow_enabled=True)
    jobs = follow.pf_home(cfg) / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / "j26fc36e7.json").write_text(json.dumps({"state": "failed", "step": "配音（每句录几条）",
                                                     "error": "ValueError: bad", "started": "2026-11-12 05:13:33"}))
    out, code = follow.run_cli(cfg, ["wait", "j26fc36e7", "--timeout", "10"])
    assert code == 1 and "配音" in out["say"] and "没做成" in out["say"] and out["dev"].startswith("ValueError")
    (jobs / "j26fc36e8.json").write_text(json.dumps({"state": "done", "result": {"verify_ok": True}}))
    out, code = follow.run_cli(cfg, ["wait", "j26fc36e8"])
    assert code == 0 and out["say"] == "出好了，验收通过"
