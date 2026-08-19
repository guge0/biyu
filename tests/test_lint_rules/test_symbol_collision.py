"""symbol_collision 规则单测。"""
from __future__ import annotations

import tempfile, os
from pathlib import Path

import pytest

from biyu.lint_rules.base import LintContext
from biyu.lint_rules.symbol_collision import SymbolCollisionRule


def _make_outline(content: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(path)


class TestSymbolCollisionRule:
    def test_collision_detected(self, tmp_path):
        """反例：outline 出现已分配符号，报 warning。"""
        outline = _make_outline("---\npresent_characters:\n  - 张今空\n---\n\n"
                                "# 关键事件\n- 金色光晕包裹了他的身体\n")
        try:
            ctx = LintContext(
                book_dir=tmp_path,
                worldbook={
                    "visual_symbols": [
                        {"symbol": "金色光晕", "assigned_to": "外部观察者", "chapters": "CH12-15"},
                    ],
                },
            )
            rule = SymbolCollisionRule()
            issues = rule.check(outline, ctx)
            assert len(issues) >= 1
            assert issues[0].severity == "warning"
            assert "金色" in issues[0].message
        finally:
            outline.unlink()

    def test_no_collision_pass(self, tmp_path):
        """正例：outline 不含已分配符号，无 issue。"""
        outline = _make_outline("---\n---\n# 关键事件\n- 青铜色的盔甲闪光\n")
        try:
            ctx = LintContext(
                book_dir=tmp_path,
                worldbook={
                    "visual_symbols": [
                        {"symbol": "金色光晕", "assigned_to": "外部观察者", "chapters": "CH12-15"},
                    ],
                },
            )
            rule = SymbolCollisionRule()
            issues = rule.check(outline, ctx)
            assert len(issues) == 0
        finally:
            outline.unlink()

    def test_no_registry_skip(self, tmp_path):
        """无 visual_symbols 注册表时静默跳过。"""
        outline = _make_outline("# 关键事件\n- 金色光晕\n")
        try:
            ctx = LintContext(book_dir=tmp_path, worldbook={})
            rule = SymbolCollisionRule()
            issues = rule.check(outline, ctx)
            assert len(issues) == 0
        finally:
            outline.unlink()
