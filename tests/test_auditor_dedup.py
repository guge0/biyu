"""test_auditor_dedup — DedupAuditor 单元测试。"""
import pytest
from pathlib import Path

from biyu.auditor.dedup import DedupAuditor, _jaccard, _char_ngrams
from biyu.auditor.base import Severity


class TestJaccard:
    def test_identical(self):
        a = _char_ngrams("今天天气真好")
        assert _jaccard(a, a) == 1.0

    def test_disjoint(self):
        a = _char_ngrams("aaaa")
        b = _char_ngrams("bbbb")
        assert _jaccard(a, b) == 0.0

    def test_empty(self):
        assert _jaccard(set(), set()) == 0.0


class TestDedupAuditor:
    def test_no_previous_chapters(self, tmp_path):
        auditor = DedupAuditor()
        ctx = {"book_dir": str(tmp_path), "chapter_num": 1, "config": {}}
        result = auditor.run("这是第一章的内容，没有历史章节。", ctx)
        assert result.checker == "dedup"

    def test_block_on_high_similarity(self, tmp_path):
        # 创建一个几乎相同的上一章
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()
        text = "这是一段很长的测试文本。" * 100
        (chapters_dir / "ch1.md").write_text(text, encoding="utf-8")

        auditor = DedupAuditor()
        ctx = {
            "book_dir": str(tmp_path),
            "chapter_num": 2,
            "config": {"checkers": {"dedup": {"enabled": True, "jaccard_threshold": 0.7}}},
        }
        # 几乎相同的文本
        result = auditor.run(text, ctx)
        assert result.severity == Severity.BLOCK

    def test_pass_on_low_similarity(self, tmp_path):
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()
        (chapters_dir / "ch1.md").write_text(
            "完全不同的内容，关于另一个故事。" * 100,
            encoding="utf-8",
        )

        auditor = DedupAuditor()
        ctx = {
            "book_dir": str(tmp_path),
            "chapter_num": 2,
            "config": {"checkers": {"dedup": {"enabled": True, "jaccard_threshold": 0.7}}},
        }
        result = auditor.run("这是一段完全不同的文本。" * 100, ctx)
        assert result.severity == Severity.PASS

    def test_missing_book_dir(self):
        auditor = DedupAuditor()
        ctx = {"chapter_num": 1, "config": {}}
        result = auditor.run("一些文本", ctx)
        assert result.severity == Severity.SKIP
