from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def _write_runtime_config(config_dir: Path, role: str, data_root: Path) -> Path:
    path = config_dir / f"runtime-{role}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"data_root": str(data_root)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("persistent", "environment", "accepted", "expected_source"),
    [
        (True, False, True, "persistent"),
        (False, True, False, None),
        (True, True, True, "environment"),
        (False, False, False, None),
    ],
)
def test_a1_a2_a6_data_root_source_matrix(
    tmp_path: Path,
    persistent: bool,
    environment: bool,
    accepted: bool,
    expected_source: str | None,
) -> None:
    from biyu.runtime_config import RuntimeConfigurationError, resolve_runtime_data_root

    config_dir = tmp_path / "user-config"
    stored_root = tmp_path / "stored-books"
    override_root = tmp_path / "override-books"
    stored_root.mkdir()
    override_root.mkdir()
    if persistent:
        _write_runtime_config(config_dir, "production", stored_root)
    environ = {"BIYU_DATA_ROOT": str(override_root)} if environment else {}

    if not accepted:
        with pytest.raises(RuntimeConfigurationError, match="持久配置"):
            resolve_runtime_data_root("production", config_dir=config_dir, environ=environ)
        return

    resolved = resolve_runtime_data_root("production", config_dir=config_dir, environ=environ)
    assert resolved.path == (override_root if environment else stored_root).resolve()
    assert resolved.persistent_path == stored_root.resolve()
    assert resolved.source == expected_source
    assert resolved.temporary is environment


def test_isolation_check_rejects_temporary_root_that_differs_from_persistent(
    tmp_path: Path,
) -> None:
    from biyu.runtime_config import RuntimeConfigurationError, verify_runtime_data_root

    config_dir = tmp_path / "user-config"
    stored_root = tmp_path / "stored-books"
    override_root = tmp_path / "override-books"
    stored_root.mkdir()
    override_root.mkdir()
    _write_runtime_config(config_dir, "development", stored_root)

    with pytest.raises(RuntimeConfigurationError, match="持久配置.*实际"):
        verify_runtime_data_root(
            "development",
            override_root,
            config_dir=config_dir,
        )

    assert verify_runtime_data_root(
        "development",
        stored_root,
        config_dir=config_dir,
    ) == stored_root.resolve()


def test_a1_author_and_development_read_distinct_persistent_files(tmp_path: Path) -> None:
    from biyu.runtime_config import resolve_runtime_data_root, runtime_config_path

    config_dir = tmp_path / "user-config"
    author_root = tmp_path / "author-books"
    development_root = tmp_path / "development-books"
    author_root.mkdir()
    development_root.mkdir()
    author_config = _write_runtime_config(config_dir, "production", author_root)
    development_config = _write_runtime_config(config_dir, "development", development_root)

    author = resolve_runtime_data_root("production", config_dir=config_dir, environ={})
    development = resolve_runtime_data_root("development", config_dir=config_dir, environ={})

    assert runtime_config_path("production", config_dir) == author_config
    assert runtime_config_path("development", config_dir) == development_config
    assert author.path == author_root.resolve()
    assert development.path == development_root.resolve()
    assert author.config_path != development.config_path


def test_a2_a3_shelf_displays_full_root_and_temporary_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "user-config"
    persistent_root = tmp_path / "persistent-books"
    temporary_root = tmp_path / "temporary-books"
    persistent_root.mkdir()
    temporary_root.mkdir()
    _write_runtime_config(config_dir, "production", persistent_root)
    monkeypatch.setenv("BIYU_USER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("BIYU_RUNTIME_ROLE", "production")
    monkeypatch.setenv("BIYU_DATA_ROOT", str(temporary_root))
    monkeypatch.setenv("BIYU_DATA_ROOT_SOURCE", "environment")
    monkeypatch.setenv("BIYU_PRODUCTION_DATA_ROOT", str(temporary_root))

    from biyu.ui import app as app_module

    payload = TestClient(app_module.app).get("/api/version").json()
    assert payload["data_root"] == str(temporary_root.resolve())
    assert payload["data_root_temporary"] is True

    html = (ROOT / "src/biyu/ui/static/index.html").read_text(encoding="utf-8")
    script = (ROOT / "src/biyu/ui/static/app.js").read_text(encoding="utf-8")
    assert 'id="data-root-location"' in html
    assert "你的书存在：" in script
    assert "（这次是临时指定的位置）" in script


def test_a5_development_runtime_never_accepts_8080() -> None:
    from biyu.runtime_config import RuntimeConfigurationError, validate_runtime_port

    with pytest.raises(RuntimeConfigurationError, match="开发版.*8080"):
        validate_runtime_port("development", 8080)
    assert validate_runtime_port("development", 8090) == 8090
    assert validate_runtime_port("development", 8091) == 8091
    assert validate_runtime_port("production", 8080) == 8080

    launcher = (ROOT / "scripts/start_biyu_dev.ps1").read_text(encoding="utf-8")
    assert "if ($Port -eq 8080)" in launcher
    assert "if ($Port -ne 8090)" not in launcher
    assert "runtime-development.json" in launcher
    assert "BiyuTestData" in launcher
    assert "BIYU_TEST_DATA_ROOT" in launcher
    assert "runtime_guard.py" in launcher
    assert "owner.Path" not in launcher
    assert "BIYU_DATA_ROOT))" not in launcher.split("runtime-development.json", 1)[0]


def test_launchers_verify_persistent_root_and_print_identity() -> None:
    production = (ROOT / "scripts/start_biyu_ui.ps1").read_text(encoding="utf-8")
    development = (ROOT / "scripts/start_biyu_dev.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "scripts/install_biyu.ps1").read_text(encoding="utf-8-sig")

    for launcher in (production, development):
        assert "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8" in launcher
        assert "verify --role" in launcher
        assert "persistent_data_root" in launcher
        assert "temporary override" in launcher
        assert "persistent: $persistentRoot" in launcher
        assert "actual:     $dataRoot" in launcher
        assert "Biyu |" in launcher
    assert "$env:BIYU_DATA_ROOT" not in installer.split("if (-not $OnlyIfNeeded)", 1)[0]


@pytest.mark.parametrize("content", ["{broken", json.dumps({}), json.dumps({"data_root": 42})])
def test_a6_broken_persistent_config_refuses_startup(tmp_path: Path, content: str) -> None:
    from biyu.runtime_config import RuntimeConfigurationError, resolve_runtime_data_root

    config_dir = tmp_path / "user-config"
    config = config_dir / "runtime-production.json"
    config.parent.mkdir(parents=True)
    config.write_text(content, encoding="utf-8")

    with pytest.raises(RuntimeConfigurationError, match="持久配置"):
        resolve_runtime_data_root("production", config_dir=config_dir, environ={})


class _RuntimeHandler(BaseHTTPRequestHandler):
    data_root = ""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/api/version":
            self.send_error(404)
            return
        body = json.dumps({"runtime": "笔驭", "data_root": self.data_root}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_a4_different_root_conflict_keeps_existing_process_alive(tmp_path: Path) -> None:
    existing_root = tmp_path / "existing-books"
    requested_root = tmp_path / "requested-books"
    existing_root.mkdir()
    requested_root.mkdir()
    _RuntimeHandler.data_root = str(existing_root.resolve())
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/runtime_guard.py"),
                "--port",
                str(port),
                "--data-root",
                str(requested_root),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert result.returncode != 0
        expected = (
            f"端口 {port} 上已经有一个笔驭在跑，它用的是 {existing_root.resolve()}，"
            f"你这次要用的是 {requested_root.resolve()}。"
        )
        assert expected in result.stdout
        assert "没有动它。先关掉那一个，再启动这一个。" in result.stdout

        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
        assert thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_unknown_listener_reports_both_roots_and_is_not_stopped(tmp_path: Path) -> None:
    requested_root = tmp_path / "requested-books"
    requested_root.mkdir()

    class UnknownHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b"not biyu"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), UnknownHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/runtime_guard.py"),
                "--port",
                str(port),
                "--data-root",
                str(requested_root),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert result.returncode == 2
        assert "已有进程数据根：无法确定" in result.stdout
        assert f"本次请求数据根：{requested_root.resolve()}" in result.stdout
        assert thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a4_author_launcher_never_kills_an_existing_process() -> None:
    launcher = (ROOT / "scripts/start_biyu_ui.ps1").read_text(encoding="utf-8")

    assert "Stop-Process" not in launcher
    assert "runtime_guard.py" in launcher
    assert "show_runtime_conflict.ps1" in launcher
    assert "BIYU_DATA_ROOT_SOURCE" in launcher

    dialog = (ROOT / "scripts/show_runtime_conflict.ps1").read_text(encoding="ascii")
    assert "$form.TopMost = $true" in dialog
    assert "[void]$layout.RowStyles.Add" in dialog
    assert "$form.Add_Shown" in dialog
    assert "$text.WordWrap = $true" in dialog
    assert "$form.ClientSize" in dialog


def test_a6_normal_startup_refresh_does_not_recreate_missing_config() -> None:
    installer = (ROOT / "scripts" / "install_biyu.ps1").read_text(encoding="utf-8")

    guard = "if (-not $OnlyIfNeeded) {"
    initialize = "Initialize-AuthorRuntimeConfig"
    assert installer.rindex(guard) < installer.rindex(initialize)
