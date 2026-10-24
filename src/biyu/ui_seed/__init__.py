"""ui_seed — S-3 安装版首启种子(示例书《死亡回溯》)与无 Key 体验层数据。

公开入口:
- maybe_seed_sample_book(data_root): 幂等种入,只在「显式开启 + 书架为空」时执行。
- sample_book_summary(data_root): 读取种入状态(调试/验收用)。

设计边界(design.md):
- 种子走正常 create_book + 既有资产 API,书本体是普通书(可玩可删可回收);
- 幂等标记防重复;书架非空绝不种入(不污染存量用户);
- 候选稿批注与 AI 味超标由真实 run_audit 生成,不改检查器与阈值。
"""
from biyu.ui_seed.sample_book import (
    MARKER_FILENAME,
    maybe_seed_sample_book,
    sample_book_summary,
)

__all__ = [
    "MARKER_FILENAME",
    "maybe_seed_sample_book",
    "sample_book_summary",
]
