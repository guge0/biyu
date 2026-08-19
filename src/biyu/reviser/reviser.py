"""Reviser 核心 — 段落改写 + 成本记账。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class ReviserResult:
    """Reviser 改写结果。"""
    revised_paragraph: str
    cost: float
    paragraph_index: int
    success: bool
    error: str = ""


async def revise_paragraph(
    chapter_text: str,
    paragraph_index: int,
    issue_description: str,
    fix_suggestion: str,
    adapter,
) -> ReviserResult:
    """调用 Reviser 改写指定段落。

    Args:
        chapter_text: 完整章节文本。
        paragraph_index: 目标段落索引。
        issue_description: 问题描述。
        fix_suggestion: 修改建议。
        adapter: LLM adapter 实例。

    Returns:
        ReviserResult
    """
    from .prompts import REVISER_SYSTEM_PROMPT, build_reviser_prompt

    user_prompt = build_reviser_prompt(
        chapter_text=chapter_text,
        paragraph_index=paragraph_index,
        issue_description=issue_description,
        fix_suggestion=fix_suggestion,
    )

    messages = [
        {"role": "system", "content": REVISER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        resp = await adapter.generate(messages, temperature=0.3, max_tokens=4096)
        revised = resp.text.strip()
        if not revised:
            return ReviserResult(
                revised_paragraph="",
                cost=resp.cost,
                paragraph_index=paragraph_index,
                success=False,
                error="Reviser 返回空文本",
            )
        return ReviserResult(
            revised_paragraph=revised,
            cost=resp.cost,
            paragraph_index=paragraph_index,
            success=True,
        )
    except Exception as e:
        return ReviserResult(
            revised_paragraph="",
            cost=0.0,
            paragraph_index=paragraph_index,
            success=False,
            error=str(e),
        )


def apply_revision(chapter_text: str, paragraph_index: int, revised_paragraph: str) -> str:
    """将改写后的段落替换回章节文本。

    Args:
        chapter_text: 完整章节文本。
        paragraph_index: 目标段落索引。
        revised_paragraph: 改写后的段落。

    Returns:
        替换后的完整章节文本。
    """
    paragraphs = chapter_text.split("\n")
    if paragraph_index < 0 or paragraph_index >= len(paragraphs):
        return chapter_text
    paragraphs[paragraph_index] = revised_paragraph
    return "\n".join(paragraphs)
