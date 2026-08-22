from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
ZERO_BOOK_MESSAGE = "这次备份没有备到任何书，请检查数据位置。"


def _book(root: Path, book_id: str = "book-one") -> Path:
    book = root / book_id
    book.mkdir(parents=True)
    (book / "book.json").write_text(
        json.dumps({"id": book_id, "title": "测试书"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return book


def test_b1_configured_backup_uses_active_process_root_not_stored_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from biyu.backup_service import BackupSettings
    from biyu.ui import backup

    active_root = tmp_path / "active-books"
    stale_root = tmp_path / "stale-books"
    destination = tmp_path / "backup"
    active_root.mkdir()
    stale_root.mkdir()
    captured: dict[str, Path] = {}
    monkeypatch.setattr(
        backup,
        "load_backup_settings",
        lambda: BackupSettings(True, str(destination), str(stale_root), "test"),
    )
    monkeypatch.setattr(backup, "get_data_root", lambda: active_root)
    monkeypatch.setattr(backup, "user_config_dir", lambda: tmp_path / "status")

    def fake_run(source: Path, target: Path, **_kwargs: object) -> None:
        captured["source"] = Path(source)
        captured["destination"] = Path(target)

    monkeypatch.setattr(backup, "run_backup", fake_run)
    backup._run_configured_backup("manual")

    assert captured["source"].resolve() == active_root.resolve()
    assert captured["destination"].resolve() == destination.resolve()
    assert captured["source"].resolve() != stale_root.resolve()

    startup = (ROOT / "src/biyu/ui/app.py").read_text(encoding="utf-8")
    scheduled = (ROOT / "scripts/run_biyu_backup.py").read_text(encoding="utf-8")
    assert "settings.source_path" not in startup
    assert "settings.source_path" not in scheduled


def test_b2_zero_book_backup_needs_attention_and_never_claims_completion(tmp_path: Path) -> None:
    from biyu.backup_service import get_backup_status, run_backup

    source = tmp_path / "empty-data"
    destination = tmp_path / "backup"
    status_dir = tmp_path / "status"
    source.mkdir()

    result = run_backup(source, destination, scope="test", reason="manual", status_dir=status_dir)
    status = get_backup_status(destination, scope="test", status_dir=status_dir)

    assert result.book_count == 0
    assert result.state == "needs_attention"
    assert status.state == "needs_attention"
    assert status.message == ZERO_BOOK_MESSAGE
    assert "备份完成" not in status.message


def test_b3_success_reports_count_destination_and_duration(tmp_path: Path) -> None:
    from biyu.backup_service import get_backup_status, run_backup

    source = tmp_path / "data"
    destination = tmp_path / "backup"
    status_dir = tmp_path / "status"
    _book(source)

    result = run_backup(source, destination, scope="test", reason="manual", status_dir=status_dir)
    status = get_backup_status(destination, scope="test", status_dir=status_dir)

    assert result.state == "ok"
    assert status.book_count == 1
    assert status.last_backup_path == result.root_path
    assert status.duration_seconds is not None
    assert "1 本" in status.message
    assert result.root_path in status.message
    assert "用时" in status.message

    panel = (ROOT / "src/biyu/ui/static/backup-panel.js").read_text(encoding="utf-8")
    assert "status.last_backup_path" in panel


def test_b4_failure_is_visible_and_preserves_last_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import biyu.backup_service as service

    source = tmp_path / "data"
    destination = tmp_path / "backup"
    status_dir = tmp_path / "status"
    _book(source)
    success = service.run_backup(source, destination, scope="test", reason="manual", status_dir=status_dir)
    monkeypatch.setattr(service.shutil, "copytree", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(RuntimeError, match="disk full"):
        service.run_backup(source, destination, scope="test", reason="manual", status_dir=status_dir)
    failed = service.get_backup_status(destination, scope="test", status_dir=status_dir)

    assert failed.state == "failed"
    assert failed.last_backup_at == success.finished_at
    assert failed.last_backup_path == success.root_path
    assert failed.book_count == 1
    assert "disk full" in (failed.last_error or "")
    panel = (ROOT / "src/biyu/ui/static/backup-panel.js").read_text(encoding="utf-8")
    assert 'detail.setAttribute("role", "alert")' in panel


def test_b5_empty_book_moves_directly_without_backup_history(tmp_path: Path) -> None:
    from biyu.deletion_service import move_book_to_trash

    data_root = tmp_path / "data"
    trash_root = tmp_path / "trash"
    book = _book(data_root, "empty-book")
    entry = move_book_to_trash(data_root, trash_root, "empty-book", actor="author")

    assert not book.exists()
    assert Path(entry.source_path).is_dir()
    route = (ROOT / "src/biyu/ui/backup.py").read_text(encoding="utf-8")
    book_trash_body = route.split("def book_trash", 1)[1].split("@router.", 1)[0]
    assert "backup" not in book_trash_body.lower()
    assert "备份并移入中" not in (ROOT / "src/biyu/ui/static/app.js").read_text(encoding="utf-8")


def test_b6_legacy_and_new_trash_entries_expose_no_expiry(tmp_path: Path) -> None:
    from biyu.deletion_service import list_book_trash, move_book_to_trash
    from biyu.ui import backup

    data_root = tmp_path / "data"
    trash_root = tmp_path / "trash"
    _book(data_root)
    entry = move_book_to_trash(data_root, trash_root, "book-one", actor="author")
    meta = trash_root / ".trash" / "books" / f"{entry.trash_id}.json"
    legacy = json.loads(meta.read_text(encoding="utf-8"))
    legacy["expires_at"] = "2026-09-21T00:00:00+00:00"
    meta.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    listed = list_book_trash(trash_root)
    assert len(listed) == 1
    assert not hasattr(listed[0], "expires_at")
    monkeypatch_payload = backup._trash_payload(listed[0])
    assert "expires_at" not in monkeypatch_payload

    page = (ROOT / "src/biyu/ui/static/trash.html").read_text(encoding="utf-8")
    assert "保留 30 天" not in page
    assert "到期" not in page
    assert "移到回收站的书会一直留着，随时能取回来。要彻底删掉，自己在回收站里删。" in page


@pytest.mark.parametrize(
    "reason",
    ["备份目录不存在", "备份目录不可写", "备份磁盘空间不足"],
)
def test_b7_invalid_destination_keeps_previous_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    from biyu.backup_service import BackupSettings, load_backup_settings, save_backup_settings
    from biyu.ui import backup

    config_dir = tmp_path / "config"
    active_root = tmp_path / "data"
    old_destination = tmp_path / "old-backup"
    requested = tmp_path / "requested"
    active_root.mkdir()
    old_destination.mkdir()
    requested.mkdir()
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "test")
    monkeypatch.setattr(backup, "get_data_root", lambda: active_root)
    previous = BackupSettings(True, str(old_destination), str(active_root), "test")
    save_backup_settings(previous)
    monkeypatch.setattr(
        backup,
        "validate_backup_destination",
        lambda _path: (_ for _ in ()).throw(RuntimeError(reason)),
    )

    with pytest.raises(HTTPException) as caught:
        backup.backup_settings(backup.BackupSettingsBody(enabled=True, destination=str(requested)))

    assert reason in str(caught.value.detail)
    assert load_backup_settings() == previous


def test_b7_nonexistent_destination_is_rejected() -> None:
    from biyu.backup_service import validate_backup_destination

    with pytest.raises(RuntimeError, match="不存在"):
        validate_backup_destination(Path("Z:/this-path-must-not-exist/biyu-backup"))
