from char import char, eye
G='stroke:#555'
def C(x,y,s,inner,cls='',rot=0):
    r=f' rotate({rot})' if rot else ''
    return f'<g transform="translate({x} {y}) scale({s}){r}"><g class="{cls}">{inner}</g></g>' if cls else f'<g transform="translate({x} {y}) scale({s}){r}">{inner}</g>'
H=lambda x,y,r=2.8: f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff"/>'
# arms in character units (shoulders L≈(-44,12) R≈(40,11); raised from L(-47,0) R(40,-9))
UP_L=f'<g class="q-armL"><path class="q" d="M-47,-1 q-8,-3 -9,-15"/>{H(-56,-17)}</g>'
UP_R=f'<g class="q-armR"><path class="q" d="M40,-8 q9,-2 10,-14"/>{H(50,-23)}</g>'
DOWN_L=f'<path class="q" d="M-44,12 q-6,3 -6,10"/>{H(-50,23)}'
DOWN_R=f'<path class="q" d="M40,11 q6,3 6,10"/>{H(46,22)}'
HOLD=f'<path class="q" d="M-44,12 q3,12 22,15"/>{H(-21,27)}<path class="q" d="M40,11 q-1,12 -17,16"/>{H(22,27)}'
GROUND='<path class="q" style="stroke:#555" d="M14 102 H106"/>'
def sparkle(x,y,s=1,cls='q-tw'):
    return f'<path class="{cls}" fill="#fff" d="M{x},{y-5*s} Q{x+1*s},{y-1*s} {x+5*s},{y} Q{x+1*s},{y+1*s} {x},{y+5*s} Q{x-1*s},{y+1*s} {x-5*s},{y} Q{x-1*s},{y-1*s} {x},{y-5*s} Z"/>'
def heart(x,y,s=1,fill='#fff',cls=''):
    c=f' class="{cls}"' if cls else ''
    return f'<path{c} d="M{x},{y+4*s} C{x-6*s},{y} {x-4.6*s},{y-5*s} {x},{y-2.2*s} C{x+4.6*s},{y-5*s} {x+6*s},{y} {x},{y+4*s} Z" fill="{fill}"/>'

S=[]
def add(row,name,when,svg): S.append(dict(row=row,name=name,when=when,svg=svg))

# ---------- 作息
add('作息','早安','早上第一条',
  '<circle class="q" cx="94" cy="28" r="9"/><g class="q-pulse"><path class="q" d="M94 12 V8 M94 44 V48 M78 28 H74 M110 28 H114 M82.7 16.7 80 14 M105.3 16.7 108 14 M82.7 39.3 80 42 M105.3 39.3 108 42"/></g>'
  + GROUND + C(56,80,.8, char('happy','open',arms=UP_L+UP_R),'q-bob'))
add('作息','晒晒太阳','叫你早上出门见光',
  '<g class="q-spin" style="transform-origin:26px 26px"><path class="q" d="M26 10 V6 M26 42 V46 M10 26 H6 M42 26 H46 M14.7 14.7 12 12 M37.3 14.7 40 12 M14.7 37.3 12 40 M37.3 37.3 40 40"/></g><circle class="q" cx="26" cy="26" r="9"/>'
  + GROUND + C(64,80,.8, char('shades','smile',arms=DOWN_L+DOWN_R),'q-sway'))
CLOUD='<path class="q" fill="#000" d="M24 104 q-11 0 -11 -9 q0 -9 10 -9 q1 -10 13 -9 q5 -8 16 -6 q9 -6 19 1 q12 -3 15 8 q10 -1 11 9 q0 9 -10 15 z"/>'
add('作息','歇一会','午休、歇口气',
  f'<g class="q-float">{C(60,62,.74, char("closed","w",feet=False,arms=DOWN_L+DOWN_R))}{CLOUD}</g><path class="q q-pulse" style="stroke:#7a7a7a" d="M90 30 q3 -3 6 0 q3 3 6 0 M98 20 q2 -2 4 0 q2 2 4 0"/>')
PILLOW='<path class="q" fill="#000" d="M-28,20 q28,-5 56,0 q3,10 0,20 q-28,5 -56,0 q-3,-10 0,-20 z"/><path class="q" style="stroke:#555" d="M-18,30 q18,3 36,0"/>'
add('作息','该睡了','过了上床时间还在聊',
  '<circle class="q" cx="26" cy="28" r="12"/><path class="q" d="M26 28 V20 M26 28 L21 25"/><g class="q-pulse"><path class="q" d="M14 12 l-4 -4 M38 12 l4 -4"/></g>'
  + C(62,72,.78, char('half','o',feet=False,arms=HOLD.replace('<path','<path')+PILLOW),'q-sway'))
CAP=('<path class="q" fill="#000" d="M-44,-14 Q-28,-50 2,-46 Q-6,-36 -12,-21 Q-28,-30 -44,-14 Z"/>'
     '<path class="q" d="M-45,-13 Q-28,-32 -10,-20"/><circle cx="3" cy="-46" r="3.6" fill="#fff"/>')
add('作息','晚安','睡前最后一条',
  '<path class="q" d="M98 16 A12 12 0 1 0 110 30 A12 12 0 0 1 98 16 Z"/><path class="q q-zz" d="M74 34 h7 l-7 7 h7"/><path class="q q-zz q-d2" d="M86 22 h5 l-5 5 h5"/>'
  + '<path class="q" style="stroke:#555" d="M14 102 Q60 94 106 102"/>' + C(56,80,.78, char('closed','smile',feet=False,hat=CAP),'q-sway',rot=-6))
PHONE='<g class="q-shake" style="transform-origin:94px 60px"><rect class="q" x="83" y="40" width="22" height="38" rx="4.5" fill="#000"/><path class="q" d="M90 54 l8 8 M98 54 l-8 8"/></g>'
add('作息','放下手机','睡前还在刷手机',
  PHONE + '<path class="q q-pulse" style="stroke:#7a7a7a" d="M110 46 l5 -3 M111 60 h6 M110 74 l5 3"/>'
  + GROUND + C(46,80,.7, char('firm','flat',arms=DOWN_L+f'<path class="q" d="M40,6 q10,-2 22,-12"/>{H(60,-16)}')))

# ---------- 夸夸
SHIELD=('<g class="q-sway" style="transform-origin:50% 100%"><path class="q" fill="#000" d="M96,52 q9,5 17,3 q1,20 -17,30 q-18,-10 -17,-30 q8,2 17,-3 z"/>'
        '<path class="q q-draw" d="M89,68 l5,5 l9,-10" style="stroke-dasharray:30"/></g>')
dots=''.join(f'<circle cx="{24+12*i}" cy="112" r="3" fill="#fff"/>' for i in range(4))+'<circle class="q-pop" cx="72" cy="112" r="3" fill="#fff"/>'+''.join(f'<circle class="q" style="stroke:#7a7a7a" cx="{84+12*i}" cy="112" r="3"/>' for i in range(2))
add('夸夸','又守住了','连着守住几晚',
  dots + C(46,79,.68, char('happy','w',arms=DOWN_L+f'<path class="q" d="M40,11 q6,2 12,-2"/>{H(52,-3)}')) + SHIELD)
CLAP=(f'<path class="q" d="M-44,12 q10,12 38,13"/><path class="q" d="M40,11 q-6,12 -34,13"/>{H(-5,25,3.2)}{H(5,24.4,3.2)}'
      '<g class="q-pulse"><path class="q" d="M-12,32 l-5,4 M0,34 v6 M12,32 l5,4"/></g>')
add('夸夸','干得漂亮','做完一件事',
  sparkle(22,26,1.2) + sparkle(36,12,.7,'q-tw q-d2') + sparkle(104,58,.8,'q-tw q-d3') + GROUND + C(60,76,.8, char('dot','smile',eyesR='happy',feet=False,arms=CLAP),'q-bob'))
conf=''.join([
 '<path class="q q-fall" d="M20 20 l5 4"/>','<path class="q q-fall q-d2" d="M98 14 l-4 6"/>','<circle class="q-fall q-d3" cx="40" cy="10" r="2.2" fill="#fff"/>',
 '<circle class="q-fall q-d2" cx="84" cy="30" r="2" fill="#fff"/>','<path class="q q-fall q-d3" d="M108 34 l-6 2"/>','<path class="q q-fall" d="M60 6 l2 6"/>',
 '<rect class="q-fall q-d2" x="12" y="40" width="4" height="4" fill="#fff" transform="rotate(20 14 42)"/>','<path class="q q-fall q-d3" d="M72 18 q3 -3 6 0"/>'])
add('夸夸','太棒了','破纪录、阶段完成', conf + GROUND + C(60,80,.8, char('star','open',arms=UP_L+UP_R),'q-jump'))
add('夸夸','比心','老大说谢谢',
  heart(96,40,1.2,cls='q-rise') + heart(104,28,.8,cls='q-rise q-d2') + heart(90,22,.7,cls='q-rise q-d3')
  + GROUND + C(54,80,.78, char('happy','w',arms=DOWN_L+f'<path class="q" d="M40,6 q8,-1 12,-10"/>{H(52,-5)}<path class="q" d="M50,-8 l5,-7 M54,-6 l4,-8"/>'),'q-bob'))
SPIN='<g class="q-spin" style="transform-origin:60px 70px"><path class="q" style="stroke:#7a7a7a;stroke-dasharray:3 6" d="M14 70 A46 22 0 0 0 106 70"/></g>'
add('夸夸','好耶','有好消息',
  SPIN + '<path class="q q-rise" d="M100 30 v-12 l7 -2 v12"/><circle cx="98" cy="30" r="2.4" fill="#fff" class="q-rise"/><path class="q q-rise q-d2" d="M22 34 v-10"/><circle cx="20" cy="34" r="2.2" fill="#fff" class="q-rise q-d2"/>'
  + C(60,70,.76, char('squeeze','open',feet=False,arms=f'<path class="q" d="M-46,4 q-10,-1 -14,-8"/>{H(-60,-5)}<path class="q" d="M40,0 q10,1 14,-6"/>{H(54,-7)}'),'q-sway2'))
add('夸夸','进步了','数据比上周好',
  '<path class="q q-draw2" style="stroke-dasharray:120" d="M58 96 L72 80 L82 86 L104 52"/><path class="q" d="M96 52 h8 v8"/>'
  + GROUND + C(38,84,.6, char('dot','open',arms=DOWN_L+UP_R),'q-bob'))

# ---------- 陪伴
add('陪伴','抱抱','没睡好、心情差',
  heart(100,30,.7,cls='q-rise q-d2') + C(60,76,.8, char('closed','w',feet=True,
     front=f'<g class="q-beat">{heart(-1,30,1.9)}</g>'+'<path class="q" d="M-44,12 q8,16 30,16"/><path class="q" d="M40,11 q-4,16 -26,17"/>'+H(-13,28)+H(13,28)),'q-sway'))
FLOWER=('<g class="q-sway" style="transform-origin:50% 100%"><path class="q" d="M52,-4 q-2,-12 2,-24"/>'
        + ''.join(f'<ellipse class="q" cx="54" cy="-33" rx="3.2" ry="5.4" transform="rotate({a} 54 -28)" fill="#000"/>' for a in (0,72,144,216,288))
        + '<circle cx="54" cy="-28" r="2.6" fill="#fff"/></g>')
add('陪伴','辛苦了','累了、疼了',
  GROUND + C(54,80,.78, char('happy','smile',arms=DOWN_L+'<path class="q" d="M40,10 q8,-4 12,-12"/>'+H(52,-3)+FLOWER),'q-bob'))
HAND=('<g transform="translate(-6 24)"><g class="q-pat"><path class="q" d="M120 2 L94 30 M112 -6 L86 22" style="stroke:#7a7a7a"/>'
      '<path class="q" fill="#000" d="M86,22 q-10,4 -12,12 q-2,8 6,8 q10,0 18,-6 q6,-6 2,-12 q-6,-6 -14,-2 z"/></g></g>')
add('陪伴','摸摸头','委屈、受挫',
  GROUND + C(54,80,.8, char('closed','w'),'q-squish') + HAND + '<path class="q q-pulse" style="stroke:#7a7a7a" d="M62 50 l-3 -5 M54 54 l-5 -3"/>')
add('陪伴','我在呢','半夜睡不着来聊',
  C(60,86,.8, char('dot','w',feet=False,blink=True)) + '<rect x="0" y="90" width="120" height="30" fill="#000"/>'
  + '<path class="q" d="M10 90 H110"/>' + H(28,90,3.6) + H(92,90,3.6)
  + '<path class="q" d="M84 46 h22 a6 6 0 0 1 6 6 v6 a6 6 0 0 1 -6 6 h-14 l-6 5 v-5 h-2 a6 6 0 0 1 -6 -6 v-6 a6 6 0 0 1 6 -6 z" fill="#000"/>'
  + '<circle class="q-pulse" cx="89" cy="55" r="1.6" fill="#fff"/><circle class="q-pulse q-d2" cx="95" cy="55" r="1.6" fill="#fff"/><circle class="q-pulse q-d3" cx="101" cy="55" r="1.6" fill="#fff"/>')
SNAIL=('<g class="q-crawl"><path class="q" d="M76 102 h30 q4 0 4 -4 l2 -10 M110 90 l-2 -8 M112 89 l4 -6"/><circle cx="108" cy="82" r="1.4" fill="#fff"/><circle cx="116.5" cy="82.5" r="1.4" fill="#fff"/>'
       '<circle class="q" cx="90" cy="91" r="10" fill="#000"/><path class="q" d="M90 91 m-1 0 a2 2 0 1 1 3 1 a4 4 0 1 1 -6 -3 a6.5 6.5 0 1 1 10 6"/></g>')
add('陪伴','慢慢来','进度慢、着急时', GROUND + C(40,84,.6, char('happy','smile',arms=DOWN_L+DOWN_R),'q-bob') + SNAIL)
add('陪伴','加油','开始一件难事',
  GROUND + C(60,80,.8, char('firm','open',arms=f'<g class="q-pump">{UP_L}{UP_R}<path class="q" d="M-62,-26 l-3,-4 M-54,-30 l0,-5 M56,-30 l0,-5 M64,-26 l3,-4"/></g>'),'q-bob'))

# ---------- 提醒
CUP=('<path class="q" fill="#000" d="M-10,8 h22 l-2.4,18 q-.5,3 -3.5,3 h-10.2 q-3,0 -3.5,-3 z"/><path class="q" style="stroke:#7a7a7a" d="M-8.6,14 q2.6,-2 5.2,0 q2.6,2 5.2,0 q2.6,-2 5.2,0 q2,1.6 2.6,0"/>'
     '<circle class="q-bub" cx="-1" cy="25" r="1.3" fill="#fff"/><circle class="q-bub q-d2" cx="5" cy="23" r="1.1" fill="#fff"/>'
     '<path class="q" d="M-44,12 q14,8 32,7"/><path class="q" d="M40,11 q-12,8 -25,8"/>')
add('提醒','喝水','提醒补水', '<path class="q q-drop" d="M100 26 q-6 8 -6 12 a6 6 0 0 0 12 0 q0 -4 -6 -12 z"/>' + GROUND + C(58,80,.8, char('happy','',feet=True,front=CUP+H(-12,19)+H(14,19)),'q-bob'))
WALK=(f'<g class="q-stepA"><path class="q" d="M-35,27.6 q0,-4 5.6,-4 q5.6,0 5.6,4 z"/></g><g class="q-stepB"><path class="q" d="M20.6,27.6 q0,-4 5.6,-4 q5.6,0 5.6,4 z"/></g>'
      f'<g class="q-swingL"><path class="q" d="M-44,12 q-6,3 -6,10"/>{H(-50,23)}</g><g class="q-swingR"><path class="q" d="M40,11 q6,3 6,10"/>{H(46,22)}</g>')
add('提醒','动一动','坐太久了',
  '<path class="q q-pulse" style="stroke:#7a7a7a" d="M10 62 h10 M6 74 h14 M12 86 h8"/>' + GROUND + C(64,80,.8, char('dot','smile',feet=False,arms=WALK),'q-bob'))
add('提醒','深呼吸','紧张、睡不着',
  '<circle class="q q-breath" style="stroke:#7a7a7a" cx="60" cy="64" r="48"/><circle class="q q-breath q-d2" style="stroke:#444" cx="60" cy="64" r="48"/>'
  + C(60,66,.72, char('closed','o',feet=False),'q-breath2'))
BOWL=('<path class="q" fill="#000" d="M36 86 q4 -10 9 -6 q4 -8 10 -3 q5 -8 11 -1 q6 -6 9 4 q5 -2 7 6 z"/>'
      '<path class="q" d="M30 86 h60 q-2 18 -22 20 h-16 q-20 -2 -22 -20 z" fill="#000"/><path class="q" d="M52 110 h16"/>'
      '<path class="q" d="M76 80 L98 56 M80 82 L104 62"/><path class="q q-rise" style="stroke:#7a7a7a" d="M40 66 q-3 -4 0 -8 q3 -4 0 -8"/><path class="q q-rise q-d2" style="stroke:#7a7a7a" d="M60 64 q-3 -4 0 -8 q3 -4 0 -8"/>')
add('提醒','好好吃饭','提醒按时吃饭', C(60,62,.62, char('happy','open',feet=False),'q-bob') + BOWL)
SALUTE=f'<g class="q-armR"><path class="q" d="M40,10 q14,-8 4,-30"/>{H(42,-22)}<path class="q" d="M38,-24 l9,-4" /></g>'
add('提醒','收到','老大交代事情',
  '<circle class="q" cx="24" cy="26" r="11"/><path class="q q-draw" style="stroke-dasharray:24" d="M19 26 l4 4 l7 -8"/>'
  + GROUND + C(62,80,.8, char('dot','smile',arms=DOWN_L+SALUTE),'q-nod'))
BOOK=('<path class="q" fill="#000" d="M-24,16 q12,-4 24,0 q12,-4 24,0 v20 q-12,-4 -24,0 q-12,-4 -24,0 z"/><path class="q" d="M0,16 v20"/>'
      '<path class="q q-write" style="stroke:#7a7a7a;stroke-dasharray:30" d="M-19,23 h14 M-19,29 h10 M5,23 h13"/>'
      '<g class="q-scribble"><path class="q" d="M18,32 L32,10 l4,2.4 L22,34.4 z" fill="#000"/><path class="q" d="M18,32 l-1,5 l4.6,-2.6"/></g>'
      '<path class="q" d="M-44,12 q6,10 18,12"/><path class="q" d="M40,11 q-2,10 -16,14"/>')
add('提醒','记下了','记完一条', GROUND + C(58,76,.8, char('down','w',feet=False,front=BOOK+H(-25,25)+H(24,26))))

import re as _re
def _fixfill(svg):
    """.q sets fill:none in CSS, which beats a fill="" attribute: move the fill into style so the black masks work"""
    def f(m):
        tag=m.group(0)
        cls=_re.search(r'class="([^"]*)"',tag); fm=_re.search(r' fill="([^"]*)"',tag)
        if not cls or not fm or 'q' not in cls.group(1).split(): return tag
        tag=tag.replace(fm.group(0),'',1)
        sm=_re.search(r'style="([^"]*)"',tag)
        if sm: return tag.replace(sm.group(0), f'style="{sm.group(1)};fill:{fm.group(1)}"',1)
        name=m.group(1)
        return tag.replace('<'+name, f'<{name} style="fill:{fm.group(1)}"',1)
    return _re.sub(r'<(path|rect|ellipse|circle)\b[^>]*>', f, svg)
for _s in S: _s['svg']=_fixfill(_s['svg'])
