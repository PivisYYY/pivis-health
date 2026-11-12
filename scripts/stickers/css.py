CSS='''/*q*/
.q{fill:none;stroke:#fff;stroke-width:1.4;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}
[class*="q-"]{transform-box:fill-box;transform-origin:center}
.q-d2{animation-delay:.6s!important}.q-d3{animation-delay:1.2s!important}
.q-bob{transform-origin:50% 100%;animation:q-bob 1.8s ease-in-out infinite}
@keyframes q-bob{0%,100%{transform:translateY(0) scale(1,1)}35%{transform:translateY(-3px) scale(.98,1.03)}70%{transform:translateY(0) scale(1.03,.97)}}
.q-jump{transform-origin:50% 100%;animation:q-jump 1.2s ease-in-out infinite}
@keyframes q-jump{0%,100%{transform:translateY(0) scale(1.04,.95)}45%{transform:translateY(-12px) scale(.97,1.04)}80%{transform:translateY(0) scale(1,1)}}
.q-sway{transform-origin:50% 100%;animation:q-sway 3s ease-in-out infinite}
@keyframes q-sway{0%,100%{transform:rotate(-4deg)}50%{transform:rotate(4deg)}}
.q-sway2{animation:q-sway2 1.4s ease-in-out infinite}
@keyframes q-sway2{0%,100%{transform:rotate(-10deg)}50%{transform:rotate(10deg)}}
.q-float{animation:q-float 3.2s ease-in-out infinite}
@keyframes q-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
.q-blink{animation:q-blink 4s infinite}
@keyframes q-blink{0%,90%,100%{transform:scaleY(1)}94%{transform:scaleY(.1)}}
.q-armR{transform-origin:0% 100%;animation:q-wave 1.6s ease-in-out infinite}
.q-armL{transform-origin:100% 100%;animation:q-waveL 1.6s ease-in-out infinite}
@keyframes q-wave{0%,100%{transform:rotate(0)}50%{transform:rotate(-14deg)}}
@keyframes q-waveL{0%,100%{transform:rotate(0)}50%{transform:rotate(14deg)}}
.q-pump{animation:q-pump .9s ease-in-out infinite}
@keyframes q-pump{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
.q-beat{animation:q-beat 1.4s ease-in-out infinite}
@keyframes q-beat{0%,60%,100%{transform:scale(1)}20%{transform:scale(1.12)}40%{transform:scale(.96)}}
.q-tw{animation:q-tw 2.2s ease-in-out infinite}
@keyframes q-tw{0%,100%{transform:scale(.5);opacity:.4}50%{transform:scale(1);opacity:1}}
.q-pulse{animation:q-pulse 2.4s ease-in-out infinite}
@keyframes q-pulse{0%,100%{opacity:.3}50%{opacity:1}}
.q-rise{animation:q-rise 2.6s ease-in infinite}
@keyframes q-rise{0%{transform:translateY(8px);opacity:0}30%{opacity:1}100%{transform:translateY(-10px);opacity:0}}
.q-zz{animation:q-zz 3s ease-in-out infinite}
@keyframes q-zz{0%{transform:translateY(4px);opacity:0}30%{opacity:1}100%{transform:translateY(-8px);opacity:0}}
.q-fall{animation:q-fall 2.4s ease-in infinite}
@keyframes q-fall{0%{transform:translateY(-6px) rotate(0);opacity:0}20%{opacity:1}100%{transform:translateY(12px) rotate(160deg);opacity:0}}
.q-spin{transform-box:view-box;animation:q-spin 10s linear infinite}
@keyframes q-spin{to{transform:rotate(360deg)}}
.q-shake{transform-box:view-box;animation:q-shake 1.6s ease-in-out infinite}
@keyframes q-shake{0%,60%,100%{transform:rotate(12deg)}70%{transform:rotate(4deg)}80%{transform:rotate(18deg)}90%{transform:rotate(8deg)}}
.q-pat{animation:q-pat 1s ease-in-out infinite}
@keyframes q-pat{0%,100%{transform:translate(0,0)}50%{transform:translate(-2px,4px)}}
.q-squish{transform-origin:50% 100%;animation:q-squish 1s ease-in-out infinite}
@keyframes q-squish{0%,100%{transform:scale(1,1)}50%{transform:scale(1.03,.95)}}
.q-nod{transform-origin:50% 100%;animation:q-nod 2s ease-in-out infinite}
@keyframes q-nod{0%,40%,100%{transform:rotate(0)}55%{transform:rotate(5deg)}70%{transform:rotate(0)}}
.q-draw{animation:q-draw 2.8s ease-out infinite}
@keyframes q-draw{0%{stroke-dashoffset:30}40%,100%{stroke-dashoffset:0}}
.q-draw2{animation:q-draw2 3.2s ease-out infinite}
@keyframes q-draw2{0%{stroke-dashoffset:120}50%,100%{stroke-dashoffset:0}}
.q-write{animation:q-draw 3s linear infinite}
.q-scribble{animation:q-scribble .5s ease-in-out infinite}
@keyframes q-scribble{0%,100%{transform:translate(0,0)}25%{transform:translate(-2px,1px)}75%{transform:translate(2px,-1px)}}
.q-crawl{animation:q-crawl 4s ease-in-out infinite alternate}
@keyframes q-crawl{from{transform:translateX(2px)}to{transform:translateX(-6px)}}
.q-breath{animation:q-breath 5s ease-in-out infinite}
@keyframes q-breath{0%,100%{transform:scale(.78);opacity:.25}50%{transform:scale(1);opacity:1}}
.q-breath2{animation:q-breath2 5s ease-in-out infinite}
@keyframes q-breath2{0%,100%{transform:scale(.96)}50%{transform:scale(1.04)}}
.q-bub{animation:q-bub 2s ease-in infinite}
@keyframes q-bub{0%{transform:translateY(0);opacity:0}30%{opacity:1}100%{transform:translateY(-10px);opacity:0}}
.q-drop{animation:q-float 2.4s ease-in-out infinite}
.q-pop{animation:q-pop 2.4s ease-in-out infinite}
@keyframes q-pop{0%,70%,100%{transform:scale(1)}80%{transform:scale(1.7)}}
.q-stepA{animation:q-step .8s ease-in-out infinite}.q-stepB{animation:q-step .8s ease-in-out infinite .4s}
@keyframes q-step{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
.q-swingL{transform-origin:100% 0%;animation:q-swing .8s ease-in-out infinite}.q-swingR{transform-origin:0% 0%;animation:q-swing .8s ease-in-out infinite reverse}
@keyframes q-swing{0%,100%{transform:rotate(-16deg)}50%{transform:rotate(16deg)}}
@media (prefers-reduced-motion: reduce){[class*="q-"]{animation:none!important}}
/*/q*/'''
