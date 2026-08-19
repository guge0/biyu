"""Reviser prompt 构建 — 段落级改写。"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

REVISER_SYSTEM_PROMPT = """\
你是一位资深网文编辑。你的任务是根据审稿意见改写指定段落。

## 核心约束

1. **只改目标段落**：不要修改其他段落的内容
2. **字数控制**：改写后字数在原段落的 ±20% 范围内
3. **上下文衔接**：改写后的段落要与前后文自然衔接
4. **保持角色和设定**：不改变角色性格、能力、关系等设定
5. **只解决指定问题**：不要顺便"优化"其他内容

## 改写原则

- 保持原文的叙事风格和语气
- 只修改问题涉及的部分，尽量保留原文可用内容
- 如果建议涉及删除内容，直接删除即可
- 如果建议涉及替换内容，用等长或略短的内容替换

## 输出格式

只输出改写后的段落全文，不要加任何前缀、说明或 markdown 标记。
"""


class ReviserLocationError(Exception):
    """无法定位目标段落时抛出。"""


def _fuzzy_match(quoted_text: str, paragraph: str, threshold: float = 0.8) -> bool:
    """模糊匹配：忽略空白后比较，允许 LLM 引文略微变形。

    策略：取 quoted_text 前 20 字做子串匹配（忽略空白），
    如果子串匹配失败则用 SequenceMatcher 全文比较。
    """
    # 去空白
    clean_quote = re.sub(r'\s+', '', quoted_text)
    clean_para = re.sub(r'\s+', '', paragraph)

    # 子串匹配：取前 20 字
    prefix = clean_quote[:20]
    if len(prefix) >= 5 and prefix in clean_para:
        return True

    # SequenceMatcher 全文比较
    ratio = SequenceMatcher(None, clean_quote, clean_para).ratio()
    return ratio >= threshold


def find_target_paragraph(
    paragraphs: list[str],
    quoted_text: str = "",
    line: int | None = None,
    issue_id: str = "",
) -> int:
    """优先用 quoted_text 匹配段落，line 作为 fallback。

    Args:
        paragraphs: 章节按换行拆分的段落列表。
        quoted_text: Editor 输出的原文片段（30-50 字）。
        line: Editor 输出的大致行号（1-indexed）。
        issue_id: 用于错误信息的 issue ID。

    Returns:
        目标段落的 0-indexed 索引。

    Raises:
        ReviserLocationError: 无法定位段落。
    """
    # 1. 引文匹配（优先）
    if quoted_text:
        for idx, para in enumerate(paragraphs):
            if quoted_text in para or _fuzzy_match(quoted_text, para):
                return idx

    # 2. line 字段 fallback，带 bounds check
    if line is not None:
        idx = line - 1  # 1-indexed → 0-indexed
        if 0 <= idx < len(paragraphs):
            return idx

    # 3. 都失败，raise 明确异常
    raise ReviserLocationError(
        f"Cannot locate paragraph for issue {issue_id}: "
        f"quoted_text not found, line={line} out of range "
        f"(章节共 {len(paragraphs)} 段)"
    )


def build_reviser_prompt(
    chapter_text: str,
    paragraph_index: int,
    issue_description: str,
    fix_suggestion: str,
) -> str:
    """构建 Reviser 用户 prompt。

    Args:
        chapter_text: 完整章节文本。
        paragraph_index: 目标段落索引（从 0 开始）。
        issue_description: 问题描述。
        fix_suggestion: 修改建议。

    Returns:
        构建好的 prompt 字符串。
    """
    paragraphs = chapter_text.split("\n")

    # 获取目标段落及上下文（完整 bounds check）
    target = (
        paragraphs[paragraph_index]
        if 0 <= paragraph_index < len(paragraphs)
        else ""
    )
    prev_para = (
        paragraphs[paragraph_index - 1]
        if 0 <= paragraph_index - 1 < len(paragraphs)
        else ""
    )
    next_para = (
        paragraphs[paragraph_index + 1]
        if 0 <= paragraph_index + 1 < len(paragraphs)
        else ""
    )

    parts = [
        "请根据以下审稿意见改写指定段落。\n",
    ]
    if prev_para:
        parts.append(f"--- 上一段落 ---\n{prev_para}\n")
    parts.append(f"--- 目标段落（需要改写） ---\n{target}\n")
    if next_para:
        parts.append(f"--- 下一段落 ---\n{next_para}\n")
    parts.append(f"--- 审稿意见 ---\n{issue_description}\n")
    parts.append(f"--- 修改建议 ---\n{fix_suggestion}\n")
    parts.append("---\n请输出改写后的完整段落（只输出段落，不加说明）：")

    return "\n".join(parts)
