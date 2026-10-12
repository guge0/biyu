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


def read_chapter_costs(book_dir: Path) -> dict[int, float] | None:
    """按章聚合管线成本(<书>/logs/cost_log.csv),返回 {章号: 合计}。

    无文件返回 None。沿用 _writing_cost 的口径:章号非正或非数字的行跳过
    (propose 等书级行),stage=editor_total 的聚合行跳过(避免双计),金额
    无效则报错(台账是唯一可信源,坏了要喊)。
    """
    from decimal import Decimal, InvalidOperation

    path = book_dir / "logs" / "cost_log.csv"
    if not path.exists():
        return None
    by_chapter: dict[int, Decimal] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"chapter", "stage", "cost_cny"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("成本记录缺少必要列")
        for line_no, row in enumerate(reader, 2):
            try:
                chapter = int(str(row.get("chapter", "")).strip())
            except ValueError:
                continue
            if chapter < 1 or row.get("stage") == "editor_total":
                continue
            try:
                cost = Decimal(str(row.get("cost_cny", "")).strip())
            except InvalidOperation as exc:
                raise ValueError(f"成本记录第 {line_no} 行金额无效") from exc
            if not cost.is_finite() or cost < 0:
                raise ValueError(f"成本记录第 {line_no} 行金额无效")
            by_chapter[chapter] = by_chapter.get(chapter, Decimal("0")) + cost
    return {chapter: float(total) for chapter, total in by_chapter.items()}


def read_book_extra_cost(book: str, data_root: Path | None = None) -> float:
    """根级 cost_log.csv 里属于本书的起名/对话等书级调用合计。

    无文件返回 0.0;单行损坏跳过(该文件是追加式历史件,不因一行阻断概览)。
    """
    from decimal import Decimal, InvalidOperation

    if data_root is None:
        data_root = get_data_root()
    path = data_root / _COST_LOG_PATH
    if not path.exists():
        return 0.0
    total = Decimal("0")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if str(row.get("book", "")).strip() != book:
                    continue
                try:
                    cost = Decimal(str(row.get("cost", "")).strip())
                except InvalidOperation:
                    continue
                if cost.is_finite() and cost > 0:
                    total += cost
    except (csv.Error, OSError):
        return 0.0
    return float(total)
