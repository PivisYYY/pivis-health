import math
from geo import pt, nrm, sp, cross, W
def d(pts,close=False):
    s="M"+" ".join(f"{x:.1f},{y:.1f}" for x,y in pts); return s+(" Z" if close else "")
def strand(k,t0,t1,n): return [sp(k,t0+(t1-t0)*i/n) for i in range(n+1)]
def mask(extra):
    L=[];R=[]
    for i in range(7):
        t=cross-0.42+0.84*i/6; p=pt(t); nv=nrm(t); w=(2*1.5*W*abs(math.sin(t/2))+3.2+extra)/2
        L.append((p[0]+nv[0]*w,p[1]+nv[1]*w)); R.append((p[0]-nv[0]*w,p[1]-nv[1]*w))
    return L+R[::-1]
KS=[1.5,-1.5]
BODY=" ".join(d(strand(k,0,2*math.pi,48)) for k in KS)
OVER=" ".join(d(strand(k,cross-0.42,cross+0.42,6)) for k in KS)
MASK=d(mask(3.0),True)
TILT=3.7   # levels the two loop bottoms so the feet sit on one line
EL=(-21,-1); ER=(22,-1); MO=(1.3,15.6)

def eye(kind,x,y,side):
    if kind=='dot':   return f'<circle cx="{x}" cy="{y}" r="4.2" fill="#fff"/><circle cx="{x-1.5}" cy="{y-1.6}" r="1.2" fill="#000"/>'
    if kind=='small': return f'<circle cx="{x}" cy="{y}" r="3.2" fill="#fff"/>'
    if kind=='down':  return f'<circle cx="{x}" cy="{y+2}" r="3.6" fill="#fff"/>'
    if kind=='happy': return f'<path class="q" d="M{x-4.2},{y+1.6} Q{x},{y-4.4} {x+4.2},{y+1.6}"/>'
    if kind=='closed':return f'<path class="q" d="M{x-4.2},{y-1} Q{x},{y+3.4} {x+4.2},{y-1}"/>'
    if kind=='flat':  return f'<path class="q" d="M{x-3.8},{y+.5} H{x+3.8}"/>'
    if kind=='half':  return f'<path class="q" d="M{x-4.4},{y} H{x+4.4}"/><path d="M{x-3.4},{y} A3.4 3.4 0 0 0 {x+3.4},{y} Z" fill="#fff"/>'
    if kind=='squeeze':
        s=1 if side=='L' else -1
        return f'<path class="q" d="M{x-3*s},{y-3.6} L{x+3*s},{y} L{x-3*s},{y+3.6}"/>'
    if kind=='star':  return f'<path d="M{x},{y-5.4} Q{x+1},{y-1} {x+5.4},{y} Q{x+1},{y+1} {x},{y+5.4} Q{x-1},{y+1} {x-5.4},{y} Q{x-1},{y-1} {x},{y-5.4} Z" fill="#fff"/>'
    if kind=='heart': return f'<path d="M{x},{y+4} C{x-6},{y} {x-4.6},{y-5} {x},{y-2.2} C{x+4.6},{y-5} {x+6},{y} {x},{y+4} Z" fill="#fff"/>'
    if kind=='shades':return f'<rect x="{x-7}" y="{y-4}" width="14" height="8.5" rx="4" fill="#fff"/><path d="M{x-4},{y-1.6} l3,-1.2" stroke="#000" stroke-width="1.4" stroke-linecap="round"/>'
    if kind=='firm':  # determined: dot + slanted brow
        s=1 if side=='L' else -1
        return eye('small',x,y+1,side)+f'<path class="q" d="M{x-4.4*s},{y-6} L{x+3.6*s},{y-3.6}"/>'
    if kind=='tear':  return eye('small',x,y,side)+f'<path class="q" d="M{x+3.2},{y+3.6} q-1.8,2.8 0,3.8 q1.8,-1 0,-3.8 z"/>'
    return ''
def mouth(kind):
    x,y=MO
    if kind=='w':    return f'<path class="q" d="M{x-4.2},{y-1.4} q2.1,3 4.2,0 q2.1,3 4.2,0"/>'
    if kind=='smile':return f'<path class="q" d="M{x-3.4},{y-1.2} q3.4,3.4 6.8,0"/>'
    if kind=='open': return f'<path class="q" d="M{x-3.8},{y-2} h7.6 q0,5.8 -3.8,5.8 q-3.8,0 -3.8,-5.8 z"/>'
    if kind=='o':    return f'<ellipse class="q" cx="{x}" cy="{y}" rx="2.2" ry="2.8"/>'
    if kind=='flat': return f'<path class="q" d="M{x-2.6},{y} h5.2"/>'
    if kind=='wave': return f'<path class="q" d="M{x-4.4},{y} q1.1,-1.8 2.2,0 q1.1,1.8 2.2,0 q1.1,-1.8 2.2,0 q1.1,1.8 2.2,0"/>'
    return ''
def blush():
    out=''
    for cx in (EL[0]-2, ER[0]+3):
        out+=f'<path class="q" style="stroke:#7a7a7a" d="M{cx-4.5},{EL[1]+9.6} l2,-2.6 M{cx-1},{EL[1]+9.6} l2,-2.6 M{cx+2.5},{EL[1]+9.6} l2,-2.6"/>'
    return out
def body(tip=True):
    return f'<path class="q" d="{BODY}"/><path fill="#000" d="{MASK}"/><path class="q" d="{OVER}"/>'+('<circle cx="42" cy="0" r="3.4" fill="#fff"/>' if tip else '')
FEET='<path class="q" d="M-35,27.6 q0,-4 5.6,-4 q5.6,0 5.6,4 z M20.6,27.6 q0,-4 5.6,-4 q5.6,0 5.6,4 z"/>'
def char(eyes='dot',mouth_='w',blush_=True,eyesR=None,blink=False,feet=True,arms='',hat='',front='',face_dy=0,eye_cls=''):
    eR=eyesR or eyes
    e=eye(eyes,EL[0],EL[1]+face_dy,'L')+eye(eR,ER[0],ER[1]+face_dy,'R')
    if blink: e=f'<g class="q-blink">{e}</g>'
    if eye_cls: e=f'<g class="{eye_cls}">{e}</g>'
    upper=f'<g transform="rotate({TILT})">{body()}{e}{blush() if blush_ else ""}{mouth(mouth_)}{hat}</g>'
    return upper+(FEET if feet else '')+arms+front
