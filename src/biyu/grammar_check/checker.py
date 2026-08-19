"""grammar_check 主检查逻辑 — 错别字/病句/占位符检测。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .whitelist import load_whitelist


@dataclass
class GrammarIssue:
    """一条 grammar 问题。"""
    type: str          # typo / placeholder / repeated_char
    position: int      # 字符偏移
    original: str      # 原文片段
    suggestion: str    # 建议修正
    confidence: float  # 0-1

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "position": self.position,
            "original": self.original,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
        }


@dataclass
class GrammarResult:
    """grammar_check 输出。"""
    typos: list[GrammarIssue] = field(default_factory=list)
    placeholders: list[GrammarIssue] = field(default_factory=list)
    repeated_chars: list[GrammarIssue] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.typos or self.placeholders or self.repeated_chars)

    @property
    def total_count(self) -> int:
        return len(self.typos) + len(self.placeholders) + len(self.repeated_chars)

    def to_dict(self) -> dict:
        return {
            "typos": [i.to_dict() for i in self.typos],
            "placeholders": [i.to_dict() for i in self.placeholders],
            "repeated_chars": [i.to_dict() for i in self.repeated_chars],
        }


# ---------------------------------------------------------------------------
# 占位符正则
# ---------------------------------------------------------------------------
# 来自 Phase 4 实际出现过的占位符模式
PLACEHOLDER_PATTERNS = [
    (re.compile(r'\[NAME\]', re.IGNORECASE), "delete", "占位符 [NAME]"),
    (re.compile(r'\{character\}', re.IGNORECASE), "delete", "占位符 {character}"),
    (re.compile(r'\{[a-z_]+\}', re.IGNORECASE), "delete", "占位符 {...}"),
    (re.compile(r'章末句'), "delete", "prompt 元词 '章末句'"),
    (re.compile(r'本章结束'), "delete", "prompt 元词 '本章结束'"),
    (re.compile(r'结尾段'), "delete", "prompt 元词 '结尾段'"),
    (re.compile(r'Layer\s*\d'), "delete", "prompt 元词 'Layer'"),
    (re.compile(r'硬规则'), "delete", "prompt 元词 '硬规则'"),
    (re.compile(r'注意事项'), "delete", "prompt 元词 '注意事项'"),
    (re.compile(r'第一人称|第三人称'), "delete", "prompt 元词 '人称'"),
]


# ---------------------------------------------------------------------------
# 常见错别字映射（基于 Phase 4 实际问题）
# ---------------------------------------------------------------------------
COMMON_TYPOS: dict[str, str] = {
    "的的": "的",
    "了了": "了",
    "是是": "是",
    "在在": "在",
    "不不": "不",
    "他他": "他",
    "我我": "我",
}

# 连续重复字检测（排除 "妈妈" "爸爸" "哥哥" "姐姐" "弟弟" "妹妹" "舅舅" "叔叔" "姑姑" 等叠词）
REPEATED_CHAR_EXCLUDES = {
    "妈", "爸", "哥", "姐", "弟", "妹", "舅", "叔", "姑", "伯",
    "爷", "奶", "婆", "公", "太", "佬", "宝", "宝宝",
    "高高兴兴", "慢慢", "轻轻", "悄悄", "静静", "偷偷",
    "紧紧", "深深", "远远", "近近", "长长", "短短",
}


def check_chapter(chapter_text: str, book_dir: Path) -> GrammarResult:
    """检查章节中的错别字 / 占位符 / 重复字。

    Args:
        chapter_text: 章节正文。
        book_dir: 书目录（用于加载白名单）。

    Returns:
        GrammarResult 包含所有发现的问题。
    """
    whitelist = load_whitelist(book_dir)
    result = GrammarResult()

    # 1. 占位符扫描
    for pattern, action, desc in PLACEHOLDER_PATTERNS:
        for m in pattern.finditer(chapter_text):
            original = m.group()
            # 检查是否在白名单中（不太可能，但保险）
            if original in whitelist:
                continue
            result.placeholders.append(GrammarIssue(
                type="placeholder",
                position=m.start(),
                original=original,
                suggestion="delete",
                confidence=1.0,
            ))

    # 2. 常见错别字（连续重复）
    for typo, fix in COMMON_TYPOS.items():
        start = 0
        while True:
            idx = chapter_text.find(typo, start)
            if idx == -1:
                break
            # 上下文检查：前后文字
            context = chapter_text[max(0, idx - 2):idx + len(typo) + 2]
            # 白名单保护
            if _is_whitelist_protected(context, whitelist):
                start = idx + 1
                continue
            result.typos.append(GrammarIssue(
                type="typo",
                position=idx,
                original=typo,
                suggestion=fix,
                confidence=0.9,
            ))
            start = idx + 1

    # 3. 三连重复字检测（如 "看看看" "说说说"）
    _detect_triple_chars(chapter_text, whitelist, result)

    return result


def auto_fix(chapter_text: str, issues: GrammarResult) -> tuple[str, int]:
    """自动修复：占位符删除 + 高置信度错别字替换。

    Returns:
        (fixed_text, fixed_count)
    """
    fixed = chapter_text
    count = 0

    # 按位置倒序修复（避免偏移量变化）
    all_issues = sorted(
        issues.placeholders + [i for i in issues.typos if i.confidence >= 0.9],
        key=lambda i: i.position,
        reverse=True,
    )

    for issue in all_issues:
        if issue.suggestion == "delete":
            # 删除占位符
            fixed = fixed[:issue.position] + fixed[issue.position + len(issue.original):]
            count += 1
        elif issue.suggestion and issue.confidence >= 0.9:
            # 替换错别字
            fixed = (
                fixed[:issue.position]
                + issue.suggestion
                + fixed[issue.position + len(issue.original):]
            )
            count += 1

    return fixed, count


def _is_whitelist_protected(context: str, whitelist: set[str]) -> bool:
    """检查上下文是否受白名单保护。"""
    for word in whitelist:
        if word in context:
            return True
    return False


def _detect_triple_chars(
    text: str, whitelist: set[str], result: GrammarResult
) -> None:
    """检测三连重复字（如 "看看看"）。"""
    i = 0
    while i < len(text) - 2:
        c = text[i]
        if '\u4e00' <= c <= '\u9fff' and text[i + 1] == c and text[i + 2] == c:
            # 排除合法叠词
            if c in REPEATED_CHAR_EXCLUDES:
                i += 1
                continue
            # 检查是否四连以上
            end = i + 3
            while end < len(text) and text[end] == c:
                end += 1
            original = text[i:end]
            # 白名单保护
            if original in whitelist:
                i = end
                continue
            result.repeated_chars.append(GrammarIssue(
                type="repeated_char",
                position=i,
                original=original,
                suggestion=c,
                confidence=0.8,
            ))
            i = end
        else:
            i += 1
