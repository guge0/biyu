"""character_check 规则单测 — 正例 + 反例。"""
from __future__ import annotations

import pytest
from pathlib import Path

from biyu.lint_rules.base import LintContext
from biyu.lint_rules.character_check import CharacterCheckRule


def _make_outline(frontmatter_chars: list[str] | None = None,
                  body: str = "") -> Path:
    """创建临时 outline 文件。"""
    import tempfile, os
    if frontmatter_chars is not None:
        fm = "---\npresent_characters:\n"
        for c in frontmatter_chars:
            fm += f"  - {c}\n"
        fm += "---\n"
        content = fm + body
    else:
        content = body

    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(path)


@pytest.fixture
def characters():
    return [
        {"name": "张今空", "tier": "protagonist", "aliases": {"called_by": {"周大龙": ["今空", "老张"]}}},
        {"name": "周大龙", "tier": "major_supporting"},
        {"name": "林溪", "tier": "major_supporting"},
        {"name": "李超妈妈", "tier": "npc"},
    ]


@pytest.fixture
def worldbook():
    return {
        "timeline": [
            "CH1-CH3：第一次秘境——三国·赤壁之战",
            "CH21-CH27：第三次秘境——斗破苍穹世界",
        ],
        "narrative_anchors": {
            "writing_constraints": {
                "pov_consistency": [
                    "秘境源世界中的角色（如曹操、关羽、刘备、诸葛亮等历史人物）",
                ],
            },
        },
    }


@pytest.fixture
def ctx(characters, worldbook, tmp_path):
    return LintContext(
        book_dir=tmp_path,
        characters=characters,
        worldbook=worldbook,
    )


class TestCharacterCheckRule:
    def test_known_characters_pass(self, ctx):
        """正例：所有角色已注册，不报错。"""
        outline = _make_outline(
            ["张今空", "周大龙", "林溪"],
            "# 关键事件\n- **事件1**: 张今空做某事\n- **事件2**: 周大龙做某事\n",
        )
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            # 应该没有 error 级别的角色问题
            char_issues = [i for i in issues if "角色" in i.message]
            assert len(char_issues) == 0
        finally:
            outline.unlink()

    def test_unknown_character_with_dialogue_error(self, ctx):
        """反例：未知角色有台词，报 error 必补卡。"""
        outline = _make_outline(
            ["张今空", "神秘人X"],
            "# 关键事件\n- 神秘人X：你好啊\n",
        )
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            errors = [i for i in issues if i.severity == "error" and "神秘人X" in i.message]
            assert len(errors) >= 1
            assert "必补卡" in errors[0].message
        finally:
            outline.unlink()

    def test_known_npc_no_error(self, ctx):
        """已在 characters.yaml 注册的 NPC 角色不出报错（视为已知角色）。"""
        outline = _make_outline(["李超妈妈"], "# 关键事件\n- 事件\n")
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            # 李超妈妈在 characters.yaml 中，是已知角色，不应产生角色类 issue
            char_issues = [i for i in issues if "李超妈妈" in i.message]
            assert len(char_issues) == 0
        finally:
            outline.unlink()

    def test_unknown_npc_exemption(self, ctx):
        """不在 characters.yaml 的路人角色，无台词无剧情，报 warning 可豁免。"""
        outline = _make_outline(["路人甲"], "# 关键事件\n- 事件\n")
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            warn = [i for i in issues if "路人甲" in i.message]
            assert len(warn) >= 1
            assert warn[0].severity == "warning"
            assert "可豁免" in (warn[0].suggestion or "")
        finally:
            outline.unlink()

    def test_original_character_exemption(self, ctx):
        """原作角色（如曹操）获得 NPC 豁免。"""
        outline = _make_outline(["曹操"], "# 关键事件\n- 事件\n")
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            orig_issues = [i for i in issues if "曹操" in i.message]
            assert len(orig_issues) >= 1
            assert orig_issues[0].severity == "info"
            assert "原作角色" in orig_issues[0].message
        finally:
            outline.unlink()

    def test_no_present_characters_warning(self, ctx):
        """无在场角色清单时报警告。"""
        outline = _make_outline(body="# 第1章\n## 关键事件\n- 事件\n")
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            warn = [i for i in issues if "未找到在场角色" in i.message]
            assert len(warn) >= 1
        finally:
            outline.unlink()

    def test_word_count_too_low(self, ctx):
        """字数密度估算过低时报警告。"""
        outline = _make_outline(
            ["张今空"],
            "# 关键事件\n- **事件1**: 短\n",
        )
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            word_issues = [i for i in issues if "字数密度" in i.message]
            assert len(word_issues) >= 1
            assert word_issues[0].severity == "warning"
        finally:
            outline.unlink()

    def test_word_count_sufficient(self, ctx):
        """字数密度足够时不报警告。"""
        events = "\n".join(f"- **事件{i}**: " + "张今空做了很长的事情" * 5
                           for i in range(6))
        outline = _make_outline(
            ["张今空"],
            f"# 关键事件\n{events}\n",
        )
        try:
            rule = CharacterCheckRule()
            issues = rule.check(outline, ctx)
            word_issues = [i for i in issues if "字数密度" in i.message]
            assert len(word_issues) == 0
        finally:
            outline.unlink()
