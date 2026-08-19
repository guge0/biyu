"""Y-1 contracts written before implementation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from biyu.context_retriever import LongContextRetriever
from biyu.pipeline import _build_context_block
from biyu.prompts.chapter_writer import build_layer2_context


def _request(host: str = "localhost", port: int = 8090) -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"host", f"{host}:{port}".encode("ascii"))],
        "client": ("127.0.0.1", 50000),
        "server": (host, port),
        "root_path": "",
    })


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "books" / "book-id"
    book.mkdir(parents=True)
    (book / "book.json").write_text(
        json.dumps({"id": "book-id", "title": "潮汐之城"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return book


def test_zebian_launch_prepends_venv_scripts_and_normalizes_localhost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.workbench as workbench

    book = _book(tmp_path)
    launcher = tmp_path / "书房.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "biyu.exe").write_bytes(b"")
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "_bookroom_bat", lambda: launcher)
    monkeypatch.setattr(workbench, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: book.parent)
    monkeypatch.setattr(workbench.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        workbench.subprocess, "Popen", lambda _argv, **kwargs: calls.append(kwargs),
    )

    workbench.open_zebian("book-id", _request())

    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert env["BIYU_SETTINGS_EDITOR_URL"] == (
        "http://127.0.0.1:8090/api/settings/editor"
    )
    assert env["PATH"].split(os.pathsep)[0] == str(scripts)


def test_zebian_launch_refuses_when_venv_biyu_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.workbench as workbench

    book = _book(tmp_path)
    launcher = tmp_path / "书房.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "_bookroom_bat", lambda: launcher)
    monkeypatch.setattr(workbench, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: book.parent)
    monkeypatch.setattr(
        workbench.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("missing biyu.exe must not spawn"),
    )

    with pytest.raises(HTTPException, match="biyu") as caught:
        workbench.open_zebian("book-id", _request())

    assert caught.value.status_code == 500
    assert "opening_prompt" in caught.value.detail


def test_long_context_middle_gap_keeps_real_chapter_numbers(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    outlines = tmp_path / "outlines"
    chapters.mkdir()
    outlines.mkdir()
    for chapter in (1, 2, 4):
        (outlines / f"ch{chapter}.md").write_text(
            f"OUTLINE-{chapter}", encoding="utf-8",
        )
    (chapters / "ch4.md").write_text("FULL-4", encoding="utf-8")

    history = LongContextRetriever(tmp_path).retrieve(5)
    labelled = "\n".join(
        f"=== 第{chapter}章 ===\n{text}"
        for chapter, text in enumerate(history, start=1)
    )

    assert "=== 第3章 ===\n（无细纲）" in labelled
    assert "=== 第4章 ===\nFULL-4" in labelled
    assert "=== 第3章 ===\nFULL-4" not in labelled


def test_context_block_middle_gap_keeps_real_chapter_numbers(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    outlines = tmp_path / "outlines"
    chapters.mkdir()
    outlines.mkdir()
    for chapter in (1, 2, 4):
        (outlines / f"ch{chapter}.md").write_text(
            f"OUTLINE-{chapter}", encoding="utf-8",
        )
    (chapters / "ch4.md").write_text("FULL-4", encoding="utf-8")

    context, _retriever = _build_context_block(tmp_path, 5)

    assert "=== 第1章 ===\nOUTLINE-1" in context
    assert "=== 第2章 ===\nOUTLINE-2" in context
    assert "=== 第3章 ===\n（无细纲）" in context
    assert "=== 第4章 ===\nFULL-4" in context
    assert "=== 第3章 ===\nFULL-4" not in context


def test_writer_quick_projection_is_stable_across_present_characters() -> None:
    characters = [
        {"name": "甲", "tier": "supporting", "role": "甲定位", "background": "甲整卡"},
        {"name": "乙", "tier": "supporting", "role": "乙定位", "background": "乙整卡"},
    ]

    first = build_layer2_context(
        worldbook_prompt="", characters=characters, truth_files_block="",
        prev_tail="", context_block="", outline="", planning="",
        present_characters=["甲"], character_projection="quick",
    )
    second = build_layer2_context(
        worldbook_prompt="", characters=characters, truth_files_block="",
        prev_tail="", context_block="", outline="", planning="",
        present_characters=["乙"], character_projection="quick",
    )

    assert first == second
    assert "甲 · supporting · 甲定位" in first
    assert "乙 · supporting · 乙定位" in first
    assert "甲整卡" not in first and "乙整卡" not in first


def test_writer_selected_projection_contains_only_selected_full_cards() -> None:
    prompt = build_layer2_context(
        worldbook_prompt="",
        characters=[
            {"name": "本章人物", "tier": "supporting", "background": "CURRENT-FULL"},
            {"name": "上章人物", "tier": "supporting", "background": "PREVIOUS-FULL"},
            {"name": "主角", "tier": "protagonist", "background": "PROTAGONIST-FULL"},
            {"name": "其他人物", "tier": "supporting", "background": "OTHER-MUST-HIDE"},
        ],
        truth_files_block="", prev_tail="", context_block="", outline="", planning="",
        present_characters=["本章人物"],
        previous_present_characters=["上章人物"],
        character_projection="selected_full",
    )

    assert "CURRENT-FULL" in prompt
    assert "PREVIOUS-FULL" in prompt
    assert "PROTAGONIST-FULL" in prompt
    assert "OTHER-MUST-HIDE" not in prompt
    assert "其他人物 · supporting" not in prompt
