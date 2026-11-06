# 常见流程

## 午睡（分两步，时间和时长让老大定，不要替他定）
1. 老大在提议里选了午睡 → 先把这张卡改成问「几点、多久」（时长最多 20 分钟，15:00 前结束）：
```json
{"title":"几点睡、睡多久？","kind":"fields","submit_label":"就这样","note":"不超过 20 分钟，15:00 前结束",
 "inputs":[{"id":"start","label":"几点躺下","type":"options","options":["12:30","13:00","13:30"],"submit":"agent"},
           {"id":"len","label":"睡多久","type":"options","options":["10 分钟","15 分钟","20 分钟"],"submit":"agent"}]}
```
2. 收到回答后（例：13:00、20 分钟）→ 这张卡改成计时卡，再加一张开始前 10 分钟的放松：
```json
{"title":"午睡 20 分钟","when":"13:00","kind":"timer","duration_min":20,"alarm":"13:20","inputs":[]}
```
```json
{"board":"sleep","when":"12:50","title":"午睡前放松","kind":"follow",
 "steps":[{"title":"慢呼吸跟练","media":{"kind":"audio","title":"慢呼吸","url":"<media-library 里的 url>","duration_min":6}}]}
```
（alarm = 开始时间 + 时长。）

## 跟做卡
拉伸、热身这类带动作的步骤用视频（media-library 里 kind=video 的，跟做页会把视频嵌进页面）；呼吸、冥想用音频；没有合适的就只写步骤和时长。
```json
{"board":"sleep","when":"23:30","title":"床外拉伸 + 呼吸","kind":"follow","note":"在床外做，床只用来睡",
 "steps":[{"title":"睡前轻拉伸","media":{"kind":"video","title":"睡前轻拉伸","url":"<media-library 里 kind=video 的 url>","duration_min":15}},
          {"title":"慢呼吸跟练","media":{"kind":"audio","title":"慢呼吸","url":"<media url>","duration_min":6}}],
 "duration_min":21}
```

## 提议卡
```json
{"board":"sleep","title":"今天补一下？","kind":"proposal","until":"14:30",
 "inputs":[{"id":"choice","label":"","type":"options","options":["中午睡 20 分钟","今晚按计划","今天不补"],"submit":"agent"}]}
```
