"""去重检测器 — 用 jaccard 相似度与近 3 章对比。

BLOCK 级（jaccard > 70% 时触发），因为章节内容重复是 30 章评审反馈的硬伤之一。
使用 Python stdlib 实现，不引入新依赖。
"""
from __future__ import annotations

import re

from biyu.auditor.base import AuditResult, BaseAuditor, Severity
from biyu.auditor.config import get_checker_config


def _char_ngrams(text: str, n: int = 4) -> set[str]:
    """将文本拆为字符级 n-gram 集合。"""
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _jaccard(set_a: set, set_b: set) -> float:
    """计算两个集合的 jaccard 相似度。"""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


class DedupAuditor(BaseAuditor):
    """与近 3 章做 jaccard 相似度检测。"""

    @property
    def name(self) -> str:
        return "dedup"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        book_dir = ctx.get("book_dir")
        chapter_num = ctx.get("chapter_num", 0)
        config = ctx.get("config", {})

        checker_cfg = get_checker_config(config, self.name)
        threshold = checker_cfg.get("jaccard_threshold", 0.7)

        if not book_dir:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="缺少 book_dir 上下文",
            )

        from pathlib import Path

        current_ngrams = _char_ngrams(chapter_text)
        max_sim = 0.0
        max_sim_ch = 0

        for prev_num in range(chapter_num - 1, max(chapter_num - 4, 0) - 1, -1):
            if prev_num < 1:
                break
            prev_path = Path(book_dir) / "chapters" / f"ch{prev_num}.md"
            if not prev_path.exists():
                continue
            prev_text = prev_path.read_text(encoding="utf-8")
            prev_ngrams = _char_ngrams(prev_text)
            sim = _jaccard(current_ngrams, prev_ngrams)
            if sim > max_sim:
                max_sim = sim
                max_sim_ch = prev_num

        if max_sim >= threshold:
            return AuditResult(
                checker=self.name,
                severity=Severity.BLOCK,
                message=f"与 ch{max_sim_ch} 的 jaccard={max_sim:.2%} >= {threshold:.0%}，疑似重复",
                details={"max_similarity": round(max_sim, 4), "similar_with_chapter": max_sim_ch},
            )

        return AuditResult(
            checker=self.name,
            severity=Severity.PASS,
            message=f"去重通过，最高 jaccard={max_sim:.2%}(与 ch{max_sim_ch})" if max_sim_ch else "去重通过，无历史章节可对比",
            details={"max_similarity": round(max_sim, 4), "similar_with_chapter": max_sim_ch},
        )
