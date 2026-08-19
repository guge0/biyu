"""F-1 必检项解析器:从 planning.md 提取结构化必检项。

契约(F-1 工单 5.1):
- 「## 必检项」块缺失 → 抛 ChecklistMissingError,不许静默当空表通过
- 四小标题任一缺失 → 该类记为空数组,missing_category 标记
- 条目 = 小标题下以 "- " 开头的行,逐行一条,不做二次切分
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

BLOCK_HEADER = "## 必检项"
CATEGORY_HEADERS = {
    "**必须发生**": "must_happen",
    "**必须不发生**": "must_not_happen",
    "**结尾状态**": "ending_state",
    "**信息层级**": "info_layers",
}


class ChecklistMissingError(Exception):
    """planning.md 中没有「## 必检项」块。"""


@dataclass
class ChecklistSpec:
    planning_hash: str  # planning.md 全文 sha256 前 12 位
    must_happen: list[str] = field(default_factory=list)
    must_not_happen: list[str] = field(default_factory=list)
    ending_state: list[str] = field(default_factory=list)
    info_layers: list[str] = field(default_factory=list)
    missing_category: list[str] = field(default_factory=list)

    def all_items(self) -> list[tuple[str, str]]:
        """返回 [(category, text)] 全量条目,保持类别内顺序。"""
        out: list[tuple[str, str]] = []
        for cat in ("must_happen", "must_not_happen", "ending_state", "info_layers"):
            for text in getattr(self, cat):
                out.append((cat, text))
        return out


def _category_from_line(line: str) -> tuple[str | None, str | None]:
    """Return category and optional inline item for either heading shape."""
    candidate = line.strip()
    if candidate.startswith("- "):
        candidate = candidate[2:].strip()
    for header, category in CATEGORY_HEADERS.items():
        if candidate == header:
            return category, None
        if candidate.startswith(header):
            remainder = candidate[len(header):].strip()
            if remainder.startswith(("：", ":")):
                return category, remainder[1:].strip() or None
    return None, None


def parse_checklist(planning_text: str) -> ChecklistSpec:
    """解析 planning.md 文本为 ChecklistSpec。"""
    planning_hash = hashlib.sha256(planning_text.encode("utf-8")).hexdigest()[:12]

    lines = planning_text.splitlines()
    block_start: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == BLOCK_HEADER:
            block_start = i
            break
    if block_start is None:
        raise ChecklistMissingError("planning.md 中未找到「## 必检项」块")

    # 块边界:到下一个 "## " 标题或文件尾
    block_end = len(lines)
    for i in range(block_start + 1, len(lines)):
        if lines[i].startswith("## ") and lines[i].strip() != BLOCK_HEADER:
            block_end = i
            break
    block = lines[block_start + 1:block_end]

    spec = ChecklistSpec(planning_hash=planning_hash)
    current_cat: str | None = None
    seen_categories: set[str] = set()
    for raw in block:
        line = raw.strip()
        if not line:
            continue
        category, inline_item = _category_from_line(line)
        if category is not None:
            current_cat = category
            seen_categories.add(category)
            if inline_item is not None:
                getattr(spec, category).append(inline_item)
            continue
        if line.startswith("- ") and current_cat is not None:
            getattr(spec, current_cat).append(line[2:].strip())
            continue
        # 非条目行(说明文字等)忽略;未进入任何小标题的行也忽略
    for cat in CATEGORY_HEADERS.values():
        if cat not in seen_categories:
            spec.missing_category.append(cat)
    return spec
