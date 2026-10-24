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


class TestNarrativeAnchorsDictOfLists:
    """S6-4: 创作锚点(字典套列表)必须活着进 prompt。

    真书事故:new-book 的 narrative_anchors 是 dict-of-lists(620 字),
    加载层把它当列表字段拍平,dict 被跳过 → 锚点就地蒸发,
    导演与写手从未见过创作锚点。
    """

    def test_load_keeps_dict_anchors(self, tmp_path):
        anchors = {
            "主角定位": ["魂穿乱世的现代青年常野", "世故不墨迹"],
            "基调": ["喜剧＋热血，配重六比四"],
        }
        (tmp_path / "worldbook.yaml").write_text(
            yaml.dump({"narrative_anchors": anchors}, allow_unicode=True),
            encoding="utf-8",
        )
        wb = load_worldbook(tmp_path)
        assert wb.get("narrative_anchors") == anchors, "dict 锚点不得被列表拍平吞掉"

    def test_prompt_renders_dict_of_lists_anchors(self):
        wb = {
            "narrative_anchors": {
                "主角定位": ["常野定位一", "常野定位二"],
                "基调": ["喜剧＋热血"],
            }
        }
        prompt = build_worldbook_prompt(wb)
        assert "创作锚点" in prompt
        assert "常野定位一" in prompt and "常野定位二" in prompt
        assert "喜剧＋热血" in prompt

    def test_prompt_still_renders_flat_str_anchors(self):
        wb = {"narrative_anchors": {"主角定位": "扁平字符串形态"}}
        prompt = build_worldbook_prompt(wb)
        assert "扁平字符串形态" in prompt


class TestPowerSystemSemanticKeys:
    """S6-6: power_system 语义键结构(如「命火总纲」)不得被静默丢弃。

    真书事故:power_system=dict 但无 rules 键(键为 命火总纲/境界/下九流之术),
    旧渲染只读 power["rules"],1289 字力量体系整节蒸发。
    """

    def test_renders_semantic_keys(self):
        wb = {"power_system": {"命火总纲": ["人人心中有一火", "修炼就是养火"]}}
        prompt = build_worldbook_prompt(wb)
        assert "力量/修炼体系" in prompt
        assert "命火总纲" in prompt and "人人心中有一火" in prompt

    def test_rules_key_keeps_legacy_shape(self):
        wb = {"power_system": {"rules": ["规则一", "规则二"]}}
        prompt = build_worldbook_prompt(wb)
        assert "规则一" in prompt and "规则二" in prompt
        assert "- rules:" not in prompt, "rules 键保持旧输出形态(不加键名标签)"
