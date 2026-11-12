# 表情包生成器

对话里的 24 个 Q 版线条表情（∞ 小人）的设计稿和编译器。

- `geo.py`：∞ 的曲线（和 App 头像同一条，竖向放大 1.3 倍，更圆）
- `char.py`：小人的身体、眼睛、嘴、腮红、脚
- `set.py`：24 个表情（作息 / 夸夸 / 陪伴 / 提醒），每个是一段 SVG（viewBox 120）
- `css.py`：设计稿用的动画（CSS 关键帧）
- `compile.py`：把 SVG 编成 App 用的 `Stickers.json`（只剩 M/L/C/Z 路径、矩阵、动画种类和关键帧）

改了表情以后重新生成（在仓库根目录跑）：

```sh
cd scripts/stickers && python3 compile.py ../../ios/PivisHealth/Stickers.json
```

服务器的 `pivis_health/cards.py` 里有一份表情名单（`STICKERS`），名字改了要一起改；`tests/test_b58_tone.py` 会对两边。
