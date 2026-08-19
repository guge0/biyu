from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta

import pytest


def _book(root: Path, book_id: str = "book-1") -> Path:
    book = root / book_id
    (book / "chapters").mkdir(parents=True)
    (book / "outlines").mkdir()
    (book / "logs" / "ch1").mkdir(parents=True)
    (book / "truth_files" / "history").mkdir(parents=True)
    (book / "chapters" / "ch1.md").write_text("正式稿", encoding="utf-8")
    (book / "chapters" / "_pending" / "ch1.md").parent.mkdir()
    (book / "chapters" / "_pending" / "ch1.md").write_text("候选稿", encoding="utf-8")
    (book / "outlines" / "ch1.md").write_text("细纲", encoding="utf-8")
    (book / "logs" / "ch1" / "planning.md").write_text("方案", encoding="utf-8")
    (book / "truth_files" / "current_state.md").write_text("记忆", encoding="utf-8")
    (book / "truth_files" / "history" / "ch1.md").write_text("历史", encoding="utf-8")
    (book / "book.json").write_text('{"id": "book-1", "title": "测试书"}', encoding="utf-8")
    return book


def test_backup_copies_book_tree_and_reports_status(tmp_path: Path) -> None:
    from biyu.backup_service import get_backup_status, run_backup

    source = tmp_path / "data"
    _book(source)
    destination = tmp_path / "D-BiyuBackup"

    result = run_backup(source, destination, scope="test", reason="manual")

    assert result.state == "ok"
    assert result.book_count == 1
    assert (Path(result.root_path) / "book-1" / "chapters" / "ch1.md").read_text(encoding="utf-8") == "正式稿"
    status = get_backup_status(destination, scope="test")
    assert status.state == "ok"
    assert status.last_backup_path == result.root_path


def test_backup_failure_is_visible_and_does_not_report_success(tmp_path: Path) -> None:
    from biyu.backup_service import run_backup

    source = tmp_path / "missing-data"
    with pytest.raises(RuntimeError, match="备份"):
        run_backup(source, tmp_path / "D-BiyuBackup", scope="test", reason="startup")


def test_book_trash_roundtrip_requires_author_and_preserves_content(tmp_path: Path) -> None:
    from biyu.deletion_service import move_book_to_trash, restore_book_from_trash

    data_root = tmp_path / "data"
    book = _book(data_root)
    backup = tmp_path / "backup"
    entry = move_book_to_trash(data_root, backup, "book-1", actor="author", backup_ok=True)
    assert not book.exists()
    assert entry.book_id == "book-1"

    restored = restore_book_from_trash(data_root, backup, entry.trash_id, actor="author")
    assert restored.state == "ok"
    assert (book / "chapters" / "ch1.md").read_text(encoding="utf-8") == "正式稿"


def test_chapter_actions_keep_number_and_separate_retract_from_clear(tmp_path: Path) -> None:
    from biyu.deletion_service import clear_chapter, retract_official_chapter

    data_root = tmp_path / "data"
    book = _book(data_root)
    retracted = retract_official_chapter(data_root, "book-1", 1, actor="author", estimated_cost=0.12)
    assert retracted.chapter_numbers_unchanged is True
    assert retracted.memory_recompute == "completed"
    assert (book / "truth_files" / "current_state.md").exists()
    assert not (book / "chapters" / "ch1.md").exists()
    assert (book / "chapters" / "_pending" / "ch1.md").exists()

    cleared = clear_chapter(data_root, "book-1", 1, actor="author")
    assert cleared.chapter_numbers_unchanged is True
    assert (book / "chapters").exists()
    assert not (book / "chapters" / "_pending" / "ch1.md").exists()
    assert (book / "outlines" / "ch1.md").exists() is False
    assert (book / "logs" / "ch1" / "planning.md").exists() is False


def test_confirmation_copy_contains_consequences_and_cost() -> None:
    from biyu.deletion_service import confirmation_copy

    assert confirmation_copy("delete_book", chapter_count=3, settings_count=5) == "整本书会移到回收站，保留 30 天。里面有 3 章正式稿、5 格设定。"
    assert "需要重算" in confirmation_copy("retract", chapter=5, estimated_cost=0.12)
    assert "约 ¥0.12" in confirmation_copy("retract", chapter=5, estimated_cost=0.12)
    assert "第 6 章还是第 6 章" in confirmation_copy("clear", chapter=5)
    assert "确定要删除吗" not in confirmation_copy("delete_book", chapter_count=1, settings_count=1)


def test_backup_retention_keeps_seven_daily_and_four_weekly_points(tmp_path: Path) -> None:
    from biyu.backup_service import retained_snapshot_names

    start = datetime(2026, 8, 16, 3, 0)
    names = [(start - timedelta(days=day)).strftime("%Y%m%d-%H%M%S") for day in range(40)]
    kept = retained_snapshot_names(names)
    assert len(kept) == 11
    assert names[0] in kept and names[6] in kept
    assert names[-1] not in kept
