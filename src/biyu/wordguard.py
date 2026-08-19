"""篇幅观察器 — 统计 CJK 字数并给出非阻断提醒。"""
from __future__ import annotations

from dataclasses import dataclass


def count_cjk_chars(text: str) -> int:
    """Count CJK Unified Ideographs in text."""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


@dataclass
class WordGuardResult:
    """Result of word guard enforcement."""
    text: str
    word_count: int
    continued: bool = False
    continuation_word_count: int = 0
    warning: str = ""


async def enforce_floor(
    text: str,
    target: int,
    floor: int,
    continuation_fn,
) -> WordGuardResult:
    """Report a short chapter without changing it or spending another LLM call.

    Args:
        text: The current text.
        target: Target word count for the chapter.
        floor: Minimum acceptable word count.
        continuation_fn: Kept for call-site compatibility; deliberately never called.

    Returns:
        WordGuardResult with the final text and metadata.

    Rules:
        - text >= floor: return as-is
        - text < floor: return as-is with a human-readable warning
        - word count alone never triggers generation or concatenation
    """
    current_count = count_cjk_chars(text)

    if current_count >= floor:
        return WordGuardResult(text=text, word_count=current_count)

    return WordGuardResult(
        text=text,
        word_count=current_count,
        warning=f"篇幅 {current_count} 字，低于参考篇幅 {floor} 字；内容完整则无需补写",
    )
