"""pivis-health：本地优先的个人健康内核。

分层：readonly（客观库只读）→ sleep/baselines/whoop/insights（确定性计算）
→ rules（三级监测）→ report（装配）→ tools/cli/web（接口）。

铁律（继承自 hermes 时代的 SKILL 契约）：
- 数字全部由本包的确定性代码计算，模型只做解读；
- 缺数据 ≠ 正常，也 ≠ 异常，一律如实标注；
- 所有规则输出 non_diagnostic，不做诊断。
"""

__version__ = "0.1.0"
