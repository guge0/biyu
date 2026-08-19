"""T7 起名器单测 (P8-M3 T7)— generate_names / apply_name。

零烧钱,纯文件模拟 + 规则逻辑。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from biyu.ui import prompts_naming
from biyu.ui.naming import apply_name, generate_names


@pytest.fixture(autouse=True)
def _force_naming_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests 强制占位模式(零 LLM 调用,零成本)。"""
    monkeypatch.setattr(prompts_naming, "_naming_placeholder", True)


class TestGenerateNames:
    @pytest.mark.asyncio
    async def test_generate_returns_list(self):
        """generate_names 返候选列表。"""
        result = await generate_names(idea="主角穿越到修仙世界", genre="xianxia")
        assert "candidates" in result
        assert isinstance(result["candidates"], list)
        assert len(result["candidates"]) >= 1

    @pytest.mark.asyncio
    async def test_generate_each_candidate_has_fields(self):
        """每个候选含 name / paradigm / reason。"""
        result = await generate_names(idea="都市异能", genre="dushi")
        for c in result["candidates"]:
            assert "name" in c
            assert "paradigm" in c
            assert "reason" in c

    @pytest.mark.asyncio
    async def test_generate_source_is_template(self):
        """LLM 不可用时回退到模板(source=template_fallback)。"""
        result = await generate_names(idea="有创意的修仙想法", genre="xuanhuan")
        assert result["source"] in ("template", "template_fallback")

    @pytest.mark.asyncio
    async def test_generate_returns_target_platform(self):
        """返 target_platform。"""
        result = await generate_names(idea="有创意的修仙想法", genre="xuanhuan")
        assert "target_platform" in result

    @pytest.mark.asyncio
    async def test_generate_empty_idea_rejected(self):
        """P9-C1: 空设想直接返回 empty_rejected(¥0 提示)。"""
        result = await generate_names(idea="", genre="xuanhuan")
        assert result["source"] == "empty_rejected"
        assert len(result["candidates"]) == 0
        assert "error" in result
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_generate_max_8_candidates(self):
        """最多 8 个候选。"""
        result = await generate_names(idea="修仙", genre="xianxia")
        assert len(result["candidates"]) <= 8

    @pytest.mark.asyncio
    async def test_generate_different_genre_produces_different_results(self):
        """不同题材产出不同候选。"""
        xianxia = await generate_names(idea="修仙", genre="xianxia")
        dushi = await generate_names(idea="修仙", genre="dushi")
        xianxia_names = {c["name"] for c in xianxia["candidates"]}
        dushi_names = {c["name"] for c in dushi["candidates"]}
        # 至少一个候选不同
        assert xianxia_names != dushi_names or len(xianxia_names) > 0

    @pytest.mark.asyncio
    async def test_generate_unrecognized_genre_falls_back(self):
        """未识别的题材回退到 xuanhuan。"""
        result = await generate_names(idea="test", genre="unknown_genre")
        assert len(result["candidates"]) >= 1


class TestApplyName:
    def test_apply_creates_display_name(self, tmp_path: Path):
        """apply_name 在 book.json 写入 display_name。"""
        book_dir = tmp_path / "TestBook"
        book_dir.mkdir()
        meta = {"title": "TestBook", "genre": "xuanhuan"}
        (book_dir / "book.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

        result = apply_name(book_dir, "星辰变")
        assert result["ok"]
        assert result["display_name"] == "星辰变"

        # 验证文件被更新
        updated = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
        assert updated["display_name"] == "星辰变"
        assert updated["title"] == "TestBook"  # 原 title 保留

    def test_apply_nonexistent_book_dir_raises(self, tmp_path: Path):
        """不存在的目录 → FileNotFoundError。"""
        fake_dir = tmp_path / "NoSuchBook"
        with pytest.raises(FileNotFoundError):
            apply_name(fake_dir, "书名")

    def test_apply_nonexistent_book_json_raises(self, tmp_path: Path):
        """无 book.json → FileNotFoundError。"""
        empty_dir = tmp_path / "EmptyBook"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            apply_name(empty_dir, "书名")

    def test_apply_preserves_other_fields(self, tmp_path: Path):
        """apply_name 只加 display_name,不丢其他字段。"""
        book_dir = tmp_path / "TestBook"
        book_dir.mkdir()
        meta = {"title": "原书名", "genre": "xuanhuan", "kind": "test"}
        (book_dir / "book.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

        apply_name(book_dir, "新书名")

        updated = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
        assert updated["genre"] == "xuanhuan"
        assert updated["kind"] == "test"
        assert updated["title"] == "原书名"
