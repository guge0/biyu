"""biyu wb-impact 集成测试。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from biyu.lint_rules.wb_impact_scan import diff_worldbook, scan_impact


@pytest.fixture
def book_dir(tmp_path):
    """创建模拟书目录。"""
    bd = tmp_path / "test_book"
    bd.mkdir()

    # chapters
    ch_dir = bd / "chapters"
    ch_dir.mkdir()
    (ch_dir / "ch16.md").write_text(
        "陈处站在指挥中心。东黎国边境出现异常。\n", encoding="utf-8"
    )
    (ch_dir / "ch17.md").write_text(
        "张今空在训练场。极阳呼吸法运转。\n", encoding="utf-8"
    )
    (ch_dir / "ch22.md").write_text(
        "白衣青年在乌坦城城墙上。\n", encoding="utf-8"
    )

    # outlines
    ol_dir = bd / "outlines"
    ol_dir.mkdir()
    (ol_dir / "ch16.md").write_text(
        "---\npresent_characters:\n  - 陈处\n---\n# 关键事件\n- 东黎国\n", encoding="utf-8"
    )

    return bd


class TestWbImpactScan:
    def test_facts_addition(self, book_dir):
        """集成测试 1：facts 新增条目。"""
        old_wb = {
            "facts": ["主角姓名：张今空"],
        }
        new_wb = {
            "facts": [
                "主角姓名：张今空",
                "镇异局南城分部新增负责人：李处",
            ],
        }

        items = scan_impact(old_wb, new_wb, book_dir)
        assert len(items) >= 1
        fact_changes = [i for i in items if "facts" in i.field_path]
        assert len(fact_changes) >= 1
        # 新增的 "李处" 应该不在已有章节中（无匹配），所以无受影响章节
        assert fact_changes[0].new_value is not None

    def test_forbidden_addition(self, book_dir):
        """集成测试 2：forbidden 新增条目。"""
        old_wb = {
            "forbidden": ["不得出现未注册角色"],
        }
        new_wb = {
            "forbidden": [
                "不得出现未注册角色",
                "不得让跨秘境意识传输未经白色空间结算",
            ],
        }

        items = scan_impact(old_wb, new_wb, book_dir)
        assert len(items) >= 1
        forbidden_changes = [i for i in items if "forbidden" in i.field_path]
        assert len(forbidden_changes) >= 1

    def test_narrative_anchors_change(self, book_dir):
        """集成测试 3：narrative_anchors 字段修改。"""
        old_wb = {
            "narrative_anchors": {
                "tone": "轻喜剧爽文",
            },
        }
        new_wb = {
            "narrative_anchors": {
                "tone": "轻喜剧爽文——但更沉稳",
            },
        }

        items = scan_impact(old_wb, new_wb, book_dir)
        assert len(items) >= 1
        anchor_changes = [i for i in items if "narrative_anchors" in i.field_path]
        assert len(anchor_changes) >= 1
        assert anchor_changes[0].old_value is not None
        assert anchor_changes[0].new_value is not None

    def test_no_changes_clean(self, book_dir):
        """正例：worldbook 无变化。"""
        wb = {"facts": ["主角姓名：张今空"]}
        items = scan_impact(wb, wb, book_dir)
        assert len(items) == 0

    def test_keyword_matching_in_chapters(self, book_dir):
        """测试关键词匹配能找到受影响章节。"""
        old_wb = {
            "facts": [],
        }
        new_wb = {
            "facts": ["陈处为镇异局南城分部负责人"],
        }

        items = scan_impact(old_wb, new_wb, book_dir)
        fact_items = [i for i in items if "facts" in i.field_path]
        assert len(fact_items) >= 1
        # "陈处" 应该在 ch16 和 ch16 outline 中找到
        ch16_found = any("ch16" in ch for item in fact_items for ch in item.affected_chapters)
        assert ch16_found, f"ch16 应该受影响，实际: {fact_items[0].affected_chapters}"


class TestDiffWorldbook:
    def test_list_addition(self):
        changes = diff_worldbook(
            {"facts": ["A"]},
            {"facts": ["A", "B"]},
        )
        assert any("facts" in c[0] and c[2] == "B" for c in changes)

    def test_list_removal(self):
        changes = diff_worldbook(
            {"facts": ["A", "B"]},
            {"facts": ["A"]},
        )
        assert any("facts" in c[0] and c[1] == "B" for c in changes)

    def test_dict_change(self):
        changes = diff_worldbook(
            {"narrative_anchors": {"tone": "old"}},
            {"narrative_anchors": {"tone": "new"}},
        )
        assert any("tone" in c[0] for c in changes)
