"""后处理层 — 在 Auditor 之前对生成正文做确定性的、可逆的修正。

设计原则:
- 纯正则 / 字符串操作,不调 LLM,确定性
- 每个 fixer 单文件单职责
- 修改前后必须保留 raw 版本(在 logs/ 下)
- 单测覆盖每条规则
"""
from biyu.postproc.dash_fixer import fix_dashes, DashFixResult

__all__ = ["fix_dashes", "DashFixResult"]
