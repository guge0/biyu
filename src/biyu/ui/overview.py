"""R5-3A whole-book read model; this module never mutates book data."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from biyu.fingerprint.ledger import read_feedback_entries
from biyu.ui.cli_executor import running_action
from biyu.ui.workbench import _book_dir, _planning_status
from biyu.ui.workbench_state import (
    STEPS,
    asset_state,
    persisted_run_state,
    read_workbench_step,
)
from biyu.wordguard import count_cjk_chars


router = APIRouter(prefix="/api/overview", tags=["overview"])

_CHAPTER_FILE = re.compile(r"^ch([1-9]\d*)\.md$")
_CHAPTER_DIR = re.compile(r"^ch([1-9]\d*)$")
_TITLE_PREFIX = re.compile(r"^第\s*[^\s:：—–-]+章\s*[:：—–-]?\s*")
_COST_NOTE = "只算生成正文，不含起名和对话"


def _chapter_numbers(book_dir: Path) -> list[int]:
    chapters: set[int] = set()
    for directory in (
        book_dir / "outlines",
        book_dir / "chapters",
        book_dir / "chapters" / "_pending",
        book_dir / "判词",
    ):
        if not directory.exists():
            continue
        for path in directory.iterdir():
            match = _CHAPTER_FILE.fullmatch(path.name)
            if path.is_file() and match:
                chapters.add(int(match.group(1)))
    logs = book_dir / "logs"
    if logs.exists():
        for path in logs.iterdir():
            match = _CHAPTER_DIR.fullmatch(path.name)
            if path.is_dir() and match:
                chapters.add(int(match.group(1)))
    return sorted(chapters)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _chapter_title(book_dir: Path, chapter: int) -> str:
    paths = (
        book_dir / "chapters" / f"ch{chapter}.md",
        book_dir / "chapters" / "_pending" / f"ch{chapter}.md",
        book_dir / "outlines" / f"ch{chapter}.md",
    )
    for path in paths:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            heading = line.lstrip("#").strip() if line.startswith("#") else ""
            if not heading:
                break
            title = _TITLE_PREFIX.sub("", heading).strip()
            if title:
                return title
            break
    return "未命名章节"


def _durable_updated_at(
    book_dir: Path,
    chapter: int,
) -> tuple[datetime, str] | None:
    path = book_dir / "logs" / f"ch{chapter}" / "workbench_state.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("step") not in STEPS:
        return None
    raw = payload.get("updated_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed, raw.strip()


def _problem_counts(book_dir: Path) -> dict[int, int]:
    counts: dict[int, int] = {}
    for item in read_feedback_entries(book_dir):
        chapter = item.get("chapter")
        if (
            item.get("scope") == "sentence"
            and item.get("action") in {"revise", "note_problem"}
            and isinstance(chapter, int)
            and not isinstance(chapter, bool)
            and chapter > 0
        ):
            counts[chapter] = counts.get(chapter, 0) + 1
    return counts


def _writing_cost(book_dir: Path) -> float | None:
    path = book_dir / "logs" / "cost_log.csv"
    if not path.exists():
        return None
    total = Decimal("0")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"chapter", "stage", "cost_cny"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError("写作花费记录缺少必要列")
            for line_no, row in enumerate(reader, 2):
                try:
                    chapter = int(str(row.get("chapter", "")).strip())
                except ValueError:
                    continue
                if chapter < 1 or row.get("stage") == "editor_total":
                    continue
                try:
                    cost = Decimal(str(row.get("cost_cny", "")).strip())
                except InvalidOperation as exc:
                    raise ValueError(
                        f"写作花费记录第 {line_no} 行金额无效"
                    ) from exc
                if not cost.is_finite() or cost < 0:
                    raise ValueError(f"写作花费记录第 {line_no} 行金额无效")
                total += cost
    except csv.Error as exc:
        raise ValueError("写作花费记录无法读取") from exc
    return float(total)


def _chapter_status(
    *,
    step: str,
    assets: str,
    run: str,
    planning_status: str,
) -> tuple[str, str]:
    has_official = assets in {"official", "both"}
    has_candidate = assets in {"candidate", "both"}
    inconsistent = (
        (step == "review" and not has_official)
        or (step in {"reading", "revision", "adoption"} and not has_candidate)
        or (step == "generation" and planning_status != "已批")
    )
    if inconsistent:
        return "这一章状态对不上，请打开检查", "工序记录与现有稿件或方案不一致"
    if run == "busy":
        return "正在处理", ""
    if run == "fail":
        return "上次操作没有完成，等你重试", ""
    return {
        "outline": "细纲还没写完",
        "planning": "方案还在确认中",
        "generation": "等着生成",
        "reading": "有稿等你读",
        "revision": "有稿等你读",
        "adoption": "有稿等你读",
        "review": "已定稿",
    }[step], ""


def _book_display_name(book_dir: Path) -> str:
    path = book_dir / "book.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return str(meta.get("display_name") or meta.get("title") or book_dir.name)


def _is_finalized(book_dir: Path, book_key: str, chapter: int) -> bool:
    """Recheck the durable author-facing finalized contract on the server."""
    assets = asset_state(book_dir, chapter)
    step = read_workbench_step(book_dir, chapter)
    planning_status = _planning_status(
        _read(book_dir / "logs" / f"ch{chapter}" / "planning.md")
    )
    persisted_run, _failure = persisted_run_state(book_dir, chapter)
    run = "busy" if running_action(book_key, chapter) else persisted_run
    _status, state_error = _chapter_status(
        step=step,
        assets=assets,
        run=run,
        planning_status=planning_status,
    )
    return (
        step == "review"
        and assets in {"official", "both"}
        and not state_error
    )


def _export_body(text: str) -> str:
    """Remove a leading Markdown chapter heading; TXT supplies its own title."""
    lines = text.strip().splitlines()
    for index, raw in enumerate(lines):
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            del lines[index]
        break
    return "\n".join(lines).strip()


def build_overview(book_dir: Path, book_key: str) -> dict[str, Any]:
    """Build one deterministic, read-only whole-book snapshot."""
    book_dir = Path(book_dir)
    chapters = _chapter_numbers(book_dir)
    problem_counts = _problem_counts(book_dir)
    encoded_book = quote(book_key, safe="")
    groups: dict[str, list[dict[str, Any]]] = {
        "waiting": [],
        "problem_finalized": [],
        "finalized": [],
    }
    latest: tuple[datetime, int, str] | None = None
    rows_by_chapter: dict[int, dict[str, Any]] = {}
    total_words = 0
    finalized_count = 0

    for chapter in chapters:
        official = book_dir / "chapters" / f"ch{chapter}.md"
        official_text = (
            official.read_text(encoding="utf-8") if official.exists() else ""
        )
        if official_text:
            total_words += count_cjk_chars(official_text)
        assets = asset_state(book_dir, chapter)
        step = read_workbench_step(book_dir, chapter)
        persisted_run, _failure = persisted_run_state(book_dir, chapter)
        run = "busy" if running_action(book_key, chapter) else persisted_run
        planning_status = _planning_status(
            _read(book_dir / "logs" / f"ch{chapter}" / "planning.md")
        )
        status, state_error = _chapter_status(
            step=step,
            assets=assets,
            run=run,
            planning_status=planning_status,
        )
        updated = _durable_updated_at(book_dir, chapter)
        updated_raw = updated[1] if updated else None
        row = {
            "chapter": chapter,
            "title": _chapter_title(book_dir, chapter),
            "status": status,
            "state_error": state_error,
            "problem_count": problem_counts.get(chapter, 0),
            "word_count": count_cjk_chars(official_text),
            "updated_at": updated_raw,
            "href": (
                f"/workbench.html?book={encoded_book}&chapter={chapter}"
            ),
        }
        rows_by_chapter[chapter] = row
        if updated:
            candidate = (updated[0], chapter, updated[1])
            if latest is None or candidate[:2] > latest[:2]:
                latest = candidate

        is_finalized = (
            step == "review"
            and assets in {"official", "both"}
            and not state_error
        )
        if is_finalized:
            finalized_count += 1
            target = (
                "problem_finalized"
                if row["problem_count"] > 0
                else "finalized"
            )
            groups[target].append(row)
        else:
            groups["waiting"].append(row)

    metrics: dict[str, Any] = {
        "finalized_chapters": finalized_count,
        "total_words": total_words,
        "waiting_chapters": len(groups["waiting"]),
    }
    writing_cost = _writing_cost(book_dir)
    if writing_cost is not None:
        metrics["writing_cost"] = writing_cost
        metrics["writing_cost_note"] = _COST_NOTE

    breakpoint = None
    if latest is not None:
        _parsed, chapter, raw = latest
        row = rows_by_chapter[chapter]
        breakpoint = {
            "chapter": chapter,
            "status": row["status"],
            "updated_at": raw,
            "href": row["href"],
        }
    return {
        "book": {
            "id": book_key,
            "display_name": _book_display_name(book_dir),
        },
        "breakpoint": breakpoint,
        "breakpoint_empty": (
            "" if breakpoint else "还没有可用的最近进度记录"
        ),
        "metrics": metrics,
        "groups": groups,
    }


@router.get("/books/{book}")
def overview(book: str) -> dict[str, Any]:
    try:
        return build_overview(_book_dir(book), book)
    except HTTPException:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"整书概览没有读成功：{exc}",
        ) from exc


@router.post("/books/{book}/export")
def export_finalized_chapters(book: str, payload: dict[str, Any]) -> Response:
    raw_chapters = payload.get("chapters")
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raise HTTPException(status_code=400, detail="请至少选择一章已定稿正文。")
    if any(
        isinstance(chapter, bool)
        or not isinstance(chapter, int)
        or chapter < 1
        for chapter in raw_chapters
    ):
        raise HTTPException(status_code=400, detail="选择的章节号不正确，请刷新后重试。")

    book_dir = _book_dir(book)
    chapters = sorted(set(raw_chapters))
    for chapter in chapters:
        if not _is_finalized(book_dir, book, chapter):
            raise HTTPException(
                status_code=409,
                detail=f"第 {chapter} 章还没有定稿，未导出任何内容。",
            )
        official = book_dir / "chapters" / f"ch{chapter}.md"
        if not official.exists() or not official.read_text(encoding="utf-8").strip():
            raise HTTPException(
                status_code=409,
                detail=f"第 {chapter} 章没有可导出的正式正文，未导出任何内容。",
            )

    display_name = _book_display_name(book_dir)
    sections = [f"《{display_name}》"]
    for chapter in chapters:
        official = book_dir / "chapters" / f"ch{chapter}.md"
        body = _export_body(official.read_text(encoding="utf-8"))
        title = _chapter_title(book_dir, chapter)
        heading = f"第 {chapter} 章"
        if title != "未命名章节":
            heading += f" {title}"
        sections.append(f"{heading}\n\n{body}".rstrip())

    filename = quote(f"{display_name}.txt", safe="")
    return Response(
        content=("\n\n\n".join(sections) + "\n").encode("utf-8"),
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )
