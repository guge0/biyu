from __future__ import annotations

from pathlib import Path

from biyu.backup_service import run_backup, restore_book
from biyu.deletion_service import clear_chapter, move_book_to_trash, restore_book_from_trash, retract_official_chapter


def _fixture(root: Path) -> Path:
    book = root / "recycle-test-book"
    (book / "chapters" / "_pending").mkdir(parents=True)
    (book / "outlines").mkdir()
    (book / "logs" / "ch1").mkdir(parents=True)
    (book / "truth_files" / "history").mkdir(parents=True)
    (book / "chapters" / "ch1.md").write_text("正文一", encoding="utf-8")
    (book / "chapters" / "_pending" / "ch1.md").write_text("候选一", encoding="utf-8")
    (book / "outlines" / "ch1.md").write_text("细纲一", encoding="utf-8")
    (book / "logs" / "ch1" / "planning.md").write_text("方案一", encoding="utf-8")
    (book / "truth_files" / "current_state.md").write_text("记忆一", encoding="utf-8")
    (book / "truth_files" / "history" / "ch1.md").write_text("历史一", encoding="utf-8")
    (book / "book.json").write_text('{"id":"recycle-test-book","title":"回收测试书"}', encoding="utf-8")
    return book


def test_backup_and_recycle_joint_flow(tmp_path: Path) -> None:
    data_root = tmp_path / "test-data"
    backup_root = tmp_path / "D-BiyuBackup"
    book = _fixture(data_root)

    # F1: backup is directly readable and contains the正文 file.
    first = run_backup(data_root, backup_root, scope="test", reason="manual")
    assert (Path(first.root_path) / "recycle-test-book" / "chapters" / "ch1.md").read_text(encoding="utf-8") == "正文一"

    # F2/F3: book disappears from the shelf root, then returns intact.
    first_trash = move_book_to_trash(data_root, backup_root, "recycle-test-book", actor="author", backup_ok=True)
    assert not book.exists()
    assert restore_book_from_trash(data_root, backup_root, first_trash.trash_id, actor="author").state == "ok"
    assert (book / "chapters" / "ch1.md").read_text(encoding="utf-8") == "正文一"

    # F4: second delete, then restore from the backup into a staging directory.
    second_trash = move_book_to_trash(data_root, backup_root, "recycle-test-book", actor="author", backup_ok=True)
    assert not book.exists()
    staging = tmp_path / "staging"
    restored = restore_book(first.backup_id, "recycle-test-book", staging, backup_root=backup_root / "test")
    assert restored["state"] == "ok"
    staged = staging / "recycle-test-book"
    for relative in ("chapters/ch1.md", "truth_files/current_state.md", "truth_files/history/ch1.md"):
        assert (staged / relative).read_text(encoding="utf-8") == (Path(first.root_path) / "recycle-test-book" / relative).read_text(encoding="utf-8")
    restore_book_from_trash(data_root, backup_root, second_trash.trash_id, actor="author")

    # F5: retract official chapter, recompute memory, and preserve chapter number.
    retracted = retract_official_chapter(data_root, "recycle-test-book", 1, actor="author", estimated_cost=0.10)
    assert retracted.memory_recompute == "completed"
    assert not (book / "chapters" / "ch1.md").exists()
    assert (book / "chapters" / "_pending" / "ch1.md").exists()
    assert (book / "truth_files" / "current_state.md").exists()

    # F6: clear the chapter into an empty slot; chapter 2 remains chapter 2.
    (book / "chapters" / "ch2.md").write_text("正文二", encoding="utf-8")
    cleared = clear_chapter(data_root, "recycle-test-book", 1, actor="author")
    assert cleared.chapter_numbers_unchanged is True
    assert not (book / "outlines" / "ch1.md").exists()
    assert not (book / "logs" / "ch1" / "planning.md").exists()
    assert (book / "chapters" / "ch2.md").read_text(encoding="utf-8") == "正文二"
