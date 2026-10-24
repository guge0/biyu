"""S-3 T4 · 旧版 biyu 数据根迁移(图纸导入向导 Tab③,决策6B)。

纯文件级复制,不调 LLM:
- POST /api/migrate/legacy/scan  {source_root} → 识别旧版书籍目录(book.json)
- POST /api/migrate/legacy/commit {source_root, ids} → 复制进当前数据根(重名加 -2 后缀)
只读源目录,不改源;目标书走正常书架(可玩可删)。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from biyu.config import get_data_root

router = APIRouter(prefix="/api/migrate/legacy", tags=["legacy-migrate"])


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_root: str


class CommitRequest(ScanRequest):
    ids: list[str]


def _find_legacy_books(source_root: Path) -> list[dict[str, Any]]:
    if not source_root.is_dir():
        raise HTTPException(status_code=400, detail="这个目录不存在,请重新选择")
    books = []
    for child in sorted(source_root.iterdir()):
        meta = child / "book.json"
        if not (child.is_dir() and meta.is_file()):
            continue
        try:
            import json

            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        chapters = child / "chapters"
        chapter_count = len(list(chapters.glob("ch*.md"))) if chapters.is_dir() else 0
        books.append({
            "id": child.name,
            "title": str(data.get("display_name") or data.get("title") or child.name),
            "chapter_count": chapter_count,
        })
    return books


@router.post("/scan")
def legacy_scan(request: ScanRequest) -> dict[str, Any]:
    root = Path(request.source_root.strip().strip('"')).expanduser()
    books = _find_legacy_books(root)
    return {"source_root": str(root), "books": books, "count": len(books)}


@router.post("/commit")
def legacy_commit(request: CommitRequest) -> dict[str, Any]:
    root = Path(request.source_root.strip().strip('"')).expanduser()
    available = {b["id"]: b for b in _find_legacy_books(root)}
    target_root = get_data_root()
    imported = []
    for book_id in request.ids:
        source = root / book_id
        if book_id not in available or not source.is_dir():
            raise HTTPException(status_code=400, detail=f"源目录里没有这一本:{book_id}")
        destination = target_root / book_id
        suffix = 2
        while destination.exists():
            destination = target_root / f"{book_id}-{suffix}"
            suffix += 1
        shutil.copytree(source, destination)
        imported.append({"id": destination.name, "title": available[book_id]["title"]})
    return {"ok": True, "imported": imported}
