"""v2 Web 层 · Less is More 版。

原则：每个数字有标签，每个结论有一句依据，多余的字段/脚注/徽章全部删。
交互：底部胶囊栏（板块导航 + 右侧独立 P 入口）；对话 = 底部抽屉（86% 高度，
背景模糊遮罩，可下滑关闭，不切页面）。抽屉内支持生成式 UI（```phealth-ui）。
四页数据全部来自 V2Pages（真实 WHOOP/Apple/主观库）。
"""
from __future__ import annotations

from . import pv_charts as PC

NAV = [("now", "现在"), ("sleep", "休息"), ("sport", "运动"), ("stress", "压力")]
# 进入对话抽屉时带给 Bot 的上下文（"现在" 页 = 主会话，无标签）
CTX = {"now": "", "sleep": "休息", "sport": "运动", "stress": "压力"}
NAV_DICT = dict(NAV)

HEAD = ('''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Pivis">
<meta name="theme-color" content="#0F1217">
<title>__TITLE__ · pivis</title>
<link rel="stylesheet" href="/static/pivis-ui.css">
<style>body{margin:0}a{color:#9DB4FF}</style>
<script>
if('serviceWorker' in navigator && location.protocol==='https:'){
navigator.serviceWorker.register('/sw.js').then(function(r){return r.pushManager.getSubscription()}).then(function(s){
if(s)return s;
return fetch('/api/v2/push-key').then(function(r){return r.json()}).then(function(j){
if(!j.publicKey)return null;
var raw=atob(j.publicKey.replace(/-/g,'+').replace(/_/g,'/')),a=new Uint8Array(raw.length);
for(var i=0;i<raw.length;i++)a[i]=raw.charCodeAt(i);
return navigator.serviceWorker.ready.then(function(r2){return r2.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:a.buffer})})})})
.then(function(s){if(!s)return;return fetch('/api/v2/push-sub',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sub:s.toJSON()})})})
.catch(function(e){})}
</script></head><body>''')

# 底部栏：左侧板块胶囊导航，右侧独立 P 对话入口（全局主会话）
TABBAR = ('''
<div class="pv-tabbar">
<div class="pv-tab-pills" role="tablist">__PILLS__</div>
<button class="pv-p-btn" aria-label="P-Health 对话" onclick="chatOpen('__CTX__')">P</button>
</div>
<div id="drawer-mask" onclick="chatClose()"></div>
<div id="drawer" class="pv-root">
<div id="drawer-bar">
<div class="pv-grabber"></div>
<b id="drawer-title" style="font-size:16px">P-Health</b>
<button onclick="chatClose()" style="border:0;background:none;color:var(--pv-text-2);font-size:14px;padding:4px 8px">收起</button>
</div>
<div id="drawer-msgs"></div>
<div id="drawer-input">
<label><input id="drawer-in" type="text" placeholder="说…" onkeydown="if(event.key==='Enter')drawerSend()"></label>
<button onclick="drawerSend()" style="min-width:40px;height:40px;border-radius:20px;border:0;background:var(--pv-accent);color:var(--pv-accent-ink);font-weight:700">→</button>
</div>
</div>
<script>
var pollTimer=null, chatCtx='', seenMsgs={};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function b(r,t){var m=r==='me';
return '<div style="display:flex;justify-content:'+(m?'flex-end':'flex-start')+';margin:3px 0">'+
'<div style="max-width:82%;border-radius:14px;padding:8px 12px;font-size:14px;line-height:1.45;'+
'background:'+(m?'var(--pv-accent)':'var(--pv-card)')+
';color:'+(m?'var(--pv-accent-ink)':'var(--pv-text)')+';white-space:pre-wrap">'+esc(t)+'</div></div>'}
/* ---- 生成式 UI：解析 ```phealth-ui 代码块，失败回退纯文本 ---- */
function parseGen(t){
var out=[],re=/```phealth-ui\\s*([\\s\\S]*?)```/g,m,last=0;
while((m=re.exec(t))){
if(m.index>last&&t.slice(last,m.index).trim())out.push({k:'text',v:t.slice(last,m.index)});
try{out.push({k:'card',v:JSON.parse(m[1])})}catch(e){out.push({k:'text',v:m[0]})}
last=m.index+m[0].length}
if(last<t.length&&t.slice(last).trim())out.push({k:'text',v:t.slice(last)});
return out}
function genWrap(title,desc,inner){
return '<div class="pv-gen">'+(title?'<div class="pv-gen-title">'+esc(title)+'</div>':'')
+(desc?'<div class="pv-sub">'+esc(desc)+'</div>':'')+inner+'</div>'}
function cardHTML(c){
var t=c.type||'';
if(t==='options'){
var opts=(c.options||[]).map(function(o){
var id=esc(o.id||o.label),lb=o.label||'';
return '<button class="pv-btn" data-gen="'+id+'" style="justify-content:flex-start;text-align:left;height:auto;min-height:36px;padding:8px 12px;flex:1">'+esc(lb)
+(o.hint?'<span class="pv-sub" style="margin-left:8px">'+esc(o.hint)+'</span>':'')+'</button>'}).join('');
return genWrap(c.title,c.description,'<div class="pv-btn-row" style="flex-direction:column;align-items:stretch">'+opts+'</div>')}
if(t==='plan'){
var steps=(c.steps||[]).map(function(s,i){
var link=s.url?'<a class="pv-link" style="margin-left:auto" href="'+esc(s.url)+'" target="_blank" rel="noopener">打开 ↗</a>':'';
return '<div class="pv-check"><span>'+(i+1)+'. '+esc(s.title||'')+'</span>'
+(s.duration_min?'<span class="pv-check-v">'+esc(s.duration_min)+'′</span>':'')+link+'</div>'}).join('');
var btns='<div class="pv-btn-row"><button class="pv-btn pv-primary" onclick="genAct(\\'confirm\\')">'+esc(c.confirm_label||'就这套')+'</button>'
+'<button class="pv-btn" onclick="genAct(\\'adjust\\')">调整</button></div>';
return genWrap(c.title,c.description,'<div class="pv-checks">'+steps+'</div>'+btns)}
if(t==='rating'){
var n=c.scale||5,chips='';
for(var i=1;i<=n;i++)chips+='<button class="pv-chip" onclick="genAct(\\'rate:'+i+'\\')">'+i+'</button>';
return genWrap(c.title,c.description,'<div class="pv-rating">'+chips+'</div>')}
if(t==='confirm'){
return genWrap(c.title,c.description,'<div class="pv-btn-row">'
+'<button class="pv-btn pv-primary" onclick="genAct(\\'yes\\')">'+esc(c.yes||'对')+'</button>'
+'<button class="pv-btn" onclick="genAct(\\'no\\')">'+esc(c.no||'不对')+'</button></div>')}
return ''}
function msgHTML(m){
if(m.role!=='phealth')return b(m.role,m.text);
return parseGen(m.text).map(function(seg){
return seg.k==='text'?b('phealth',seg.v)
:'<div style="display:flex;justify-content:flex-start;margin:3px 0"><div style="max-width:86%;min-width:60%">'+cardHTML(seg.v)+'</div></div>'}).join('')}
function chatClose(){var d=document.getElementById('drawer'),mk=document.getElementById('drawer-mask');
d.style.transform='translateY(100%)';mk.style.opacity='0';
setTimeout(function(){d.style.display='none';mk.style.display='none'},250);
if(pollTimer){clearInterval(pollTimer);pollTimer=null}}
function chatOpen(ctx){chatCtx=ctx||'';
document.getElementById('drawer-title').textContent=chatCtx?('P-Health · '+chatCtx):'P-Health';
var d=document.getElementById('drawer'),mk=document.getElementById('drawer-mask');
mk.style.display='block';d.style.display='flex';
requestAnimationFrame(function(){mk.style.opacity='1';d.style.transform='translateY(0)'});
chatLoad();if(pollTimer)clearInterval(pollTimer);pollTimer=setInterval(chatPoll,4000)}
async function chatLoad(){try{
var r=await fetch('/api/chat?limit=15'),j=await r.json(),el=document.getElementById('drawer-msgs');
var m=j.messages||j.mirror||[];seenMsgs={};
el.innerHTML=m.map(function(x){seenMsgs[x.role+'|'+(x.time||'')+'|'+x.text.substring(0,24)]=1;return msgHTML(x)}).join('');
el.scrollTop=el.scrollHeight}catch(e){}}
async function chatPoll(){try{
var r=await fetch('/api/chat?limit=3'),j=await r.json(),el=document.getElementById('drawer-msgs');
(j.messages||[]).forEach(function(m){
var k=m.role+'|'+(m.time||'')+'|'+m.text.substring(0,24);
if(!seenMsgs[k]){seenMsgs[k]=1;el.insertAdjacentHTML('beforeend',msgHTML(m))}});
el.scrollTop=el.scrollHeight}catch(e){}}
function drawerSend(){var q=document.getElementById('drawer-in').value.trim();if(!q)return;
document.getElementById('drawer-in').value='';drawerSendText(q)}
async function drawerSendText(t){
var el=document.getElementById('drawer-msgs');
el.insertAdjacentHTML('beforeend',b('me',t));el.scrollTop=el.scrollHeight;
var payload={text:t};if(chatCtx)payload.context=chatCtx;
try{var r=await fetch('/api/chat/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
var j=await r.json();
if(!j.ok)el.insertAdjacentHTML('beforeend','<div style="color:var(--pv-text-2);font-size:12px;text-align:center;padding:4px">'+(j.message||'发送失败')+'</div>')}
catch(e){el.insertAdjacentHTML('beforeend','<div style="color:var(--pv-text-2);font-size:12px;text-align:center">网络错误</div>')}
el.scrollTop=el.scrollHeight}
function genAct(id){
var t=String(id);
if(t==='')return;
if(t.indexOf('rate:')===0)t='评分：'+t.slice(5);
else if(t==='confirm')t='确认这套方案';
else if(t==='adjust')t='帮我调整这套方案';
else if(t==='yes')t='对';
else if(t==='no')t='不对';
drawerSendText(t)}
document.addEventListener('click',function(e){var el=e.target&&e.target.closest?e.target.closest('[data-gen]'):null;if(el)genAct(el.getAttribute('data-gen'))});
(function(){var bar=document.getElementById('drawer-bar'),d=document.getElementById('drawer'),sy=0,dy=0;
bar.addEventListener('touchstart',function(e){sy=e.touches[0].clientY;dy=0;d.style.transition='none'},{passive:true});
bar.addEventListener('touchmove',function(e){dy=e.touches[0].clientY-sy;if(dy>0)d.style.transform='translateY('+dy+'px)'},{passive:true});
bar.addEventListener('touchend',function(){d.style.transition='';if(dy>60)chatClose();else d.style.transform='translateY(0)'})})();
async function rating(k,s){await fetch('/api/v2/rating',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:k,score:s})});location.reload()}
async function needAction(t,a){await fetch('/api/v2/need_feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({need_type:t,action:a})});location.reload()}
async function confirmWhoop(ok){var r=document.getElementById('c19r')?document.getElementById('c19r').value:'';await fetch('/api/v2/whoop_confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ok:ok,reason:r})});location.reload()}
</script></body></html>''')


def _page(name: str, headline: str, body: str) -> str:
    pills = ""
    for k, v in NAV:
        cur = ' aria-current="page"' if k == name else ""
        pills += f'<button{cur} role="tab" onclick="location.href=\'/v2/{k}\'">{v}</button>'
    return (HEAD.replace("__TITLE__", NAV_DICT.get(name, name))
            + '<div class="pv-root" style="min-height:100vh;padding-bottom:96px">'
            + '<div class="pv-page-body" style="padding-top:18px">'
            + '<div class="pv-headline"><span class="pv-avatar" aria-hidden="true">P</span>'
            + f'<div><h1>{headline}</h1></div></div>{body}</div>'
            + TABBAR.replace("__PILLS__", pills).replace("__CTX__", CTX.get(name, ""))
            + "</div>")


def _tile(eyebrow: str, value: str, attn: bool = False, sub: str = "", unit: str = "") -> str:
    cls = "pv-tile-value" + (" pv-is-attn" if attn else "")
    u = f'<span class="pv-unit">{unit}</span>' if unit else ""
    s = f'<p class="pv-tile-sub">{sub}</p>' if sub else ""
    return (f'<div class="pv-card pv-tight"><p class="pv-eyebrow">{eyebrow}</p>'
            f'<p class="{cls}">{value}{u}</p>{s}</div>')


def _tiles_grid(tiles: list[str]) -> str:
    return ('<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px">'
            + "".join(tiles) + "</div>")


# ══════════ 现在 ══════════
def render_now(p: dict) -> str:
    hero = p["hero"]
    rng = hero["range"]
    dev = hero["deviation"]
    band = (rng["low"], rng["high"]) if rng.get("ready") else None
    spark = PC.spark_band([x["value"] for x in hero["spark"]], band)

    if hero["value"] is None:
        num = '<span style="font-size:36px;color:var(--pv-text-2)">数据不足</span>'
        meter = sub = ""
    else:
        attn = " pv-is-attn" if dev.get("state") == "below" else ""
        num = f'<span class="pv-hero-num{attn}">{hero["value"]:.0f}<span class="pv-unit">{hero.get("unit", "%")}</span></span>'
        if rng.get("ready"):
            lo, hi = rng["low"], rng["high"]
            pct = max(0, min(100, hero["value"] / (hi * 1.15) * 100))
            meter = (f'<div class="pv-meter{" pv-is-attn" if dev.get("state")=="below" else ""}">'
                     f'<div class="pv-meter-fill" style="width:{pct:.0f}%"></div>'
                     f'<span class="pv-meter-tick" style="left:{lo/(hi*1.15)*100:.0f}%"></span>'
                     f'<span class="pv-meter-tick" style="left:{hi/(hi*1.15)*100:.0f}%"></span></div>')
            st = "偏低" if dev.get("state") == "below" else ("偏高" if dev.get("state") == "high" else "范围内")
            sub = f'<span>{st}</span><span class="pv-sub">{lo:.0f}–{hi:.0f}</span>'
        else:
            meter = f'<div class="pv-learning" style="min-height:28px;padding:4px">{rng["learning_days"]}天</div>'
            sub = '<span class="pv-sub">学习范围中</span>'

    rc = p.get("rating_card") or {}
    rating_html = ""
    rows = []
    if not rc.get("energy_done"):
        rows.append(("subj_energy", "醒来精神？"))
    if rc.get("ask_latency_today") and not rc.get("latency_done"):
        rows.append(("subj_latency", "入睡难度？"))
    for kind, q in rows:
        rating_html += (f'<div class="pv-card pv-tight"><p class="pv-eyebrow">{q}</p>'
                        '<div class="pv-rating" style="margin-top:4px">'
                        + "".join(f'<button class="pv-chip" onclick="rating(\'{kind}\',{i})">{i}</button>' for i in range(1, 6))
                        + "</div></div>")

    needs_html = ""
    if p["needs"]:
        for n in p["needs"]:
            needs_html += f"""
<article class="pv-card pv-mid pv-need"{' style="box-shadow:inset 0 0 0 1.5px var(--pv-attn)"' if n.get('top') else ''}>
<h3>{n["action"]}</h3>
<p class="pv-sub">{n["evidence"]}</p>
<div class="pv-btn-row" style="margin-top:6px">
<button class="pv-btn pv-primary" onclick="needAction('{n["need_type"]}','做了')">做了</button>
<button class="pv-btn" onclick="needAction('{n["need_type"]}','换一个')">换</button>
<button class="pv-btn" onclick="needAction('{n["need_type"]}','今天算了')">算了</button>
</div></article>"""
    else:
        needs_html = '<p class="pv-sub" style="padding:8px 4px">今天照常就好</p>'

    body = f"""
<section class="pv-card" style="display:flex;flex-direction:column;gap:8px">
<div style="display:flex;justify-content:space-between;align-items:flex-end">
<div><p class="pv-eyebrow">恢复</p><p style="margin:0">{num}</p></div>{spark or ''}
</div>{meter}
<div style="display:flex;justify-content:space-between;font-size:12px;color:var(--pv-text-2)">{sub}</div>
</section>
{rating_html}{needs_html}"""
    return _page("now", p["headline"], body)


render_today = render_now  # 兼容旧导入


# ══════════ 休息 ══════════
def render_sleep(p: dict) -> str:
    t = p["tiles"]
    lat = t["latency"]
    hq = t["hq"]
    debt = t["debt"]
    lat_v = f'{lat["mean"]:.1f}' if lat["mean"] is not None else "—"
    hq_v = str(hq["score"]) if hq["score"] is not None else "—"
    debt_v = f'{debt["debt_h"]:.1f}' if debt else "—"

    tiles = _tiles_grid([
        _tile("入睡", lat_v),
        _tile("高质量", hq_v, attn=(hq["score"] or 0) >= 4, sub=f'{hq["nights_pass"]}/{hq["n_nights"]}'),
        _tile("债", debt_v, attn=bool(debt and debt["debt_h"] > 3), unit="h"),
    ])

    chart = PC.bars_need(p["chart14"])
    tn = p["tonight"]
    tgt = tn.get("target") or {}
    bed = tgt.get("bedtime", "—")
    caf = f' · 咖啡因 {tn["caffeine_cutoff"]}' if tn.get("caffeine_cutoff") else ""

    if tn.get("plan_set_today"):
        plan = ('<div class="pv-btn-row"><button class="pv-btn pv-lg pv-primary pv-block" '
                'onclick="location.href=\'/v2/relax?exec=1\'">开始放松</button>'
                '<button class="pv-btn pv-lg" onclick="location.href=\'/v2/relax\'">换</button></div>')
    else:
        plan = ('<button class="pv-btn pv-lg pv-primary pv-block" '
                'onclick="location.href=\'/v2/relax\'">定今晚放松</button>')

    wc = p.get("whoop_confirm") or {}
    confirm = ""
    if wc.get("pending") and wc.get("claim"):
        confirm = (f'<div class="pv-card pv-tight"><p style="font-size:13px">{wc["claim"]}</p>'
                   '<div class="pv-btn-row" style="margin-top:4px">'
                   '<button class="pv-btn pv-primary" onclick="confirmWhoop(true)">对</button>'
                   '<button class="pv-btn" onclick="confirmWhoop(false)">不对</button></div>'
                   '<input id="c19r" class="pv-input" style="height:32px;font-size:13px;margin-top:4px" placeholder="原因…"></div>')

    big = (f'<section class="pv-card pv-mid"><p class="pv-eyebrow">今晚</p>'
           f'<div class="pv-plan-head"><b style="font-size:22px">{bed} 上床</b>'
           f'<span class="pv-sub">{caf}</span></div>{plan}</section>')

    details = (f'<details class="pv-card pv-details"><summary>近 14 晚依据</summary>'
               f'<div style="margin-top:8px">{chart}</div>'
               f'<p class="pv-footnote">{p["on_time"]["label"]}</p></details>')

    return _page("sleep", p.get("headline", ""), big + tiles + confirm + details)


# ══════════ 运动 ══════════
def render_sport(p: dict) -> str:
    band = p["band"]
    rng = band["range"]
    band_t = (rng["low"], rng["high"]) if rng.get("ready") else None
    chart = PC.band_dots(
        [{"date": x["date"], "value": x["value"]} for x in band["series"]],
        band_t, events=band.get("markers") or [], event_row=True)

    s = p["tiles"]
    play = p["play"]
    vc = "var(--pv-attn)" if play["verdict"] in ("不宜", "可以但轻一点") else "var(--pv-good)"
    checks = "".join(
        f'<div class="pv-check"><span style="color:{_cc(c)}">{_cm(c)}</span>'
        f'<span>{c["name"]}</span><span class="pv-check-v">{c["value"]}</span></div>'
        for c in play["checks"])

    big = (f'<section class="pv-card pv-mid"><div class="pv-verdict" style="color:{vc}">{play["verdict"]}运动</div>'
           f'<div class="pv-checks" style="margin-top:6px">{checks}</div></section>')

    tiles = _tiles_grid([
        _tile("本周", str(s["sessions"]["done"]), sub=f'/{s["sessions"]["quota"]}'),
        _tile("负荷", f'{s["load"]["used"]:.0f}', sub=f'/{s["load"]["budget"]:.0f}'),
        _tile("回范围", str(s["days_to_range"]["value"] or "—"), sub="天"),
    ])

    rng_txt = f'{rng["low"]:.0f}–{rng["high"]:.0f}%' if rng.get("ready") else (rng.get("label") or "学习范围中")
    details = (f'<details class="pv-card pv-details"><summary>恢复走势 · 近 28 天</summary>'
               f'<div style="margin-top:8px">{chart}</div>'
               f'<p class="pv-footnote">个人范围 {rng_txt}</p></details>')

    return _page("sport", f'{play["verdict"]}运动', big + tiles + details)


def _cc(c):
    return "var(--pv-good)" if c.get("pass") is True else ("var(--pv-text-2)" if c.get("pass") is None else "var(--pv-attn)")

def _cm(c):
    return "✓" if c.get("pass") is True else ("—" if c.get("pass") is None else "✗")


# ══════════ 压力 ══════════
def render_stress(p: dict) -> str:
    band = p["band"]
    rng = band["range"]
    series = band["series"]
    band_t = (rng["low"], rng["high"]) if rng.get("ready") else None
    chart = PC.band_dots(
        [{"date": x["date"], "value": x["value"]} for x in series],
        band_t, h=122, y_ticks=[band_t[0], band_t[1]] if band_t else None)

    hrv_latest = next((x["value"] for x in reversed(series) if x["value"] is not None), None)
    out_n = len(band.get("out_points") or [])
    ws = p["work_signals"]

    ws_v, ws_sub = "—", ""
    if ws.get("available"):
        d = ws["data"]
        ws_v = str(d.get("meeting_hours") or "—")
        ws_sub = f'会议 h · 深夜 {d.get("late_online") or "—"} 晚 · 连续 {d.get("meeting_blocks_2h") or "—"}'
    else:
        ws_v, ws_sub = "未接入", (ws.get("label") or "")

    if rng.get("ready"):
        rng_v = f'{rng["low"]:.0f}'
        rng_sub = f'–{rng["high"]:.0f} · {"跌出 " + str(out_n) + " 天" if out_n else "范围内"}'
    else:
        rng_v = "—"
        rng_sub = rng.get("label") or "学习范围中"

    tiles = _tiles_grid([
        _tile("HRV", f'{hrv_latest:.0f}' if hrv_latest is not None else "—", unit="ms"),
        _tile("个人范围", rng_v, attn=bool(out_n), sub=rng_sub),
        _tile("工作信号", ws_v, sub=ws_sub),
    ])

    sug = p.get("suggestion") or {}
    if sug.get("title"):
        big = (f'<section class="pv-card pv-mid"><b style="font-size:15px">{sug["title"]}</b>'
               f'<p class="pv-sub">{sug.get("reason", "")}</p>'
               '<div class="pv-btn-row" style="margin-top:6px">'
               '<button class="pv-btn pv-primary" onclick="needAction(\'stress_suggest\',\'做了\')">好</button>'
               '<button class="pv-btn" onclick="needAction(\'stress_suggest\',\'今天算了\')">不</button></div></section>')
    else:
        state = f'HRV 近 14 天 {"跌出 " + str(out_n) + " 天" if out_n else "稳定"}'
        big = (f'<section class="pv-card pv-mid"><b style="font-size:15px">{state}</b>'
               f'<p class="pv-sub">{sug.get("note") or "暂无需要处理的压力信号"}</p></section>')

    details = (f'<details class="pv-card pv-details"><summary>HRV 走势 · 近 14 天</summary>'
               f'<div style="margin-top:8px">{chart}</div>'
               f'<p class="pv-footnote">相关≠因果</p></details>')

    return _page("stress", "守住 HRV", big + tiles + details)


# ══════════ 放松 / 夜间 / 周报 ══════════
_STEP_MAP = [("拉伸", ["拉伸"]), ("呼吸/CBT", ["呼吸", "CBT-I"]), ("音频", ["冥想", "音频"])]


def render_relax(lib, suggested, plan_today, bed):
    sug = {it["id"] for it in suggested}
    steps = ""
    for si, (title, cats) in enumerate(_STEP_MAP):
        opts = ""
        for it in lib["items"]:
            if it["category"] not in cats:
                continue
            on = "checked" if it["id"] in sug else ""
            opts += (f'<label class="pv-option"><input type="checkbox" name="s{si}" value="{it["id"]}" {on} style="display:none">'
                     f'<span class="pv-opt-main"><span class="pv-opt-title">{it["title"]}</span></span>'
                     f'<span class="pv-opt-min">{it.get("duration_min","—")}′</span><span class="pv-radio"></span></label>')
        steps += f'<div><p class="pv-section-label">{title}</p><div class="pv-options">{opts}</div></div>'

    plan_html = ""
    if plan_today:
        rows = "".join(f'<li>{t}</li>' for t in plan_today.get("titles", []))
        plan_html = (f'<section class="pv-card"><ul class="pv-player-list" style="margin-top:4px">{rows}</ul>'
                     '<button class="pv-btn pv-lg pv-primary pv-block" style="margin-top:8px" '
                     'onclick="location.href=\'/v2/relax?exec=1\'">开始</button></section>')

    body = (steps
            + '<button class="pv-btn pv-lg pv-primary" style="width:100%;margin-top:4px" onclick="makePlan()">定了</button>'
            + plan_html)
    return (_page("sleep", "今晚放松", body)
            + "<script>async function makePlan(){"
              "const ids=[...document.querySelectorAll('.pv-option input:checked')].map(i=>i.value);"
              "const r=await fetch('/api/relax/plan',{method:'POST',headers:{'Content-Type':'application/json'},"
              "body:JSON.stringify({item_ids:ids})});if(r.ok)location.reload();else alert('选至少一项')}</script>")


def render_relax_exec(items):
    rows = ""
    for i, it in enumerate(items):
        link = f'<a class="pv-link" href="{it.get("url","")}" target="_blank" rel="noopener">打开 ↗</a>' if it.get("url") else ""
        rows += (f'<div class="pv-card"><b>{i+1}. {it.get("title","")}</b>'
                 f'<div class="pv-btn-row" style="margin-top:6px">{link}'
                 f'<button class="pv-btn pv-primary" onclick="rate(\'{it.get("id","")}\',\'good\')">👍</button>'
                 f'<button class="pv-btn" onclick="rate(\'{it.get("id","")}\',\'bad\')">👎</button></div></div>')
    return (_page("sleep", "执行", rows or '<p class="pv-sub">计划为空</p>')
            + "<script>async function rate(id,r){await fetch('/api/relax/rate',{method:'POST',"
              "headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:id,rating:r})});"
              "location.href='/v2/relax?exec=1'}</script>")


def render_night():
    body = ('<div class="pv-card"><b>夜里醒了？</b></div>'
            '<div class="pv-options">'
            '<a class="pv-option" href="/v2/relax?exec=1"><span class="pv-opt-main"><b>呼吸</b></span><span class="pv-opt-min">6′</span></a>'
            '<a class="pv-option" href="/v2/relax?exec=1"><span class="pv-opt-main"><b>白噪音</b></span><span class="pv-opt-min">30′</span></a>'
            '<a class="pv-option" href="/v2/relax"><span class="pv-opt-main"><b>忧虑清空</b></span></a></div>')
    return _page("sleep", "夜间", body)


def render_weekly(p):
    w = p.get("window", {})
    corr = p.get("correlation_candidates", [])
    ch = "".join(f'<li class="pv-sub">{c["statement"]}</li>' for c in corr)
    body = (f'<section class="pv-card"><p class="pv-sub">睡眠 {w.get("night_avg_h") or "—"}h · '
            f'HRV {w.get("hrv_avg") or "—"} · 负荷 {w.get("strain_avg") or "—"} · '
            f'体重 {w.get("weight_delta_kg") or "—"}kg</p></section>'
            + (f'<section class="pv-card"><b>行为×结果</b><ul style="margin:6px 0 0;padding-left:16px">{ch}</ul></section>' if ch else ""))
    return _page("now", "周报", body)
