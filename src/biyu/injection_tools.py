"""Static injection catalogs, lossless lookups, and per-book tool telemetry.

This module is deliberately independent from model adapters.  Catalogs are
derived from files on disk, while query callers supply any token/cost figures
when recording a completed tool call.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from threading import Lock
from typing import Any, Iterable

import yaml

from biyu.truth_files import TRUTH_FILE_NAMES


CATALOG_GUIDANCE = "以下只是清单,要用再查,不必全查"

_WORLD_SECTIONS: tuple[tuple[str, str], ...] = (
    ("narrative_anchors", "创作锚点"),
    ("facts", "不可变硬设定"),
    ("power_system", "力量·修炼体系"),
    ("forbidden", "绝对禁止"),
    ("geography", "地理"),
    ("factions", "势力"),
    ("timeline", "时间线锚点"),
)
_LOG_LOCK = Lock()


@dataclass(frozen=True)
class QueryResult:
    """Lossless lookup result plus telemetry metadata."""

    content: str
    hit: bool
    return_count: int


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def _is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _render_yaml(value: Any) -> str:
    if isinstance(value, str):
        return value
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()


def _one_sentence(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未填写定位"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), text)
    match = re.match(r"^.*?[。！？!?](?:[\"'”’])?", first_line)
    return match.group(0) if match else first_line


def build_character_catalog(book_dir: Path) -> str:
    """Return one static directory line per character."""
    data = _load_yaml(book_dir / "characters.yaml")
    characters = data.get("characters", [])
    lines = [CATALOG_GUIDANCE]
    if not isinstance(characters, list):
        return "\n".join(lines)
    for character in characters:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "未命名")
        tier = str(character.get("tier") or "未分档")
        positioning = next(
            (
                _one_sentence(character.get(field))
                for field in ("role", "brief", "background")
                if _is_nonempty(character.get(field))
            ),
            "未填写定位",
        )
        lines.append(f"- {name} · {tier} · {positioning} · 要用再查,不必全查")
    return "\n".join(lines)


def build_worldbook_catalog(
    book_dir: Path, *, exclude_fields: set[str] | None = None
) -> str:
    """Return the seven known worldbook sections with exact stored sizes."""
    worldbook = _load_yaml(book_dir / "worldbook.yaml")
    lines = [CATALOG_GUIDANCE]
    for field, title in _WORLD_SECTIONS:
        if field in (exclude_fields or set()):
            continue
        value = worldbook.get(field)
        size = len(_render_yaml(value).strip()) if _is_nonempty(value) else 0
        state = f"{size} 字" if size else "空"
        lines.append(f"- {title} · {state} · 要用再查,不必全查")
    return "\n".join(lines)


def build_book_material_catalog(book_dir: Path) -> str:
    """List chapter prose and outlines by filename only for subscription roles."""
    lines = [CATALOG_GUIDANCE]
    for directory, label in (("chapters", "正式正文"), ("outlines", "章节细纲")):
        root = book_dir / directory
        if not root.exists():
            continue
        for path in sorted(root.glob("ch*.md")):
            if re.fullmatch(r"ch\d+\.md", path.name):
                lines.append(f"- {label} {path.name} · 要用再查,不必全查")
    return "\n".join(lines)


def build_truth_catalog(book_dir: Path) -> str:
    """Return only non-empty truth-file names."""
    lines = [CATALOG_GUIDANCE]
    truth_dir = book_dir / "truth_files"
    for name in TRUTH_FILE_NAMES:
        path = truth_dir / name
        if path.exists() and path.read_text(encoding="utf-8").strip():
            lines.append(f"- {name} · 要用再查,不必全查")
    return "\n".join(lines)


def build_history_catalog(book_dir: Path, *, exclude_chapter: int | None = None) -> str:
    """Return an official-chapter directory without loading chapter prose."""
    lines = [CATALOG_GUIDANCE]
    for path in _chapter_files(book_dir):
        chapter = int(path.stem.removeprefix("ch"))
        if chapter == exclude_chapter:
            continue
        lines.append(f"- 第 {chapter} 章 · 要用再查,不必全查")
    return "\n".join(lines)


def _alias_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _alias_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _alias_values(nested)


def query_character(book_dir: Path, query: str) -> QueryResult:
    """Look up complete character cards by exact canonical name or alias."""
    needle = query.strip()
    if not needle:
        return QueryResult("", False, 0)
    characters = _load_yaml(book_dir / "characters.yaml").get("characters", [])
    matches = []
    if isinstance(characters, list):
        for character in characters:
            if not isinstance(character, dict):
                continue
            names = {str(character.get("name") or "")}
            names.update(alias for alias in _alias_values(character.get("aliases")) if alias)
            if needle in names:
                matches.append(character)
    content = yaml.safe_dump(matches, allow_unicode=True, sort_keys=False).strip()
    return QueryResult(content if matches else "", bool(matches), len(matches))


def query_worldbook(book_dir: Path, query: str) -> QueryResult:
    """Return every complete top-level worldbook item containing ``query``."""
    needle = query.strip()
    if not needle:
        return QueryResult("", False, 0)
    worldbook = _load_yaml(book_dir / "worldbook.yaml")
    matches: list[dict[str, Any]] = []
    for field, _title in _WORLD_SECTIONS:
        value = worldbook.get(field)
        if isinstance(value, list):
            for item in value:
                if needle in _render_yaml(item):
                    matches.append({"section": field, "content": item})
        elif isinstance(value, dict):
            for key, item in value.items():
                complete_item = {key: item}
                if needle in _render_yaml(complete_item):
                    matches.append({"section": field, "content": complete_item})
        elif _is_nonempty(value) and needle in str(value):
            matches.append({"section": field, "content": value})
    content = yaml.safe_dump(matches, allow_unicode=True, sort_keys=False).strip()
    return QueryResult(content if matches else "", bool(matches), len(matches))


def _chapter_files(book_dir: Path) -> list[Path]:
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.exists():
        return []
    numbered: list[tuple[int, Path]] = []
    for path in chapters_dir.glob("ch*.md"):
        match = re.fullmatch(r"ch(\d+)\.md", path.name)
        if match:
            numbered.append((int(match.group(1)), path))
    return [path for _number, path in sorted(numbered)]


def query_history(book_dir: Path, query: str) -> QueryResult:
    """Return complete official chapters matching a number or literal keyword."""
    needle = query.strip()
    if not needle:
        return QueryResult("", False, 0)
    chapters = _chapter_files(book_dir)
    chapter_match = re.fullmatch(r"(?:第\s*)?(\d+)(?:\s*章)?", needle)
    if chapter_match:
        chapters = [
            path for path in chapters
            if path.stem == f"ch{int(chapter_match.group(1))}"
        ]
    else:
        chapters = [path for path in chapters if needle in path.read_text(encoding="utf-8")]
    blocks = [f"## {path.stem}\n\n{path.read_text(encoding='utf-8')}" for path in chapters]
    return QueryResult("\n\n".join(blocks), bool(blocks), len(blocks))


def query_truth(book_dir: Path, query: str) -> QueryResult:
    """Return complete truth files containing a literal keyword."""
    needle = query.strip()
    if not needle:
        return QueryResult("", False, 0)
    blocks: list[str] = []
    for name in TRUTH_FILE_NAMES:
        path = book_dir / "truth_files" / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if needle in content:
            blocks.append(f"## {name}\n\n{content}")
    return QueryResult("\n\n".join(blocks), bool(blocks), len(blocks))


def _book_id(book_dir: Path) -> str:
    meta_path = book_dir / "book.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("id"):
                return str(meta["id"])
        except (OSError, json.JSONDecodeError):
            pass
    return book_dir.name


def append_tool_call(
    book_dir: Path,
    *,
    role: str,
    chapter: int,
    item: str,
    query: str,
    result: QueryResult,
    tokens: int,
    cost: float,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    response_group: str | None = None,
    response_tool_call_count: int = 1,
    usage_scope: str = "triggering_response_shared",
) -> dict[str, Any]:
    """Append one hit or miss to ``logs/tool_calls.jsonl``.

    ``query_index`` is scoped to the same book, chapter, and role.  Existing
    malformed lines are retained but ignored while calculating the next index.
    """
    log_path = book_dir / "logs" / "tool_calls.jsonl"
    book = _book_id(book_dir)
    with _LOG_LOCK:
        query_index = 1
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8").splitlines():
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    existing.get("book") == book
                    and existing.get("chapter") == chapter
                    and existing.get("role") == role
                ):
                    try:
                        query_index = max(query_index, int(existing.get("query_index", 0)) + 1)
                    except (TypeError, ValueError):
                        continue
        row: dict[str, Any] = {
            "role": role,
            "book": book,
            "chapter": chapter,
            "item": item,
            "query": query,
            "hit": result.hit,
            "return_count": result.return_count,
            "tokens": tokens if total_tokens is None else total_tokens,
            "cost": cost,
            "query_index": query_index,
            "prompt_tokens": tokens if prompt_tokens is None else prompt_tokens,
            "completion_tokens": 0 if completion_tokens is None else completion_tokens,
            "response_group": response_group or f"{role}:{chapter}:{query_index}",
            "response_tool_call_count": response_tool_call_count,
            "usage_scope": usage_scope,
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return row


def editor_observation_sink(book_dir: Path, *, chapter: int):
    """Adapt Editor's existing lookup events to the common JSONL contract."""
    from biyu.editor.tool_observer import ToolObservation

    item_names = {
        "look_up_character": "character",
        "look_up_setting": "worldbook",
        "look_up_history": "history",
        "look_up_visual": "history_visual",
    }

    def _append(event: ToolObservation) -> None:
        append_tool_call(
            book_dir,
            role="editor",
            chapter=chapter,
            item=item_names.get(event.tool_name, event.tool_name),
            query=event.query,
            result=QueryResult(event.result, event.matched, event.return_count),
            tokens=event.response_total_tokens,
            prompt_tokens=event.response_prompt_tokens,
            completion_tokens=event.response_completion_tokens,
            total_tokens=event.response_total_tokens,
            cost=event.response_cost,
            response_group=f"editor:{event.response_group}",
            response_tool_call_count=event.response_tool_call_count,
            usage_scope=event.usage_scope,
        )

    return _append
