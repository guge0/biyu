"""成本日志模块(P7-1 T8 + P9-C1 单口径)。

propose 命令的成本日志:
  per-book csv(同 pipeline._log_cost 格式):
    timestamp, chapter, stage, cost_cny, latency_s
    路径:data_root / <name> / "logs" / "cost_log.csv"

propose 没有"章节"概念,子目录 chapter 字段固定写 'propose'。
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def log_propose_cost(
    data_root: Path,
    name: str,
    stage: str,
    cost_cny: float,
    latency_s: float,
    log_path: Path | None = None,
    *,
    session: str = "",
    model: str = "",
) -> Path:
    """Append 一行成本记录到 per-book cost_log.csv(单口径,无双写)。

    Args:
        data_root: 项目数据根目录(用于推导默认路径)
        name: 书名/临时名
        stage: 阶段名(如 'analyzer' / 'craft' / 'router' / 'tropes' / 'redblue')
        cost_cny: 单次成本(CNY)
        latency_s: 单次耗时(秒)
        log_path: 显式路径(优先用),None 时走默认

    Returns:
        实际写入的文件路径
    """
    if log_path is None:
        log_path = data_root / name / "logs" / "cost_log.csv"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()

    with open(log_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "chapter", "stage", "cost_cny", "latency_s"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "propose",  # chapter 字段固定 'propose'
            stage,
            f"{cost_cny:.4f}",
            f"{latency_s:.1f}",
        ])

    return log_path
