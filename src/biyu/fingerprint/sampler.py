"""文本采样 — 按段落等距采样，不切句子中间."""
from __future__ import annotations

import re
import warnings
from pathlib import Path


def load_source(path: str) -> str:
    """支持单文件或目录：
    - 单文件：读
    - 目录：读所有 .txt，按文件名排序拼接
    """
    p = Path(path)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    if p.is_dir():
        txts = sorted(p.glob("*.txt"))
        if not txts:
            raise FileNotFoundError(f"目录 {path} 下没有 .txt 文件")
        parts = [f.read_text(encoding="utf-8") for f in txts]
        return "\n\n".join(parts)
    raise FileNotFoundError(f"路径不存在: {path}")


def _is_separator(line: str) -> bool:
    """判断是否为分隔线（纯 - 或 = 组成的行）."""
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) >= 10 and all(c in "-=" for c in stripped):
        return True
    return False


def merge_small_paragraphs(text: str, min_block_chars: int = 500) -> str:
    """合并过小的段落，使 LLM 能提取到足够长的代表段落。

    策略：
    - 去掉分隔线（纯 - 或 = 组成的行）
    - 合并连续段落直到 >= min_block_chars
    """
    paragraphs = text.split("\n\n")

    # 过滤掉分隔线和空行
    content_paras = []
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        if _is_separator(stripped):
            continue
        content_paras.append(stripped)

    # 合并小段落
    blocks = []
    current_block = []

    for para in content_paras:
        current_block.append(para)
        block_text = "\n".join(current_block)
        if len(block_text) >= min_block_chars:
            blocks.append(block_text)
            current_block = []

    if current_block:
        # 剩余段落合并到最后一个块或独立成块
        remaining = "\n".join(current_block)
        if blocks and len(remaining) < min_block_chars:
            blocks[-1] = blocks[-1] + "\n" + remaining
        else:
            blocks.append(remaining)

    return "\n\n".join(blocks)


def uniform_paragraph_sample(text: str, target_chars: int = 8000) -> tuple[str, str]:
    """按段落等距采样，不切句子中间。

    - 段落分隔：双换行（\\n\\n）
    - 上传 <= target：全用
    - 上传 > target：按比例取段落，直到累计字符接近 target

    Returns:
        (sampled_text, method)  method 为 "full" 或 "uniform"
    """
    total = len(text)

    # 样本不足警告
    if total <= 3000:
        warnings.warn(
            f"样本仅 {total} 字符，可能不足。建议 >= 3000 字符。",
            UserWarning,
            stacklevel=2,
        )

    # 小于等于目标，全用
    if total <= target_chars:
        return text, "full"

    # 等距采样
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return text, "full"

    # 计算需要取的段落数：按总字数比例
    ratio = target_chars / total
    n_take = max(1, int(len(paragraphs) * ratio))

    # 等距取段落索引
    if n_take >= len(paragraphs):
        return "\n\n".join(paragraphs), "uniform"

    step = len(paragraphs) / n_take
    indices = [int(i * step) for i in range(n_take)]

    sampled_paragraphs = [paragraphs[i] for i in indices]
    result = "\n\n".join(sampled_paragraphs)
    return result, "uniform"
