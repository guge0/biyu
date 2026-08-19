"""sampler.py 单测 — 采样规则."""
import os
import tempfile

import pytest

from biyu.fingerprint.sampler import load_source, uniform_paragraph_sample


def _make_paragraphs(n: int, chars_per: int = 200) -> str:
    """生成 n 个段落，每段 chars_per 字符."""
    return "\n\n".join("x" * chars_per for _ in range(n))


class TestLoadSource:
    def test_single_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        text = load_source(str(f))
        assert text == "hello world"

    def test_directory(self, tmp_path):
        (tmp_path / "01.txt").write_text("aaa", encoding="utf-8")
        (tmp_path / "02.txt").write_text("bbb", encoding="utf-8")
        text = load_source(str(tmp_path))
        assert text == "aaa\n\nbbb"

    def test_directory_sorted(self, tmp_path):
        (tmp_path / "02.txt").write_text("second", encoding="utf-8")
        (tmp_path / "01.txt").write_text("first", encoding="utf-8")
        text = load_source(str(tmp_path))
        assert text.startswith("first")

    def test_nonexistent_path(self):
        with pytest.raises(FileNotFoundError):
            load_source("/nonexistent/path")

    def test_empty_directory(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_source(str(tmp_path))


class TestUniformParagraphSample:
    def test_small_text_returns_full(self):
        text = "短文本"
        result, method = uniform_paragraph_sample(text, target_chars=8000)
        assert method == "full"
        assert result == text

    def test_text_under_target_returns_full(self):
        text = _make_paragraphs(10, 500)  # 5000 chars
        result, method = uniform_paragraph_sample(text, target_chars=8000)
        assert method == "full"
        assert result == text

    def test_text_over_target_samples(self):
        text = _make_paragraphs(100, 300)  # 30000 chars
        result, method = uniform_paragraph_sample(text, target_chars=8000)
        assert method == "uniform"
        assert len(result) <= 12000  # 允许一些余量

    def test_sampling_preserves_paragraphs(self):
        text = _make_paragraphs(100, 300)
        result, method = uniform_paragraph_sample(text, target_chars=8000)
        # 结果应该包含完整段落
        paragraphs = [p for p in result.split("\n\n") if p.strip()]
        for p in paragraphs:
            assert len(p) == 300  # 每段完整

    def test_warning_on_short_text(self):
        with pytest.warns(UserWarning, match="样本仅"):
            uniform_paragraph_sample("短", target_chars=8000)

    def test_exact_target_returns_full(self):
        text = "x" * 8000
        result, method = uniform_paragraph_sample(text, target_chars=8000)
        assert method == "full"

    def test_custom_target(self):
        text = _make_paragraphs(50, 300)  # 15000 chars
        result, method = uniform_paragraph_sample(text, target_chars=3000)
        assert method == "uniform"
        assert len(result) <= 6000  # 余量

    def test_empty_paragraphs_handled(self):
        text = "\n\n\n\n"
        result, method = uniform_paragraph_sample(text, target_chars=100)
        assert method == "full"  # 只有空段落
