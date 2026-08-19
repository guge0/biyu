"""grammar_check 单测 — 6 个用例。"""
import pytest
from pathlib import Path
from unittest.mock import patch
from biyu.grammar_check.checker import check_chapter, auto_fix, GrammarIssue, GrammarResult
from biyu.grammar_check.whitelist import load_whitelist


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_book_dir(tmp_path):
    """Create a minimal book dir with characters.yaml and worldbook.yaml."""
    (tmp_path / "characters.yaml").write_text(
        "characters:\n"
        "  - name: 张今空\n"
        "    aliases:\n"
        "      narrator_default: '他'\n"
        "    voice_examples:\n"
        "      - '卧槽，这也太猛了'\n"
        "  - name: 周大龙\n"
        "    voice_examples:\n"
        "      - '我擦，牛逼'\n",
        encoding="utf-8",
    )
    (tmp_path / "worldbook.yaml").write_text(
        "facts:\n"
        "  - 镇异局是最高管理机构\n"
        "  - 命甲是核心装备\n"
        "  - 古虚帝国是古代文明\n"
        "forbidden: []\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: 正常文本无误报
# ---------------------------------------------------------------------------
def test_clean_text_no_false_positives(mock_book_dir):
    """正常文本不应产生误报。"""
    text = "张今空走进镇异局，看着周大龙说：'卧槽，这也太猛了。'"
    result = check_chapter(text, mock_book_dir)
    assert len(result.placeholders) == 0
    assert len(result.typos) == 0
    assert len(result.repeated_chars) == 0


# ---------------------------------------------------------------------------
# Test 2: 占位符命中
# ---------------------------------------------------------------------------
def test_placeholder_detection(mock_book_dir):
    """占位符 [NAME] 应被检测。"""
    text = "他看着[NAME]说了一句话。"
    result = check_chapter(text, mock_book_dir)
    assert len(result.placeholders) >= 1
    assert any(p.original == "[NAME]" for p in result.placeholders)


# ---------------------------------------------------------------------------
# Test 3: 白名单保护（"镇异局" 不被误报）
# ---------------------------------------------------------------------------
def test_whitelist_protection(mock_book_dir):
    """worldbook 中的专有名词不应被误报。"""
    whitelist = load_whitelist(mock_book_dir)
    assert "镇异局" in whitelist
    assert "命甲" in whitelist
    assert "张今空" in whitelist
    assert "周大龙" in whitelist


# ---------------------------------------------------------------------------
# Test 4: voice_examples 口语词不误报（"卧槽"）
# ---------------------------------------------------------------------------
def test_oral_words_not_flagged(mock_book_dir):
    """voice_examples 中的口语词不应被误报。"""
    whitelist = load_whitelist(mock_book_dir)
    # "卧槽" should be in whitelist via voice_examples extraction
    assert "卧槽" in whitelist


# ---------------------------------------------------------------------------
# Test 5: 自动修后文本正确
# ---------------------------------------------------------------------------
def test_auto_fix_removes_placeholders(mock_book_dir):
    """占位符应被自动删除。"""
    text = "老樵看着张今空，[NAME]忽然说了句话。"
    result = check_chapter(text, mock_book_dir)
    fixed, count = auto_fix(text, result)
    assert count >= 1
    assert "[NAME]" not in fixed
    assert "老樵看着张今空" in fixed


# ---------------------------------------------------------------------------
# Test 6: 三连重复字检测
# ---------------------------------------------------------------------------
def test_triple_char_detection(mock_book_dir):
    """三连重复字应被检测。"""
    text = "他看看看着远方，心里想了很多。"
    result = check_chapter(text, mock_book_dir)
    assert len(result.repeated_chars) >= 1
    assert any(r.original == "看看看" for r in result.repeated_chars)
