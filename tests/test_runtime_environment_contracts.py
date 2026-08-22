from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request


def _request(method: str, path: str) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 1),
    })


def _book(root: Path, name: str) -> Path:
    book = root / name
    book.mkdir(parents=True)
    (book / "book.json").write_text(json.dumps({"id": name}), encoding="utf-8")
    return book


def test_runtime_binding_requires_role_and_explicit_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from biyu.config import validate_runtime_binding

    monkeypatch.delenv("BIYU_DATA_ROOT", raising=False)
    with pytest.raises(ValueError, match="角色"):
        validate_runtime_binding(role=None, data_root=tmp_path / "prod", project_root=tmp_path)
    with pytest.raises(ValueError, match="数据根"):
        validate_runtime_binding(role="production", data_root=None, project_root=tmp_path)


@pytest.mark.parametrize(
    ("role", "root_kind"),
    [("production", "project"), ("test", "production")],
)
def test_runtime_binding_rejects_role_root_mismatch(tmp_path: Path, role: str, root_kind: str):
    from biyu.config import validate_runtime_binding

    project_data = tmp_path / "data"
    project_data.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    root = project_data if root_kind == "project" else external
    with pytest.raises(ValueError, match="不匹配"):
        validate_runtime_binding(role=role, data_root=root, project_root=tmp_path)


def test_runtime_binding_accepts_explicit_matching_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from biyu.config import validate_runtime_binding

    project_data = tmp_path / "data"
    project_data.mkdir()
    production = tmp_path / "production-data"
    production.mkdir()
    monkeypatch.setenv("BIYU_PRODUCTION_DATA_ROOT", str(production))
    assert validate_runtime_binding(role="test", data_root=project_data, project_root=tmp_path) == project_data.resolve()
    assert validate_runtime_binding(role="production", data_root=production, project_root=tmp_path) == production.resolve()


def test_author_launcher_requires_persistent_data_root_configuration():
    script = Path("scripts/start_biyu_ui.ps1").read_text(encoding="utf-8")
    assert "$env:BIYU_DATA_ROOT" in script
    assert "biyu.runtime_config resolve --role production" in script
    assert "Join-Path $HOME 'BiyuData'" not in script
    assert "configuration is missing or invalid" in script


def test_secondary_book_trash_is_blocked_by_server_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import biyu.config as config
    from biyu.ui import app as ui_app
    import biyu.ui.workbench as workbench

    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    _book(secondary, "secondary-book")
    monkeypatch.setattr(config, "get_data_root", lambda: primary)
    monkeypatch.setattr(config, "get_data_root_2", lambda: secondary)
    monkeypatch.setattr(workbench, "get_data_root", lambda: primary)
    monkeypatch.setattr(workbench, "get_data_root_2", lambda: secondary)
    blocked = ui_app._write_protection(_request("POST", "/api/books/secondary-book/trash"))
    assert blocked is not None
    assert blocked.status_code == 403
    assert "当前运行数据根" in blocked.body.decode("utf-8")


def test_workbench_books_do_not_expose_root_label():
    source = Path("src/biyu/ui/workbench.py").read_text(encoding="utf-8")
    assert '"root": root_label' not in source
    assert "root_label = \"生产根\"" not in source


def test_backup_status_and_snapshots_are_scoped(tmp_path: Path):
    from biyu.backup_service import get_backup_status, run_backup

    source = tmp_path / "source"
    source.mkdir()
    _book(source, "book")
    backup = tmp_path / "backup"
    result = run_backup(source, backup, scope="test", reason="test")
    assert (backup / "test" / ".biyu_backup_status.json").exists()
    assert not (backup / ".biyu_backup_status.json").exists()
    assert get_backup_status(backup, scope="test").last_backup_path == result.root_path


def test_backup_contains_only_books_and_root_cost_log(tmp_path: Path):
    from biyu.backup_service import run_backup

    source = tmp_path / "source"
    source.mkdir()
    _book(source, "book")
    (source / "cost_log.csv").write_text("ts,task\n", encoding="utf-8")
    (source / "report.md").write_text("noise", encoding="utf-8")
    (source / "non-book").mkdir()
    result = run_backup(source, tmp_path / "backup", scope="production", reason="test")
    snapshot = Path(result.root_path)
    assert (snapshot / "book" / "book.json").exists()
    assert (snapshot / "cost_log.csv").exists()
    assert not (snapshot / "report.md").exists()
    assert not (snapshot / "non-book").exists()


def test_backup_failure_is_scoped_and_logged(tmp_path: Path):
    from biyu.backup_service import get_backup_status, run_backup

    backup = tmp_path / "backup"
    with pytest.raises(RuntimeError):
        run_backup(tmp_path / "missing", backup, scope="production", reason="test")
    assert get_backup_status(backup, scope="production").state == "failed"
    assert (backup / "production" / "backup.log").exists()


def test_shelf_contract_removes_root_and_has_single_primary_action():
    source = Path("src/biyu/ui/static/app.js").read_text(encoding="utf-8")
    assert "book.root" not in source
    assert 'textContent = "接着写"' in source
    assert 'textContent = "移到回收站"' not in source
