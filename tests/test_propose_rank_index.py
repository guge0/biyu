"""T7.2 后端 plumbing 测试:title_rank_index builder(P8-M3R R7)。

verify:
- _build_title_rank_index 建 {platform: {title: rank}}
- 平台失败时不入 index
- LLM 编不存在的书名 → 前端 lookup miss(本测只验 index 建对,前端兜底在 T7.5)
- _platform_labels_used 返中文显示名

零烧钱,纯单元。
"""
from __future__ import annotations

from biyu.propose.scanner import PlatformResult, BookEntry
from biyu.ui.orchestrator import _build_title_rank_index, _platform_labels_used


def _book(rank: int, title: str) -> BookEntry:
    """便捷构造 BookEntry(只填 rank/title,其他默认)。"""
    return BookEntry(
        rank=rank, title=title, author="A", category="C",
        word_count="100", url="http://x", abstract="",
    )


def test_build_title_rank_index_basic():
    """两个平台 + 各 3 本 → {platform: {title: rank}}。"""
    scan = {
        "qidian": PlatformResult(
            platform="qidian", success=True, fetched_at="2026-07-04T10:00",
            source_url="u", books=[_book(1, "甲"), _book(2, "乙"), _book(3, "丙")],
        ),
        "fanqie": PlatformResult(
            platform="fanqie", success=True, fetched_at="2026-07-04T10:00",
            source_url="u", books=[_book(1, "X"), _book(2, "Y")],
        ),
    }
    idx = _build_title_rank_index(scan)
    assert idx["qidian"]["甲"] == 1
    assert idx["qidian"]["乙"] == 2
    assert idx["qidian"]["丙"] == 3
    assert idx["fanqie"]["X"] == 1
    assert idx["fanqie"]["Y"] == 2


def test_build_title_rank_index_skips_failed_platforms():
    """失败平台不入 index(无 books 可索引)。"""
    scan = {
        "qidian": PlatformResult(
            platform="qidian", success=False, fetched_at="",
            source_url="u", error="timeout",
        ),
        "fanqie": PlatformResult(
            platform="fanqie", success=True, fetched_at="2026-07-04T10:00",
            source_url="u", books=[_book(1, "F1")],
        ),
    }
    idx = _build_title_rank_index(scan)
    assert "qidian" not in idx, "失败平台不应入 index"
    assert idx["fanqie"]["F1"] == 1


def test_build_title_rank_index_unknown_title_will_miss():
    """LLM 编的不存在书名不在 index 中(前端 lookup 会 KeyError / miss)。

    这是 T7.5 兜底机制的核心:不存在 → 显"(榜位未知)"。
    """
    scan = {
        "qidian": PlatformResult(
            platform="qidian", success=True, fetched_at="",
            source_url="u", books=[_book(1, "真书")],
        ),
    }
    idx = _build_title_rank_index(scan)
    assert "真书" in idx["qidian"]
    assert "LLM编的假书" not in idx["qidian"]


def test_platform_labels_used():
    """返 {platform_code: 中文显示名}。"""
    scan = {
        "qidian": PlatformResult(platform="qidian", success=True, fetched_at="",
                                  source_url="u"),
        "fanqie": PlatformResult(platform="fanqie", success=True, fetched_at="",
                                  source_url="u"),
    }
    labels = _platform_labels_used(scan)
    assert labels == {"qidian": "起点", "fanqie": "番茄"}


def test_platform_labels_unknown_fallback():
    """未知平台(没在 _PLATFORM_LABELS 里)→ 回退 code 本身。"""
    scan = {"xxx": PlatformResult(platform="xxx", success=True, fetched_at="", source_url="u")}
    labels = _platform_labels_used(scan)
    assert labels == {"xxx": "xxx"}
