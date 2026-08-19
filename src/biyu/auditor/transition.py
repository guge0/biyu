"""衔接检查 — 首段是否承接上一章末场景。

检查当前章节首段与上一章末段之间的场景连续性。
"""
from __future__ import annotations

from pathlib import Path

from biyu.auditor.base import AuditResult, BaseAuditor, Severity


def _get_first_paragraph(text: str) -> str:
    """取正文第一段（跳过空行）。"""
    for line in text.strip().split("\n"):
        line = line.strip()
        if line:
            return line
    return ""


def _get_last_paragraph(text: str) -> str:
    """取正文最后一段。"""
    lines = text.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line:
            return line
    return ""


class TransitionAuditor(BaseAuditor):
    """检查章节首段是否承接上一章末段。"""

    @property
    def name(self) -> str:
        return "transition"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        book_dir = ctx.get("book_dir")
        chapter_num = ctx.get("chapter_num", 0)

        if not book_dir or chapter_num <= 1:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="第一章或缺少上下文，跳过衔接检查",
            )

        prev_path = Path(book_dir) / "chapters" / f"ch{chapter_num - 1}.md"
        if not prev_path.exists():
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message=f"上一章 ch{chapter_num - 1} 不存在，跳过衔接检查",
            )

        prev_text = prev_path.read_text(encoding="utf-8")
        prev_tail = _get_last_paragraph(prev_text)
        curr_head = _get_first_paragraph(chapter_text)

        if not prev_tail or not curr_head:
            return AuditResult(
                checker=self.name, severity=Severity.SKIP,
                message="首段或末段为空，无法判断衔接",
            )

        # 简单启发式：检查首段是否包含末段的关键词（角色名、地点）
        # 以及是否出现承接性词汇
        transition_signals = ["接着", "随后", "于是", "这时", "此时", "就在", "突然"]
        has_transition = any(sig in curr_head for sig in transition_signals)

        # 检查角色名或地点是否有重叠
        # 从末段提取 2 字以上的词，看首段是否有重叠
        common_chars = set(prev_tail) & set(curr_head)
        overlap_ratio = len(common_chars) / max(len(set(prev_tail)), 1)

        if overlap_ratio < 0.3 and not has_transition:
            return AuditResult(
                checker=self.name, severity=Severity.WARN,
                message="首段与上一章末段关联度低，可能存在衔接断裂",
                details={
                    "prev_tail": prev_tail[:100],
                    "curr_head": curr_head[:100],
                    "overlap_ratio": round(overlap_ratio, 2),
                },
            )

        return AuditResult(
            checker=self.name, severity=Severity.PASS,
            message="衔接检查通过" + (" (含承接信号)" if has_transition else ""),
            details={
                "prev_tail": prev_tail[:100],
                "curr_head": curr_head[:100],
                "overlap_ratio": round(overlap_ratio, 2),
            },
        )
