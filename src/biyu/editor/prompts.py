"""Editor system prompt + user prompt 构建。"""
from __future__ import annotations

import json
import re
from pathlib import Path


_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts" / "editor"


def _read_required_text(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Required prompt file could not be read: {path}") from exc


def _read_required_fragments(filename: str) -> dict:
    path = _PROMPTS_DIR / filename
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Required prompt fragments could not be read: {path}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Required prompt fragments must be a JSON object: {path}")
    return loaded


EDITOR_SYSTEM_PROMPT = _read_required_text("system.md")
_FRAGMENTS = _read_required_fragments("fragments.json")


def build_editor_system_prompt(*, has_approved_planning: bool) -> str:
    """按确定性批准状态构建 Editor system prompt。

    有已批合同时返回现役 prompt 原文；无合同时物理移除完整第 8 维，
    包括其边界句，避免让 LLM 自行判断是否跳过。
    """
    if has_approved_planning:
        return EDITOR_SYSTEM_PROMPT

    planning_start = re.search(r"(?m)^\*\*8\.", EDITOR_SYSTEM_PROMPT)
    if planning_start is None:
        path = _PROMPTS_DIR / "system.md"
        raise RuntimeError(f"Required Editor prompt section boundaries are missing: {path}")
    workflow_start = re.search(
        r"(?m)^##\s", EDITOR_SYSTEM_PROMPT[planning_start.end() :]
    )
    if workflow_start is None:
        path = _PROMPTS_DIR / "system.md"
        raise RuntimeError(f"Required Editor prompt section boundaries are missing: {path}")
    workflow_index = planning_start.end() + workflow_start.start()
    return (
        EDITOR_SYSTEM_PROMPT[: planning_start.start()]
        + EDITOR_SYSTEM_PROMPT[workflow_index:]
    )


def build_editor_user_prompt(
    chapter_num: int,
    chapter_text: str,
    characters_summary: str = "",
    prev_chapter_tail: str = "",
    planning: str = "",
    injection_v2: bool = False,
    creative_anchor: str = "",
    lookup_catalog: str = "",
) -> str:
    """Build the user prompt for the Editor LLM call.

    Args:
        chapter_num: 章节号
        chapter_text: 章节正文
        characters_summary: 角色速查信息
        prev_chapter_tail: 上一章末500字
        planning: 规划件全文(已批的 planning.md 内容),用于规划履约检查
        injection_v2: 是否启用 Q-1 注入分档。
        creative_anchor: 创作锚点全文;默认路径同样预注入。
        lookup_catalog: 人物、世界观与历史的目录档文本。
    """
    parts = [_FRAGMENTS["review_header"].format(chapter_num=chapter_num)]

    if prev_chapter_tail:
        if injection_v2:
            parts.append("--- 上一章结尾(若本章另起新场景,可不接续) ---")
        else:
            parts.append(_FRAGMENTS["prev_tail_header"])
        parts.append(prev_chapter_tail)
        parts.append(_FRAGMENTS["chapter_header"])

    parts.append(chapter_text)

    if planning:
        parts.append(_FRAGMENTS["planning_header"])
        parts.append(planning)

    if creative_anchor:
        parts.append("\n--- 创作锚点 ---")
        parts.append(creative_anchor)

    if injection_v2 and lookup_catalog:
        parts.append("\n--- 以下只是清单,要用再查,不必全查 ---")
        parts.append(lookup_catalog)

    if characters_summary:
        parts.append(_FRAGMENTS["characters_header"])
        parts.append(characters_summary)

    return "\n".join(parts)
