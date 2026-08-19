"""一致性检查 — Phase 1 只做一条规则: 已死角色不能在本章"活动"。

算法: 正则 + 关键词, 不走 LLM。
明确不做: 语义级判断、复杂回忆/梦境识别(Phase 2)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from biyu.db import Character, list_characters


@dataclass
class ConsistencyIssue:
    """一致性检查发现的问题。"""
    rule: str              # "dead_character_active"
    severity: str          # "warning" / "critical"
    character: str
    chapter_num: int
    location: str          # 段落前80字 + "...[出现点]..." + 后20字
    suggestion: str


# 活动动词: 死角色名 + 这些动词在同一段落内且距离 < 10 字 → 命中
ACTIVE_VERBS = [
    '说', '道', '笑', '喊', '叫', '吼', '骂', '问', '答', '唱',
    '走', '跑', '冲', '飞', '跳', '站', '坐', '蹲', '跪', '躺',
    '看', '望', '盯', '瞪', '瞥', '瞅',
    '拿', '握', '挥', '击', '拍', '推', '拉', '抓', '扔', '挑',
    '想', '觉得', '感觉', '知道',
    '点头', '摇头', '叹', '哭', '怒', '怒喝', '冷笑', '大笑',
]

# 活动名词模式: "死角色名的 + 动作名词" → 也算活动
ACTIVE_NOUNS = [
    '笑声', '脚步', '呼吸', '声音', '身影', '动作', '话', '回答',
    '手', '眼神', '目光', '声音', '怒吼', '咆哮',
]

# 回忆关键词: 段落包含这些词 → 跳过该段落不检查
RECALL_KEYWORDS = [
    '想起', '回忆', '梦见', '记得', '记得那', '记忆中', '脑海中',
    '回忆起', '忆起', '不禁想起', '忽然想起', '突然想起',
    '往事', '曾经', '那时候', '那一年',
    '祭拜', '遗物', '墓前', '牌位', '遗言', '生前',
    '当年', '从前', '小时候',
]


def _is_recall_paragraph(paragraph: str) -> bool:
    """Check if paragraph is a recall/flashback context."""
    return any(kw in paragraph for kw in RECALL_KEYWORDS)


def _is_in_dialogue(text: str, name_pos: int) -> bool:
    """Check if name_pos falls inside a quoted dialogue segment (「」or ""or "")."""
    # Track quote pairs: find the nearest opening quote before name_pos
    # and check if it's been closed after name_pos
    quote_pairs = [('「', '」'), ('"', '"'), ('\u201c', '\u201d')]
    for open_q, close_q in quote_pairs:
        # Find last opening quote before name_pos
        last_open = text.rfind(open_q, 0, name_pos)
        if last_open == -1:
            continue
        # Check if there's a closing quote between the opening and name_pos
        close_before = text.find(close_q, last_open, name_pos)
        if close_before == -1:
            # Opening quote found, no close before name_pos → inside dialogue
            return True
    return False


def _check_dead_character_in_paragraph(
    char: Character,
    paragraph: str,
) -> list[dict]:
    """Check if a dead character is 'active' in a paragraph.

    Returns list of match dicts with keys: verb/noun, position, snippet.
    """
    issues = []
    name = char.name

    # Find all occurrences of the character name
    start = 0
    while True:
        idx = paragraph.find(name, start)
        if idx == -1:
            break

        # Check active verbs: name ... verb within 10 chars after
        segment_after = paragraph[idx + len(name):idx + len(name) + 12]
        for verb in ACTIVE_VERBS:
            verb_idx = segment_after.find(verb)
            if 0 <= verb_idx <= 10:
                issues.append({
                    "type": "verb",
                    "match": verb,
                    "name_pos": idx,
                })
                break  # One hit per name occurrence is enough

        # Check "name的 + active_noun" pattern
        pattern_pos = paragraph.find(name + "的", idx)
        if pattern_pos == idx:
            after_de = paragraph[idx + len(name) + 1:idx + len(name) + 6]
            for noun in ACTIVE_NOUNS:
                if after_de.startswith(noun):
                    issues.append({
                        "type": "noun",
                        "match": noun,
                        "name_pos": idx,
                    })
                    break

        start = idx + len(name)

    return issues


def _make_location_snippet(text: str, position: int) -> str:
    """Create a location snippet around the match position."""
    before = text[max(0, position - 40):position]
    after = text[position:min(len(text), position + 40)]
    return f"...{before}【出现点】{after}..."


def check_chapter(
    book_dir: Path,
    chapter_num: int,
    chapter_text: str | None = None,
) -> list[ConsistencyIssue]:
    """Check a chapter for consistency issues.

    Args:
        book_dir: Book directory containing book.db and chapters/.
        chapter_num: Chapter number to check.
        chapter_text: Optional pre-loaded text. If None, reads from file.

    Returns:
        List of ConsistencyIssue instances.
    """
    # Load chapter text if not provided
    if chapter_text is None:
        ch_path = book_dir / "chapters" / f"ch{chapter_num}.md"
        if not ch_path.exists():
            return []
        chapter_text = ch_path.read_text(encoding="utf-8")

    # Load dead characters
    dead_chars = list_characters(book_dir, status="dead")
    if not dead_chars:
        return []

    # Split into paragraphs
    paragraphs = chapter_text.split("\n")
    issues: list[ConsistencyIssue] = []

    for para in paragraphs:
        para = para.strip()
        if not para or _is_recall_paragraph(para):
            continue

        for char in dead_chars:
            if char.name not in para:
                continue

            matches = _check_dead_character_in_paragraph(char, para)
            for match in matches:
                # D-04: Skip if the character name is inside dialogue quotes
                if _is_in_dialogue(para, match["name_pos"]):
                    continue

                # Build location snippet
                snippet = para[:80]
                if len(para) > 100:
                    snippet = para[:80] + "..."

                issues.append(ConsistencyIssue(
                    rule="dead_character_active",
                    severity="warning",
                    character=char.name,
                    chapter_num=chapter_num,
                    location=snippet,
                    suggestion=(
                        f"若是回忆场景,建议在段首加'陈风想起{char.name}生前'"
                        if char.name else ""
                    ),
                ))

    return issues
