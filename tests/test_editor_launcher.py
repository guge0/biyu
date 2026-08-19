from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
from fastapi import Request


def _request(port: int = 8090) -> Request:
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/", "raw_path": b"/", "query_string": b"", "headers": [],
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", port), "root_path": "",
    })


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "book-dir"
    book.mkdir()
    (book / "book.json").write_text(
        json.dumps({"id": "book-id", "title": "潮汐之城"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return book


def _install_fake_biyu(tmp_path: Path) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "biyu.exe").write_bytes(b"")


def test_zebian_action_opens_new_claude_session_with_book_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.workbench as workbench

    book = _book(tmp_path)
    launcher = tmp_path / "书房.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    _install_fake_biyu(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "_bookroom_bat", lambda: launcher)
    monkeypatch.setattr(workbench, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: book.parent)
    monkeypatch.setattr(workbench.shutil, "which", lambda name: "C:/Windows/wt.exe" if name == "wt.exe" else None)
    monkeypatch.setattr(
        workbench.subprocess,
        "Popen",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    first = workbench.open_zebian("book-id", _request())
    second = workbench.open_zebian("book-id", _request())

    assert len(calls) == 2
    assert calls[0][0][0] == "C:/Windows/wt.exe"
    assert "powershell.exe" in calls[0][0]
    assert calls[0][0][-2] == "-Command"
    first_session = re.search(r"--session-id' '([^']+)", calls[0][0][-1])
    second_session = re.search(r"--session-id' '([^']+)", calls[1][0][-1])
    assert first_session and second_session
    assert first_session.group(1) != second_session.group(1)
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["env"]["BIYU_TRACK"] == "creative"
    assert "我们在写《潮汐之城》" in calls[0][0][-1]
    assert str(book) in calls[0][0][-1]
    assert calls[0][1]["creationflags"] == 0
    assert first["opening_prompt"] == second["opening_prompt"]
    assert "每次都是新对话" in first["message"]


def test_zebian_action_falls_back_to_classic_console_without_windows_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.workbench as workbench

    book = _book(tmp_path)
    launcher = tmp_path / "书房.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    _install_fake_biyu(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "_bookroom_bat", lambda: launcher)
    monkeypatch.setattr(workbench, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: book.parent)
    monkeypatch.setattr(workbench.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        workbench.subprocess,
        "Popen",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    workbench.open_zebian("book-id", _request())

    assert calls[0][0][:4] == ["cmd.exe", "/d", "/c", str(launcher)]
    assert calls[0][1]["creationflags"] == getattr(workbench.subprocess, "CREATE_NEW_CONSOLE", 0)


def test_zebian_launch_failure_keeps_copyable_opening_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.workbench as workbench

    book = _book(tmp_path)
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "_bookroom_bat", lambda: tmp_path / "missing.bat")
    monkeypatch.setattr(workbench, "get_data_root", lambda: book.parent)

    with pytest.raises(workbench.HTTPException) as caught:
        workbench.open_zebian("book-id", _request())

    assert caught.value.status_code == 500
    assert "opening_prompt" in caught.value.detail
    assert "潮汐之城" in caught.value.detail["opening_prompt"]


def test_zebian_entry_contract_is_present_on_settings_and_book_pages() -> None:
    static = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"
    settings_html = (static / "settings.html").read_text(encoding="utf-8")
    settings_js = (static / "settings.js").read_text(encoding="utf-8")
    book_html = (static / "book.html").read_text(encoding="utf-8")

    assert "打开 Claude Code" in settings_html
    assert '<div class="entry-label">责编</div>' in book_html
    assert "在 Claude Code 里跟责编聊" in book_html
    assert "责编会读你已存进设定集的内容" in settings_html
    assert "它会读你已存进设定集的内容" in book_html
    for text in (settings_html, book_html):
        assert "每次都是新对话" in text
        assert "一键复制开场白" in text
    assert "/api/workbench/books/${encoded}/zebian" in settings_js
    assert 'fetch("/api/workbench/books/"' in book_html
    assert "action==='talk'" not in settings_js


def test_bookroom_launcher_uses_checkout_root_for_editable_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu.cli import talk_cmd

    launcher = tmp_path / "书房.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.delenv("BIYU_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(talk_cmd, "get_project_root", lambda: tmp_path / ".venv" / "Lib")

    assert talk_cmd._bookroom_bat() == launcher


def test_bookroom_launcher_uses_explicit_checkout_when_venv_is_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from biyu.cli import talk_cmd

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    launcher = checkout / "书房.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("BIYU_PROJECT_ROOT", str(checkout))
    monkeypatch.setattr(talk_cmd, "get_project_root", lambda: tmp_path / "external-venv" / "Lib")

    assert talk_cmd._bookroom_bat() == launcher
