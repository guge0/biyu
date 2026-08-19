"""worldbook_check (引用校验) 规则单测。"""
from __future__ import annotations

import tempfile, os
from pathlib import Path

import pytest

from biyu.lint_rules.base import LintContext
from biyu.lint_rules.worldbook_check import WorldbookRefRule


def _make_outline(content: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(path)


@pytest.fixture
def worldbook():
    return {
        "facts": [
            "主角金手指：在秘境结算获取奖励时，奖励会发生'变异'",
            "镇异局：秘境出现后政府成立的官方机构",
        ],
        "power_system": {
            "name": "职业者修炼体系",
            "rules": ["境界共九境"],
        },
        "geography": ["南城：华国大城市"],
        "factions": ["镇异局：政府机构"],
    }


@pytest.fixture
def characters():
    return [
        {"name": "张今空", "abilities": "金手指『奖励变异』",
         "aliases": {"called_by": {"周大龙": "今空"}}},
        {"name": "楚老"},
    ]


class TestWorldbookRefRule:
    def test_known_ref_pass(self, tmp_path, worldbook, characters):
        """正例：引用的术语在 worldbook 中存在，不报。"""
        outline = _make_outline(
            "# 关键事件\n- 张今空使用『奖励变异』能力\n- 镇异局介入\n"
        )
        try:
            ctx = LintContext(
                book_dir=tmp_path, worldbook=worldbook, characters=characters,
            )
            rule = WorldbookRefRule()
            issues = rule.check(outline, ctx)
            # 奖励变异、镇异局 都是已知引用
            ref_issues = [i for i in issues if "引用校验" in i.message]
            assert len(ref_issues) == 0
        finally:
            outline.unlink()

    def test_unknown_ref_warning(self, tmp_path, worldbook, characters):
        """反例：引用未知术语，报 warning。"""
        outline = _make_outline(
            "# 关键事件\n- 使用『时空断裂』能力\n"
        )
        try:
            ctx = LintContext(
                book_dir=tmp_path, worldbook=worldbook, characters=characters,
            )
            rule = WorldbookRefRule()
            issues = rule.check(outline, ctx)
            ref_issues = [i for i in issues if "时空断裂" in i.message]
            assert len(ref_issues) >= 1
            assert "worldbook/characters 中未找到" in ref_issues[0].message
        finally:
            outline.unlink()

    def test_generic_term_skip(self, tmp_path, worldbook, characters):
        """正例：通用术语不需要注册，不报。"""
        outline = _make_outline(
            "# 关键事件\n- 秘境开始结算\n"
        )
        try:
            ctx = LintContext(
                book_dir=tmp_path, worldbook=worldbook, characters=characters,
            )
            rule = WorldbookRefRule()
            issues = rule.check(outline, ctx)
            ref_issues = [i for i in issues if "秘境" in i.message and "未找到" in i.message]
            assert len(ref_issues) == 0
        finally:
            outline.unlink()
