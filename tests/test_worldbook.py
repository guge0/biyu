"""test_worldbook — worldbook.py 单元测试。"""
import pytest
from pathlib import Path
import tempfile
import yaml

from biyu.worldbook import load_worldbook, build_worldbook_prompt


class TestLoadWorldbook:
    def test_load_existing(self, tmp_path):
        wb_data = {
            "facts": ["主角姓名:张三", "主角城市:南城"],
            "forbidden": ["不得穿越"],
            "power_system": {"name": "修炼", "rules": ["九境"]},
        }
        wb_path = tmp_path / "worldbook.yaml"
        wb_path.write_text(yaml.dump(wb_data, allow_unicode=True), encoding="utf-8")

        result = load_worldbook(tmp_path)
        assert result is not None
        assert "facts" in result
        assert result["facts"][0] == "主角姓名:张三"

    def test_load_missing(self, tmp_path):
        result = load_worldbook(tmp_path)
        assert result is None


class TestBuildWorldbookPrompt:
    def test_none_returns_empty(self):
        assert build_worldbook_prompt(None) == ""

    def test_empty_dict_returns_empty(self):
        assert build_worldbook_prompt({}) == ""

    def test_facts_injected(self):
        wb = {"facts": ["主角姓名:张今空", "主角城市:南城"]}
        prompt = build_worldbook_prompt(wb)
        assert "张今空" in prompt
        assert "不可变硬设定" in prompt

    def test_forbidden_injected(self):
        wb = {"forbidden": ["不得穿越", "不得死主角"]}
        prompt = build_worldbook_prompt(wb)
        assert "绝对禁止" in prompt
        assert "不得穿越" in prompt

    def test_narrative_anchors_injected(self):
        wb = {
            "narrative_anchors": {
                "protagonist_archetype": "平凡少年逆袭流",
                "tone": "轻喜剧爽文",
            }
        }
        prompt = build_worldbook_prompt(wb)
        assert "创作锚点" in prompt
        assert "平凡少年逆袭流" in prompt

    def test_power_system_injected(self):
        wb = {"power_system": {"name": "职业者修炼体系", "rules": ["九境四期"]}}
        prompt = build_worldbook_prompt(wb)
        assert "力量/修炼体系" in prompt
        assert "九境四期" in prompt

    def test_missing_fields_skipped(self):
        wb = {"facts": ["主角姓名:张三"]}  # no forbidden, no power_system
        prompt = build_worldbook_prompt(wb)
        assert "主角姓名:张三" in prompt
        assert "绝对禁止" not in prompt

    def test_timeline_injected(self):
        wb = {"timeline": ["CH1-CH3:第一次秘境"]}
        prompt = build_worldbook_prompt(wb)
        assert "时间线锚点" in prompt
        assert "CH1-CH3" in prompt

    def test_full_worldbook(self):
        wb = {
            "narrative_anchors": {"tone": "爽文"},
            "power_system": {"rules": ["九境"]},
            "facts": ["主角姓名:张今空"],
            "forbidden": ["不得穿越"],
            "geography": ["南城:华国大城市"],
            "factions": ["镇异局"],
            "timeline": ["CH1:开局"],
        }
        prompt = build_worldbook_prompt(wb)
        assert "世界观锁" in prompt
        assert "世界观锁结束" in prompt
        assert "张今空" in prompt
        assert "不得穿越" in prompt
        assert "南城" in prompt
