import math
a=42.0; W=3.6; cross=3*math.pi/2; SY=1.3
def pt(t):
    s,c=math.sin(t),math.cos(t); d=1+s*s; return (a*c/d, a*s*c/d*SY)
def nrm(t):
    e=1e-4; p0=pt(t-e); p1=pt(t+e); dx=p1[0]-p0[0]; dy=p1[1]-p0[1]; l=max(math.hypot(dx,dy),1e-9); return (-dy/l, dx/l)
def sp(k,t):
    p=pt(t); nv=nrm(t); o=k*W*math.sin(t/2); return (p[0]+nv[0]*o,p[1]+nv[1]*o)
