from pathlib import Path


def _registered_paths(routes) -> set[str]:
    paths: set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            paths.update(_registered_paths(original_router.routes))
    return paths


def test_backup_routes_are_registered() -> None:
    from biyu.ui.app import app

    paths = _registered_paths(app.routes)
    assert "/api/backup/status" in paths
    assert "/api/backup/run" in paths
    assert "/api/trash/books" in paths
    assert "/api/books/{book_id}/trash" in paths
    assert "/api/books/{book_id}/chapters/{chapter_num}/retract-official" in paths
    assert "/api/books/{book_id}/chapters/{chapter_num}/clear" in paths


def test_launchers_leave_startup_backup_disabled_by_default() -> None:
    launcher = Path("scripts/start_biyu_ui.ps1").read_text(encoding="utf-8")
    app = Path("src/biyu/ui/app.py").read_text(encoding="utf-8")
    assert "BIYU_AUTO_BACKUP" not in launcher
    assert "BIYU_AUTO_BACKUP" in app
    assert '!= "1"' in app
    assert "run_backup" in app


def test_daily_backup_task_configuration_is_present() -> None:
    runner = Path("scripts/run_biyu_backup.py").read_text(encoding="utf-8") if Path("scripts/run_biyu_backup.py").exists() else ""
    installer = Path("scripts/install_biyu_backup_task.ps1").read_text(encoding="utf-8") if Path("scripts/install_biyu_backup_task.ps1").exists() else ""
    assert "run_backup" in runner
    assert "D:\\BiyuBackup" in installer
    assert "New-ScheduledTaskTrigger" in installer
    assert "-Daily" in installer


def test_shelf_surfaces_backup_state_and_recycle_bin() -> None:
    html = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/app.js").read_text(encoding="utf-8")
    assert 'id="backup-status"' in html
    assert 'href="/trash.html"' in html
    assert "/api/backup/status?scope=production" in script
    assert "移到回收站" in script
    assert "/api/books/" in script and "/trash" in script
    assert "确定要删除吗" not in script


def test_recycle_bin_failure_is_persistent_and_has_no_irreversible_action() -> None:
    html = Path("src/biyu/ui/static/trash.html").read_text(encoding="utf-8")
    workbench = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    assert 'id="trash-error"' in html
    assert "role=\"alert\"" in html
    assert "alert(" not in html
    assert "彻底删除" not in workbench
    assert "purgeTrash" not in workbench
