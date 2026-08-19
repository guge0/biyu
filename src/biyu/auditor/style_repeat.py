"""句式重复检查 — 统计本章 + 近 3 章的 AI 句式模板使用频率。

30 章评审发现 AI 味浓是因为高频使用特定句式模板。
本检查器统计 STYLE_BLACKLIST 中每个模板在当前章和近 3 章的出现次数。
"""
from __future__ import annotations

import re
from pathlib import Path

from biyu.auditor.base import AuditResult, BaseAuditor, Severity
from biyu.auditor.config import get_checker_config


# 复用 v3_opening 的 STYLE_BLACKLIST
def _get_style_blacklist() -> list[str]:
    try:
        from biyu.prompts.v3_opening import STYLE_BLACKLIST
        return STYLE_BLACKLIST
    except ImportError:
        return [
            "不是[^。，]*[，。](?:而)?是",  # 不是X，是Y / 不是X，而是Y / 不是X。是Y
            "不是[^。，]*[，。]不是",       # 不是X，不是Y
            "与其说.*不如说",
            "在这一刻",
            "仿佛.*一般",
            "仿佛.*一样",
            "心中(暗想|暗叹|不由得|不禁)",
            "一股.*涌上心头",
            "不由得.*起来",
            "眼眸中闪过一丝",
            "嘴角勾起一抹",
            "刹那间",
        ]


def _count_pattern(text: str, pattern: str) -> int:
    """统计 pattern 在 text 中的出现次数。"""
    try:
        return len(re.findall(pattern, text))
    except re.error:
        return 0


class StyleRepeatAuditor(BaseAuditor):
    """统计 AI 句式模板在当前章和近 3 章的使用频率。"""

    @property
    def name(self) -> str:
        return "style_repeat"

    def run(self, chapter_text: str, ctx: dict) -> AuditResult:
        book_dir = ctx.get("book_dir")
        chapter_num = ctx.get("chapter_num", 0)
        config = ctx.get("config", {})

        checker_cfg = get_checker_config(config, self.name)
        max_per_chapter = checker_cfg.get("max_per_chapter", 1)
        max_per_3chapters = checker_cfg.get("max_per_3chapters", 2)

        blacklist = _get_style_blacklist()

        # 统计当前章
        current_counts = {}
        for pattern in blacklist:
            cnt = _count_pattern(chapter_text, pattern)
            if cnt > 0:
                current_counts[pattern] = cnt

        # 统计近 3 章
        recent_counts: dict[str, int] = {}
        if book_dir:
            for prev_num in range(chapter_num - 1, max(chapter_num - 4, 0) - 1, -1):
                if prev_num < 1:
                    break
                prev_path = Path(book_dir) / "chapters" / f"ch{prev_num}.md"
                if not prev_path.exists():
                    continue
                prev_text = prev_path.read_text(encoding="utf-8")
                for pattern in blacklist:
                    cnt = _count_pattern(prev_text, pattern)
                    if cnt > 0:
                        recent_counts[pattern] = recent_counts.get(pattern, 0) + cnt

        # 合并统计
        total_counts = {}
        for p in set(list(current_counts.keys()) + list(recent_counts.keys())):
            total_counts[p] = current_counts.get(p, 0) + recent_counts.get(p, 0)

        # 检查违规
        violations = []
        for pattern, cnt in current_counts.items():
            if cnt > max_per_chapter:
                violations.append(f"'{pattern}' 在本章出现 {cnt} 次（限制 {max_per_chapter}）")
        for pattern, cnt in total_counts.items():
            if cnt > max_per_3chapters:
                violations.append(f"'{pattern}' 在近 4 章共出现 {cnt} 次（限制 {max_per_3chapters}）")

        if violations:
            return AuditResult(
                checker=self.name, severity=Severity.WARN,
                message=f"发现 {len(violations)} 处句式重复: {'; '.join(violations)}",
                details={
                    "current_counts": current_counts,
                    "recent_3ch_counts": recent_counts,
                    "violations": violations,
                },
            )

        return AuditResult(
            checker=self.name, severity=Severity.PASS,
            message="句式重复检查通过",
            details={"current_counts": current_counts, "recent_3ch_counts": recent_counts},
        )
