"""hook_tracking 规则单测。"""
from __future__ import annotations

import tempfile, os
from pathlib import Path

import pytest

from biyu.lint_rules.base import LintContext
from biyu.lint_rules.hook_tracking import HookTrackingRule


def _make_outline(name: str, content: str) -> Path:
    """创建临时 outline 文件，文件名包含 ch 前缀以支持章节号提取。"""
    dir_ = tempfile.mkdtemp()
    path = Path(dir_) / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


class TestHookTrackingRule:
    def test_overdue_hook_warning(self, tmp_path):
        """反例：伏笔已过预期回收章节但未推进，报 warning。"""
        # 模拟 ch15.md（ch20 的 outline）
        outline = _make_outline("ch20", "# 关键事件\n- 普通事件\n")
        try:
            ctx = LintContext(
                book_dir=tmp_path,
                pending_hooks=[
                    {
                        "hook_id": "hook_05",
                        "状态": "open",
                        "预期回收": "CH18",
                        "备注": "张父与老樵的渊源",
                    },
                ],
            )
            rule = HookTrackingRule()
            issues = rule.check(outline, ctx)
            assert len(issues) >= 1
            assert any("hook_05" in i.message for i in issues)
        finally:
            outline.unlink()

    def test_closed_hook_skip(self, tmp_path):
        """正例：已关闭的伏笔不报。"""
        outline = _make_outline("ch20", "# 关键事件\n- 普通事件\n")
        try:
            ctx = LintContext(
                book_dir=tmp_path,
                pending_hooks=[
                    {
                        "hook_id": "hook_01",
                        "状态": "closed",
                        "预期回收": "CH10",
                        "备注": "已回收",
                    },
                ],
            )
            rule = HookTrackingRule()
            issues = rule.check(outline, ctx)
            assert len(issues) == 0
        finally:
            outline.unlink()

    def test_no_pending_hooks_clean(self, tmp_path):
        """无伏笔时不报。"""
        outline = _make_outline("ch20", "# 关键事件\n- 普通事件\n")
        try:
            ctx = LintContext(book_dir=tmp_path, pending_hooks=[])
            rule = HookTrackingRule()
            issues = rule.check(outline, ctx)
            assert len(issues) == 0
        finally:
            outline.unlink()
