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
    assert "/api/backup/settings" in paths
    assert "/api/backup/choose-directory" in paths
    assert "/api/backup/run" in paths
    assert "/api/trash/books" in paths
    assert "/api/books/{book_id}/trash" in paths
    assert "/api/books/{book_id}/chapters/{chapter_num}/retract-official" in paths
    assert "/api/books/{book_id}/chapters/{chapter_num}/clear" in paths


def test_launchers_leave_startup_backup_disabled_by_default() -> None:
    launcher = Path("scripts/start_biyu_ui.ps1").read_text(encoding="utf-8")
    app = Path("src/biyu/ui/app.py").read_text(encoding="utf-8")
    assert "BIYU_AUTO_BACKUP" not in launcher
    assert "load_backup_settings" in app
    assert "if not settings.enabled" in app
    assert "run_backup" in app


def test_daily_backup_task_configuration_is_present() -> None:
    runner = Path("scripts/run_biyu_backup.py").read_text(encoding="utf-8") if Path("scripts/run_biyu_backup.py").exists() else ""
    installer = Path("scripts/install_biyu_backup_task.ps1").read_text(encoding="utf-8") if Path("scripts/install_biyu_backup_task.ps1").exists() else ""
    assert "run_backup" in runner
    assert "run_biyu_backup.py" in installer
    assert "New-ScheduledTaskTrigger" in installer
    assert "-Daily" in installer
    assert "StartWhenAvailable" in installer


def test_shelf_surfaces_backup_state_and_recycle_bin() -> None:
    html = Path("src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    script = Path("src/biyu/ui/static/app.js").read_text(encoding="utf-8")
    panel = Path("src/biyu/ui/static/backup-panel.js").read_text(encoding="utf-8")
    styles = Path("src/biyu/ui/static/styles.css").read_text(encoding="utf-8")
    assert 'id="backup-status"' in html
    assert 'id="backup-settings-button"' in html
    assert 'id="backup-overlay"' in html
    assert 'href="/trash.html"' in html
    assert "/api/backup/status" in panel
    assert "/api/backup/settings" in panel
    assert "/api/backup/run" in panel
    assert panel.index('const enabled = $("backup-auto").checked') < panel.index('render({ ...current, enabled, destination, state: "running" })')
    assert ".setup-card.backup-panel{width:min(520px,100%)" in styles
    assert "overflow-wrap:anywhere" in styles
    assert "移到回收站" in script
    assert "备份并移入中" not in script
    assert "window.confirm" not in script
    assert "/api/books/" in script and "/trash" in script
    assert "确定要删除吗" not in script


def test_recycle_bin_failure_is_persistent_and_has_no_irreversible_action() -> None:
    html = Path("src/biyu/ui/static/trash.html").read_text(encoding="utf-8")
    workbench = Path("src/biyu/ui/static/workbench.js").read_text(encoding="utf-8")
    assert 'id="trash-error"' in html
    assert "role=\"alert\"" in html
    assert "alert(" not in html
    assert "保留 30 天" not in html
    assert "到期" not in html
    assert "彻底删除" not in workbench
    assert "purgeTrash" not in workbench
