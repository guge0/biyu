"""forbidden_check 规则单测。"""
from __future__ import annotations

import tempfile, os
from pathlib import Path

import pytest

from biyu.lint_rules.base import LintContext
from biyu.lint_rules.forbidden_check import ForbiddenCheckRule


def _make_outline(content: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(path)


class TestForbiddenCheckRule:
    def test_white_space_exemption_info(self, tmp_path):
        """正例：白色空间结算相关情节，worldbook 有豁免条款，报 info。"""
        outline = _make_outline(
            "# 关键事件\n- 白色空间结算，李超意识被传送回现实世界\n"
        )
        try:
            ctx = LintContext(
                book_dir=tmp_path,
                worldbook={
                    "forbidden": [
                        "不得让秘境内的人/物/能力直接出现在现实世界（仅可通过白色空间奖励结算获得，"
                        "结算形式见 facts 中'白色空间结算豁免扩展'条目，包含意识等非物理形式）",
                    ],
                },
            )
            rule = ForbiddenCheckRule()
            issues = rule.check(outline, ctx)
            ws_issues = [i for i in issues if "D-24" in i.message]
            assert len(ws_issues) >= 1
            assert ws_issues[0].severity == "info"
        finally:
            outline.unlink()

    def test_dash_density_warning(self, tmp_path):
        """反例：破折号密度过高报 warning。"""
        dashes = "——" * 10
        outline = _make_outline(f"# 关键事件\n{dashes} 短文本\n")
        try:
            ctx = LintContext(
                book_dir=tmp_path,
                worldbook={"forbidden": ["禁令-破折号：严格遵循"]},
            )
            rule = ForbiddenCheckRule()
            issues = rule.check(outline, ctx)
            dash_issues = [i for i in issues if "破折号" in i.message]
            assert len(dash_issues) >= 1
            assert dash_issues[0].severity == "warning"
        finally:
            outline.unlink()

    def test_no_forbidden_clean(self, tmp_path):
        """正例：无 forbidden 触发，无 issue。"""
        outline = _make_outline("# 关键事件\n- 普通事件\n")
        try:
            ctx = LintContext(
                book_dir=tmp_path,
                worldbook={"forbidden": ["不得出现未注册角色"]},
            )
            rule = ForbiddenCheckRule()
            issues = rule.check(outline, ctx)
            assert len(issues) == 0
        finally:
            outline.unlink()
