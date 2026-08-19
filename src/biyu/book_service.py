"""Single application service for creating a complete local book workspace."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CreatedBook:
    book_id: str
    book_dir: Path


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-") or "new-book"


def create_book(title: str, genre: str, *, data_root: Path | None = None) -> CreatedBook:
    """Create every file needed by CLI, workbench, Observer and local history."""
    title = title.strip()
    genre = genre.strip()
    if not title:
        raise ValueError("请填写书名")
    if not genre:
        raise ValueError("请选择题材")

    if data_root is None:
        from biyu.config import get_data_root

        data_root = get_data_root()
    from biyu.git_helper import ensure_local_repository

    data_root = Path(data_root).expanduser().resolve()
    ensure_local_repository(data_root)
    base = _slug(title)
    book_id = base
    suffix = 2
    while (data_root / book_id).exists():
        book_id = f"{base}-{suffix}"
        suffix += 1
    book_dir = data_root / book_id
    for relative in (
        "outlines", "chapters", "chapters/_pending", "logs", "audit_reports",
    ):
        (book_dir / relative).mkdir(parents=True, exist_ok=True)

    from biyu.truth_files import init_truth_files

    init_truth_files(book_dir)
    meta = {
        "id": book_id,
        "title": title,
        "display_name": title,
        "genre": genre,
        "kind": "real",
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "biyu_version": "phase1-0.1",
        "chapter_target_words": 5000,
        "chapter_min_words": 4250,
        "context_mode": "long_context",
    }
    (book_dir / "book.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (book_dir / "characters.yaml").write_text(
        yaml.safe_dump({"characters": []}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    from biyu.setup_asset_versions import save_setup_asset_version

    save_setup_asset_version(book_dir, "characters", reason="create_book")
    from biyu.db import init_db

    init_db(book_dir)
    return CreatedBook(book_id=book_id, book_dir=book_dir)
