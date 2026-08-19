"""R2 read_chapter 工具(P8-M3R T2.1)— D-96 分层读书 L2 点读。

Spec(specs/P8-M3R.md line 44-48):
- chat_tools.py 加 _tool_read_chapter(book_dir, n)
- 读 chapters/ch{n}.md,≤4000 字截断,标"[已截断]"
- 消息含"第 X 章"时解析章号,否则默认最新章
- 每轮 ≤3 章上限(D-96):超限只取前 3 + 采样声明

零烧钱,纯文件读取测试。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.chat_tools import (
    _parse_chapter_numbers,
    _tool_read_chapter,
    _tool_read_chapters,
)


@pytest.fixture
def book_dir(tmp_path: Path) -> Path:
    """临时书目录 + 3 章 + 1 个无章号文件。"""
    chapters = book_dir if (book_dir := tmp_path / "TestBook") else book_dir
    chapters.mkdir()
    (chapters / "chapters").mkdir()
    (chapters / "chapters" / "ch1.md").write_text("第 1 章正文", encoding="utf-8")
    (chapters / "chapters" / "ch2.md").write_text("第 2 章正文", encoding="utf-8")
    (chapters / "chapters" / "ch3.md").write_text("第 3 章正文", encoding="utf-8")
    return chapters


# ---------------------------------------------------------------------------
# _tool_read_chapter(单章)
# ---------------------------------------------------------------------------


def test_read_chapter_returns_content(book_dir: Path):
    """读存在的章节,返正文。"""
    r = _tool_read_chapter(book_dir, 1)
    assert r["name"] == "read_chapter"
    assert "第 1 章正文" in r["result"]
    assert r["cost"] == 0.0


def test_read_chapter_nonexistent(book_dir: Path):
    """读不存在的章号,不崩,返'章节不存在'。"""
    r = _tool_read_chapter(book_dir, 99)
    assert "不存在" in r["result"] or "未找到" in r["result"]


def test_read_chapter_truncates_long_content(tmp_path: Path):
    """超长(>4000 字)截断,标'[已截断]'。"""
    book = tmp_path / "LongBook"
    book.mkdir()
    (book / "chapters").mkdir()
    long_text = "x" * 5000
    (book / "chapters" / "ch1.md").write_text(long_text, encoding="utf-8")

    r = _tool_read_chapter(book, 1)
    assert "[已截断]" in r["result"], "超长应标[已截断]"
    assert len(r["result"]) < 5000, "应截断到 ≤4000 字 + 标记"


def test_read_chapter_args_contain_chapter_num(book_dir: Path):
    """工具结果 args 含章号(供前端展示)。"""
    r = _tool_read_chapter(book_dir, 2)
    assert r["args"].get("chapter") == 2 or r["args"].get("n") == 2


# ---------------------------------------------------------------------------
# _parse_chapter_numbers(消息解析)
# ---------------------------------------------------------------------------


def test_parse_single_chapter():
    """'第 3 章' → [3]。"""
    assert _parse_chapter_numbers("看看第 3 章写得怎么样") == [3]


def test_parse_multiple_chapters():
    """'第 1 章和第 3 章' → [1, 3]。"""
    assert _parse_chapter_numbers("对比第 1 章和第 3 章") == [1, 3]


def test_parse_no_chapter_returns_empty():
    """无章号 → 空列表(调用方默认最新章)。"""
    assert _parse_chapter_numbers("这本书怎么样") == []


def test_parse_chinese_number():
    """'第十章' → [10](中文数字)。"""
    assert _parse_chapter_numbers("看看第十章") == [10]


# ---------------------------------------------------------------------------
# _tool_read_chapters(多章 + D-96 ≤3 上限)
# ---------------------------------------------------------------------------


def test_read_chapters_multiple(book_dir: Path):
    """读多章,每章独立结果。"""
    results = _tool_read_chapters(book_dir, [1, 2])
    assert len(results) == 2
    assert results[0]["args"].get("chapter") == 1 or results[0]["args"].get("n") == 1
    assert results[1]["args"].get("chapter") == 2 or results[1]["args"].get("n") == 2


def test_read_chapters_d96_limit_3(book_dir: Path):
    """D-96:超过 3 章只取前 3 + 采样声明。"""
    # 造 5 章
    for n in range(4, 6):
        (book_dir / "chapters" / f"ch{n}.md").write_text(f"第 {n} 章正文", encoding="utf-8")

    results = _tool_read_chapters(book_dir, [1, 2, 3, 4, 5])
    assert len(results) <= 4, "应只返 3 章结果 + 1 条采样声明,≤4"
    # 最后一条应是采样声明
    last = results[-1]
    assert "采样" in last["result"] or "≤3" in last["result"] or "上限" in last["result"], \
        f"超限应追加采样声明,实际末条:{last['result'][:50]}"


def test_read_chapters_within_limit_no_notice(book_dir: Path):
    """≤3 章时不追加采样声明。"""
    results = _tool_read_chapters(book_dir, [1, 2, 3])
    # 不应有采样声明(3 章以内)
    for r in results:
        assert "采样" not in r["result"], f"≤3 章不应有采样声明,实际:{r['result'][:50]}"
