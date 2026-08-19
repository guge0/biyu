"""R2 read_chapter 接入工具集(P8-M3R T2.2)— 消息含章号时触发。

Spec(specs/P8-M3R.md line 44):
- 接入 run_chat_tools + run_director_tools
- 消息含"第 X 章"时解析章号,否则默认最新章

零烧钱,纯文件读取。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.chat_tools import run_chat_tools, run_director_tools


@pytest.fixture
def book_dir(tmp_path: Path) -> Path:
    """临时书目录 + 3 章 + truth_files(避免保底工具集干扰)。"""
    b = tmp_path / "TestBook"
    b.mkdir()
    (b / "chapters").mkdir()
    (b / "chapters" / "ch1.md").write_text("第 1 章正文内容", encoding="utf-8")
    (b / "chapters" / "ch2.md").write_text("第 2 章正文内容", encoding="utf-8")
    (b / "chapters" / "ch3.md").write_text("第 3 章正文内容", encoding="utf-8")
    # truth_files 占位(避免 read_truth_files 报错)
    (b / "truth_files").mkdir()
    (b / "truth_files" / "current_state.md").write_text("状态占位", encoding="utf-8")
    return b


def test_run_chat_tools_triggers_read_chapter_on_chapter_num(book_dir: Path, tmp_path: Path):
    """消息含'第 2 章' → 工具结果列表含 read_chapter。"""
    results = run_chat_tools(book_dir, data_root=tmp_path, message="看看第 2 章写得怎么样")
    names = [r["name"] for r in results]
    assert "read_chapter" in names, f"应触发 read_chapter,实际工具:{names}"
    # 验证读的是第 2 章
    ch_result = next(r for r in results if r["name"] == "read_chapter")
    assert "第 2 章正文" in ch_result["result"]


def test_run_chat_tools_multiple_chapters(book_dir: Path, tmp_path: Path):
    """消息含多个章号 → 多个 read_chapter 结果。"""
    results = run_chat_tools(book_dir, data_root=tmp_path, message="对比第 1 章和第 3 章")
    ch_results = [r for r in results if r["name"] == "read_chapter"]
    assert len(ch_results) == 2, f"应返 2 个 read_chapter,实际:{len(ch_results)}"


def test_run_chat_tools_d96_limit_in_integration(book_dir: Path, tmp_path: Path):
    """集成路径也守 D-96 ≤3 上限:5 章只返 3 + 采样声明。"""
    for n in range(4, 6):
        (book_dir / "chapters" / f"ch{n}.md").write_text(f"第 {n} 章正文", encoding="utf-8")

    results = run_chat_tools(
        book_dir, data_root=tmp_path,
        message="读第 1 章、第 2 章、第 3 章、第 4 章、第 5 章",
    )
    ch_results = [r for r in results if r["name"] == "read_chapter"]
    assert len(ch_results) == 3, f"D-96 应限 3 章,实际:{len(ch_results)}"
    # 末尾应有采样声明
    notices = [r for r in results if "采样" in r.get("result", "")]
    assert len(notices) >= 1, "超限应追加采样声明"


def test_run_director_tools_triggers_read_chapter(book_dir: Path):
    """导演工具集也接入 read_chapter。"""
    results = run_director_tools(book_dir, message="会诊第 1 章")
    names = [r["name"] for r in results]
    assert "read_chapter" in names, f"导演应触发 read_chapter,实际:{names}"


def test_run_chat_tools_no_chapter_num_no_trigger(book_dir: Path, tmp_path: Path):
    """消息不含章号也不含'章'关键词 → 不触发 read_chapter(避免每次都读最新章)。"""
    results = run_chat_tools(book_dir, data_root=tmp_path, message="这本书的设定怎么样")
    names = [r["name"] for r in results]
    assert "read_chapter" not in names, f"无章号不应触发 read_chapter,实际:{names}"
