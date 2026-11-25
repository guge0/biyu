"""S-7c：生成类动作确认框里的预估金额（不调用模型）。

有本书历史账（logs/cost_log.csv）时，按历史每章生成花费给区间；
新书没有历史时，按写手模型单价相对 DeepSeek v4_pro 的倍数，套用实跑基线给区间。
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

HISTORY_PLACEHOLDER = "按本书历史记录预估"

# 写一章（写手 + 编辑审读，不含必检项）在 DeepSeek v4_pro 上的实跑基线（2026-11-19 S-7 实跑：¥0.19）。
_BASE_LOW, _BASE_HIGH = 0.15, 0.40
_BASE_OUTPUT_PRICE = 0.006  # v4_pro 每千输出 token 单价
# editor=工作台 force_pending 审读行(S-7d);editor_total=CLI 路径聚合行,两代都吃
_GENERATION_STAGES = {"writer", "editor", "editor_total", "checklist_f4", "rewrite", "revise", "polisher"}


def _history_totals(book_dir: Path) -> list[float]:
    path = book_dir / "logs" / "cost_log.csv"
    if not path.exists():
        return []
    per_chapter: dict[str, float] = defaultdict(float)
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if (row.get("stage") or "") not in _GENERATION_STAGES:
                    continue
                try:
                    per_chapter[row.get("chapter") or "?"] += float(row.get("cost_cny") or 0)
                except ValueError:
                    continue
    except OSError:
        return []
    return [v for v in per_chapter.values() if v > 0]


def _price_ratio() -> float:
    try:
        from biyu.llm import ModelRegistry
        from biyu.config import get_config_path

        reg = ModelRegistry(get_config_path())
        alias = str(reg._configured_stage_alias("writer") or reg.get_pipeline_config().get("writer") or "")
        model = reg._models.get(alias) or {}
        price = float(model.get("cost_per_1k_output") or 0)
        if price > 0:
            return max(0.2, min(price / _BASE_OUTPUT_PRICE, 10.0))
    except Exception:
        pass
    return 1.0


def _fmt(low: float, high: float) -> str:
    return f"约 ¥{low:.2f}–{high:.2f}（以模型实际计费为准）"


def estimate_text(action_id: str, book_dir: Path | None, placeholder: str) -> str:
    """把注册表里的占位文案换成带数字的区间；其它文案原样返回。"""
    if placeholder != HISTORY_PLACEHOLDER:
        return placeholder
    history = _history_totals(book_dir) if book_dir else []
    if history:
        avg = sum(history) / len(history)
        return _fmt(avg * 0.7, avg * 1.5) + f"，按本书 {len(history)} 章历史"
    ratio = _price_ratio()
    return _fmt(_BASE_LOW * ratio, _BASE_HIGH * ratio) + "，新书按经验估算"
