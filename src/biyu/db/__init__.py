"""SQLite 数据层 — schema 初始化、yaml→SQLite 同步、角色查询、章节落盘。

Phase 1 原则: yaml 是真相, SQLite 是索引。
每次 biyu write 开始前执行 sync_from_yaml(),清空 characters 表全量重写。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Character:
    """角色数据结构。"""
    id: int = 0
    name: str = ""
    role: str = "minor"
    status: str = "alive"
    personality: str = ""
    speaking_style: str = ""
    background: str = ""
    abilities: str = ""
    sample_lines: list[str] = field(default_factory=list)
    current_location: str = ""
    current_power_level: str = ""
    current_emotional_state: str = ""
    first_appearance_chapter: int | None = None
    last_updated_chapter: int | None = None


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'alive',
    personality TEXT,
    speaking_style TEXT,
    background TEXT,
    abilities TEXT,
    sample_lines_json TEXT,
    current_location TEXT,
    current_power_level TEXT,
    current_emotional_state TEXT,
    first_appearance_chapter INTEGER,
    last_updated_chapter INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_characters_status ON characters(status);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_num INTEGER NOT NULL UNIQUE,
    title TEXT,
    word_count INTEGER,
    cost_cny REAL,
    latency_seconds REAL,
    warnings_json TEXT,
    consistency_issues_json TEXT,
    generated_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(book_dir: Path) -> Path:
    """Initialize book.db in the book directory. Returns the db path."""
    db_path = book_dir / "book.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)
    conn.close()
    return db_path


def sync_characters_from_yaml(book_dir: Path) -> tuple[int, int, int]:
    """Sync characters from characters.yaml into SQLite.

    Clears the characters table and does a full rewrite.

    Returns:
        (yaml_count, written_count, cleared_count)
    """
    yaml_path = book_dir / "characters.yaml"
    db_path = book_dir / "book.db"

    if not yaml_path.exists():
        return (0, 0, 0)

    from biyu.setup_asset_versions import load_setup_yaml, sync_setup_asset_version

    sync_setup_asset_version(book_dir, "characters", reason="managed_read")
    data = load_setup_yaml(yaml_path, label="角色设定")

    chars_data = data.get("characters", [])
    yaml_count = len(chars_data)

    conn = sqlite3.connect(str(db_path))
    try:
        # Count existing rows to be cleared
        cleared = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]

        # Full rewrite
        conn.execute("DELETE FROM characters")

        written = 0
        for c in chars_data:
            sample_lines = c.get("sample_lines", [])
            conn.execute(
                """INSERT INTO characters
                   (name, role, status, personality, speaking_style,
                    background, abilities, sample_lines_json,
                    current_location, current_power_level, current_emotional_state)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c.get("name", ""),
                    c.get("role", "minor"),
                    c.get("status", "alive"),
                    c.get("personality", ""),
                    c.get("speaking_style", ""),
                    c.get("background", ""),
                    c.get("abilities", ""),
                    json.dumps(sample_lines, ensure_ascii=False),
                    c.get("current_location", ""),
                    c.get("current_power_level", ""),
                    c.get("current_emotional_state", ""),
                ),
            )
            written += 1

        conn.commit()
        return (yaml_count, written, cleared)
    finally:
        conn.close()


def list_characters(
    book_dir: Path,
    status: str | None = None,
) -> list[Character]:
    """Query characters from SQLite.

    Args:
        book_dir: Book directory containing book.db.
        status: Filter by status (alive/dead/absent). None = all.

    Returns:
        List of Character dataclass instances.
    """
    db_path = book_dir / "book.db"
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM characters WHERE status = ?", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM characters").fetchall()

        result = []
        for r in rows:
            sl_json = r["sample_lines_json"]
            sample_lines = json.loads(sl_json) if sl_json else []
            result.append(Character(
                id=r["id"],
                name=r["name"],
                role=r["role"],
                status=r["status"],
                personality=r["personality"] or "",
                speaking_style=r["speaking_style"] or "",
                background=r["background"] or "",
                abilities=r["abilities"] or "",
                sample_lines=sample_lines,
                current_location=r["current_location"] or "",
                current_power_level=r["current_power_level"] or "",
                current_emotional_state=r["current_emotional_state"] or "",
                first_appearance_chapter=r["first_appearance_chapter"],
                last_updated_chapter=r["last_updated_chapter"],
            ))
        return result
    finally:
        conn.close()


def record_chapter(
    book_dir: Path,
    chapter_num: int,
    title: str | None = None,
    word_count: int | None = None,
    cost_cny: float | None = None,
    latency_seconds: float | None = None,
    warnings: list[str] | None = None,
    consistency_issues: list[dict] | None = None,
) -> None:
    """Insert or update chapter metadata in SQLite."""
    db_path = book_dir / "book.db"
    conn = sqlite3.connect(str(db_path))
    try:
        existing = conn.execute(
            "SELECT id FROM chapters WHERE chapter_num = ?",
            (chapter_num,),
        ).fetchone()

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        warnings_json = json.dumps(warnings or [], ensure_ascii=False)
        issues_json = json.dumps(consistency_issues or [], ensure_ascii=False)

        if existing:
            conn.execute(
                """UPDATE chapters SET
                   title=?, word_count=?, cost_cny=?, latency_seconds=?,
                   warnings_json=?, consistency_issues_json=?, generated_at=?
                   WHERE chapter_num=?""",
                (title, word_count, cost_cny, latency_seconds,
                 warnings_json, issues_json, now, chapter_num),
            )
        else:
            conn.execute(
                """INSERT INTO chapters
                   (chapter_num, title, word_count, cost_cny, latency_seconds,
                    warnings_json, consistency_issues_json, generated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (chapter_num, title, word_count, cost_cny, latency_seconds,
                 warnings_json, issues_json, now),
            )
        conn.commit()
    finally:
        conn.close()
