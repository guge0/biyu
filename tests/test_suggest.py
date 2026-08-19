"""biyu suggest 单测 — 留白识别 + 选项生成 + 决策记录。"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import yaml

from biyu.suggest_engine import (
    BlankDecision,
    build_options,
    record_decision,
    resolve_outline_path,
    scan_file,
    _split_frontmatter,
    _scan_body_placeholders,
    _scan_frontmatter_blank,
)
from biyu.suggest_engine import generate_suggestion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_book_dir(tmp_path):
    """创建最小化的书目录用于测试。"""
    (tmp_path / "characters.yaml").write_text(
        "characters:\n"
        "  - name: 张今空\n"
        "    personality: '热血少年'\n",
        encoding="utf-8",
    )
    (tmp_path / "worldbook.yaml").write_text(
        "facts:\n"
        "  - 东黎国是东方宗主国\n"
        "geography:\n"
        "  - 东黎国位于大陆东部\n",
        encoding="utf-8",
    )
    outlines_dir = tmp_path / "outlines"
    outlines_dir.mkdir()
    return tmp_path


@pytest.fixture
def outline_with_tbd(mock_book_dir):
    """创建含 [TBD] 标记的 outline 文件。"""
    content = """\
---
present_characters:
  - 张今空
首都:
名字:
---

# 第28章: 东黎国

## 关键事件

- 主角降落在东黎国都城，但首都名称 [TBD]
- 在都城遇到一位神秘老者 <ELDER_NAME>，老者送了他一把剑
- 离开都城后前往附近的秘境 ??? 修炼
"""
    path = mock_book_dir / "outlines" / "ch28.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 测试 1: 显式 [TBD] 标记识别
# ---------------------------------------------------------------------------

class TestPlaceholderDetection:
    """测试显式占位符标记的识别。"""

    def test_tbd_marker(self, outline_with_tbd):
        """[TBD] 标记能被正确识别。"""
        decisions = scan_file(outline_with_tbd)
        tbd_decisions = [d for d in decisions if "[TBD]" in d.raw_text]
        assert len(tbd_decisions) == 1
        assert "首都名称" in tbd_decisions[0].prompt or "TBD" in tbd_decisions[0].prompt

    def test_named_placeholder(self, outline_with_tbd):
        """<NAME> 形式的占位符能被识别。"""
        decisions = scan_file(outline_with_tbd)
        named = [d for d in decisions if "ELDER_NAME" in d.prompt]
        assert len(named) == 1

    def test_triple_question_mark(self, outline_with_tbd):
        """??? 占位符能被识别。"""
        decisions = scan_file(outline_with_tbd)
        qmark = [d for d in decisions if "???" in d.raw_text]
        assert len(qmark) == 1

    def test_all_placeholders_found(self, outline_with_tbd):
        """总共识别出 3 个 body 占位符。"""
        decisions = scan_file(outline_with_tbd)
        body_decisions = [d for d in decisions if d.raw_text]
        assert len(body_decisions) == 3

    def test_empty_file(self, tmp_path):
        """空文件不应产生任何决策。"""
        empty = tmp_path / "empty.md"
        empty.write_text("", encoding="utf-8")
        assert scan_file(empty) == []

    def test_no_frontmatter(self, tmp_path):
        """没有 frontmatter 的文件只扫描 body。"""
        f = tmp_path / "no_fm.md"
        f.write_text("# 第1章\n\n一些内容 [TBD] 在这里", encoding="utf-8")
        decisions = scan_file(f)
        assert len(decisions) == 1
        assert "[TBD]" in decisions[0].raw_text

    def test_chinese_tbd(self, tmp_path):
        """[待定] 标记能被识别。"""
        f = tmp_path / "test.md"
        f.write_text("---\n---\n\n某地 [待定]", encoding="utf-8")
        decisions = scan_file(f)
        assert any("[待定]" in d.raw_text for d in decisions)


# ---------------------------------------------------------------------------
# 测试 2: frontmatter 空值识别
# ---------------------------------------------------------------------------

class TestFrontmatterBlank:
    """测试 frontmatter 空值字段的识别。"""

    def test_empty_string_field(self, outline_with_tbd):
        """frontmatter 中值为空的字段能被识别。"""
        decisions = scan_file(outline_with_tbd)
        fm_decisions = [d for d in decisions if d.location.startswith("frontmatter.")]
        assert len(fm_decisions) == 2
        fields = {d.location.split(".")[1] for d in fm_decisions}
        assert "首都" in fields
        assert "名字" in fields

    def test_null_field(self, tmp_path):
        """frontmatter 中 null 值的字段能被识别。"""
        f = tmp_path / "test.md"
        f.write_text("---\n首都: \n面积:\n---\n\n正文内容", encoding="utf-8")
        decisions = scan_file(f)
        fm_decisions = [d for d in decisions if d.location.startswith("frontmatter.")]
        assert len(fm_decisions) == 2

    def test_non_empty_field_ignored(self, tmp_path):
        """非空字段不应被识别为留白。"""
        f = tmp_path / "test.md"
        f.write_text("---\n首都: 东都临安\n---\n\n正文", encoding="utf-8")
        decisions = scan_file(f)
        fm_decisions = [d for d in decisions if d.location.startswith("frontmatter.")]
        assert len(fm_decisions) == 0


# ---------------------------------------------------------------------------
# 测试 3: 选项生成（示例值）
# ---------------------------------------------------------------------------

class TestBuildOptions:
    """测试选项构建逻辑。"""

    def test_with_suggestion(self):
        """有示例值时生成正确的 3 个选项。"""
        decision = BlankDecision(
            id="suggest_001",
            prompt="东黎国首都名称",
            context="CH28 提到主角降落",
            raw_text="[TBD]",
            location="L5",
            source_file="ch28.md",
        )
        options = build_options(decision, "东都临安")
        assert len(options) == 3
        assert "东都临安" in options[0]
        assert "auto" in options[1]
        assert "skip" in options[2]

    def test_without_suggestion(self):
        """无示例值时选项 1 应提示生成失败。"""
        decision = BlankDecision(
            id="suggest_001",
            prompt="某地名称",
            context="...",
            raw_text="???",
            location="L3",
            source_file="test.md",
        )
        options = build_options(decision, "")
        assert "生成失败" in options[0]


# ---------------------------------------------------------------------------
# 测试 4: auto/skip 的记录
# ---------------------------------------------------------------------------

class TestRecordDecision:
    """测试决策记录到 suggest_log.yaml。"""

    def test_record_auto(self, mock_book_dir):
        """选择 auto 时正确记录。"""
        decision = BlankDecision(
            id="suggest_001",
            prompt="东黎国首都名称",
            context="CH28 提到",
            raw_text="[TBD]",
            location="L5",
            source_file="ch28.md",
            options=["示例值:东都临安", "auto", "skip"],
            chosen=2,
            chosen_value="auto",
        )
        log_path = record_decision(decision, mock_book_dir)
        assert log_path.exists()

        with open(log_path, encoding="utf-8") as f:
            records = yaml.safe_load(f)
        assert len(records) == 1
        assert records[0]["chosen"] == 2
        assert records[0]["chosen_value"] == "auto"
        assert records[0]["applied_to"] is None

    def test_record_skip(self, mock_book_dir):
        """选择 skip 时正确记录。"""
        decision = BlankDecision(
            id="suggest_002",
            prompt="NPC名字",
            context="...",
            raw_text="<NAME>",
            location="L7",
            source_file="ch28.md",
            options=["示例值:张老", "auto", "skip"],
            chosen=3,
            chosen_value="skip",
        )
        log_path = record_decision(decision, mock_book_dir)
        with open(log_path, encoding="utf-8") as f:
            records = yaml.safe_load(f)
        assert records[0]["chosen"] == 3
        assert records[0]["chosen_value"] == "skip"

    def test_record_sample_value(self, mock_book_dir):
        """选择示例值时正确记录。"""
        decision = BlankDecision(
            id="suggest_003",
            prompt="秘境名",
            context="...",
            raw_text="???",
            location="L9",
            source_file="ch28.md",
            options=["示例值:幽冥谷", "auto", "skip"],
            chosen=1,
            chosen_value="幽冥谷",
        )
        log_path = record_decision(decision, mock_book_dir)
        with open(log_path, encoding="utf-8") as f:
            records = yaml.safe_load(f)
        assert records[0]["chosen"] == 1
        assert records[0]["chosen_value"] == "幽冥谷"

    def test_append_to_existing(self, mock_book_dir):
        """多次记录追加到同一文件。"""
        d1 = BlankDecision(
            id="suggest_001", prompt="A", context="...", raw_text="[TBD]",
            location="L1", source_file="test.md", chosen=1, chosen_value="x",
        )
        d2 = BlankDecision(
            id="suggest_002", prompt="B", context="...", raw_text="???",
            location="L2", source_file="test.md", chosen=2, chosen_value="auto",
        )
        record_decision(d1, mock_book_dir)
        record_decision(d2, mock_book_dir)

        log_path = mock_book_dir / "decisions" / "suggest_log.yaml"
        with open(log_path, encoding="utf-8") as f:
            records = yaml.safe_load(f)
        assert len(records) == 2


# ---------------------------------------------------------------------------
# 测试 5: 路径解析
# ---------------------------------------------------------------------------

class TestResolvePath:
    """测试文件路径解析。"""

    def test_resolve_by_chapter(self, mock_book_dir):
        """通过章节号找到 outline 文件。"""
        outlines = mock_book_dir / "outlines"
        (outlines / "ch5.md").write_text("# CH5", encoding="utf-8")
        result = resolve_outline_path(mock_book_dir, chapter=5)
        assert result is not None
        assert result.name == "ch5.md"

    def test_resolve_by_outline_path(self, tmp_path):
        """通过 outline 路径找到文件。"""
        f = tmp_path / "custom_outline.md"
        f.write_text("# test", encoding="utf-8")
        result = resolve_outline_path(tmp_path, outline=str(f))
        assert result == f

    def test_resolve_nonexistent_returns_none(self, mock_book_dir):
        """不存在的章节号返回 None。"""
        result = resolve_outline_path(mock_book_dir, chapter=999)
        assert result is None

    def test_resolve_no_args_returns_none(self, mock_book_dir):
        """不提供参数返回 None。"""
        result = resolve_outline_path(mock_book_dir)
        assert result is None


# ---------------------------------------------------------------------------
# 测试 6: LLM 示例值生成（mock）
# ---------------------------------------------------------------------------

class TestGenerateSuggestion:
    """测试示例值生成（mock LLM）。"""

    def test_generate_calls_llm(self, mock_book_dir):
        """generate_suggestion 调用 LLM 并返回结果。"""
        mock_adapter = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "东都临安"
        mock_adapter.generate.return_value = mock_response

        decision = BlankDecision(
            id="suggest_001",
            prompt="东黎国首都名称",
            context="CH28 提到东黎国都城",
            raw_text="[TBD]",
            location="L5",
            source_file="ch28.md",
        )

        import asyncio
        result = asyncio.run(generate_suggestion(decision, mock_book_dir, mock_adapter))
        assert result == "东都临安"
        mock_adapter.generate.assert_called_once()

    def test_generate_cleans_multiline(self, mock_book_dir):
        """多行 LLM 输出只取第一行。"""
        mock_adapter = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "东都临安\n（解释：参考宋制）"
        mock_adapter.generate.return_value = mock_response

        decision = BlankDecision(
            id="suggest_001",
            prompt="首都",
            context="...",
            raw_text="[TBD]",
            location="L1",
            source_file="test.md",
        )

        import asyncio
        result = asyncio.run(generate_suggestion(decision, mock_book_dir, mock_adapter))
        assert "\n" not in result
        assert result == "东都临安"
