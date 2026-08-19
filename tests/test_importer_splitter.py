"""P8-M2 T1 · 手写书分章器单测。

覆盖三维:
- 正确性:基础切分(3 章 + 卷名)+ 章字段
- 稳定性:同输入多次跑同输出
- 边角:无标题章 / 末章不完整 / 卷名仅在章节前识别

夹具全部 mock,不含真书人物/情节(守"手写书全程真书待遇"红线)。
"""

from __future__ import annotations

import json
from pathlib import Path

from biyu.importer.splitter import (
    Chapter,
    SplitResult,
    activate_chapters,
    split_file,
    split_text,
    write_chapters,
)

MOCK_TEXT = """第一卷

第1章 测试标题一
　　章节一内容行1。
　　章节一内容行2。

第2章 测试标题二
　　章节二内容行1。

第3章
　　章节三无标题内容。
"""


# ---------- 正确性 ----------

def test_split_text_basic_three_chapters_one_volume() -> None:
    result = split_text(MOCK_TEXT)
    assert result.volume == "第一卷"
    assert len(result.chapters) == 3
    assert result.chapter_count == 3


def test_split_text_chapter_fields() -> None:
    result = split_text(MOCK_TEXT)
    ch1 = result.chapters[0]
    assert ch1.num == 1
    assert ch1.title == "测试标题一"
    assert "章节一内容行1" in ch1.text
    assert "章节一内容行2" in ch1.text
    # line_start:卷名在 line 1,空行 line 2,第1章标志 line 3
    assert ch1.line_start == 3


def test_split_text_chapter_two() -> None:
    result = split_text(MOCK_TEXT)
    ch2 = result.chapters[1]
    assert ch2.num == 2
    assert ch2.title == "测试标题二"
    assert "章节二内容行1" in ch2.text


# ---------- 边角 ----------

def test_split_text_no_title_chapter() -> None:
    result = split_text(MOCK_TEXT)
    ch3 = result.chapters[2]
    assert ch3.num == 3
    assert ch3.title == ""
    assert "章节三无标题内容" in ch3.text


def test_split_text_incomplete_last_chapter_ok() -> None:
    """末章戛然而止(无后续章节标志)也能切——P8-M2 真实用例:第26章未完。"""
    text = "第1章 标题\n　　内容戛然而止"
    result = split_text(text)
    assert len(result.chapters) == 1
    assert "戛然而止" in result.chapters[0].text


def test_split_text_volume_only_recognized_before_first_chapter() -> None:
    """卷名仅在第一篇章节前识别;过章节后行内'第一卷'当正文。"""
    text_late = """第1章 标题
　　内容。

第一卷
　　这不应被识别为卷名(已过章节)。
"""
    result = split_text(text_late)
    assert result.volume is None
    assert len(result.chapters) == 1
    assert "第一卷" in result.chapters[0].text


def test_split_text_no_volume_no_chapter_returns_empty() -> None:
    """全文无章无卷,返回空。"""
    result = split_text("一段没有章节标志的文字。\n另一行。\n")
    assert result.volume is None
    assert result.chapters == []


def test_split_text_volume_without_chapter() -> None:
    """只有卷名没章节:卷名识别,章节空。"""
    result = split_text("第一卷\n")
    assert result.volume == "第一卷"
    assert result.chapters == []


# ---------- 稳定性 ----------

def test_split_text_stability_same_input_same_output() -> None:
    r1 = split_text(MOCK_TEXT)
    r2 = split_text(MOCK_TEXT)
    assert r1 == r2


# ---------- 文件 IO ----------

def test_write_chapters_creates_chNN_files(tmp_path: Path) -> None:
    result = split_text(MOCK_TEXT)
    write_chapters(result, tmp_path)
    raw = tmp_path / "chapters_raw"
    assert (raw / "ch01.txt").exists()
    assert (raw / "ch02.txt").exists()
    assert (raw / "ch03.txt").exists()


def test_write_chapters_file_header_format(tmp_path: Path) -> None:
    result = split_text(MOCK_TEXT)
    write_chapters(result, tmp_path)
    ch01 = (tmp_path / "chapters_raw" / "ch01.txt").read_text(encoding="utf-8")
    assert ch01.startswith("第1章 测试标题一\n")
    ch03 = (tmp_path / "chapters_raw" / "ch03.txt").read_text(encoding="utf-8")
    # 无标题章:首行只 "第3章"(无尾随空格)
    assert ch03.startswith("第3章\n")


def test_write_chapters_index_json(tmp_path: Path) -> None:
    result = split_text(MOCK_TEXT)
    write_chapters(result, tmp_path)
    index_path = tmp_path / "index.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["volume"] == "第一卷"
    assert index["chapter_count"] == 3
    assert index["chapters"][0]["num"] == 1
    assert index["chapters"][0]["title"] == "测试标题一"
    assert index["chapters"][0]["file"] == "chapters_raw/ch01.txt"
    assert index["chapters"][2]["title"] == ""  # 第3章无标题


def test_write_chapters_idempotent(tmp_path: Path) -> None:
    """同一 result 写两次结果一致(覆盖不append)。"""
    result = split_text(MOCK_TEXT)
    write_chapters(result, tmp_path)
    first = (tmp_path / "chapters_raw" / "ch01.txt").read_text(encoding="utf-8")
    write_chapters(result, tmp_path)
    second = (tmp_path / "chapters_raw" / "ch01.txt").read_text(encoding="utf-8")
    assert first == second


def test_split_file_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text(MOCK_TEXT, encoding="utf-8")
    dest = tmp_path / "out"
    result = split_file(src, dest)
    assert isinstance(result, SplitResult)
    assert result.chapter_count == 3
    assert (dest / "chapters_raw" / "ch01.txt").exists()
    assert (dest / "index.json").exists()


# ---------- 类型 ----------

def test_chapter_dataclass_fields() -> None:
    ch = Chapter(num=1, title="x", text="y", line_start=1, line_end=2)
    assert ch.num == 1
    assert ch.title == "x"
    assert ch.text == "y"
    assert ch.line_start == 1
    assert ch.line_end == 2


# ---------- activate_chapters(T2 前置)----------


def _make_raw(tmp_path: Path, files: dict) -> Path:
    """建临时 chapters_raw/ + 一组 chNN.txt。files = {filename: content}。"""
    raw = tmp_path / "chapters_raw"
    raw.mkdir()
    for name, content in files.items():
        (raw / name).write_text(content, encoding="utf-8")
    return raw


def test_activate_chapters_basic_two_files(tmp_path: Path) -> None:
    _make_raw(tmp_path, {
        "ch01.txt": "第1章 A\n内容A",
        "ch02.txt": "第2章 B\n内容B",
    })
    count = activate_chapters(tmp_path)
    assert count == 2
    chap = tmp_path / "chapters"
    assert (chap / "ch1.md").exists()
    assert (chap / "ch2.md").exists()
    # 不补 0
    assert not (chap / "ch01.md").exists()
    # 内容一致
    assert (chap / "ch1.md").read_text(encoding="utf-8") == "第1章 A\n内容A"


def test_activate_chapters_strips_leading_zeros(tmp_path: Path) -> None:
    """ch26.txt → ch26.md(26 没有 leading 0,但 ch01/ch09 应去掉)。"""
    _make_raw(tmp_path, {
        "ch01.txt": "x",
        "ch09.txt": "y",
        "ch26.txt": "z",
    })
    activate_chapters(tmp_path)
    chap = tmp_path / "chapters"
    assert (chap / "ch1.md").exists()
    assert (chap / "ch9.md").exists()
    assert (chap / "ch26.md").exists()


def test_activate_chapters_idempotent(tmp_path: Path) -> None:
    """激活幂等:跑两次结果一致(覆盖写,非 append)。"""
    _make_raw(tmp_path, {"ch01.txt": "第1章 A\n内容"})
    activate_chapters(tmp_path)
    first = (tmp_path / "chapters" / "ch1.md").read_text(encoding="utf-8")
    activate_chapters(tmp_path)
    second = (tmp_path / "chapters" / "ch1.md").read_text(encoding="utf-8")
    assert first == second


def test_activate_chapters_no_src_returns_zero(tmp_path: Path) -> None:
    """chapters_raw/ 不存在:返 0 + warning(不抛错,D-70 兜底出声)。"""
    count = activate_chapters(tmp_path)
    assert count == 0
    # chapters/ 不应被创建
    assert not (tmp_path / "chapters").exists()


def test_activate_chapters_skips_non_conforming_filenames(tmp_path: Path) -> None:
    """不符合 chNN.txt 命名的文件跳过(readme.txt / ch.txt 等)。"""
    _make_raw(tmp_path, {
        "ch01.txt": "valid",
        "readme.txt": "should skip",
        "ch.txt": "no number",
    })
    count = activate_chapters(tmp_path)
    assert count == 1
    assert (tmp_path / "chapters" / "ch1.md").exists()
    assert not (tmp_path / "chapters" / "readme.md").exists()


def test_activate_chapters_dest_dir_separate(tmp_path: Path) -> None:
    """dest_dir 与 src_dir 不同:写到 dest_dir/chapters/。"""
    src = tmp_path / "src"
    src.mkdir()
    _make_raw(src, {"ch01.txt": "x"})
    dest = tmp_path / "dest"
    count = activate_chapters(src, dest)
    assert count == 1
    assert (dest / "chapters" / "ch1.md").exists()
    # src/chapters/ 不应被创建
    assert not (src / "chapters").exists()
