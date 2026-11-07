# 常见流程

## 午睡（分两步，时间和时长让老大定，不要替他定）
1. 老大在提议里选了午睡 → 先把这张卡改成问「几点、多久」（时长最多 20 分钟，15:00 前结束）：
```json
{"title":"几点睡、睡多久？","kind":"fields","submit_label":"就这样","note":"不超过 20 分钟，15:00 前结束",
 "inputs":[{"id":"start","label":"几点躺下","type":"options","options":["12:30","13:00","13:30"],"submit":"agent"},
           {"id":"len","label":"睡多久","type":"options","options":["10 分钟","15 分钟","20 分钟"],"submit":"agent"}]}
```
2. 收到回答后（例：13:00、20 分钟）→ 这张卡改成计时卡：
```json
{"title":"午睡 20 分钟","when":"13:00","kind":"timer","duration_min":20,"alarm":"13:20","inputs":[]}
```
（alarm = 开始时间 + 时长。）午睡只是计时，不是练习，不用视频。
- 闭眼歇也一样，只用计时卡：`{"board":"sleep","when":"15:30","title":"闭眼歇 10 分钟","kind":"timer","duration_min":10,"alarm":"15:40"}`。
- 计时卡只用于午睡和闭眼歇，任何练习都不用它。

## 练习视频卡
拉伸、力量、呼吸、身体扫描、睡前流程、入眠练习，都是「这个项目 + 一个视频」。视频只认 follow 出的片（`./pivis-health follow session list` 里的 video）。
```json
{"board":"sleep","when":"23:30","title":"床外拉伸","kind":"follow","note":"在床外做，床只用来睡",
 "media":{"kind":"video","title":"睡前拉伸 · 10 分钟","url":"/media/follow/<ssid>/out.mp4","duration_min":10}}
```
- 拉伸在床外做。上床以后只听声音：视频锁屏也能接着放，老大可以锁屏听。
- 还没有视频：不写文字步骤，请老大发一个博主视频（小红书或 B 站分享链接），一天最多问一次；follow 出片后发视频卡 + plan 卡，老大点「就这样」再 todo-add / project-set（做法见 follow-video skill）。
- 白噪音、雨声不是练习：在对话里发音频卡，不做成待办。

## 提议卡
```json
{"board":"sleep","title":"今天补一下？","kind":"proposal","until":"14:30",
 "inputs":[{"id":"choice","label":"","type":"options","options":["中午睡 20 分钟","今晚按计划","今天不补"],"submit":"agent"}]}
```
