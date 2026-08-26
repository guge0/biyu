from __future__ import annotations

import json
from subprocess import CompletedProcess
from pathlib import Path


def _book(root: Path, book_id: str) -> Path:
    book = root / book_id
    (book / "chapters").mkdir(parents=True)
    (book / "book.json").write_text(
        json.dumps({"id": book_id, "title": f"书-{book_id}"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return book


def test_backup_settings_persist_outside_data_and_destination(tmp_path: Path, monkeypatch) -> None:
    from biyu.backup_service import BackupSettings, load_backup_settings, save_backup_settings

    config = tmp_path / "user-config"
    data = tmp_path / "data"
    destination = tmp_path / "snapshots"
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(config))
    save_backup_settings(BackupSettings(True, str(destination), str(data), "test"))
    loaded = load_backup_settings()
    assert loaded.enabled is True
    assert loaded.destination == str(destination)
    assert loaded.source_path == str(data)
    assert (config / "backup.json").exists()
    assert not (data / "backup.json").exists()
    assert not (destination / "backup.json").exists()


def test_backup_manifest_reports_completed_snapshot_truth(tmp_path: Path) -> None:
    from biyu.backup_service import run_backup

    source = tmp_path / "data"
    _book(source, "one")
    _book(source, "two")
    (source / "noise").mkdir()
    destination = tmp_path / "backup"
    result = run_backup(source, destination, scope="test", reason="manual")
    manifest = json.loads((Path(result.root_path) / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_path"] == str(source.resolve())
    manifest = json.loads((Path(result.root_path) / "_manifest.json").read_text(encoding="utf-8"))
    assert result.book_count == 2
    assert manifest["book_count"] == 2
    assert set(manifest["books"]) == {"one", "two"}
    assert Path(result.root_path).is_dir()
    assert not list((destination / "test").glob(".partial-*"))


def test_failed_backup_keeps_last_success_facts(tmp_path: Path) -> None:
    from biyu.backup_service import get_backup_status, run_backup

    source = tmp_path / "data"
    _book(source, "one")
    destination = tmp_path / "backup"
    status_dir = tmp_path / "status"
    success = run_backup(source, destination, scope="test", reason="manual", status_dir=status_dir)
    source.rename(tmp_path / "missing-now")
    try:
        run_backup(source, destination, scope="test", reason="manual", status_dir=status_dir)
    except RuntimeError:
        pass
    status = get_backup_status(destination, scope="test", status_dir=status_dir)
    assert status.state == "failed"
    assert status.last_backup_path == success.root_path
    assert status.book_count == 1
    assert status.last_error


def test_old_status_json_remains_readable(tmp_path: Path) -> None:
    from biyu.backup_service import get_backup_status

    destination = tmp_path / "backup"
    status_path = destination / "production" / ".biyu_backup_status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({
        "scope": "production", "configured": True, "writable": True,
        "last_backup_at": "2026-08-21T15:04:00+00:00", "last_backup_path": "D:/old",
        "state": "ok", "message": "旧状态", "unknown_old_field": 1,
    }), encoding="utf-8")
    status = get_backup_status(destination, scope="production")
    assert status.state == "ok"
    assert status.last_backup_path == "D:/old"
    assert status.book_count == 0


def test_status_contract_has_disabled_never_and_next_run(tmp_path: Path, monkeypatch) -> None:
    from biyu.backup_service import BackupSettings, save_backup_settings
    from biyu.ui import backup

    config = tmp_path / "config"
    data = tmp_path / "data"
    destination = tmp_path / "backup"
    data.mkdir()
    destination.mkdir()
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(config))
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "test")
    monkeypatch.setenv("BIYU_DATA_ROOT", str(data))
    save_backup_settings(BackupSettings(False, str(destination), str(data), "disabled"))
    disabled = backup.backup_status()
    assert disabled["state"] == "disabled"
    assert disabled["enabled"] is False
    assert disabled["next_backup_at"] is None
    updated = backup.backup_settings(backup.BackupSettingsBody(enabled=True, destination=str(destination)))
    assert updated["state"] == "never"
    assert updated["enabled"] is True
    assert updated["next_backup_at"]
    assert updated["retention"] == {"daily": 7, "weekly": 4}

    other = tmp_path / "other"
    other.mkdir()
    changed = backup.backup_settings(backup.BackupSettingsBody(enabled=True, destination=str(other)))
    assert changed["state"] == "never"
    assert changed["last_backup_at"] is None


def test_trash_api_omits_legacy_expiry_without_rewriting_metadata(tmp_path: Path, monkeypatch) -> None:
    from biyu.deletion_service import move_book_to_trash
    from biyu.ui import backup

    data = tmp_path / "data"
    trash = tmp_path / "trash"
    _book(data, "one")
    entry = move_book_to_trash(data, trash, "one", actor="author")
    meta = trash / ".trash" / "books" / f"{entry.trash_id}.json"
    before = meta.read_bytes()
    monkeypatch.setattr(backup, "_trash_root", lambda: trash)
    payload = backup.trash_books()
    assert len(payload) == 1
    assert "expires_at" not in payload[0]
    assert meta.read_bytes() == before


def test_schedule_uses_runtime_project_root_when_package_is_installed(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import backup

    project = tmp_path / "project"
    script = project / "scripts" / "install_biyu_backup_task.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# fixture", encoding="ascii")
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        assert kwargs == {"capture_output": True}
        return CompletedProcess(command, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(project))
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "production")
    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    assert backup._sync_daily_schedule(True) == ("enabled", None)
    assert str(script) in captured
    assert str(project) in captured


def test_schedule_error_decodes_local_windows_output(tmp_path: Path, monkeypatch) -> None:
    from biyu.ui import backup

    project = tmp_path / "project"
    script = project / "scripts" / "install_biyu_backup_task.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# fixture", encoding="ascii")
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(project))
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "production")
    monkeypatch.setattr(backup.locale, "getpreferredencoding", lambda _do_setlocale=False: "gbk")
    monkeypatch.setattr(
        backup.subprocess,
        "run",
        lambda *_args, **_kwargs: CompletedProcess([], 1, stdout=b"", stderr="计划任务失败".encode("gbk")),
    )
    state, error = backup._sync_daily_schedule(True)
    assert state == "failed"
    assert error and "计划任务失败" in error
