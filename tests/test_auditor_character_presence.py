"""test_auditor_character_presence — CharacterPresenceAuditor 单元测试。"""
import pytest

from biyu.auditor.character_presence import CharacterPresenceAuditor, _extract_named_characters
from biyu.auditor.base import Severity


class TestExtractNamedCharacters:
    def test_basic(self):
        text = "张今空和林晚一起走进了秘境。"
        names = ["张今空", "林晚", "韩铮"]
        found = _extract_named_characters(text, names)
        assert "张今空" in found
        assert "林晚" in found
        assert "韩铮" not in found


class TestCharacterPresenceAuditor:
    def test_no_present_list(self):
        auditor = CharacterPresenceAuditor()
        ctx = {
            "characters": [{"name": "张今空"}, {"name": "林晚"}],
        }
        result = auditor.run("张今空站在那里。", ctx)
        assert result.checker == "character_presence"
        assert "张今空" in result.message

    def test_unexpected_character(self):
        auditor = CharacterPresenceAuditor()
        ctx = {
            "characters": [{"name": "张今空"}, {"name": "林晚"}, {"name": "韩铮"}],
            "present_characters": ["张今空"],
        }
        result = auditor.run("张今空和林晚一起走进了秘境。", ctx)
        assert "非在场角色出现" in result.message
        assert "林晚" in result.message

    def test_all_present(self):
        auditor = CharacterPresenceAuditor()
        ctx = {
            "characters": [{"name": "张今空"}, {"name": "林晚"}],
            "present_characters": ["张今空", "林晚"],
        }
        result = auditor.run("张今空和林晚一起走进了秘境。", ctx)
        assert "一致" in result.message

    def test_name_property(self):
        auditor = CharacterPresenceAuditor()
        assert auditor.name == "character_presence"
