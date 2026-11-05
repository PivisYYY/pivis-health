"""pivis-health CLI —— dsh P-Health bot 的主接口。全部输出 JSON（UTF-8）。"""
from __future__ import annotations

import argparse
import json
import time
import sys
from datetime import date, datetime

from .config import Config, load_config
from .tools import HealthTools


def _json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _republish_async(tools, pages) -> None:
    """项目变了：后台刷新页面的结论和主卡，不阻塞当前对话。"""
    from .v3 import republish_async
    republish_async(tools.cfg)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pivis-health", description="个人健康内核（只读客观库 + 确定性计算）")
    p.add_argument("--config", help="配置文件路径（默认仓库内 config.local.json）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="自检：库可达性、各源最新时间")

    sp = sub.add_parser("today"); sp.add_argument("--date")
    sp = sub.add_parser("sleep"); sp.add_argument("--date")
    sp = sub.add_parser("morning-report"); sp.add_argument("--date")
    sp = sub.add_parser("weekly-report"); sp.add_argument("--week-of", help="周一日期，默认本周")
    sp = sub.add_parser("monitor"); sp.add_argument("--date"); sp.add_argument("--now-hour", type=int)
    sp = sub.add_parser("series"); sp.add_argument("--metric", required=True); sp.add_argument("--days", type=int, default=30); sp.add_argument("--date")
    sp = sub.add_parser("baseline"); sp.add_argument("--metric", required=True); sp.add_argument("--date")
    sp = sub.add_parser("coverage")

    sp = sub.add_parser("answer"); sp.add_argument("--question-id", required=True); sp.add_argument("--answer", required=True); sp.add_argument("--date")
    sp = sub.add_parser("log"); sp.add_argument("--kind", required=True); sp.add_argument("--payload", required=True, help="JSON 字符串"); sp.add_argument("--date")

    sp = sub.add_parser("rules-list")
    sp = sub.add_parser("rules-add"); sp.add_argument("--metric", required=True); sp.add_argument("--comparator", choices=["below", "above"], required=True); sp.add_argument("--threshold", type=float, required=True); sp.add_argument("--days", type=int, default=1); sp.add_argument("--level", choices=["notice", "alert", "see_doctor"], default="notice"); sp.add_argument("--note", default="")
    sp = sub.add_parser("rules-remove"); sp.add_argument("--id", type=int, required=True)

    sp = sub.add_parser("push-reserve"); sp.add_argument("--key", required=True); sp.add_argument("--date")

    sp = sub.add_parser("relax-library")
    sp = sub.add_parser("relax-plan"); sp.add_argument("--items", required=True, help="逗号分隔的内容 id")
    sp = sub.add_parser("relax-rate"); sp.add_argument("--item", required=True); sp.add_argument("--rating", choices=["good", "bad"], required=True)

    sp = sub.add_parser("morning-wait"); sp.add_argument("--deadline", default="09:00")
    sp = sub.add_parser("nap-today")
    sp = sub.add_parser("v2-page"); sp.add_argument("name", choices=["today", "sleep", "sport", "stress"]); sp.add_argument("--date")
    sp = sub.add_parser("params-list"); sp.add_argument("--history", action="store_true")
    sp = sub.add_parser("params-set"); sp.add_argument("--key", required=True); sp.add_argument("--value", required=True); sp.add_argument("--reason", default="")
    sp = sub.add_parser("dialogue-list", help="读取客户端对话偏好"); sp.add_argument("--session", default="main")
    sp = sub.add_parser("dialogue-add", help="新增持久对话规则"); sp.add_argument("--session", default="main"); sp.add_argument("--rule", required=True)
    sp = sub.add_parser("dialogue-remove"); sp.add_argument("--session", default="main"); sp.add_argument("--index", type=int, required=True)
    sp = sub.add_parser("ui-list", help="读取页面字段/表现覆盖"); sp.add_argument("--page", choices=["now", "sleep", "sport", "stress", "relax"])
    sp = sub.add_parser("ui-set", help="对话中调整既有组件，不可改结构"); sp.add_argument("--page", required=True); sp.add_argument("--component", required=True); sp.add_argument("--patch", required=True, help="JSON 字符串"); sp.add_argument("--reason", default=""); sp.add_argument("--source-session", default="unknown", help="该决定来源的 Session，默认 unknown")
    # ---- v3：生成式待办 + 项目（P-Health 在对话里直接调用）----
    sp = sub.add_parser("todo-add", help="新增一张生成式待办卡（JSON）"); sp.add_argument("--json", required=True)
    sp = sub.add_parser("todo-update", help="修改待办（JSON 补丁）"); sp.add_argument("--id", required=True); sp.add_argument("--json", required=True)
    sp = sub.add_parser("todo-remove"); sp.add_argument("--id", required=True)
    sp = sub.add_parser("todo-list", help="列出某天待办"); sp.add_argument("--date"); sp.add_argument("--board")
    sp = sub.add_parser("project-set", help="创建或修改项目（含每日待办模板）"); sp.add_argument("--json", required=True)
    sp = sub.add_parser("project-list")
    sp = sub.add_parser("media-library", help="可用的放松/跟练素材（只能从这里选链接）")
    sp = sub.add_parser("facts", help="v3 主卡可引用的数字"); sp.add_argument("--date")
    sp = sub.add_parser("page-v3", help="查看 v3 页面文档"); sp.add_argument("page", choices=["now", "sleep", "sport", "stress"])
    sp = sub.add_parser("daily-review", help="每天早上让各板块 P-Health 决定要不要加待办"); sp.add_argument("--board", choices=["sleep", "sport", "stress"]); sp.add_argument("--force", action="store_true")
    sp = sub.add_parser("publish-v3", help="让 P-Health 重新生成 v3 页面主卡"); sp.add_argument("page", choices=["now", "sleep", "sport", "stress", "all"]); sp.add_argument("--timeout", type=int, default=420)
    sp = sub.add_parser("now", help="当前时间（模拟回放时为模拟时间）")
    sp = sub.add_parser("ui-reset"); sp.add_argument("--page", required=True); sp.add_argument("--component"); sp.add_argument("--source-session", default="unknown")
    sp = sub.add_parser("context-record", help="由 P-Health 保存可跨 Session 复用的个人记忆/决定")
    sp.add_argument("--scope", required=True); sp.add_argument("--payload", required=True, help="JSON 对象")
    sp.add_argument("--source-session", default="unknown"); sp.add_argument("--reason", default="")
    sp = sub.add_parser("compare", help="和老大指定的基线对比（数字由内核算）")
    sp.add_argument("--metric", required=True); sp.add_argument("--recent", type=int, default=7)
    sp.add_argument("--baseline", default="prev_week", choices=["prev_week", "personal"]); sp.add_argument("--date")
    sp = sub.add_parser("viz", help="主卡图表的数字（P-Health 定画什么，内核填数）；不带 --metric 列出每项能不能画")
    sp.add_argument("--metric"); sp.add_argument("--kind"); sp.add_argument("--days", type=int)
    sp.add_argument("--show", help="逗号分隔：band,warn,need,pace,goal,target,plan")
    sp = sub.add_parser("prefs-sync", help="把老大定下的偏好写进工作区 AGENTS.md")
    sp = sub.add_parser("context-list", help="读取当前共享记忆或 append-only 历史")
    sp.add_argument("--scope"); sp.add_argument("--history", action="store_true")
    sp = sub.add_parser("need-feedback"); sp.add_argument("--type", required=True); sp.add_argument("--action", choices=["做了", "不做", "换一个", "今天算了"], required=True)
    sp = sub.add_parser("hero-skip"); sp.add_argument("--hero", required=True, help="要换掉的当前异常指标名（恢复/睡眠债/HRV）")
    sp = sub.add_parser("agent-pages-status", help="查看 Agent 组件发布版本")
    sp = sub.add_parser("agent-pages-publish", help="由 P-Health Agent 生成并发布业务组件")
    sp.add_argument("--page", choices=["all", "now", "sleep", "sport", "stress", "relax"], default="all")
    sp.add_argument("--timeout", type=int, default=480)
    sp = sub.add_parser("agent-events-status", help="查看尚未交给 P-Health 的原始事件")
    sp = sub.add_parser("agent-events-dispatch", help="把未分发原始事件交给 P-Health 处理")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--dry-run", action="store_true", help="只列出待分发事件，不发送")

    sp = sub.add_parser("pushd", help="主动触达守护：命中时刻表则推当日待办")
    sp.add_argument("--once", action="store_true", help="跑一轮退出（launchd 模式）")
    sp.add_argument("--interval", type=int, default=0, help="循环间隔秒数；0=只跑一轮")
    sp = sub.add_parser("push", help="立即推送（bot 触达用）")
    sp.add_argument("--title", required=True); sp.add_argument("--body", required=True)
    sp.add_argument("--page", choices=["today", "sleep", "sport", "stress"])
    sp.add_argument("--pending", help="生成式 UI 问句（点通知直达对话）")
    sp.add_argument("--level", choices=["notice", "alert", "see_doctor"], default="notice")
    sp.add_argument("--kind", help="当日去重 key，默认按内容生成")

    sp = sub.add_parser("serve"); sp.add_argument("--host", default="127.0.0.1"); sp.add_argument("--port", type=int, default=8943); sp.add_argument("--tls-cert"); sp.add_argument("--tls-key")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # 旧版（v2）页面命令：P-Health 自己的工作区里一律拒绝，免得 Agent 绕开 v3 页面去改旧组件
    # （launchd 的旧编排任务从 / 启动，不受影响）
    import os as _os
    if args.cmd in ("ui-set", "ui-reset", "ui-list", "hero-skip", "agent-pages-publish", "agent-pages-status") \
            and _os.path.basename(_os.getcwd()) in ("p-health", "workspace-sim"):
        _json({"error": "旧版页面命令已停用。要改页面放什么：./pivis-health context-record --scope "
                        "pref.page.<now|sleep|sport|stress> --payload '{\"rule\": \"…\"}'，"
                        "系统会在后台按新要求重排页面，几分钟后生效。"})
        return 2
    try:
        cfg: Config = load_config(getattr(args, "config", None))
        if args.cmd == "serve":
            from .web import serve
            serve(cfg, host=args.host, port=args.port, tls_cert=args.tls_cert, tls_key=args.tls_key)
            return 0
        tools = HealthTools(cfg)
        if args.cmd == "doctor":
            _json(tools.doctor())
        elif args.cmd == "today":
            _json(tools.today(_day(args.date)))
        elif args.cmd == "sleep":
            _json(tools.sleep_day(_day(args.date)))
        elif args.cmd == "morning-report":
            _json(tools.morning_report(_day(args.date)))
        elif args.cmd == "weekly-report":
            _json(tools.weekly_report(_day(args.week_of)))
        elif args.cmd == "monitor":
            _json(tools.monitor(_day(args.date), args.now_hour))
        elif args.cmd == "series":
            _json(tools.series(args.metric, args.days, _day(args.date)))
        elif args.cmd == "baseline":
            _json(tools.baseline(args.metric, _day(args.date)))
        elif args.cmd == "coverage":
            _json(tools.coverage())
        elif args.cmd == "answer":
            _json(tools.answer_question(args.question_id, args.answer, _day(args.date)))
        elif args.cmd == "log":
            _json(tools.log_subjective(args.kind, json.loads(args.payload), _day(args.date)))
        elif args.cmd == "rules-list":
            _json(tools.rules_list())
        elif args.cmd == "rules-add":
            _json(tools.rules_add(args.metric, args.comparator, args.threshold, args.days, args.level, args.note))
        elif args.cmd == "rules-remove":
            _json(tools.rules_remove(args.id))
        elif args.cmd == "push-reserve":
            _json(tools.push_reserve(args.key, _day(args.date)))
        elif args.cmd == "relax-library":
            _json(tools.relax_library())
        elif args.cmd == "relax-plan":
            _json(tools.relax_plan_save([i.strip() for i in args.items.split(",") if i.strip()]))
        elif args.cmd == "relax-rate":
            _json(tools.content_rate(args.item, args.rating))
        elif args.cmd == "morning-wait":
            _json(tools.morning_wait(args.deadline))
        elif args.cmd == "nap-today":
            _json(tools.nap_today())
        elif args.cmd == "v2-page":
            from .pages import V2Pages
            pages = V2Pages(tools)
            _json(getattr(pages, args.name)(_day(args.date)))
        elif args.cmd == "params-list":
            from .params import Params
            p = Params(tools.subj)
            _json({"history": p.changes()} if args.history else {"params": p.all()})
        elif args.cmd == "params-set":
            from .params import Params
            _json(Params(tools.subj).set(args.key, args.value, args.reason))
        elif args.cmd == "dialogue-list":
            from .experience import Experience
            _json(Experience(tools.cfg, tools.subj).dialogue_list(args.session))
        elif args.cmd == "dialogue-add":
            from .experience import Experience
            _json(Experience(tools.cfg, tools.subj).dialogue_add(args.session, args.rule))
        elif args.cmd == "dialogue-remove":
            from .experience import Experience
            _json(Experience(tools.cfg, tools.subj).dialogue_remove(args.session, args.index))
        elif args.cmd == "ui-list":
            from .experience import Experience
            exp = Experience(tools.cfg, tools.subj)
            _json({"pages": exp.all()["pages"]} if args.page is None else {"page": args.page, "overrides": exp.ui(args.page)})
        elif args.cmd == "ui-set":
            from .experience import Experience
            _json(Experience(tools.cfg, tools.subj).ui_set(
                args.page, args.component, json.loads(args.patch), args.reason,
                source_session=args.source_session))
        elif args.cmd == "ui-reset":
            from .experience import Experience
            _json(Experience(tools.cfg, tools.subj).ui_reset(
                args.page, args.component, source_session=args.source_session))
        elif args.cmd == "context-record":
            from .agent_context import AgentContextStore
            payload = json.loads(args.payload)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            if args.scope.startswith("pref.") and not str(payload.get("rule") or "").strip():
                raise ValueError("pref.* 的 payload 要带一句人话 rule，例如 {\"rule\": \"图表一律用折线\"}")
            entry = AgentContextStore(tools.cfg).record(
                args.scope, payload, source_session=args.source_session, reason=args.reason)
            if args.scope.startswith("pref."):
                from . import prefs
                entry = {**entry, "prefs_sync": prefs.sync_agents_md(tools.cfg)}
                # 偏好会改页面（放什么字段、怎么对比）：后台重排四个页面，不卡对话
                _republish_async(tools, ["now", "sleep", "sport", "stress"])
                entry["pages"] = "页面会在后台按新偏好重排，几分钟后生效"
            _json(entry)
        elif args.cmd == "compare":
            from . import prefs
            day = date.fromisoformat(args.date) if args.date else tools._now().date()
            _json(prefs.compare(tools, args.metric, day, args.recent, args.baseline))
        elif args.cmd == "viz":
            from . import viz
            if not args.metric:
                _json(viz.available(tools))
            else:
                spec = {"metric": args.metric}
                if args.kind: spec["kind"] = args.kind
                if args.days: spec["days"] = args.days
                if args.show: spec["show"] = [x.strip() for x in args.show.split(",") if x.strip()]
                try:
                    _json(viz.build(tools, spec))
                except viz.VizUnavailable as exc:
                    _json({"ok": False, "reason": str(exc)})
        elif args.cmd == "prefs-sync":
            from . import prefs
            _json(prefs.sync_agents_md(tools.cfg))
        elif args.cmd == "context-list":
            from .agent_context import AgentContextStore
            ctx = AgentContextStore(tools.cfg)
            _json({"history": ctx.history(args.scope)} if args.history else ctx.snapshot())
        elif args.cmd == "need-feedback":
            _json(tools.log_subjective("need_feedback", {"need_type": args.type, "action": args.action}))
        elif args.cmd == "hero-skip":
            _json(tools.log_subjective("hero_skip", {"hero": args.hero}))
        elif args.cmd == "agent-pages-status":
            from .publications import PublicationStore
            _json({"pages": PublicationStore(tools.cfg).all()["pages"]})
        elif args.cmd == "agent-pages-publish":
            from .publications import publish_all, publish_page
            _json(publish_all(tools) if args.page == "all" else publish_page(tools, args.page, args.timeout))
        elif args.cmd == "agent-events-status":
            from .event_dispatch import EventDelivery
            _json({"pending": EventDelivery(tools.cfg).pending()})
        elif args.cmd == "agent-events-dispatch":
            from .event_dispatch import EventDelivery, send_event_to_agent
            delivery = EventDelivery(tools.cfg)
            if args.dry_run:
                _json({"pending": delivery.pending()[:args.limit], "dispatched": 0, "failed": []})
            else:
                _json(delivery.dispatch(lambda event: send_event_to_agent(tools.cfg, event),
                                        limit=args.limit))
        elif args.cmd in ("todo-add", "todo-update", "todo-remove", "todo-list", "project-set", "project-list"):
            from .todos import TodoStore
            store = TodoStore(tools.cfg)
            today = tools._now().date()
            if args.cmd == "todo-add":
                _json(store.add(json.loads(args.json), today))
            elif args.cmd == "todo-update":
                _json(store.update(args.id, json.loads(args.json)))
            elif args.cmd == "todo-remove":
                _json(store.remove(args.id))
            elif args.cmd == "todo-list":
                day = _day(args.date) or today
                if day == today:
                    store.materialize(day, tools._now())
                _json({"date": day.isoformat(), "todos": store.for_date(day, args.board)})
            elif args.cmd == "project-set":
                proj = store.project_set(json.loads(args.json), today, tools._now())
                _json(proj)
                _republish_async(tools, [proj["board"], "now"])
            else:
                _json({"projects": store.projects()})
        elif args.cmd == "media-library":
            from .v3 import media_library
            _json({"items": media_library()})
        elif args.cmd == "facts":
            from .v3 import facts
            _json(facts(tools, _day(args.date) or tools._now().date()))
        elif args.cmd == "page-v3":
            from .v3 import page_doc
            _json(page_doc(tools, args.page))
        elif args.cmd == "publish-v3":
            from .v3 import publish
            pages = ["now", "sleep", "sport", "stress"] if args.page == "all" else [args.page]
            out = {}
            prog = tools.cfg.data_dir / "republish.progress.json"
            for i, pg in enumerate(pages):
                # 客户端据此知道哪几页正在重排（主卡显示「正在改」）
                prog.write_text(json.dumps({"current": pg, "left": pages[i + 1:], "at": time.time()}))
                try:
                    out[pg] = publish(tools, pg, args.timeout)
                except Exception as exc:  # noqa: BLE001
                    out[pg] = {"error": str(exc)}
            for f in (prog, tools.cfg.data_dir / "republish.lock"):
                try:
                    f.unlink()
                except OSError:
                    pass
            _json(out)
        elif args.cmd == "daily-review":
            from .v3 import daily_review
            _json(daily_review(tools, [args.board] if args.board else None, args.force))
        elif args.cmd == "now":
            n = tools._now()
            _json({"now": n.isoformat(timespec="minutes"), "date": n.date().isoformat(),
                   "weekday": "一二三四五六日"[n.weekday()], "sim": tools.cfg.sim_mode})
        elif args.cmd == "pushd":
            from .push import run_pushd_once
            import time as _time
            while True:
                out = run_pushd_once(tools)
                _json(out)
                if not args.interval:
                    break
                _time.sleep(args.interval)
        elif args.cmd == "push":
            from .push import send_push
            _json(send_push(tools, args.title, args.body, page=args.page,
                            pending=args.pending, level=args.level, kind=args.kind))
        return 0
    except Exception as exc:  # 对 agent 友好：错误也是结构化输出
        _json({"error": type(exc).__name__, "message": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
