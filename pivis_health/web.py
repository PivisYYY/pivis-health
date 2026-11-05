"""Web 层：PWA 手机客户端 + 独立页面 + JSON API。

- /app            PWA 壳（底部标签：今天/监测/打卡/放松/周报），iOS"添加到主屏幕"即客户端
- /morning /relax /weekly   独立页（bot 发链接直达）
- /api/*          JSON（bot 与客户端共用）
- /manifest.webmanifest /icon.png   PWA 安装件（图标为运行时生成的 PNG，零依赖）

安全边界：无鉴权，仅限本机/Tailnet（默认绑 Tailscale IP），不要暴露公网。
"""
from __future__ import annotations

import json
import struct
import zlib
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from . import content, dsh_chat
from .config import Config
from .tools import HealthTools

# ---------------------------------------------------------------- 样式
_STYLE = """
:root{color-scheme:light dark;--bg:light-dark(#f5f5f7,#000);--card:light-dark(#fff,#1c1c1e);
--fg:light-dark(#1d1d1f,#f5f5f7);--muted:light-dark(#6e6e73,#98989f);
--chip:light-dark(#e8e8ed,#3a3a3c);--line:light-dark(#e5e5ea,#2c2c2e)}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:-apple-system,'PingFang SC',system-ui,sans-serif;margin:0;background:var(--bg);
color:var(--fg);line-height:1.6;padding:12px 12px calc(76px + env(safe-area-inset-bottom))}
.wrap{max-width:560px;margin:0 auto}
.card{background:var(--card);border-radius:16px;padding:18px;margin-bottom:12px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:17px;margin:0 0 8px}
.sub{font-size:13px;color:var(--muted);margin-bottom:12px}
.big{font-size:34px;font-weight:600;letter-spacing:-.5px}
.muted{font-size:13px;color:var(--muted)}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;margin:8px 0}
.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--muted)}
.dot{display:inline-block;width:8px;height:8px;border-radius:4px;margin-right:4px}
.q{margin:12px 0;padding:12px;border-radius:12px;background:var(--chip)}
.choices{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
button{font:inherit;border:0;border-radius:12px;padding:10px 16px;background:#0a84ff;color:#fff}
.chipbtn{background:var(--chip);color:var(--fg);min-height:44px}
.warn{background:light-dark(#fff4e5,#3d2e12);border-radius:12px;padding:12px;font-size:13px;margin-bottom:12px}
.badge{display:inline-block;font-size:12px;border-radius:8px;padding:2px 8px;background:var(--chip);margin-right:6px}
.lv-notice{color:#c77700}.lv-alert{color:#c9372c}.lv-see_doctor{color:#c9372c;font-weight:700}
a{color:#0a84ff}
ul{margin:8px 0 0;padding-left:18px}
#tabs{position:fixed;left:0;right:0;bottom:0;display:flex;background:var(--card);
border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom);z-index:9}
#tabs button{flex:1;background:none;color:var(--muted);font-size:12px;border-radius:0;padding:8px 0 6px}
#tabs button.on{color:#0a84ff}
.rate{display:flex;gap:8px;margin-top:6px}
.rate button{background:var(--chip);color:var(--fg);min-height:44px;flex:1}
.rate button.g{background:#30b15a;color:#fff}.rate button.b{background:#c9372c;color:#fff}
svg{width:100%;height:auto;display:block}
input[type=text]{font:inherit;border:0;border-radius:12px;padding:10px 12px;background:var(--chip);color:var(--fg);width:100%}
"""

# ---------------------------------------------------------------- 纯 Python PNG 图标
def _make_icon() -> bytes:
    W = H = 180
    r = 42
    rows = bytearray()
    for y in range(H):
        rows.append(0)
        for x in range(W):
            cx, cy = min(max(x, r), W - 1 - r), min(max(y, r), H - 1 - r)
            inside = (x - cx) ** 2 + (y - cy) ** 2 <= r * r or (r <= x < W - r and r <= y < H - r)
            moon = (x - 95) ** 2 + (y - 88) ** 2 <= 34 ** 2 and (x - 113) ** 2 + (y - 76) ** 2 > 30 ** 2
            rgba = (0, 0, 0, 0) if not inside else ((255, 255, 255, 255) if moon else (10, 132, 255, 255))
            rows.extend(rgba)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


ICON_PNG = _make_icon()

MANIFEST = {
    "name": "Pivis Health",
    "short_name": "Pivis",
    "start_url": "/app",
    "display": "standalone",
    "background_color": "#000000",
    "theme_color": "#0a84ff",
    "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"}],
}


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------------------------------------------------------- 片段构建
def _sleep_bar(stages: dict | None) -> str:
    if not stages:
        return '<div class="muted">睡眠数据缺口（如实标注，不推断）</div>'
    colors = {"deep": "#5e5ce6", "core": "#0a84ff", "rem": "#bf5af2", "unspecified": "#8e8e93", "awake": "#ffd60a"}
    names = {"core": "核心", "deep": "深睡", "rem": "REM", "unspecified": "未分期", "awake": "清醒"}
    total = sum(v for v in stages.values()) or 1
    parts = [f'<div style="width:{v/total*100:.1f}%;background:{colors.get(k, "#8e8e93")}"></div>'
             for k, v in stages.items() if v > 0]
    legend = "".join(f'<span><span class="dot" style="background:{colors.get(k)}"></span>{names.get(k, k)} {v:.1f}h</span>'
                     for k, v in stages.items() if v > 0)
    return f'<div class="bar">{"".join(parts)}</div><div class="legend">{legend}</div>'


def _spark(values: list, baseline=None, unit="") -> str:
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return '<div class="muted">样本不足</div>'
    w, h, pad = 460, 96, 8
    lo = min(pts + ([baseline] if baseline is not None else []))
    hi = max(pts + ([baseline] if baseline is not None else [])) or (lo + 1)
    if hi == lo:
        hi = lo + 1
    step = (w - 2 * pad) / max(1, len(values) - 1)

    def y(v):
        return h - pad - (v - lo) / (hi - lo) * (h - 2 * pad)

    path, started = [], False
    for i, v in enumerate(values):
        if v is None:
            started = False
            continue
        path.append(f"{'M' if not started else 'L'}{pad + i * step:.1f},{y(v):.1f}")
        started = True
    bl = (f'<line x1="{pad}" y1="{y(baseline):.1f}" x2="{w - pad}" y2="{y(baseline):.1f}" '
          f'stroke="#ff9f0a" stroke-width="1" stroke-dasharray="4 3"/>') if baseline is not None else ""
    blt = f" · 基线 {baseline:.0f}（虚线）" if baseline is not None else ""
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="趋势">{bl}'
            f'<path d="{" ".join(path)}" fill="none" stroke="#0a84ff" stroke-width="2"/>'
            f'<text x="{w - pad}" y="{h - 1}" text-anchor="end" font-size="11" fill="currentColor" opacity=".7">'
            f'{pts[-1]:.0f}{unit}{blt}</text></svg>')


_LV = {"notice": "关注", "alert": "提醒", "see_doctor": "建议就医"}


def _findings_html(findings: list[dict], limit: int = 5) -> str:
    if not findings:
        return '<li class="muted">无待处理发现（正常即静默）</li>'
    return "".join(
        f'<li><b class="lv-{f["level"]}">[{_LV.get(f["level"], f["level"])}]</b> '
        f'{_esc(f.get("reason"))}<br><span class="muted">{_esc(f.get("metric"))} · {_esc(f.get("window"))} · {_esc(f.get("rule_id"))}</span></li>'
        for f in findings[:limit])


def view_today(report: dict) -> str:
    m = report.get("metrics", {})
    whoop = report.get("whoop") or {}
    hrv = m.get("hrv") or {}
    sleep = report.get("sleep") or {}
    night = (sleep.get("night") or {}).get("hours")
    nap = (sleep.get("nap") or {}).get("hours")
    rec = ((whoop.get("recovery") or {}).get("recovery_score"))
    race = (report.get("completeness") or {}).get("race_note")
    hero = f'{night:.1f}h 夜间' if night else "睡眠数据缺口"
    if nap:
        hero += f" + {nap:.1f}h 小憩"
    cards = [f'''<div class="card"><h1>{_esc(report.get('local_date'))}</h1>
<div class="sub">晨报 · 数字来自确定性计算 · {_esc(report.get('generated_at'))}</div>
<div class="big">{_esc(hero)}</div>
<div class="muted">HRV {hrv.get('today') or '—'} ms（基线 {hrv.get('baseline') or '—'}，z={hrv.get('z') if hrv.get('z') is not None else '—'}）
· WHOOP HRV {m.get('whoop_hrv_rmssd_last_night') or '—'} · 恢复 {f'{rec:.0f}%' if rec is not None else '—'}
· 睡眠需求 {whoop.get('sleep_need_h') or '—'}h · 建议 {_esc(whoop.get('suggested_bedtime') or '—')} 上床</div></div>''']
    if race:
        cards.append(f'<div class="warn">⏳ {_esc(race)}</div>')
    cards.append(f'<div class="card"><h2>睡眠结构（夜间）</h2>{_sleep_bar((sleep.get("night") or {}).get("stages"))}</div>')
    t = report.get("charts", {}).get("hrv_trend_14d") or {}
    cards.append(f'<div class="card"><h2>HRV 近 14 天</h2>{_spark(t.get("values", []), t.get("baseline"), "ms")}</div>')
    t2 = report.get("charts", {}).get("recovery_trend_14d") or {}
    cards.append(f'<div class="card"><h2>WHOOP 恢复 · 近 14 天</h2>{_spark(t2.get("values", []), None, "%")}</div>')
    cards.append(f'<div class="card"><h2>发现（确定性）</h2><ul>{_findings_html(report.get("findings", []))}</ul>'
                 f'<div class="muted" style="margin-top:8px">建议素材：{_esc("；".join(report.get("advice_inputs", [])[:2]))}</div></div>')
    if report.get("questions"):
        q_html = "".join(
            f'<div class="q"><b>{_esc(q["text"])}</b><div class="choices">'
            + "".join(f'<button class="chipbtn" onclick="answer(\'{q["id"]}\',this.textContent)">{_esc(c)}</button>'
                      for c in (q.get("choices") or []))
            + f'</div><div style="margin-top:8px"><input type="text" id="free_{_esc(q["id"])}" placeholder="自由填写">'
              f'<div class="choices"><button class="chipbtn" onclick="answer(\'{q["id"]}\',document.getElementById(\'free_{_esc(q["id"])}\').value)">提交</button></div></div></div>'
            for q in report["questions"])
        cards.append(f'<div class="card"><h2>两个小问题（喂给洞察）</h2>{q_html}</div>')
    return "".join(cards)


def view_monitor(mon: dict, cov: dict) -> str:
    lvl_counts = mon.get("summary", {})
    f_html = _findings_html(mon.get("findings", []), limit=8)
    src = "".join(
        f'<li>{_esc(s["label"])}（{_esc(s["source"])}）：最后数据 {_esc(s["last_data_local"] or "—")}，'
        f'断更 {s["gap_days"] if s["gap_days"] is not None else "—"} 天'
        + ('<b class="lv-alert"> · 需提醒</b>' if s["notify"] else "") + "</li>"
        for s in cov.get("sources", []))
    return f'''<div class="card"><h1>监测</h1><div class="sub">{_esc(mon.get('local_date'))} · 免打扰 {mon.get('dnd_hours')[0]}:00–{mon.get('dnd_hours')[1]}:00（仅放就医级）</div>
<div class="muted">建议就医 {lvl_counts.get('see_doctor', 0)} · 提醒 {lvl_counts.get('alert', 0)} · 关注 {lvl_counts.get('notice', 0)}</div></div>
<div class="card"><h2>当前发现</h2><ul>{f_html}</ul><div class="muted" style="margin-top:8px">非诊断：全部为生活方式参考</div></div>
<div class="card"><h2>数据管道（分源核对）</h2><ul>{src}</ul>
<div class="muted" style="margin-top:8px">{_esc(cov.get('rule'))}</div></div>'''


def view_checkin(pool: list[dict], answered_today: list[str]) -> str:
    from .report import QUESTION_POOL
    items = []
    for q in pool or QUESTION_POOL:
        done = q["id"] in answered_today
        choices = "".join(
            f'<button class="chipbtn" onclick="answer(\'{q["id"]}\',this.textContent)">{_esc(c)}</button>'
            for c in (q.get("choices") or []))
        items.append(
            f'<div class="q"><b>{_esc(q["text"])}</b>' + (' <span class="badge">今日已答 ✓</span>' if done else "")
            + f'<div class="choices">{choices}</div>'
            + f'<div style="margin-top:8px"><input type="text" id="free_{_esc(q["id"])}" placeholder="自由填写">'
              f'<div class="choices"><button class="chipbtn" onclick="answer(\'{q["id"]}\',document.getElementById(\'free_{_esc(q["id"])}\').value)">提交</button></div></div></div>')
    note = next((q.get("note") for q in (pool or QUESTION_POOL) if q["id"] == "shower_time" and q.get("note")), None)
    return (f'<div class="card"><h1>打卡</h1><div class="sub">行为数据喂给周报的相关性分析</div>{"".join(items)}</div>'
            + (f'<div class="card"><div class="muted">ℹ️ {_esc(note)}</div></div>' if note else ""))


def view_relax(lib: dict, suggested: list[dict]) -> str:
    sug = {it["id"] for it in suggested}
    groups = []
    for cat in lib["categories"]:
        items = [it for it in lib["items"] if it["category"] == cat]
        if not items:
            continue
        rows = "".join(
            f'<label class="q" style="display:block"><input type="checkbox" value="{_esc(it["id"])}" '
            f'{"checked" if it["id"] in sug else ""}> <b>{_esc(it["title"])}</b>'
            f'<br><span class="muted">{_esc(it["category"])} · {it.get("duration_min", "—")} 分钟 · {_esc(it.get("source", ""))} '
            f'· 评分 👍{it["ratings"].get("good", 0)} 👎{it["ratings"].get("bad", 0)}</span></label>'
            for it in items)
        groups.append(f'<h2>{_esc(cat)}</h2>{rows}')
    plan_area = '<div id="plan"></div>'
    return f'''<div class="card"><h1>今晚放松</h1>
<div class="sub">挑内容组成今晚流程（按拉伸→呼吸→CBT→冥想→音频顺序执行）· 素材只找不改</div>
<div id="lib">{''.join(groups)}</div>
<div class="choices"><button onclick="makePlan()">组成今晚流程</button></div></div>
<div class="card"><h2>今晚流程</h2><div class="muted">还没生成——上面勾选后点按钮</div>{plan_area}</div>
<div class="card"><div class="muted">内容链接为搜索页/权威站点种子，精确官方嵌入由 P-Health 审定中（12-06 后逐步替换）。最后一段建议选可后台播放的音频。</div></div>'''


def _plan_item_html(it: dict, idx: int) -> str:
    embed = it.get("embed")
    media = (f'<div style="margin-top:8px">{_esc(embed)}</div>' if embed else "")
    return (f'<div class="q"><b>{idx + 1}. {_esc(it["title"])}</b>'
            f'<br><span class="muted">{_esc(it["category"])} · {it.get("duration_min", "—")} 分钟</span>{media}'
            f'<div class="choices"><a class="chipbtn" style="display:inline-block;text-decoration:none;padding:10px 16px" '
            f'href="{_esc(it["url"])}" target="_blank" rel="noopener">打开内容 ↗</a></div>'
            f'<div class="rate"><button class="g" onclick="rate(\'{it["id"]}\',\'good\')">好用 👍</button>'
            f'<button class="b" onclick="rate(\'{it["id"]}\',\'bad\')">不行 👎</button></div></div>')


def view_weekly(rep: dict) -> str:
    w = rep.get("window", {})
    corr = rep.get("correlation_candidates", [])
    corr_html = "".join(f'<li>{_esc(c["statement"])}</li>' for c in corr) or '<li class="muted">样本还在积累（每组至少 3 天、共 10 天才出候选）</li>'
    jetlag = rep.get("social_jetlag")
    jet = f'工作日中点 {jetlag["work_midpoint_h"]} 点 vs 周末 {jetlag["weekend_midpoint_h"]} 点，差 {jetlag["diff_h"]}h' if jetlag else "样本不足"
    strain_cmp = ""
    if w.get("strain_avg") is not None and w.get("strain_prior_avg") is not None:
        d = w["strain_avg"] - w["strain_prior_avg"]
        strain_cmp = f'（上周 {w["strain_prior_avg"]:.1f}，{"↑" if d >= 0 else "↓"}{abs(d):.1f}）'
    return f'''<div class="card"><h1>周报 · {_esc(rep.get('week_of'))} 起</h1>
<div class="sub">趋势与相关性 · 相关不等于因果 · {_esc(rep.get('generated_at'))}</div>
<ul>
<li>夜间睡眠均值 <b>{w.get('night_avg_h') or '—'}h</b>（{w.get('nights_n', 0)} 晚有数据）</li>
<li>HRV 均值 <b>{w.get('hrv_avg') or '—'} ms</b></li>
<li>步数合计 <b>{w.get('steps_total') or 0}</b></li>
<li>WHOOP 负荷均值 <b>{w.get('strain_avg') or '—'}</b>{_esc(strain_cmp)}</li>
<li>体重变化 <b>{w.get('weight_delta_kg') if w.get('weight_delta_kg') is not None else '—'} kg</b></li>
<li>睡眠规律指数 SRI <b>{rep.get('sri') or '—'}</b> / 100</li>
<li>社交时差：{_esc(jet)}</li>
</ul></div>
<div class="card"><h2>行为 × 结果（相关性候选）</h2><ul>{corr_html}</ul></div>'''


# ---------------------------------------------------------------- 完整页面
_PAGE_HEAD = f"""<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Pivis"><meta name="theme-color" content="#0a84ff">
<link rel="apple-touch-icon" href="/icon.png"><link rel="manifest" href="/manifest.webmanifest"><style>{_STYLE}</style>"""


def morning_page(report: dict) -> str:
    return (f'<!doctype html><html lang="zh"><head><title>晨报 {_esc(report.get("local_date"))}</title>'
            f'{_PAGE_HEAD}</head><body><div class="wrap">{view_today(report)}</div></body></html>')


def relax_page(lib: dict, suggested: list[dict]) -> str:
    body = view_relax(lib, suggested)
    return f'''<!doctype html><html lang="zh"><head><title>今晚放松</title>{_PAGE_HEAD}</head><body>
<div class="wrap">{body}</div>
<script>
async function makePlan() {{
  const ids = [...document.querySelectorAll('#lib input:checked')].map(i => i.value);
  const r = await fetch('/api/relax/plan', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{item_ids: ids}})}});
  const j = await r.json();
  const el = document.getElementById('plan');
  if (j.error) {{ el.innerHTML = '<div class="warn">' + j.message + '</div>'; return; }}
  el.parentElement.querySelector('.muted').style.display = 'none';
  el.innerHTML = j.plan.map((t, i) => {{}}).join('') || '';
  el.innerHTML = j.items.map((it, i) =>
    '<div class=\\"q\\"><b>' + (i + 1) + '. ' + it.title + '</b><br><span class=\\"muted\\">' + it.category +
    ' · ' + (it.duration_min || '—') + ' 分钟</span><div class=\\"choices\\"><a class=\\"chipbtn\\" style=\\"display:inline-block;text-decoration:none;padding:10px 16px\\" href=\\"' + it.url + '\\" target=\\"_blank\\" rel=\\"noopener\\">打开内容 ↗</a></div>' +
    '<div class=\\"rate\\"><button class=\\"g\\" onclick=\\"rate(\\'' + it.id + '\\',\\'good\\')\\">好用 👍</button>' +
    '<button class=\\"b\\" onclick=\\"rate(\\'' + it.id + '\\',\\'bad\\')\\">不行 👎</button></div></div>').join('');
}}
async function rate(id, rating) {{
  await fetch('/api/relax/rate', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{item_id: id, rating: rating}})}});
  location.href = '/relax';
}}
</script></body></html>'''


def weekly_page(rep: dict) -> str:
    return (f'<!doctype html><html lang="zh"><head><title>周报 {_esc(rep.get("week_of"))}</title>'
            f'{_PAGE_HEAD}</head><body><div class="wrap">{view_weekly(rep)}</div></body></html>')


def app_page() -> str:
    # /app 只保留到 /v2 的重定向（见 Handler.do_GET）；此函数留空壳防止误引用
    return ""


# ---------------------------------------------------------------- HTTP 服务
def _today_relax_plan(tools: HealthTools) -> dict | None:
    from datetime import date as _date
    today = _date.today().isoformat()
    for e in reversed(tools.subj.entries(kinds=["relax_plan"], since=_date.fromisoformat(today), until=_date.fromisoformat(today))):
        return e["payload"]
    return None


def _ensure_now_hero(page: str, doc: dict, components: list[dict]) -> list[dict]:
    """旧发布可能只有 quiet_note；结构层补 1 张 hero_status，保留 Agent 的文案与顺序。"""
    if page != "now" or any(c.get("type") == "hero_status" for c in components):
        return components
    from .layout import today_components
    hero = next((c for c in today_components(doc) if c.get("type") == "hero_status"), None)
    if hero is None:
        return components
    out: list[dict] = []
    inserted = False
    for c in components:
        out.append(c)
        if not inserted and c.get("type") == "headline":
            out.append(hero)
            inserted = True
    if not inserted:
        out.insert(0, hero)
    return out


def make_handler(cfg: Config, tools: HealthTools, v2=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False, indent=1, default=str).encode(),
                       "application/json; charset=utf-8")

        # ---------------- v3：主卡 + 生成式待办 ----------------
        def _v3_get(self, u, q) -> bool:
            from . import v3 as v3mod
            from .todos import TodoStore
            from urllib.parse import unquote
            if u.path.startswith("/media/sleep-audio/"):
                name = unquote(u.path.rsplit("/", 1)[-1])
                f = Path.home() / ".dsh/bot/workspace/sleep-audio" / name
                if "/" in name or not f.is_file():
                    self._json({"error": "not_found"}, 404)
                    return True
                data = f.read_bytes()
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].partition("-")
                    start = int(a or 0)
                    end = int(b) if b else len(data) - 1
                    chunk = data[start:end + 1]
                    self.send_response(206)
                    self.send_header("Content-Type", "audio/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.end_headers()
                    self.wfile.write(chunk)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                return True
            if u.path.startswith("/api/v3/page/"):
                self._json(v3mod.page_doc(tools, u.path.rsplit("/", 1)[-1]))
                return True
            if u.path.startswith("/api/v3/todo/"):
                t = TodoStore(cfg).get(u.path.rsplit("/", 1)[-1])
                self._json(t or {"error": "not_found"}, 200 if t else 404)
                return True
            if u.path == "/api/v3/clock":
                self._json({"now": tools._now().isoformat(timespec="seconds"), "sim": cfg.sim_mode})
                return True
            return False

        def _v3_post(self, u) -> None:
            from . import v3 as v3mod
            from .clock import set_now
            if u.path.startswith("/api/v3/todo/") and u.path.endswith("/photo"):
                n = int(self.headers.get("Content-Length") or 0)
                if n > 12 * 1024 * 1024:
                    self._json({"error": "too_large"}, 413)
                    return
                todo_id = u.path[len("/api/v3/todo/"):-len("/photo")]
                self._json(v3mod.save_photo(tools, todo_id, self.rfile.read(n)))
                return
            body = self._read_body_json() if int(self.headers.get("Content-Length") or 0) else {}
            if u.path.startswith("/api/v3/todo/"):
                self._json(v3mod.submit(tools, u.path.rsplit("/", 1)[-1], body))
            elif u.path == "/api/v3/clock":
                self._json({"now": set_now(cfg, str(body["now"])).isoformat(timespec="seconds")})
            else:
                self._json({"error": "not_found"}, 404)

        def _day_arg(self, q):
            return date.fromisoformat(q["date"][0]) if q.get("date") else None

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            d = self._day_arg(q)
            if u.path.startswith("/api/v3/") or u.path.startswith("/media/"):
                try:
                    if self._v3_get(u, q):
                        return
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": type(exc).__name__, "message": str(exc)}, 400)
                    return
            if u.path == "/app":
                self.send_response(302)
                self.send_header("Location", "/v2")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if u.path == "/v2" or u.path == "/v2/":
                self.send_response(302)
                self.send_header("Location", "/v2/now")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if u.path == "/v2/today":  # 旧入口兼容
                self.send_response(302)
                self.send_header("Location", "/v2/now")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if u.path == "/sw.js":
                from pathlib import Path as _P
                self._send(200, (_P(__file__).parent / "static" / "sw.js").read_bytes(),
                           "application/javascript; charset=utf-8")
                return
            if u.path.startswith("/install"):
                from pathlib import Path as _P
                import mimetypes as _mt
                root = _P(__file__).parent.parent / "install"
                rel = u.path[len("/install"):].lstrip("/") or "index.html"
                f = (root / rel).resolve()
                if not str(f).startswith(str(root.resolve())) or not f.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                ctype = _mt.guess_type(str(f))[0] or "application/octet-stream"
                if f.suffix in (".plist", ".html"):
                    # manifest/页面里的绝对地址跟随当前请求 Host（公网隧道/内网域名自适应）
                    host = (self.headers.get("Host") or u.netloc).encode()
                    body = f.read_bytes().replace(b"__HOST__", host)
                    self._send(200, body, "text/xml" if f.suffix == ".plist" else "text/html; charset=utf-8")
                    return
                elif f.suffix == ".ipa":
                    ctype = "application/octet-stream"
                self._send(200, f.read_bytes(), ctype)
                return
            if u.path == "/api/dsh-token":
                import re as _re2
                log_path = cfg.data_dir / "dshweb.log"
                token = None
                if log_path.exists():
                    tokens = _re2.findall(r"token=([A-Za-z0-9_-]+)", log_path.read_text(encoding="utf-8", errors="ignore"))
                    token = tokens[-1] if tokens else None
                self._json({"token": token})
                return
            if u.path == "/api/v2/push-key":
                import json as _j
                from pathlib import Path as _P2
                v = _P2.home() / ".dsh/bot/workspace/pivis-runtime/vapid.json"
                key = _j.loads(v.read_text())["publicKey"] if v.exists() else None
                self._json({"publicKey": key})
                return
            if u.path == "/static/pivis-ui.css":
                from pathlib import Path as _P
                css = (_P(__file__).parent / "static" / "pivis-ui.css").read_bytes()
                self._send(200, css, "text/css; charset=utf-8")
                return
            if u.path in ("/v2/now", "/v2/sleep", "/v2/sport", "/v2/stress"):
                from . import web_v2
                name = u.path.split("/")[-1]
                fn = {"now": v2.today, "sleep": v2.sleep, "sport": v2.sport, "stress": v2.stress}[name]
                renderer = {"now": web_v2.render_now, "sleep": web_v2.render_sleep,
                            "sport": web_v2.render_sport, "stress": web_v2.render_stress}[name]
                self._send(200, renderer(fn(d)).encode(), "text/html; charset=utf-8")
                return
            if u.path == "/v2/night":
                from .web_v2 import render_night
                self._send(200, render_night().encode(), "text/html; charset=utf-8")
                return
            if u.path == "/v2/weekly":
                from .web_v2 import render_weekly
                self._send(200, render_weekly(tools.weekly_report()).encode(), "text/html; charset=utf-8")
                return
            if u.path == "/v2/relax":
                from . import web_v2
                if q.get("exec"):
                    plan = _today_relax_plan(tools)
                    if not plan:
                        self._send(200, "今晚还没定计划".encode(), "text/html; charset=utf-8")
                        return
                    from . import content as content_mod
                    items = [content_mod.item_by_id(i) or {"title": t, "url": "", "category": "", "duration_min": ""}
                             for i, t in zip(plan["items"], plan["titles"])]
                    self._send(200, web_v2.render_relax_exec(items).encode(), "text/html; charset=utf-8")
                    return
                plan = _today_relax_plan(tools)
                bed = v2.sleep(d)["tonight"]["target"]["bedtime"]
                self._send(200, web_v2.render_relax(
                    tools.relax_library(), tools.relax_suggest()["suggested"], plan, bed).encode(),
                    "text/html; charset=utf-8")
                return
            if u.path == "/api/v2/relax":
                from .layout import apply_component_experience
                from .publications import PublicationStore, relax_document
                lib = relax_document(tools)
                record = PublicationStore(cfg).get("relax")
                lib["components"] = apply_component_experience(
                    "relax", lib, record["components"], cfg) if record else []
                lib["publication"] = {k: v for k, v in (record or {}).items() if k != "components"}
                self._json(lib)
                return
            if u.path.startswith("/api/v2/"):
                page = u.path.split("/")[-1]
                fn = {"now": v2.today, "today": v2.today,  # today = 兼容别名
                      "sleep": v2.sleep, "sport": v2.sport, "stress": v2.stress}.get(page)
                if not fn:
                    self._json({"error": "not_found"}, 404)
                    return
                doc = fn(d)
                from .layout import apply_component_experience
                from .publications import PublicationStore
                store_page = "now" if page == "today" else page
                record = PublicationStore(cfg).get(store_page)
                components = record["components"] if record else []
                components = _ensure_now_hero(store_page, doc, components)
                doc["components"] = apply_component_experience(page, doc, components, cfg)
                doc["publication"] = {k: v for k, v in (record or {}).items() if k != "components"}
                self._json(doc)
                return
            if u.path == "/dsh":
                # 直连入口：从 dshweb 日志读最新 token，302 到 P-Health 会话
                token = None
                try:
                    log = cfg.data_dir / "dshweb.log"
                    if log.exists():
                        import re as _re
                        m = None
                        for m in _re.finditer(r"token=([A-Za-z0-9_-]+)", log.read_text(encoding="utf-8", errors="ignore")):
                            pass
                        if m:
                            token = m.group(1)
                except OSError:
                    token = None
                if token:
                    self.send_response(302)
                    self.send_header(
                        "Location",
                        dsh_chat.DSH_WEB + "/?token=" + token
                        + "&session=" + dsh_chat.SESSION_MAIN,
                    )
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._send(200, "dsh web 未就绪，稍后刷新".encode(), "text/html; charset=utf-8")
                return
            try:
                if u.path == "/":
                    self._send(200, f'''<!doctype html><html lang="zh"><head>{_PAGE_HEAD}<title>pivis-health</title></head>
                    <body><div class="wrap"><div class="card"><h1>pivis health</h1>
                    <div class="muted">本地健康内核 · 只读客观库 + 确定性计算</div>
                    <ul><li><a href="/app">📱 手机客户端（PWA）</a></li>
                    <li><a href="/morning">晨报页</a> · <a href="/relax">今晚放松</a> · <a href="/weekly">周报</a></li>
                    <li><a href="/api/morning">晨报 JSON</a> · <a href="/api/monitor">监测</a> · <a href="/api/coverage">覆盖</a></li></ul>
                    </div></div></body></html>'''.encode(), "text/html; charset=utf-8")
                elif u.path == "/morning":
                    self._send(200, morning_page(tools.morning_report(d)).encode(), "text/html; charset=utf-8")
                elif u.path == "/relax":
                    self._send(200, relax_page(tools.relax_library(), tools.relax_suggest()["suggested"]).encode(),
                               "text/html; charset=utf-8")
                elif u.path == "/weekly":
                    self._send(200, weekly_page(tools.weekly_report(d)).encode(), "text/html; charset=utf-8")
                elif u.path == "/manifest.webmanifest":
                    self._send(200, json.dumps(MANIFEST).encode(), "application/manifest+json; charset=utf-8")
                elif u.path == "/icon.png":
                    self._send(200, ICON_PNG, "image/png")
                elif u.path == "/view/today":
                    self._send(200, view_today(tools.morning_report(d)).encode(), "text/html; charset=utf-8")
                elif u.path == "/view/monitor":
                    self._send(200, view_monitor(tools.monitor(d), tools.coverage()).encode(), "text/html; charset=utf-8")
                elif u.path == "/view/checkin":
                    from .report import QUESTION_POOL
                    today = date.today().isoformat()
                    answered = {e["payload"].get("question_id") for e in tools.subj.entries(
                        kinds=["behavior_answer", "subjective_sleep"],
                        since=date.fromisoformat(today), until=date.fromisoformat(today))}
                    self._send(200, view_checkin(QUESTION_POOL, answered).encode(), "text/html; charset=utf-8")
                elif u.path == "/view/relax":
                    self._send(200, view_relax(tools.relax_library(), tools.relax_suggest()["suggested"]).encode(),
                               "text/html; charset=utf-8")
                elif u.path == "/view/weekly":
                    self._send(200, view_weekly(tools.weekly_report(d)).encode(), "text/html; charset=utf-8")
                elif u.path == "/api/morning":
                    self._json(tools.morning_report(d))
                elif u.path == "/api/today":
                    self._json(tools.today(d))
                elif u.path == "/api/monitor":
                    self._json(tools.monitor(d))
                elif u.path == "/api/coverage":
                    self._json(tools.coverage())
                elif u.path == "/api/relax":
                    lib = tools.relax_library()
                    lib["suggested"] = tools.relax_suggest()["suggested"]
                    self._json(lib)
                elif u.path == "/api/chat":
                    after = q.get("after", [None])[0]
                    limit = int(q.get("limit", [20])[0])
                    session = q.get("session", [""])[0]
                    print(f"[chat-req] path={u.path} session={session!r} after={after!r}", flush=True)
                    self._json(tools.chat_history(limit, after, session))
                elif u.path == "/api/weekly":
                    self._json(tools.weekly_report(d))
                else:
                    self._json({"error": "not_found", "path": u.path}, 404)
            except Exception as exc:
                self._json({"error": type(exc).__name__, "message": str(exc)}, 500)

        def _read_body_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8")
            ctype = self.headers.get("Content-Type", "")
            if "application/json" in ctype:
                return json.loads(raw)
            return {k: v[0] for k, v in parse_qs(raw).items()}

        def do_POST(self):
            u = urlparse(self.path)
            if u.path.startswith("/api/v3/"):
                try:
                    self._v3_post(u)
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": type(exc).__name__, "message": str(exc)}, 400)
                return
            try:
                if u.path == "/api/v2/rating":
                    data = self._read_body_json()
                    kind = str(data.get("kind") or "")
                    if kind not in ("subj_energy", "subj_latency"):
                        raise ValueError("kind must be subj_energy|subj_latency")
                    score = int(data.get("score") or 0)
                    if not 1 <= score <= 5:
                        raise ValueError("score 1-5")
                    self._json(tools.log_subjective(kind, {"score": score}))
                elif u.path == "/api/v2/whoop_confirm":
                    data = self._read_body_json()
                    ok = bool(data.get("ok"))
                    reason = str(data.get("reason") or "")
                    payload = {"ok": ok}
                    if reason:
                        payload["reason"] = reason
                        payload["tag"] = "洗澡晚" if "洗澡" in reason else "想事" if ("想" in reason or "事" in reason) else "环境"
                    self._json(tools.log_subjective("whoop_confirm", payload))
                elif u.path == "/api/v2/push-sub":
                    data = self._read_body_json()
                    sub = data.get("sub") or {}
                    tools.subj.push_sub_add(str(sub.get("endpoint") or ""),
                                            str((sub.get("keys") or {}).get("p256dh") or ""),
                                            str((sub.get("keys") or {}).get("auth") or ""))
                    self._json({"ok": True})
                elif u.path == "/api/v2/apns-token":
                    data = self._read_body_json()
                    token = str(data.get("token") or "").strip()
                    if not token:
                        raise ValueError("token required")
                    env = str(data.get("env") or "development")
                    tools.subj.apns_token_save(token, env)
                    self._json({"ok": True, "tokens": len(tools.subj.apns_tokens_list())})
                elif u.path == "/api/v2/push-test":
                    key = self.headers.get("X-Push-Key") or ""
                    if not cfg.apns.get("push_key") or key != cfg.apns["push_key"]:
                        self._json({"error": "unauthorized"}, 401)
                        return
                    from .push import send_push
                    data = self._read_body_json()
                    result = send_push(
                        tools,
                        title=str(data.get("title") or "P-Health"),
                        body=str(data.get("body") or "推送测试"),
                        page=data.get("page"),
                        pending=data.get("pending"),
                        kind="push-test",
                    )
                    self._json(result)
                elif u.path == "/api/v2/need_feedback":
                    data = self._read_body_json()
                    ntype = str(data.get("need_type") or "")
                    action = str(data.get("action") or "")
                    if not ntype or action not in ("做了", "不做", "换一个", "今天算了"):
                        raise ValueError("need_type + action(做了/不做) required")
                    self._json(tools.need_feedback(ntype, action))
                elif u.path == "/api/v2/device-data":
                    data = self._read_body_json()
                    from . import ingest
                    device_id = str(data.get("device_id") or "iphone-native")[:64]
                    result = ingest.ingest_samples(Path(tools.cfg.vault_db),
                                                   list(data.get("samples") or []),
                                                   device_id)
                    for obs in list(data.get("observations") or [])[:50]:
                        kind = str(obs.get("kind") or "unknown")[:32]
                        payload = obs.get("data") if isinstance(obs.get("data"), dict) else {}
                        ingest.log_observation(
                            Path(tools.cfg.data_dir), kind, payload,
                            source=device_id,
                            event_id=(str(obs.get("event_id"))[:128] if obs.get("event_id") else None),
                            occurred_at=(str(obs.get("occurred_at") or obs.get("ts"))[:80]
                                         if obs.get("occurred_at") or obs.get("ts") else None))
                    self._json(result)
                elif u.path == "/api/v2/hero_skip":
                    data = self._read_body_json()
                    hero = str(data.get("hero") or "")
                    if not hero:
                        raise ValueError("hero required")
                    self._json(tools.log_subjective("hero_skip", {"hero": hero}))
                elif u.path == "/api/subjective":
                    data = self._read_body_json()
                    qid, ans = str(data.get("question_id") or ""), str(data.get("answer") or "")
                    if not qid or not ans:
                        raise ValueError("question_id and answer are required")
                    self._json(tools.answer_question(qid, ans))
                elif u.path == "/api/relax/plan":
                    data = self._read_body_json()
                    ids = data.get("item_ids") or []
                    if not isinstance(ids, list) or not ids:
                        raise ValueError("item_ids (non-empty list) required")
                    result = tools.relax_plan_save([str(i) for i in ids])
                    from .publications import publish_page
                    try:
                        record = publish_page(tools, "relax", timeout=180)
                        result["components"] = record["components"]
                        result["publication"] = {k: v for k, v in record.items() if k != "components"}
                    except Exception as publish_exc:
                        result["publish_error"] = str(publish_exc)
                    self._json(result)
                elif u.path == "/api/chat/send":
                    data = self._read_body_json()
                    text = str(data.get("text") or "")
                    if not text.strip():
                        raise ValueError("text required")
                    context = str(data.get("context") or "")
                    self._json(tools.chat_send(text, context))
                elif u.path == "/api/relax/rate":
                    data = self._read_body_json()
                    self._json(tools.content_rate(str(data.get("item_id") or ""),
                                                  str(data.get("rating") or "")))
                else:
                    self._json({"error": "not_found"}, 404)
            except Exception as exc:
                self._json({"error": type(exc).__name__, "message": str(exc)}, 400)

    return Handler


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8943,
          tls_cert: str | None = None, tls_key: str | None = None) -> None:
    tools = HealthTools(cfg)
    from .pages import V2Pages
    make_handler_v2 = __import__("pivis_health.web_v2", fromlist=["x"])
    handler = make_handler(cfg, tools, V2Pages(tools))
    httpd = ThreadingHTTPServer((host, port), handler)
    if tls_cert and tls_key:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tls_cert, tls_key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(json.dumps({"serving": f"http://{host}:{port}", "app": f"http://{host}:{port}/v2"}, ensure_ascii=False))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
