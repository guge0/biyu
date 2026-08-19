"""Guarded manuscript import used only by the chapter workbench."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from biyu.importer.splitter import split_text
from biyu.projections import select_new_shard


class ImportConflict(RuntimeError):
    """Raised when an import would overwrite an existing chapter."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def chapter_origin(book_dir: Path, chapter: int) -> str:
    """Return the explicit source marker; missing/invalid metadata is unknown."""
    path = book_dir / "logs" / f"ch{chapter}" / "meta.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "unknown"
    origin = str(value.get("origin", "unknown"))
    return origin if origin in {"imported", "generated", "unknown"} else "unknown"


def items_from_explicit_text(
    text: str,
    *,
    identity: str,
    source: str = "paste",
) -> list[dict[str, Any]]:
    """Reuse the existing splitter for an explicitly chapter-delimited text."""
    result = split_text(text)
    return [
        {
            "chapter": chapter.num,
            "content": (
                f"第{chapter.num}章"
                + (f" {chapter.title}" if chapter.title else "")
                + "\n"
                + chapter.text
            ).rstrip(),
            "identity": identity,
            "source": source,
        }
        for chapter in result.chapters
    ]


def _normalize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for raw in items:
        identity = str(raw.get("identity", ""))
        if identity not in {"candidate", "official"}:
            raise ValueError("导入身份必须选择候选稿或正式稿")
        chapter = int(raw.get("chapter", 0) or 0)
        if chapter < 1:
            raise ValueError("导入章节号必须从 1 开始")
        content = str(raw.get("content", "")).strip()
        if not content:
            raise ValueError(f"第 {chapter} 章导入内容为空")
        key = (chapter, identity)
        if key in seen:
            raise ValueError(f"第 {chapter} 章的同一身份重复出现")
        seen.add(key)
        normalized.append({
            "chapter": chapter,
            "content": content,
            "identity": identity,
            "source": str(raw.get("source") or "paste"),
        })
    if not normalized:
        raise ValueError("没有可导入的稿件")
    return normalized


def _target(book_dir: Path, chapter: int, identity: str) -> Path:
    if identity == "candidate":
        return book_dir / "chapters" / "_pending" / f"ch{chapter}.md"
    return book_dir / "chapters" / f"ch{chapter}.md"


def preview_import(book_dir: Path, items: list[dict[str, Any]]) -> dict[str, Any]:
    values = _normalize(items)
    return {
        "items": [
            {
                **item,
                "content": item["content"],
                "exists": _target(book_dir, item["chapter"], item["identity"]).exists(),
                "target": str(_target(book_dir, item["chapter"], item["identity"])),
                "origin": chapter_origin(book_dir, item["chapter"]),
            }
            for item in values
        ],
        "requires_confirmation": any(
            _target(book_dir, item["chapter"], item["identity"]).exists()
            for item in values
        ),
        "llm_calls": 0,
        "estimated_cost": 0.0,
    }


def _recycle(book_dir: Path, chapter: int, identity: str, target: Path) -> None:
    trash = book_dir / "logs" / f"ch{chapter}" / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    prefix = "official_import" if identity == "official" else "candidate_import"
    entry_id = f"{prefix}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}_{uuid4().hex[:8]}"
    content_path = trash / f"{entry_id}.md"
    shutil.move(str(target), content_path)
    meta = {
        "id": entry_id,
        "kind": identity,
        "deleted_at": _now(),
        "content_path": content_path.name,
    }
    (trash / f"{entry_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _mark_imported(book_dir: Path, chapter: int, source: str) -> None:
    path = book_dir / "logs" / f"ch{chapter}" / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = {}
    meta.update({
        "origin": "imported",
        "imported_at": _now(),
        "imported_from": source,
    })
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_manuscripts(
    book_dir: Path,
    items: list[dict[str, Any]],
    *,
    confirmed: bool = False,
) -> list[dict[str, Any]]:
    """Write guarded imports without invoking the legacy activation path."""
    values = _normalize(items)
    conflicts = [
        item for item in values
        if _target(book_dir, item["chapter"], item["identity"]).exists()
    ]
    if conflicts and not confirmed:
        chapters = "、".join(str(item["chapter"]) for item in conflicts)
        raise ImportConflict(f"第 {chapters} 章已有同身份稿件，需要二次确认")
    results: list[dict[str, Any]] = []
    for item in values:
        target = _target(book_dir, item["chapter"], item["identity"])
        if target.exists():
            _recycle(book_dir, item["chapter"], item["identity"], target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
        _mark_imported(book_dir, item["chapter"], item["source"])
        results.append({
            "chapter": item["chapter"],
            "identity": item["identity"],
            "target": str(target),
            "origin": "imported",
        })
    return results


def preview_memory(
    book_dir: Path,
    chapters: list[int],
    build_one: Callable[[int, Path], dict[str, Any]],
) -> dict[str, Any]:
    """Build exactly the first chapter shard and stop for author confirmation."""
    ordered = sorted(set(int(chapter) for chapter in chapters if int(chapter) > 0))
    if not ordered:
        raise ValueError("没有可建立记忆的正式章节")
    first = ordered[0]
    official = book_dir / "chapters" / f"ch{first}.md"
    if not official.exists():
        raise FileNotFoundError(f"第 {first} 章正式稿不存在")
    shard = build_one(first, official)
    shard.setdefault("chapter", first)
    shard.setdefault("official_sha256", hashlib.sha256(official.read_bytes()).hexdigest())
    select_new_shard(book_dir, first, shard)
    return {
        "preview_chapter": first,
        "preview": shard,
        "remaining": ordered[1:],
        "calls": len(ordered),
        "estimated_cost": round(len(ordered) * 0.03, 2),
    }

