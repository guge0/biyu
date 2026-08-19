"""Append-only author feedback ledger.

Ring 6 will own any future reader.  This module intentionally exposes only the
write seam used when the author marks a sentence.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def append_feedback(
    book_dir: Path,
    *,
    book: str,
    chapter: int,
    round_no: int,
    scope: str,
    action: str,
    candidate_sha: str = "",
    anchor: int | None = None,
    text: str = "",
    verdict: str = "",
    author_comment: str = "",
    in_revision_package: bool,
    from_kind: str = "",
) -> dict[str, Any]:
    """Append one immutable JSON record and return the exact written value."""
    if action not in {"revise", "note_problem", "good"}:
        raise ValueError("反馈动作必须是 revise、note_problem 或 good")
    if scope not in {"sentence", "chapter"}:
        raise ValueError("反馈范围必须是 sentence 或 chapter")
    if chapter < 1:
        raise ValueError("章节号必须从 1 开始")
    entry: dict[str, Any] = {
        "id": uuid4().hex,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "book": book,
        "chapter": chapter,
        "round": max(0, int(round_no)),
        "scope": scope,
        "action": action,
        "author_comment": author_comment.strip(),
        "in_revision_package": bool(in_revision_package),
    }
    if scope == "sentence":
        normalized = text.strip()
        if not normalized or not candidate_sha or anchor is None or anchor < 1:
            raise ValueError("句级反馈必须包含候选 SHA、段落锚点和原句")
        entry.update({
            "candidate_sha": candidate_sha,
            "anchor": anchor,
            "text": normalized,
        })
    else:
        normalized_verdict = verdict.strip()
        if not normalized_verdict:
            raise ValueError("章级反馈必须包含判词或摘要")
        entry["verdict"] = normalized_verdict
    if from_kind:
        entry["from"] = from_kind
    path = book_dir / "反馈账.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    return entry
