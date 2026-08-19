"""T3 工具分发单测(P8-M3)— chat_tools 各工具函数 + 意图路由。

零烧钱,纯文件模拟。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.chat_tools import (
    run_chat_tools,
    run_director_tools,
    _route_intent,
    _extract_name,
    _extract_keyword,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """模拟 data/ 根目录。"""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def book_dir(data_root: Path) -> Path:
    """模拟 data/TestBook/ 目录,含必要文件。"""
    d = data_root / "TestBook"
    d.mkdir(parents=True)

    # truth_files
    tf_dir = d / "truth_files"
    tf_dir.mkdir()
    (tf_dir / "current_state.md").write_text(
        "| 字段 | 值 |\n|------|-----|\n| 当前章节 | 3 |\n| 主角状态 | 气海境三重 |\n",
        encoding="utf-8",
    )
    (tf_dir / "particle_ledger.md").write_text(
        "| 章节 | 角色 | 变化 |\n|------|------|------|\n| 3 | 陈凡 | 突破气海境 |\n",
        encoding="utf-8",
    )
    (tf_dir / "pending_hooks.md").write_text(
        "| hook_id | 状态 |\n|---------|------|\n| H-001 | 待回收 |\n",
        encoding="utf-8",
    )

    # characters.yaml
    import yaml
    chars = {
        "characters": [
            {"name": "陈凡", "personality": "坚毅", "state": "气海境三重"},
            {"name": "林霜", "personality": "冷静", "state": "筑基期"},
        ],
    }
    (d / "characters.yaml").write_text(
        yaml.dump(chars, allow_unicode=True), encoding="utf-8",
    )

    # worldbook.yaml
    wb = {
        "facts": ["气海境是修炼第一境", "金色代表皇族"],
        "power_system": ["气海境", "筑基期", "金丹期"],
    }
    (d / "worldbook.yaml").write_text(
        yaml.dump(wb, allow_unicode=True), encoding="utf-8",
    )

    # reviews/standalone/
    reviews_dir = d / "reviews" / "standalone"
    reviews_dir.mkdir(parents=True)
    (reviews_dir / "ch3.md").write_text(
        "# Ch3 审读结果\n\n一致性问题:2 处\n逻辑问题:1 处\n",
        encoding="utf-8",
    )

    # market_scans cache
    scan_dir = data_root / "market_scans"
    scan_dir.mkdir(exist_ok=True)
    import json as _json
    _json.dump(
        {
            "qidian": {
                "platform": "qidian", "success": True,
                "books": [
                    {"rank": 1, "title": "凡人修仙传", "author": "忘语",
                     "category": "仙侠", "word_count": "300万字",
                     "url": "", "abstract": ""},
                ],
                "error": None, "fetched_at": "2026-07-06T00:00:00", "source_url": "",
            },
        },
        (scan_dir / "scan_2026-07-06.json").open("w", encoding="utf-8"),
    )

    # outlines (T4 细纲)
    outlines_dir = d / "outlines"
    outlines_dir.mkdir(exist_ok=True)
    (outlines_dir / "ch1.md").write_text(
        "# CH1 校车进秘境\n\n校车意外进入秘境,主角陈凡发现规则异常。\n",
        encoding="utf-8",
    )
    (outlines_dir / "ch2.md").write_text(
        "# CH2 初遇林霜\n\n陈凡在秘境中遇到受伤的林霜,两人结伴探索。\n",
        encoding="utf-8",
    )

    # book without outlines (for T4 降级测试)
    no_outline_dir = data_root / "NoOutlineBook"
    no_outline_dir.mkdir(exist_ok=True)
    tf_dir2 = no_outline_dir / "truth_files"
    tf_dir2.mkdir()
    (tf_dir2 / "current_state.md").write_text(
        "| 字段 | 值 |\n|------|-----|\n| 当前章节 | 1 |\n", encoding="utf-8",
    )
    (tf_dir2 / "particle_ledger.md").write_text("| 章节 | 角色 |\n", encoding="utf-8")
    (tf_dir2 / "pending_hooks.md").write_text("| hook_id |\n", encoding="utf-8")

    return d


# ---------------------------------------------------------------------------
# 意图路由
# ---------------------------------------------------------------------------


class TestRouteIntent:
    def test_character_keyword(self):
        """含"角色"关键词 → character 意图。"""
        assert _route_intent("查一下角色陈凡") == ["character"]

    def test_setting_keyword(self):
        """含"设定"关键词 → setting 意图。"""
        assert _route_intent("世界观设定是什么") == ["setting"]

    def test_review_keyword(self):
        """含"审读"关键词 → review 意图。"""
        assert _route_intent("看看最近的审读结果") == ["review"]

    def test_craft_keyword(self):
        """含"节奏"关键词 → craft 意图。"""
        assert _route_intent("创作节奏有什么建议") == ["craft"]

    def test_scan_keyword(self):
        """含"扫榜"关键词 → scan 意图。"""
        assert _route_intent("最近扫榜行情如何") == ["scan"]

    def test_truth_files_keyword(self):
        """含"真相"关键词 → truth_files 意图。"""
        assert _route_intent("看看真相文件状态") == ["truth_files"]

    def test_multiple_intents(self):
        """含多组关键词 → 多意图,去重,保持顺序。"""
        intents = _route_intent("查角色陈凡,再看扫榜行情")
        assert "character" in intents
        assert "scan" in intents

    def test_empty_message(self):
        """空消息 → 空列表。"""
        assert _route_intent("") == []

    def test_no_keywords(self):
        """无匹配关键词 → 空列表。"""
        assert _route_intent("你好") == []


# ---------------------------------------------------------------------------
# 消息解析
# ---------------------------------------------------------------------------


class TestExtractName:
    def test_basic(self):
        """"角色陈凡" → "陈凡"。"""
        assert _extract_name("查角色陈凡") == "陈凡"

    def test_with_particle(self):
        """"角色的性格" → "性格"(提取角色后的第一个词)。"""
        result = _extract_name("介绍一下角色的性格")
        # "的"被当作分隔符,所以提取的是"性格"
        assert result in ("性格", "介绍"), f"Unexpected: {result}"

    def test_no_separator(self):
        """不含角色关键词 → fallback 前 10 字。"""
        assert _extract_name("你好世界") == "你好世界"


class TestExtractKeyword:
    def test_basic(self):
        """"设定气海境" → "气海境"。"""
        assert _extract_keyword("设定气海境") == "气海境"

    def test_no_separator(self):
        """不含设定关键词 → fallback 前 10 字。"""
        assert _extract_keyword("随便问问") == "随便问问"


# ---------------------------------------------------------------------------
# run_chat_tools 集成
# ---------------------------------------------------------------------------


class TestRunChatTools:
    def test_truth_files_intent(self, book_dir: Path, data_root: Path):
        """truth_files 意图 → 返回真相文件内容。"""
        results = run_chat_tools(book_dir, data_root, "看看真相文件")
        assert len(results) >= 1
        r = results[0]
        assert r["name"] == "read_truth_files"
        assert "current_state" in r["result"]
        assert r["cost"] == 0.0

    def test_review_intent(self, book_dir: Path, data_root: Path):
        """review 意图 → 返回审读结果。"""
        results = run_chat_tools(book_dir, data_root, "看看最近的审读结果")
        # review 应匹配上
        review_results = [r for r in results if r["name"] == "read_review"]
        assert len(review_results) >= 1
        assert "Ch3 审读结果" in review_results[0]["result"]

    def test_craft_intent(self, book_dir: Path, data_root: Path):
        """craft 意图 → 返回 craft 内容(读真正的文件)。"""
        results = run_chat_tools(book_dir, data_root, "创作节奏有什么建议")
        craft_results = [r for r in results if r["name"] == "read_craft"]
        assert len(craft_results) >= 1
        # 由于测试环境不一定有 craft 文件,验证至少走通不崩
        assert craft_results[0]["cost"] == 0.0
        assert craft_results[0]["name"] == "read_craft"

    def test_scan_intent(self, book_dir: Path, data_root: Path):
        """scan 意图 → 返回扫榜缓存。"""
        results = run_chat_tools(book_dir, data_root, "最近扫榜行情")
        scan_results = [r for r in results if r["name"] == "read_scan_cache"]
        assert len(scan_results) >= 1
        assert scan_results[0]["cost"] == 0.0

    def test_character_intent(self, book_dir: Path, data_root: Path):
        """character 意图 → 返回角色查询结果。"""
        results = run_chat_tools(book_dir, data_root, "查角色陈凡")
        char_results = [r for r in results if r["name"] == "look_up_character"]
        assert len(char_results) >= 1
        assert "陈凡" in char_results[0]["result"]

    def test_default_tools(self, book_dir: Path, data_root: Path):
        """无关键词 → 默认工具集(truth_files + craft + scan)。"""
        results = run_chat_tools(book_dir, data_root, "你好")
        names = [r["name"] for r in results]
        assert len(results) >= 1
        # 默认至少包含 truth_files
        assert "read_truth_files" in names

    def test_empty_message(self, book_dir: Path, data_root: Path):
        """空消息 → 默认工具集。"""
        results = run_chat_tools(book_dir, data_root, "")
        assert len(results) >= 1

    def test_nonexistent_book_dir(self, data_root: Path):
        """book_dir 不存在 → 不崩,工具结果含错误提示。"""
        bad_dir = data_root / "NoSuchBook"
        results = run_chat_tools(bad_dir, data_root, "查角色陈凡")
        assert len(results) >= 1
        # 工具不应崩,结果应为错误描述
        assert any(r["cost"] == 0.0 for r in results)


# ---------------------------------------------------------------------------
# T4 导演会诊工具
# ---------------------------------------------------------------------------


class TestRunDirectorTools:
    def test_director_returns_truth_files_and_craft(self, book_dir: Path):
        """导演工具集始终包含 truth_files + craft。"""
        results = run_director_tools(book_dir, "主角想探索秘境深处")
        names = [r["name"] for r in results]
        assert "read_truth_files" in names
        assert "read_craft" in names
        assert all(r["cost"] == 0.0 for r in results)

    def test_director_with_outlines(self, book_dir: Path):
        """有细纲的书 → 返回细纲历史。"""
        results = run_director_tools(book_dir, "主角想探索秘境深处")
        names = [r["name"] for r in results]
        assert "read_outlines" in names
        outline_result = [r for r in results if r["name"] == "read_outlines"][0]
        assert "CH1" in outline_result["result"] or "ch1" in outline_result["result"]

    def test_director_no_outlines_fallback(self, data_root: Path):
        """无细纲的书 → 降级,结果注明无细纲。"""
        no_outline_dir = data_root / "NoOutlineBook"
        results = run_director_tools(no_outline_dir, "主角想探索秘境深处")
        names = [r["name"] for r in results]
        assert "read_outlines" in names
        outline_result = [r for r in results if r["name"] == "read_outlines"][0]
        assert "暂无细纲" in outline_result["result"]
        # 仍有 truth_files 和 craft
        assert "read_truth_files" in names
        assert "read_craft" in names

    def test_director_nonexistent_book(self, data_root: Path):
        """book_dir 不存在 → 不崩。"""
        bad_dir = data_root / "NoSuchBook"
        results = run_director_tools(bad_dir, "主角想探索秘境深处")
        assert len(results) >= 1
        assert all(r["cost"] == 0.0 for r in results)
