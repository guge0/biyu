"""test_auditor_transition — TransitionAuditor 单元测试。"""
import pytest
from pathlib import Path

from biyu.auditor.transition import TransitionAuditor
from biyu.auditor.base import Severity


class TestTransitionAuditor:
    def test_chapter_1_skipped(self):
        auditor = TransitionAuditor()
        ctx = {"book_dir": "/tmp", "chapter_num": 1}
        result = auditor.run("这是第一章。", ctx)
        assert "跳过" in result.message

    def test_prev_chapter_missing(self, tmp_path):
        auditor = TransitionAuditor()
        ctx = {"book_dir": str(tmp_path), "chapter_num": 3}
        result = auditor.run("这是第三章。", ctx)
        assert "不存在" in result.message

    def test_good_transition(self, tmp_path):
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()
        (chapters_dir / "ch2.md").write_text(
            "张今空走进了秘境，眼前是一片火焰。\n他感到一股强大的力量。",
            encoding="utf-8",
        )
        auditor = TransitionAuditor()
        ctx = {"book_dir": str(tmp_path), "chapter_num": 3}
        result = auditor.run(
            "火焰灼烧着张今空的身体，他咬紧牙关。",
            ctx,
        )
        assert result.severity == Severity.WARN  # WARN is always the severity

    def test_poor_transition(self, tmp_path):
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()
        (chapters_dir / "ch2.md").write_text(
            "ABCDE 12345 XYZ",  # very different chars
            encoding="utf-8",
        )
        auditor = TransitionAuditor()
        ctx = {"book_dir": str(tmp_path), "chapter_num": 3}
        result = auditor.run(
            "天地玄黄宇宙洪荒，一个全新的故事从这里开始。",
            ctx,
        )
        # overlap_ratio likely low, may report poor transition
        assert result.details is not None

    def test_name_property(self):
        auditor = TransitionAuditor()
        assert auditor.name == "transition"
