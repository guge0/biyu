"""test_auditor_style_repeat — StyleRepeatAuditor 单元测试。"""
import pytest
from pathlib import Path

from biyu.auditor.style_repeat import StyleRepeatAuditor
from biyu.auditor.base import Severity


class TestStyleRepeatAuditor:
    def test_no_violations(self):
        auditor = StyleRepeatAuditor()
        ctx = {
            "book_dir": None,
            "chapter_num": 1,
            "config": {"checkers": {"style_repeat": {"enabled": True, "max_per_chapter": 1}}},
        }
        result = auditor.run("张今空站在秘境入口，深吸一口气。", ctx)
        assert result.checker == "style_repeat"
        assert "通过" in result.message

    def test_violation_detected(self):
        auditor = StyleRepeatAuditor()
        ctx = {
            "book_dir": None,
            "chapter_num": 1,
            "config": {"checkers": {"style_repeat": {"enabled": True, "max_per_chapter": 1}}},
        }
        # 使用 "不是X而是Y" 两次
        text = (
            "这不是普通的剑，而是传说中的神兵利器。"
            "他的力量不是来自修炼，而是来自血脉深处的觉醒。"
        )
        result = auditor.run(text, ctx)
        # 至少应该检测到 "不是X，而是Y" 模式出现 2 次
        assert any("不是" in k and "是" in k for k in result.details.get("current_counts", {}))

    def test_with_previous_chapters(self, tmp_path):
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()
        # 上一章也用了这些句式
        (chapters_dir / "ch1.md").write_text(
            "在这一刻，他仿佛战神一般。心中暗想这一切的起因。",
            encoding="utf-8",
        )
        auditor = StyleRepeatAuditor()
        ctx = {
            "book_dir": str(tmp_path),
            "chapter_num": 2,
            "config": {
                "checkers": {
                    "style_repeat": {
                        "enabled": True,
                        "max_per_chapter": 1,
                        "max_per_3chapters": 2,
                    }
                }
            },
        }
        result = auditor.run("在这一刻，他感受到了力量。", ctx)
        assert result.details is not None

    def test_name_property(self):
        auditor = StyleRepeatAuditor()
        assert auditor.name == "style_repeat"
