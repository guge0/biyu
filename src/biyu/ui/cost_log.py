"""D-93 中央成本台账 — data/cost_log.csv append-only。

格式:
  ts, task, book, session, model, cost

所有 LLM 调用(chat SSE / naming / summarize / propose)写入同一 CSV,
月预算核对以台账为准。会话内嵌记账照旧,不冲突。
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from biyu.config import get_data_root

_COST_LOG_PATH = "cost_log.csv"
_HEADER = ["ts", "task", "book", "session", "model", "cost"]

# 已知模型名映射(适配器 key → 显示名)
_MODEL_LABELS: dict[str, str] = {
    "v4_flash": "deepseek-v4-flash",
    "v4_pro": "deepseek-v4-pro",
    "v3": "deepseek-v3",
    "r1": "deepseek-r1",
    "glm": "glm-4.6",
}


def _resolve_path(data_root: Path | None = None) -> Path:
    if data_root is None:
        data_root = get_data_root()
    return data_root / _COST_LOG_PATH


def write_cost_log(
    task: str,
    book: str,
    session: str,
    cost: float,
    model: str = "",
    data_root: Path | None = None,
) -> Path:
    """Append 一行成本记录到中央 cost_log.csv。

    Args:
        task: 任务类型(chat / naming / summarize / propose)
        book: 书名
        session: 会话 ID(session_id 或 propose session_id)
        cost: LLM 调用成本(CNY)
        model: 模型名(如 deepseek-v4-flash),可空
        data_root: 数据根目录(None 自动获取)

    Returns:
        实际写入的文件路径
    """
    log_path = _resolve_path(data_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()

    # 模型名查表
    model_label = _MODEL_LABELS.get(model, model)

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    with open(log_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(_HEADER)
        writer.writerow([ts, task, book, session, model_label, f"{cost:.6f}"])

    return log_path
