"""wb_impact_scan — worldbook 改动影响扫描。

解析 worldbook diff，扫描受影响章节和 outline。
只报告，不自动改。

用法（由 CLI 调用）:
    wb_impact_scan(old_wb, new_wb, book_dir) → list[ImpactItem]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ImpactItem:
    """单条 worldbook 变动的影响报告。"""

    field_path: str  # 变动字段路径，如 "facts.主角姓名"
    old_value: str | None = None
    new_value: str | None = None
    affected_chapters: list[str] = field(default_factory=list)
    affected_outlines: list[str] = field(default_factory=list)
    suggestion: str = ""


def diff_worldbook(old_wb: dict, new_wb: dict) -> list[tuple[str, str | None, str | None]]:
    """比较两个 worldbook 字典，返回变动列表。

    Returns:
        [(field_path, old_value, new_value), ...]
    """
    changes: list[tuple[str, str | None, str | None]] = []

    # 比较 list 类型字段
    for key in ("facts", "forbidden", "geography", "factions", "timeline"):
        old_list = old_wb.get(key, []) or []
        new_list = new_wb.get(key, []) or []
        if not isinstance(old_list, list):
            old_list = []
        if not isinstance(new_list, list):
            new_list = []

        old_set = {str(item) for item in old_list}
        new_set = {str(item) for item in new_list}

        for item in new_set - old_set:
            changes.append((f"{key}.+", None, item))
        for item in old_set - new_set:
            changes.append((f"{key}.-", item, None))

    # 比较 narrative_anchors（dict 类型）
    old_anchors = old_wb.get("narrative_anchors", {}) or {}
    new_anchors = new_wb.get("narrative_anchors", {}) or {}
    _diff_dict(old_anchors, new_anchors, "narrative_anchors", changes)

    # 比较 power_system
    old_power = old_wb.get("power_system", {}) or {}
    new_power = new_wb.get("power_system", {}) or {}
    _diff_dict(old_power, new_power, "power_system", changes)

    return changes


def _diff_dict(
    old: dict, new: dict, prefix: str,
    changes: list[tuple[str, str | None, str | None]],
) -> None:
    """递归比较两个 dict。"""
    all_keys = set(old.keys()) | set(new.keys())
    for key in all_keys:
        path = f"{prefix}.{key}"
        old_val = old.get(key)
        new_val = new.get(key)

        if old_val == new_val:
            continue

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            _diff_dict(old_val, new_val, path, changes)
        else:
            changes.append((
                path,
                str(old_val) if old_val is not None else None,
                str(new_val) if new_val is not None else None,
            ))


def scan_impact(
    old_wb: dict | None,
    new_wb: dict,
    book_dir: Path,
) -> list[ImpactItem]:
    """扫描 worldbook 变动的影响。

    Args:
        old_wb: 变动前的 worldbook（None 表示全新创建）。
        new_wb: 变动后的 worldbook。
        book_dir: 书目录。

    Returns:
        ImpactItem 列表。
    """
    if old_wb is None:
        old_wb = {}

    changes = diff_worldbook(old_wb, new_wb)
    if not changes:
        return []

    # 收集所有章节和 outline 文件
    chapters_dir = book_dir / "chapters"
    outlines_dir = book_dir / "outlines"

    chapter_files = sorted(chapters_dir.glob("ch*.md")) if chapters_dir.exists() else []
    outline_files = sorted(outlines_dir.glob("ch*.md")) if outlines_dir.exists() else []

    # 读取所有章节/outline 的文本（缓存）
    chapter_texts: dict[str, str] = {}
    for f in chapter_files:
        chapter_texts[f.stem] = f.read_text(encoding="utf-8")

    outline_texts: dict[str, str] = {}
    for f in outline_files:
        outline_texts[f.stem] = f.read_text(encoding="utf-8")

    items: list[ImpactItem] = []

    for field_path, old_val, new_val in changes:
        # 提取搜索关键词
        keywords = _extract_search_keywords(field_path, old_val, new_val)
        if not keywords:
            continue

        # 在章节中搜索
        affected_ch = []
        for ch_name, text in chapter_texts.items():
            if any(kw in text for kw in keywords):
                affected_ch.append(ch_name)

        # 在 outline 中搜索
        affected_ol = []
        for ol_name, text in outline_texts.items():
            if any(kw in text for kw in keywords):
                affected_ol.append(ol_name)

        # 生成建议
        suggestion = _generate_suggestion(field_path, old_val, new_val, affected_ch)

        items.append(ImpactItem(
            field_path=field_path,
            old_value=old_val,
            new_value=new_val,
            affected_chapters=affected_ch,
            affected_outlines=affected_ol,
            suggestion=suggestion,
        ))

    return items


def _extract_search_keywords(
    field_path: str, old_val: str | None, new_val: str | None
) -> list[str]:
    """从变动中提取用于搜索的关键词。

    策略：优先提取专有名词（冒号前名称、引号内术语、3字以上中文词），
    避免使用 2 字通用词导致误匹配。
    """
    keywords: list[str] = []

    for val in (new_val, old_val):
        if not val:
            continue
        # 提取冒号前的名称（最精确）
        for key in re.findall(r"^([^：:，。]{2,10})[：:]", val):
            keywords.append(key.strip())
        # 提取引号内术语
        for quoted in re.findall(r"[『「](.+?)[』」]", val):
            keywords.append(quoted)
        # 提取 3 字以上连续中文字（专有名词）
        for name in re.findall(r"[\u4e00-\u9fff]{3,6}", val):
            keywords.append(name)
        # 提取开头的 2-3 字中文名（人名、地名）
        head_match = re.match(r"^([\u4e00-\u9fff]{2,3})", val)
        if head_match:
            name = head_match.group(1)
            keywords.append(name)
            if len(name) >= 3:
                keywords.append(name[:2])  # 也提取前 2 字

    # 从 field_path 提取
    path_parts = field_path.split(".")
    for part in path_parts:
        if part not in ("facts", "forbidden", "geography", "factions",
                        "timeline", "narrative_anchors", "power_system",
                        "+", "-", "rules", "writing_constraints"):
            if len(part) >= 2:
                keywords.append(part)

    # 去重且去除通用词
    seen = set()
    unique: list[str] = []
    generic = {
        "不得", "主角", "秘境", "世界", "需要", "不得让", "不得出",
        "能力", "角色", "设定", "场景", "战斗", "修炼", "训练",
        "存在", "出现", "管理", "机构", "政府", "成为", "通过",
    }
    for kw in keywords:
        if kw not in seen and kw not in generic:
            seen.add(kw)
            unique.append(kw)

    return unique


def _generate_suggestion(
    field_path: str,
    old_val: str | None,
    new_val: str | None,
    affected_ch: list[str],
) -> str:
    """生成人工审核建议。"""
    if old_val is None and new_val:
        return f"新增设定，检查受影响章节是否一致"
    if new_val is None and old_val:
        return f"删除设定，检查受影响章节是否仍引用此设定"
    return f"设定变更，人工核查受影响章节描述是否一致"
