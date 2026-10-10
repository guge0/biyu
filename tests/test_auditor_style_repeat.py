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


class TestDensityGroups:
    """2026-10 融合轮: 词族每千字密度检查(老板授权导入的外部反AI阈值)。"""

    FILLER = "他往灶里添柴，火苗旺了，锅里冒出白气。"

    @staticmethod
    def _ctx(density_limits=None):
        cfg = {"checkers": {"style_repeat": {"enabled": True, "max_per_chapter": 1}}}
        if density_limits:
            cfg["checkers"]["style_repeat"]["density_limits"] = density_limits
        return {"book_dir": None, "chapter_num": 1, "config": cfg}

    def test_simile_density_over_limit_warns(self):
        text = self.FILLER * 100 + "像是" * 12  # ~3000字 12处 → 4/千字 > 3
        result = StyleRepeatAuditor().run(text, self._ctx())
        density_notes = result.details.get("density_violations", [])
        assert any("明喻引导词" in note for note in density_notes)
        assert result.severity == Severity.WARN

    def test_density_under_limit_passes(self):
        text = self.FILLER * 100 + "像是风，又不是风。"  # 1处 → 低于阈值
        result = StyleRepeatAuditor().run(text, self._ctx())
        assert result.severity == Severity.PASS
        assert result.details["density"]["simile_markers"]["count"] == 1

    def test_cliche_expression_family_counts_together(self):
        # 3字套话+2字"嘴角勾起"族合计 → 5处/约3000字 ≈ 1.7/千字 > 1
        text = (
            self.FILLER * 100
            + "瞳孔一缩。瞳孔一缩。倒吸一口凉气。嘴角勾起。嘴角勾起。"
        )
        result = StyleRepeatAuditor().run(text, self._ctx())
        assert result.details["density"]["cliche_expressions"]["count"] == 5
        assert any("套话表情" in note for note in result.details["density_violations"])

    def test_density_limit_override_via_config(self):
        text = self.FILLER * 100 + "缓缓抬头。"  # 1处,默认5/千字不报;覆盖为0后必报
        passing = StyleRepeatAuditor().run(text, self._ctx())
        assert passing.severity == Severity.PASS
        overriding = StyleRepeatAuditor().run(text, self._ctx({"tic_words": 0}))
        assert any("缓冲词" in note for note in overriding.details["density_violations"])
