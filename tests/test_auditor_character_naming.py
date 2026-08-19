"""test_auditor_character_naming — CharacterNamingAuditor 单元测试。"""
import pytest

from biyu.auditor.character_naming import CharacterNamingAuditor
from biyu.auditor.base import Severity


def _make_ctx(characters=None):
    return {"characters": characters or [], "config": {}}


class TestCharacterNamingAuditor:
    def test_block_when_role_appears_in_narrative(self):
        """正文出现'张父' -> BLOCK (major_supporting tier)"""
        auditor = CharacterNamingAuditor()
        characters = [
            {
                "name": "张父",
                "tier": "major_supporting",
                "role": "张今空父亲(代号,正文不得出现'张父'字样)",
                "forbidden_in_narrative": ["张父"],
            }
        ]
        ctx = _make_ctx(characters)
        text = "张今空看着张父,心里五味杂陈。父亲拍了拍他的肩膀。"
        result = auditor.run(text, ctx)
        assert result.severity == Severity.BLOCK
        assert "称谓穿帮" in result.message
        assert len(result.details["violations"]) == 1
        assert "张父" in result.details["violations"][0]

    def test_pass_when_using_proper_alias(self):
        """正文用'父亲'/'爸' -> WARN(通过)"""
        auditor = CharacterNamingAuditor()
        characters = [
            {
                "name": "张父",
                "role": "张今空父亲(代号,正文不得出现'张父'字样)",
                "forbidden_in_narrative": ["张父"],
            }
        ]
        ctx = _make_ctx(characters)
        text = "张今空看着父亲,心里五味杂陈。父亲拍了拍他的肩膀。"
        result = auditor.run(text, ctx)
        assert result.severity == Severity.PASS
        assert "称谓检查通过" in result.message

    def test_handles_no_aliases_field(self):
        """角色没 aliases/forbidden_in_narrative 字段 -> 正常运行不报错"""
        auditor = CharacterNamingAuditor()
        characters = [
            {"name": "张今空", "role": "主角"},
            {"name": "周大龙", "role": "配角"},
        ]
        ctx = _make_ctx(characters)
        text = "张今空和周大龙走在路上。"
        result = auditor.run(text, ctx)
        assert result.severity == Severity.PASS
        assert "称谓检查通过" in result.message

    def test_multiple_forbidden_hits(self):
        """多个禁用称谓同时出现 (major_supporting tier)"""
        auditor = CharacterNamingAuditor()
        characters = [
            {"name": "张父", "tier": "major_supporting", "forbidden_in_narrative": ["张父"]},
            {"name": "张母", "tier": "major_supporting", "forbidden_in_narrative": ["张母"]},
        ]
        ctx = _make_ctx(characters)
        text = "张父站在门口,张母在厨房里忙碌。"
        result = auditor.run(text, ctx)
        assert result.severity == Severity.BLOCK
        assert len(result.details["violations"]) == 2
