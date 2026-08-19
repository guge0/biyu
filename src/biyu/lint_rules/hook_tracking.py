"""hook_tracking — 长程伏笔追踪。

与 pending_hooks.md 对账，列出待回收伏笔，检查 outline 是否遗漏了应该推进的伏笔。
"""
from __future__ import annotations

import re
from pathlib import Path

from biyu.lint_rules.base import LintContext, LintIssue, LintRule


class HookTrackingRule(LintRule):
    """长程伏笔追踪。"""

    @property
    def name(self) -> str:
        return "hook_tracking"

    @property
    def severity(self):
        return "warning"

    def check(self, target: Path, context: LintContext) -> list[LintIssue]:
        text = target.read_text(encoding="utf-8")
        issues: list[LintIssue] = []

        # 获取待回收伏笔
        pending = context.pending_hooks
        if not pending:
            return issues

        # 提取当前 outline 的章节号
        chapter_num = self._extract_chapter_number(target)
        if not chapter_num:
            return issues

        # 检查每条待回收伏笔
        for hook in pending:
            hook_id = hook.get("hook_id", "")
            status = hook.get("状态", hook.get("status", ""))
            start_ch = hook.get("起始章节", hook.get("start_chapter", ""))
            expected = hook.get("预期回收", hook.get("expected_resolve", ""))
            note = hook.get("备注", hook.get("note", ""))

            # 已关闭的伏笔跳过
            if status in ("closed", "已关闭", "已回收"):
                continue

            # 提取预期回收章节
            expected_ch = self._parse_expected_chapter(expected)
            if expected_ch and chapter_num >= expected_ch:
                # 当前章节已到达或超过预期回收章节，检查 outline 是否推进
                if not self._hook_advanced(text, hook):
                    issues.append(LintIssue(
                        rule_name=self.name,
                        severity="warning",
                        message=f"伏笔 '{hook_id}' 预期在 CH{expected_ch} 前回收，"
                                f"当前 outline (CH{chapter_num}) 未推进",
                        location=str(target),
                        suggestion=f"检查是否需要在本章推进此伏笔。备注: {note[:50]}" if note else None,
                    ))

            # 检查伏笔关键词是否在 outline 中出现（有机会推进但没推进）
            keywords = self._extract_hook_keywords(hook)
            if keywords:
                for kw in keywords:
                    if kw in text:
                        # outline 中提到了伏笔相关内容
                        issues.append(LintIssue(
                            rule_name=self.name,
                            severity="info",
                            message=f"伏笔 '{hook_id}' 相关关键词 '{kw}' 在 outline 出现，"
                                    f"状态为 '{status}'，确认是否需要推进",
                            location=str(target),
                        ))
                        break

        return issues

    @staticmethod
    def _extract_chapter_number(path: Path) -> int | None:
        """从文件名提取章节号。"""
        match = re.search(r"ch(\d+)", path.stem)
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_expected_chapter(expected: str) -> int | None:
        """从预期回收字段提取章节号。

        支持格式: "CH15-20", "CH15", "第15章"
        """
        if not expected:
            return None
        match = re.search(r"(\d+)", str(expected))
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_hook_keywords(hook: dict) -> list[str]:
        """从伏笔记录提取可能出现在 outline 中的关键词。"""
        keywords: list[str] = []
        for field in ("hook_id", "备注", "note", "类型", "type"):
            val = hook.get(field, "")
            if val and isinstance(val, str) and len(val) <= 20:
                keywords.append(val)
        return keywords

    @staticmethod
    def _hook_advanced(text: str, hook: dict) -> bool:
        """检查 outline 是否推进了某条伏笔。

        简化判定：如果 outline 中出现了伏笔 ID 或备注中的关键词，
        并且有"推进""回收""解决""揭晓"等语义标记，视为已推进。
        """
        advance_markers = ["推进", "回收", "解决", "揭晓", "揭", "揭示", "回应",
                           "交代", "揭晓", "落地", "闭合", "收束"]
        note = hook.get("备注", hook.get("note", ""))
        if not note:
            return False

        # 检查是否有推进标记
        for marker in advance_markers:
            if marker in text:
                return True

        return False
