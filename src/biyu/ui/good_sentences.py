"""Read-only, book-level view of sentences the author marked as good."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from biyu.fingerprint.ledger import read_feedback_entries
from biyu.ui.overview import _book_display_name
from biyu.ui.workbench import _book_dir


router = APIRouter(prefix="/api/good-sentences", tags=["good-sentences"])


def _time_key(raw: str) -> tuple[int, str]:
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return (1, raw)
    return (0, raw)


def build_good_sentences(book_dir, book_key: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for item in read_feedback_entries(book_dir):
        chapter = item.get("chapter")
        text = item.get("text")
        created_at = item.get("created_at")
        if item.get("action") != "good" or item.get("scope") != "sentence":
            continue
        if (
            isinstance(chapter, bool)
            or not isinstance(chapter, int)
            or chapter < 1
            or not isinstance(text, str)
            or not text.strip()
            or not isinstance(created_at, str)
            or not created_at.strip()
        ):
            continue
        entries.append(
            {
                "chapter": chapter,
                "text": text.strip(),
                "created_at": created_at.strip(),
            }
        )
    entries.sort(key=lambda item: (item["chapter"], _time_key(item["created_at"])))
    return {
        "book": {
            "id": book_key,
            "display_name": _book_display_name(book_dir),
        },
        "chapters": sorted({item["chapter"] for item in entries}),
        "entries": entries,
    }


@router.get("/books/{book}")
def good_sentences(book: str) -> dict[str, Any]:
    try:
        return build_good_sentences(_book_dir(book), book)
    except HTTPException:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"全书好句没有读成功：{exc}",
        ) from exc
