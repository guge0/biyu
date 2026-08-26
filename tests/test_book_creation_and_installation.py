"""Backend/install contracts; all filesystem work stays under tmp_path."""
from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout.strip()


def test_data_root_requires_an_explicit_environment_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import biyu.config as config

    selected = tmp_path / "elsewhere"
    monkeypatch.setenv("BIYU_DATA_ROOT", str(selected))
    assert config.get_data_root() == selected.resolve()

    monkeypatch.delenv("BIYU_DATA_ROOT")
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(RuntimeError, match="找不到数据根，不启动"):
        config.get_data_root()


def test_create_book_builds_complete_local_repository(tmp_path: Path) -> None:
    from biyu.book_service import create_book

    created = create_book("我的新书", "xuanhuan", data_root=tmp_path / "BiyuData")
    book = created.book_dir

    assert created.book_id == "new-book"
    assert json.loads((book / "book.json").read_text(encoding="utf-8"))["genre"] == "xuanhuan"
    for relative in (
        "outlines", "chapters", "chapters/_pending", "logs", "truth_files",
        "audit_reports", "characters.yaml", "book.db",
    ):
        assert (book / relative).exists(), relative
    assert Path(_git("rev-parse", "--show-toplevel", cwd=book)).resolve() == (tmp_path / "BiyuData").resolve()
    assert _git("remote", cwd=book) == ""
    assert _git("config", "--local", "user.name", cwd=book) == "Biyu Local"


def test_create_book_rejects_blank_fields_and_deduplicates_slug(tmp_path: Path) -> None:
    from biyu.book_service import create_book

    with pytest.raises(ValueError, match="书名"):
        create_book("  ", "xuanhuan", data_root=tmp_path)
    with pytest.raises(ValueError, match="题材"):
        create_book("Book", "  ", data_root=tmp_path)
    assert create_book("中文", "dushi", data_root=tmp_path).book_id == "new-book"
    assert create_book("中文", "dushi", data_root=tmp_path).book_id == "new-book-2"


def test_external_data_repo_adoption_and_history(tmp_path: Path) -> None:
    from biyu.book_service import create_book
    from biyu.git_helper import commit_adoption, get_chapter_history

    book = create_book("Outside", "kehuan", data_root=tmp_path / "BiyuData").book_dir
    pending = book / "chapters/_pending/ch1.md"
    pending.write_text("候选正文", encoding="utf-8")
    official = book / "chapters/ch1.md"
    pending.replace(official)

    commit_hash = commit_adoption(book, 1)

    assert commit_hash != ""
    assert get_chapter_history(book, 1)[0]["message"].endswith("作者采用为正式正文")
    assert not (tmp_path / ".git").exists()


def test_external_repo_undo_and_workbench_save_use_book_repository(tmp_path: Path) -> None:
    from biyu.book_service import create_book
    from biyu.cli.workbench_cmd import _commit_undo_adoption
    from biyu.ui.workbench import _commit_official_edit, _git_chapter_history

    book = create_book("Versioned", "xuanhuan", data_root=tmp_path / "BiyuData").book_dir
    official = book / "chapters/ch1.md"
    official.write_text("正式第一版", encoding="utf-8")
    _git("add", "--", "versioned/chapters/ch1.md", cwd=book.parent)
    _git("commit", "-m", "manual: CH1 初版", cwd=book.parent)

    official.write_text("作者保存版", encoding="utf-8")
    _commit_official_edit(official, 1)
    assert _git_chapter_history(book, 1)[0]["message"].endswith("作者在工作台直接修改正式正文")
    assert _git("show", "HEAD:versioned/chapters/ch1.md", cwd=book.parent) == "作者保存版"

    pending = book / "chapters/_pending/ch1.md"
    official.replace(pending)
    commit_hash = _commit_undo_adoption(book, 1)
    assert commit_hash
    assert _git("show", "HEAD:versioned/chapters/_pending/ch1.md", cwd=book.parent) == "作者保存版"


def test_missing_models_yaml_uses_safe_current_example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import biyu.config as config
    import biyu.ui.setup as setup

    missing = tmp_path / "config/models.yaml"
    example = Path(__file__).resolve().parents[1] / "config/models.yaml.example"
    monkeypatch.setattr(config, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(config, "get_models_example_path", lambda: example)
    monkeypatch.setattr(setup, "get_config_path", config.get_config_path)

    assert config.get_config_path() == example
    catalog = setup._catalog()
    assert catalog
    assert all(item["provider"] for item in catalog)
    assert not missing.exists()


def test_runtime_diagnostics_follow_external_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import biyu.config as config
    import biyu.editor.editor as editor
    import biyu.editor.multi_agent as multi_agent

    data_root = tmp_path / "BiyuData"
    monkeypatch.setattr(config, "get_data_root", lambda: data_root)
    multi_agent._dump_phase_trace("phase1", {}, 1, book_dir=data_root / "book")
    assert list((data_root / "book/phase_trace").glob("phase1_trace_*.json"))

    old_handler = editor._EDITOR_FILE_HANDLER
    editor._EDITOR_FILE_HANDLER = None
    try:
        path = editor._enable_editor_file_logging()
        assert path == data_root / ".editor_logs/editor.log"
        editor._EDITOR_FILE_HANDLER.close()
    finally:
        editor._EDITOR_FILE_HANDLER = old_handler


def test_books_api_create_uses_shared_complete_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import biyu.config as config
    import biyu.web.routes as routes
    from biyu.ui.app import app

    monkeypatch.setattr(config, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(routes, "get_data_root", lambda: tmp_path)
    response = TestClient(app).post("/api/books", json={"title": "API Book", "genre": "qihuan"})

    assert response.status_code == 200, response.text
    book = tmp_path / response.json()["id"]
    assert (book / "characters.yaml").exists()
    assert (book / "truth_files/current_state.md").exists()
    assert (book / "book.db").exists()


def test_production_package_and_launcher_contracts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    launcher = (root / "start_biyu_ui.bat").read_text(encoding="utf-8")
    installer = (root / "安装笔驭.bat").read_text(encoding="utf-8")
    install_script = (root / "scripts" / "install_biyu.ps1").read_text(encoding="utf-8")

    assert "ui/static/*" in project
    for page in ("editor.html", "propose.html", "prompts.html", "preferences.html", "reviews.html"):
        assert page in project
    assert "scripts\\start_biyu_ui.ps1" in launcher
    assert "-Port 8080" in launcher
    assert "-Mode" not in launcher
    assert "Test-Path -LiteralPath '.venv\\Scripts\\python.exe'" in (
        root / "scripts" / "start_biyu_ui.ps1"
    ).read_text(encoding="utf-8")
    assert "pull --ff-only" in install_script
    assert "install_biyu.ps1" in (root / "scripts" / "start_biyu_ui.ps1").read_text(encoding="utf-8")
    assert "scripts\\install_biyu.ps1" in installer

    subprocess.run(
        [str(root / ".venv/Scripts/python.exe"), "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(tmp_path)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    wheel = next(tmp_path.glob("biyu-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    prefix = "biyu/ui/static/"
    for removed in ("editor.html", "editor.js", "propose.html", "propose.js", "prompts.html", "prompts.js", "preferences.html", "reviews.html"):
        assert prefix + removed not in names
    for retained in (
        "index.html", "app.js", "book.html", "workbench.html", "workbench.js",
        "overview.html", "overview.js", "settings.html", "settings.css", "settings.js",
        "styles.css", "mini-md.js", "genre.js",
    ):
        assert prefix + retained in names

    installed = tmp_path / "installed"
    subprocess.run(
        [str(root / ".venv/Scripts/python.exe"), "-m", "pip", "install", str(wheel), "--no-deps", "--target", str(installed)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    assert (installed / "biyu/ui/static/index.html").exists()
    assert not (installed / "biyu/ui/static/editor.html").exists()
    for runtime_asset in (
        "Lib/config/editor.yaml",
        "Lib/prompts/writer/system.md",
        "Lib/prompts/editor/system.md",
        "Lib/prompts/workbench/diagnosis.md",
        "Lib/prompts/assets/章节细纲模板.md",
        "Lib/assets/声纹库/内置/江南文风.json",
    ):
        assert any(name.endswith("/data/" + runtime_asset) for name in names), runtime_asset

    smoke_venv = tmp_path / "smoke-venv"
    subprocess.run(
        [str(root / ".venv/Scripts/python.exe"), "-m", "venv", "--system-site-packages", str(smoke_venv)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    smoke_python = smoke_venv / "Scripts/python.exe"
    subprocess.run(
            [str(smoke_python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--force-reinstall", str(wheel)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    imported = subprocess.run(
        [str(smoke_python), "-c", "from biyu.prompts.chapter_writer import WRITER_SYSTEM_V4; from biyu.editor.prompts import EDITOR_SYSTEM_PROMPT; assert WRITER_SYSTEM_V4 and EDITOR_SYSTEM_PROMPT"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert imported.returncode == 0, imported.stderr
