"""P8-M2 T1 · 手写书分章器。

把手写书纯文本按 `第N章` 行切分成结构化章节,落到 chapters_raw/chNN.txt + index.json。

设计要点(对应 spec specs/P8-M2.md T1):
- **纯函数 split_text**:无 IO,易于单测;re 输入 → SplitResult 输出。
- **正则**:仅匹配行首 `第N章`(N 阿拉伯数字,网文最常见);中文数字章节(如"第一章")
  不在范围(spec 真实用例确认是阿拉伯数字 1-26，避免扩大未验证的解析范围)。
- **卷名识别**:行首 `第N卷`(N 中/阿)识别为卷名,**仅在第一篇章节前**;过章节后行内
  "第N卷"当正文(防止把正文里的"第三卷起来"之类误识别)。
- **未识别行**:序章/楔子/前言/引子/卷名(过章节后)等不切,留在前一章的 text 里。
  守"边角列入报告不猜"原则;真实用例确认无此类边角(全文仅"第N章"+ 卷名"第一卷")。
- **D-70 兜底出声**:本模块的 except 兜底路径全部 log warning(目前无 except,纯函数)。
- **不完整末章**:照样切(不抛错)。对应真实用例:第26章未完,老板拍板"不在意,照样跑"。

接口:
    split_text(text) -> SplitResult           # 纯函数
    write_chapters(result, dest_dir)          # 写 chapters_raw/ + index.json
    split_file(src_file, dest_dir) -> SplitResult  # split_text + write_chapters 组合
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# 行首 `第N章`(N 阿拉数字)+ 可选标题(同行剩余,strip)
CHAPTER_RE = re.compile(r"^第([0-9]+)章\s*(.*)$")
# 行首 `第N卷`(N 中文数字 / 阿拉伯)+ 行尾(整行就是卷名,无其他内容)
VOLUME_RE = re.compile(r"^第[〇一二三四五六七八九十百千0-9]+卷\s*$")


@dataclass
class Chapter:
    """单章结果。

    Attributes:
        num: 章号(整数,如 1, 2, 26)
        title: 章标题(strip 后;无标题则空串)
        text: 章正文(从章标志下一行到下一章/卷/文件末,原样含换行)
        line_start: 章标志所在行号(1-indexed)
        line_end: 章最后一行行号(1-indexed;下一章前一行 / 文件末)
    """

    num: int
    title: str
    text: str
    line_start: int
    line_end: int


@dataclass
class SplitResult:
    """split_text 输出。

    Attributes:
        volume: 卷名(如 "第一卷"),无卷则 None
        chapters: 章节列表(按出现顺序)
    """

    volume: Optional[str]
    chapters: List[Chapter]

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)


def split_text(text: str) -> SplitResult:
    """把手写书纯文本按 `第N章` 切分。纯函数,无 IO。

    Args:
        text: 手写书全文(UTF-8 解码后)

    Returns:
        SplitResult(volume, chapters)
    """
    lines = text.splitlines()
    volume: Optional[str] = None
    chapters: List[Chapter] = []
    current: Optional[Chapter] = None

    for i, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()

        # 卷名识别:仅在还没有章节且当前没在章内时(即"第一篇章节前")
        if not chapters and current is None:
            vol_match = VOLUME_RE.match(stripped)
            if vol_match:
                volume = stripped
                continue

        # 章节识别
        chap_match = CHAPTER_RE.match(stripped)
        if chap_match:
            # 收尾上一章
            if current is not None:
                current.line_end = i - 1
                chapters.append(current)
            num_str, title = chap_match.group(1), chap_match.group(2).strip()
            try:
                num = int(num_str)
            except ValueError:
                # 不该发生(正则保证 [0-9]+),兜底出声(D-70)
                logger.warning("splitter: 章号解析失败 num_str=%r, 跳过", num_str)
                continue
            current = Chapter(
                num=num, title=title, text="", line_start=i, line_end=i
            )
            continue

        # 章正文累加(只在已在某章内时)
        if current is not None:
            current.text += raw_line + "\n"

    # 收尾最后一章
    if current is not None:
        current.line_end = len(lines)
        chapters.append(current)

    return SplitResult(volume=volume, chapters=chapters)


def write_chapters(
    result: SplitResult,
    dest_dir: Path,
    *,
    encoding: str = "utf-8",
) -> None:
    """把 SplitResult 落到 dest_dir/chapters_raw/chNN.txt + dest_dir/index.json。

    文件命名:chNN.txt(N = num,至少 2 位 0 填充;num > 99 自动扩宽)。
    章节文件首行:`第N章 标题`(标题为空则 `第N章`,无尾随空格)。
    幂等:同一 result 写多次结果一致(覆盖写,非 append)。

    Args:
        result: split_text 的输出
        dest_dir: 目标书目录(如 data/手写书-第一卷/)
        encoding: 文件编码,默认 utf-8
    """
    raw_dir = dest_dir / "chapters_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for ch in result.chapters:
        width = max(2, len(str(ch.num)))
        fname = raw_dir / f"ch{ch.num:0{width}d}.txt"
        header = f"第{ch.num}章 {ch.title}".rstrip()
        fname.write_text(header + "\n" + ch.text, encoding=encoding)

    index = {
        "volume": result.volume,
        "chapter_count": result.chapter_count,
        "chapters": [
            {
                "num": ch.num,
                "title": ch.title,
                "file": f"chapters_raw/ch{ch.num:0{max(2, len(str(ch.num)))}d}.txt",
                "line_start": ch.line_start,
                "line_end": ch.line_end,
            }
            for ch in result.chapters
        ],
    }
    (dest_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding=encoding
    )


def split_file(
    src_file: Path,
    dest_dir: Path,
    *,
    encoding: str = "utf-8",
) -> SplitResult:
    """读 src_file → split_text → write_chapters。返回 SplitResult。

    Args:
        src_file: 源 txt 文件路径
        dest_dir: 目标书目录
        encoding: 文件编码,默认 utf-8

    Returns:
        SplitResult
    """
    text = src_file.read_text(encoding=encoding)
    result = split_text(text)
    write_chapters(result, dest_dir, encoding=encoding)
    return result


# 章文件命名 `chNN.txt`(splitter 输出格式)
_RAW_CHAPTER_RE = re.compile(r"^ch0*(\d+)\.txt$")


def activate_chapters(
    src_dir: Path,
    dest_dir: Optional[Path] = None,
    *,
    encoding: str = "utf-8",
) -> int:
    """把 chapters_raw/chNN.txt 复制为 chapters/chN.md(激活到 T2 倒灌可用格式)。

    作用:splitter 输出 chapters_raw/chNN.txt(2 位补 0 + .txt),但下游
    `biyu refresh` / `BookConfig.chapter_path` 期望 chapters/ch{N}.md(不补 0 + .md)。
    本函数做格式转换,内容原样保留(覆盖写)。

    Args:
        src_dir: 源书目录(含 chapters_raw/)
        dest_dir: 目标书目录(将创建/写入 chapters/);默认 = src_dir
        encoding: 文件编码,默认 utf-8

    Returns:
        激活的章节数(0 表示 chapters_raw/ 不存在或为空,会 log warning,不抛错)

    Raises:
        FileNotFoundError: chapters_raw/ 不存在时返 0 + warning(D-70 兜底出声)
    """
    if dest_dir is None:
        dest_dir = src_dir
    src_raw = src_dir / "chapters_raw"
    if not src_raw.exists():
        logger.warning(
            "activate_chapters: chapters_raw/ 不存在,无可激活: %s", src_raw
        )
        return 0
    dest_chap = dest_dir / "chapters"
    dest_chap.mkdir(parents=True, exist_ok=True)

    count = 0
    for src_file in sorted(src_raw.glob("ch*.txt")):
        m = _RAW_CHAPTER_RE.match(src_file.name)
        if not m:
            logger.warning(
                "activate_chapters: 跳过不符合 chNN.txt 命名的文件: %s",
                src_file.name,
            )
            continue
        num = int(m.group(1))
        dest_file = dest_chap / f"ch{num}.md"
        dest_file.write_text(
            src_file.read_text(encoding=encoding), encoding=encoding
        )
        count += 1
    return count
