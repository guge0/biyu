"""Editor 字面伪影自动修。"""
from __future__ import annotations

from .parser import EditorIssue


def auto_fix_issues(chapter_text: str, issues: list[EditorIssue]) -> tuple[str, int]:
    """自动修字面伪影类 issue（仅 auto_fixable=True 的）。

    Returns:
        (fixed_text, fixed_count)
    """
    fixable = [i for i in issues if i.auto_fixable]
    if not fixable:
        return chapter_text, 0

    fixed = chapter_text
    count = 0

    # 按位置倒序修复
    # 先找所有 quote 在原文中的位置
    fixes: list[tuple[int, int, str]] = []
    for issue in fixable:
        if not issue.quote:
            continue
        idx = fixed.rfind(issue.quote)  # rfind 更安全
        if idx == -1:
            continue

        if issue.fix_suggestion == "delete":
            fixes.append((idx, idx + len(issue.quote), ""))
        elif issue.fix_suggestion.startswith("replace_with: "):
            replacement = issue.fix_suggestion[len("replace_with: "):]
            fixes.append((idx, idx + len(issue.quote), replacement))

    # 按位置倒序排序
    fixes.sort(key=lambda x: x[0], reverse=True)

    for start, end, replacement in fixes:
        fixed = fixed[:start] + replacement + fixed[end:]
        count += 1

    return fixed, count
