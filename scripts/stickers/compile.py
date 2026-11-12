"""SVG stickers (set.py) → compact JSON the iOS app draws with SwiftUI Canvas.
Paths become absolute M/L/C/Z; transforms become 2x3 matrices; CSS animation classes become
{kind, origin, delay} with origins resolved from fill-box bounds, and the keyframe table ships alongside."""
import json, math, re, sys
import xml.etree.ElementTree as ET
from set import S

# ---------- path parsing → absolute M L C Z
TOK=re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?')
def arc_to_cubic(x1,y1,rx,ry,phi,fa,fs,x2,y2):
    if rx==0 or ry==0: return [('L',x2,y2)]
    phi=math.radians(phi); cp,sp=math.cos(phi),math.sin(phi)
    dx,dy=(x1-x2)/2,(y1-y2)/2; x1p=cp*dx+sp*dy; y1p=-sp*dx+cp*dy
    rx,ry=abs(rx),abs(ry); lam=x1p**2/rx**2+y1p**2/ry**2
    if lam>1: rx*=math.sqrt(lam); ry*=math.sqrt(lam)
    num=rx*rx*ry*ry-rx*rx*y1p*y1p-ry*ry*x1p*x1p; den=rx*rx*y1p*y1p+ry*ry*x1p*x1p
    co=math.sqrt(max(0,num/den)) if den else 0
    if fa==fs: co=-co
    cxp=co*rx*y1p/ry; cyp=-co*ry*x1p/rx
    cx=cp*cxp-sp*cyp+(x1+x2)/2; cy=sp*cxp+cp*cyp+(y1+y2)/2
    def ang(ux,uy,vx,vy):
        a=math.atan2(ux*vy-uy*vx, ux*vx+uy*vy); return a
    t1=ang(1,0,(x1p-cxp)/rx,(y1p-cyp)/ry); dt=ang((x1p-cxp)/rx,(y1p-cyp)/ry,(-x1p-cxp)/rx,(-y1p-cyp)/ry)
    if not fs and dt>0: dt-=2*math.pi
    if fs and dt<0: dt+=2*math.pi
    n=max(1,int(math.ceil(abs(dt)/(math.pi/2)))); d=dt/n; out=[]
    k=4/3*math.tan(d/4)
    def pt(t): return (cx+rx*math.cos(t)*cp-ry*math.sin(t)*sp, cy+rx*math.cos(t)*sp+ry*math.sin(t)*cp)
    def dv(t): return (-rx*math.sin(t)*cp-ry*math.cos(t)*sp, -rx*math.sin(t)*sp+ry*math.cos(t)*cp)
    for i in range(n):
        a,b=t1+i*d,t1+(i+1)*d; p0,p3=pt(a),pt(b); d0,d3=dv(a),dv(b)
        out.append(('C',p0[0]+k*d0[0],p0[1]+k*d0[1],p3[0]-k*d3[0],p3[1]-k*d3[1],p3[0],p3[1]))
    return out
def parse_d(d):
    toks=TOK.findall(d); i=0; cmd=None; out=[]; x=y=sx=sy=0; lc=None; lq=None
    def num():
        nonlocal i; v=float(toks[i]); i+=1; return v
    while i<len(toks):
        if re.match(r'[A-Za-z]',toks[i]): cmd=toks[i]; i+=1
        elif cmd in ('M','m'): cmd='L' if cmd=='M' else 'l'
        c=cmd; rel=c.islower(); C=c.upper()
        if C=='Z':
            out.append(('Z',)); x,y=sx,sy; lc=lq=None; continue
        if C=='M':
            nx,ny=num(),num()
            if rel: nx+=x; ny+=y
            x,y=sx,sy=nx,ny; out.append(('M',x,y)); lc=lq=None
            cmd='l' if rel else 'L'; continue
        if C=='L':
            nx,ny=num(),num()
            if rel: nx+=x; ny+=y
            x,y=nx,ny; out.append(('L',x,y)); lc=lq=None
        elif C=='H':
            nx=num(); x=nx+x if rel else nx; out.append(('L',x,y)); lc=lq=None
        elif C=='V':
            ny=num(); y=ny+y if rel else ny; out.append(('L',x,y)); lc=lq=None
        elif C=='C':
            a=[num() for _ in range(6)]
            if rel: a=[a[0]+x,a[1]+y,a[2]+x,a[3]+y,a[4]+x,a[5]+y]
            out.append(('C',*a)); lc=(a[2],a[3]); lq=None; x,y=a[4],a[5]
        elif C=='S':
            a=[num() for _ in range(4)]
            if rel: a=[a[0]+x,a[1]+y,a[2]+x,a[3]+y]
            c1=(2*x-lc[0],2*y-lc[1]) if lc else (x,y)
            out.append(('C',c1[0],c1[1],*a)); lc=(a[0],a[1]); lq=None; x,y=a[2],a[3]
        elif C in ('Q','T'):
            if C=='Q':
                a=[num() for _ in range(4)]
                if rel: a=[a[0]+x,a[1]+y,a[2]+x,a[3]+y]
                q=(a[0],a[1]); e=(a[2],a[3])
            else:
                a=[num(),num()]
                if rel: a=[a[0]+x,a[1]+y]
                q=(2*x-lq[0],2*y-lq[1]) if lq else (x,y); e=(a[0],a[1])
            out.append(('C',x+2/3*(q[0]-x),y+2/3*(q[1]-y),e[0]+2/3*(q[0]-e[0]),e[1]+2/3*(q[1]-e[1]),e[0],e[1]))
            lq=q; lc=None; x,y=e
        elif C=='A':
            rx,ry,ph,fa,fs,nx,ny=num(),num(),num(),num(),num(),num(),num()
            if rel: nx+=x; ny+=y
            out+=arc_to_cubic(x,y,rx,ry,ph,int(fa),int(fs),nx,ny); x,y=nx,ny; lc=lq=None
    return out
def ellipse(cx,cy,rx,ry):
    k=0.5522847498
    return [('M',cx+rx,cy),('C',cx+rx,cy+k*ry,cx+k*rx,cy+ry,cx,cy+ry),('C',cx-k*rx,cy+ry,cx-rx,cy+k*ry,cx-rx,cy),
            ('C',cx-rx,cy-k*ry,cx-k*rx,cy-ry,cx,cy-ry),('C',cx+k*rx,cy-ry,cx+rx,cy-k*ry,cx+rx,cy),('Z',)]
def rrect(x,y,w,h,r):
    r=min(r,w/2,h/2)
    if r<=0: return [('M',x,y),('L',x+w,y),('L',x+w,y+h),('L',x,y+h),('Z',)]
    k=0.5522847498*r
    return [('M',x+r,y),('L',x+w-r,y),('C',x+w-r+k,y,x+w,y+r-k,x+w,y+r),('L',x+w,y+h-r),('C',x+w,y+h-r+k,x+w-r+k,y+h,x+w-r,y+h),
            ('L',x+r,y+h),('C',x+r-k,y+h,x,y+h-r+k,x,y+h-r),('L',x,y+r),('C',x,y+r-k,x+r-k,y,x+r,y),('Z',)]
# ---------- transforms (a b c d e f), point' = (a x + c y + e, b x + d y + f)
def mul(m,n):  # m ∘ n  (apply n first, then m)
    a,b,c,d,e,f=m; A,B,C,D,E,F=n
    return (a*A+c*B, b*A+d*B, a*C+c*D, b*C+d*D, a*E+c*F+e, b*E+d*F+f)
I=(1,0,0,1,0,0)
def parse_tf(s):
    m=I
    for name,args in re.findall(r'(\w+)\(([^)]*)\)', s or ''):
        v=[float(x) for x in re.split(r'[\s,]+',args.strip()) if x]
        if name=='translate': t=(1,0,0,1,v[0],v[1] if len(v)>1 else 0)
        elif name=='scale': sx=v[0]; sy=v[1] if len(v)>1 else sx; t=(sx,0,0,sy,0,0)
        elif name=='rotate':
            r=math.radians(v[0]); c,s_=math.cos(r),math.sin(r); t=(c,s_,-s_,c,0,0)
            if len(v)==3: t=mul((1,0,0,1,v[1],v[2]),mul(t,(1,0,0,1,-v[1],-v[2])))
        else: raise ValueError(name)
        m=mul(m,t)
    return m
def apply(m,p): return (m[0]*p[0]+m[2]*p[1]+m[4], m[1]*p[0]+m[3]*p[1]+m[5])
def seg_points(segs):
    pts=[]; cur=(0,0)
    for s in segs:
        if s[0] in ('M','L'): cur=(s[1],s[2]); pts.append(cur)
        elif s[0]=='C':
            p0=cur; p1=(s[1],s[2]); p2=(s[3],s[4]); p3=(s[5],s[6])
            for i in range(1,9):
                t=i/8; u=1-t
                pts.append((u**3*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*p3[0], u**3*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*p3[1]))
            cur=p3
    return pts
def fmt(v): s=f'{v:.2f}'.rstrip('0').rstrip('.'); return '0' if s in ('-0','') else s
def dstr(segs): return ' '.join(s[0]+(' '+' '.join(fmt(v) for v in s[1:]) if len(s)>1 else '') for s in segs)
# ---------- CSS → animation
ORIGIN={'bob':(.5,1),'jump':(.5,1),'sway':(.5,1),'squish':(.5,1),'nod':(.5,1),'armR':(0,1),'armL':(1,1),'swingL':(1,0),'swingR':(0,0)}
VIEWBOX={'spin','shake'}
DELAY={'q-d2':.6,'q-d3':1.2}
def styles(el):
    st={}
    for part in (el.get('style') or '').split(';'):
        if ':' in part: k,v=part.split(':',1); st[k.strip()]=v.strip()
    return st
def anim_of(el, st):
    cls=(el.get('class') or '').split()
    kinds=[c[2:] for c in cls if c.startswith('q-') and c not in DELAY]
    if not kinds: return None
    k=kinds[0]
    dl=max([DELAY[c] for c in cls if c in DELAY]+[0])
    if k=='stepB': k,dl='stepA',max(dl,.4)
    return dict(k=k, dl=dl, origin=st.get('transform-origin'))
def bbox(pts):
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]; return (min(xs),min(ys),max(xs),max(ys))
def node(el):
    """returns (json node or None, points in this node's parent space)"""
    tag=el.tag.split('}')[-1]; st=styles(el)
    tf=parse_tf(el.get('transform'))
    an=anim_of(el, st)
    out={}
    pts_local=[]
    if tag=='g':
        ch=[]
        for c in el:
            n,p=node(c)
            if n: ch.append(n); pts_local+=p
        if not ch: return None,[]
        out['c']=ch
    else:
        if tag=='path': segs=parse_d(el.get('d'))
        elif tag=='circle': r=float(el.get('r')); segs=ellipse(float(el.get('cx')),float(el.get('cy')),r,r)
        elif tag=='ellipse': segs=ellipse(float(el.get('cx')),float(el.get('cy')),float(el.get('rx')),float(el.get('ry')))
        elif tag=='rect': segs=rrect(float(el.get('x',0)),float(el.get('y',0)),float(el.get('width')),float(el.get('height')),float(el.get('rx',0)))
        else: raise ValueError(tag)
        cls=(el.get('class') or '').split()
        q='q' in cls
        fill=st.get('fill', el.get('fill', 'none' if q else '#000'))
        stroke=st.get('stroke', el.get('stroke', '#fff' if q else None))
        out['p']=dstr(segs)
        if fill and fill!='none': out['f']=fill
        if stroke and stroke!='none':
            out['s']=stroke
            w=float(st.get('stroke-width', el.get('stroke-width', 1.4)))
            if w!=1.4: out['w']=w
        if 'stroke-dasharray' in st: out['da']=[float(x) for x in re.split(r'[\s,]+',st['stroke-dasharray'])]
        pts_local=seg_points(segs)
    if tf!=I: out['t']=[round(v,4) for v in tf]
    if an:
        if an['k'] in VIEWBOX:
            o=[float(v.replace('px','')) for v in an['origin'].split()]
            # view-box origin is in the parent's space (these sit at the top level); express it in local space
            out['an']=dict(k=an['k'], o=[round(o[0],2),round(o[1],2)], vb=1)
        else:
            if an['origin'] and '%' in an['origin']:
                fx,fy=[float(v.strip('%'))/100 for v in an['origin'].split()]
            else:
                fx,fy=ORIGIN.get(an['k'],(.5,.5))
            x0,y0,x1,y1=bbox(pts_local)
            out['an']=dict(k=an['k'], o=[round(x0+fx*(x1-x0),2), round(y0+fy*(y1-y0),2)])
        if an['dl']: out['an']['dl']=an['dl']
    return out, [apply(tf,p) for p in pts_local]
# keyframes, mirroring css.py (per property: [[pct, value], …])
IO='io'
A={
 'bob':dict(d=1.8,e=IO,p=dict(ty=[[0,0],[.35,-3],[.7,0],[1,0]],sx=[[0,1],[.35,.98],[.7,1.03],[1,1]],sy=[[0,1],[.35,1.03],[.7,.97],[1,1]])),
 'jump':dict(d=1.2,e=IO,p=dict(ty=[[0,0],[.45,-12],[.8,0],[1,0]],sx=[[0,1.04],[.45,.97],[.8,1],[1,1.04]],sy=[[0,.95],[.45,1.04],[.8,1],[1,.95]])),
 'sway':dict(d=3,e=IO,p=dict(r=[[0,-4],[.5,4],[1,-4]])),
 'sway2':dict(d=1.4,e=IO,p=dict(r=[[0,-10],[.5,10],[1,-10]])),
 'float':dict(d=3.2,e=IO,p=dict(ty=[[0,0],[.5,-4],[1,0]])),
 'drop':dict(d=2.4,e=IO,p=dict(ty=[[0,0],[.5,-4],[1,0]])),
 'blink':dict(d=4,e='ease',p=dict(sy=[[0,1],[.9,1],[.94,.1],[1,1]])),
 'armR':dict(d=1.6,e=IO,p=dict(r=[[0,0],[.5,-14],[1,0]])),
 'armL':dict(d=1.6,e=IO,p=dict(r=[[0,0],[.5,14],[1,0]])),
 'pump':dict(d=.9,e=IO,p=dict(ty=[[0,0],[.5,-3],[1,0]])),
 'beat':dict(d=1.4,e=IO,p=dict(sx=[[0,1],[.2,1.12],[.4,.96],[.6,1],[1,1]],sy=[[0,1],[.2,1.12],[.4,.96],[.6,1],[1,1]])),
 'tw':dict(d=2.2,e=IO,p=dict(sx=[[0,.5],[.5,1],[1,.5]],sy=[[0,.5],[.5,1],[1,.5]],op=[[0,.4],[.5,1],[1,.4]])),
 'pulse':dict(d=2.4,e=IO,p=dict(op=[[0,.3],[.5,1],[1,.3]])),
 'rise':dict(d=2.6,e='in',p=dict(ty=[[0,8],[1,-10]],op=[[0,0],[.3,1],[1,0]])),
 'zz':dict(d=3,e=IO,p=dict(ty=[[0,4],[1,-8]],op=[[0,0],[.3,1],[1,0]])),
 'fall':dict(d=2.4,e='in',p=dict(ty=[[0,-6],[1,12]],r=[[0,0],[1,160]],op=[[0,0],[.2,1],[1,0]])),
 'spin':dict(d=10,e='linear',p=dict(r=[[0,0],[1,360]])),
 'shake':dict(d=1.6,e=IO,p=dict(r=[[0,12],[.6,12],[.7,4],[.8,18],[.9,8],[1,12]])),
 'pat':dict(d=1,e=IO,p=dict(tx=[[0,0],[.5,-2],[1,0]],ty=[[0,0],[.5,4],[1,0]])),
 'squish':dict(d=1,e=IO,p=dict(sx=[[0,1],[.5,1.03],[1,1]],sy=[[0,1],[.5,.95],[1,1]])),
 'nod':dict(d=2,e=IO,p=dict(r=[[0,0],[.4,0],[.55,5],[.7,0],[1,0]])),
 'draw':dict(d=2.8,e='out',p=dict(do=[[0,30],[.4,0],[1,0]])),
 'draw2':dict(d=3.2,e='out',p=dict(do=[[0,120],[.5,0],[1,0]])),
 'write':dict(d=3,e='linear',p=dict(do=[[0,30],[.4,0],[1,0]])),
 'scribble':dict(d=.5,e=IO,p=dict(tx=[[0,0],[.25,-2],[.75,2],[1,0]],ty=[[0,0],[.25,1],[.75,-1],[1,0]])),
 'crawl':dict(d=4,e=IO,dir='alt',p=dict(tx=[[0,2],[1,-6]])),
 'breath':dict(d=5,e=IO,p=dict(sx=[[0,.78],[.5,1],[1,.78]],sy=[[0,.78],[.5,1],[1,.78]],op=[[0,.25],[.5,1],[1,.25]])),
 'breath2':dict(d=5,e=IO,p=dict(sx=[[0,.96],[.5,1.04],[1,.96]],sy=[[0,.96],[.5,1.04],[1,.96]])),
 'bub':dict(d=2,e='in',p=dict(ty=[[0,0],[1,-10]],op=[[0,0],[.3,1],[1,0]])),
 'pop':dict(d=2.4,e=IO,p=dict(sx=[[0,1],[.7,1],[.8,1.7],[1,1]],sy=[[0,1],[.7,1],[.8,1.7],[1,1]])),
 'stepA':dict(d=.8,e=IO,p=dict(ty=[[0,0],[.5,-4],[1,0]])),
 'swingL':dict(d=.8,e=IO,p=dict(r=[[0,-16],[.5,16],[1,-16]])),
 'swingR':dict(d=.8,e=IO,dir='rev',p=dict(r=[[0,-16],[.5,16],[1,-16]])),
}
def main(out):
    stickers=[]
    used=set()
    for s in S:
        root=ET.fromstring(f'<g xmlns="http://www.w3.org/2000/svg">{s["svg"]}</g>')
        n,_=node(root)
        def walk(x):
            if 'an' in x: used.add(x['an']['k'])
            for c in x.get('c',[]): walk(c)
        walk(n)
        stickers.append(dict(name=s['name'], group=s['row'], when=s['when'], root=n))
    missing=used-set(A)
    assert not missing, missing
    data=dict(v=1, size=120, stickers=stickers, anims={k:A[k] for k in sorted(used)})
    txt=json.dumps(data, ensure_ascii=False, separators=(',',':'))
    open(out,'w').write(txt)
    print(len(stickers),'stickers', len(txt)//1024,'KB', 'anims', sorted(used))
if __name__=='__main__': main(sys.argv[1])
