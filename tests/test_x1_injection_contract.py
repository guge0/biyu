"""X-1 contracts written before implementation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, Request

from biyu.context_retriever import LongContextRetriever
from biyu.editor.prompts import build_editor_user_prompt
from biyu.observer import update_truth_files
from biyu.pipeline import _run_checklist_with_cost_log
from biyu.prompts.chapter_writer import build_layer2_context
from biyu.prompts.v3_opening import build_planning_prompt, build_writer_user_prompt


def _request(port: int | None) -> Request:
    server = ("127.0.0.1", port) if port is not None else ("127.0.0.1", None)
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": server,
        "root_path": "",
    })


@pytest.mark.parametrize(
    ("port", "expected_url"),
    [
        (8090, "http://127.0.0.1:8090/api/settings/editor"),
        (8080, "http://127.0.0.1:8080/api/settings/editor"),
    ],
)
def test_zebian_launch_propagates_source_endpoint_and_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, port: int, expected_url: str,
) -> None:
    import biyu.ui.workbench as workbench

    root = tmp_path / "books"
    book = root / "book-id"
    book.mkdir(parents=True)
    launcher = tmp_path / "launcher.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "biyu.exe").write_bytes(b"")
    calls = []
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(workbench, "_bookroom_bat", lambda: launcher)
    monkeypatch.setattr(workbench, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: root)
    monkeypatch.setattr(workbench.shutil, "which", lambda _name: None)
    monkeypatch.setattr(workbench.subprocess, "Popen", lambda argv, **kwargs: calls.append(kwargs))

    workbench.open_zebian("book-id", _request(port))

    env = calls[0]["env"]
    assert env["BIYU_SETTINGS_EDITOR_URL"] == expected_url
    assert Path(env["BIYU_SETTINGS_DATA_ROOT"]).resolve() == root.resolve()


def test_zebian_launch_without_source_port_refuses_and_never_spawns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biyu.ui.workbench as workbench

    book = tmp_path / "books" / "book-id"
    book.mkdir(parents=True)
    monkeypatch.setattr(workbench, "_book_dir", lambda _book: book)
    monkeypatch.setattr(
        workbench.subprocess, "Popen",
        lambda *_args, **_kwargs: pytest.fail("missing port must not spawn Claude Code"),
    )

    with pytest.raises(HTTPException, match="端口"):
        workbench.open_zebian("book-id", _request(None))


@pytest.mark.parametrize("port", [8090, 8080])
def test_settings_bridge_echo_root_is_the_put_target(tmp_path: Path, port: int) -> None:
    from biyu.cli.settings_bridge import write_cell

    root = tmp_path / f"root-{port}"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={
                "data_root": str(root),
                "cells": [{"id": "north_star", "label": "北极星", "length": 3, "version": "v1"}],
            })
        return httpx.Response(200, json={"cell": {"length": 4}})

    result = write_cell(
        book="book-id",
        cell_id="north_star",
        content="新内容",
        base_url=f"http://127.0.0.1:{port}/api/settings/editor",
        expected_data_root=root,
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ok"
    assert Path(result["data_root"]).resolve() == root.resolve()
    assert [request.url.port for request in requests] == [port, port]


def test_settings_bridge_root_mismatch_refuses_before_put(tmp_path: Path) -> None:
    from biyu.cli.settings_bridge import write_cell

    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={
            "data_root": str(tmp_path / "other-root"),
            "cells": [{"id": "north_star", "label": "北极星", "length": 3, "version": "v1"}],
        })

    result = write_cell(
        book="book-id",
        cell_id="north_star",
        content="不能写",
        base_url="http://127.0.0.1:8090/api/settings/editor",
        expected_data_root=tmp_path / "expected-root",
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "failed"
    assert "数据根" in result["message"]
    assert methods == ["GET"]


def test_writer_current_chapter_contract_does_not_gain_outline() -> None:
    current = build_layer2_context(
        worldbook_prompt="",
        characters=[],
        truth_files_block="",
        prev_tail="",
        context_block="",
        outline="SIGNED_CURRENT_PLAN",
        planning="",
        original_outline="MUST_NOT_ADD_CURRENT_OUTLINE",
        injection_v2=False,
    )
    baseline = build_layer2_context(
        worldbook_prompt="",
        characters=[],
        truth_files_block="",
        prev_tail="",
        context_block="",
        outline="SIGNED_CURRENT_PLAN",
        planning="",
        injection_v2=False,
    )
    assert current == baseline
    assert "SIGNED_CURRENT_PLAN" in current
    assert "MUST_NOT_ADD_CURRENT_OUTLINE" not in current


def test_long_context_uses_previous_full_text_and_earlier_outlines(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    outlines = tmp_path / "outlines"
    plans = tmp_path / "logs"
    chapters.mkdir()
    outlines.mkdir()
    plans.mkdir()
    for chapter in (1, 2, 3):
        (chapters / f"ch{chapter}.md").write_text(f"FULL-{chapter}", encoding="utf-8")
        (outlines / f"ch{chapter}.md").write_text(f"OUTLINE-{chapter}", encoding="utf-8")
        plan_dir = plans / f"ch{chapter}"
        plan_dir.mkdir()
        (plan_dir / "planning.md").write_text(f"PLAN-{chapter}", encoding="utf-8")

    history = "\n".join(LongContextRetriever(tmp_path).retrieve(4))

    assert "FULL-3" in history
    assert "OUTLINE-1" in history and "OUTLINE-2" in history
    assert "FULL-1" not in history and "FULL-2" not in history
    assert "PLAN-1" not in history and "PLAN-2" not in history


def test_writer_v4_and_v3_remove_separate_previous_tail() -> None:
    v4 = build_layer2_context(
        worldbook_prompt="", characters=[], truth_files_block="",
        prev_tail="DUPLICATE-PREV-TAIL", context_block="FULL-PREVIOUS",
        outline="SIGNED-PLAN", planning="", injection_v2=False,
    )
    v3 = build_writer_user_prompt(
        planning="", outline="SIGNED-PLAN", context_block="FULL-PREVIOUS",
        prev_tail="DUPLICATE-PREV-TAIL", characters=[],
    )
    assert "FULL-PREVIOUS" in v4 and "FULL-PREVIOUS" in v3
    assert "DUPLICATE-PREV-TAIL" not in v4
    assert "DUPLICATE-PREV-TAIL" not in v3


def test_writer_two_tier_cards_include_previous_presence_and_protagonists() -> None:
    prompt = build_layer2_context(
        worldbook_prompt="",
        characters=[
            {"name": "本章人物", "tier": "supporting", "background": "CURRENT-FULL"},
            {"name": "上章人物", "tier": "supporting", "background": "PREVIOUS-FULL"},
            {"name": "主角", "tier": "protagonist", "background": "PROTAGONIST-FULL"},
            {"name": "其他人物", "tier": "minor", "role": "一句定位", "background": "OTHER-FULL-MUST-HIDE"},
        ],
        truth_files_block="", prev_tail="", context_block="", outline="方案", planning="",
        present_characters=["本章人物"],
        previous_present_characters=["上章人物"],
        injection_v2=False,
    )
    assert "CURRENT-FULL" in prompt
    assert "PREVIOUS-FULL" in prompt
    assert "PROTAGONIST-FULL" in prompt
    assert "其他人物 · minor · 一句定位" in prompt
    assert "OTHER-FULL-MUST-HIDE" not in prompt


def test_architect_default_gets_only_previous_tail() -> None:
    full = "PREFIX-MUST-HIDE" + ("甲" * 600) + "TAIL-MUST-SHOW"
    prompt = build_planning_prompt(
        outline="本章细纲", characters=[], truth_files_block="", worldbook_prompt="",
        chapter_num=2, prev_tail=full[-500:], injection_v2=False,
    )
    assert full[-500:] in prompt
    assert "PREFIX-MUST-HIDE" not in prompt


def test_web_architect_passes_previous_tail_and_outline_presence_to_prompt() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "workbench.py").read_text(encoding="utf-8")
    assert "prev_tail = _load_prev_chapter_tail(book_dir, chapter)" in source
    assert "present_characters=present_characters" in source
    assert "previous_present_characters=previous_present_characters" in source


def test_editor_default_preinjects_creative_anchor() -> None:
    prompt = build_editor_user_prompt(
        chapter_num=1,
        chapter_text="正文",
        creative_anchor="段落约100字；感叹号密度极低",
        injection_v2=False,
    )
    assert "段落约100字；感叹号密度极低" in prompt


@pytest.mark.asyncio
async def test_checklist_cost_is_logged_when_postprocessing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Book:
        cost_log_path = tmp_path / "cost_log.csv"
        logs_dir = tmp_path / "logs"

    response = SimpleNamespace(cost=0.0123, text="not-json")

    class Adapter:
        async def generate(self, _messages):
            return response

    async def fake_run_and_save_checklist(**kwargs):
        await kwargs["adapter"].generate([])
        return None, ["解析失败"]

    monkeypatch.setattr("biyu.checklist.run_and_save_checklist", fake_run_and_save_checklist)
    rows = []
    monkeypatch.setattr("biyu.pipeline._log_cost", lambda *args, **kwargs: rows.append((args, kwargs)))
    result, warnings = await _run_checklist_with_cost_log(
        book=Book(), book_dir=tmp_path, chapter_num=1,
        planning_text="方案", chapter_text="正文", adapter=Adapter(),
    )
    assert result is None and warnings == ["解析失败"]
    assert len(rows) == 1
    assert rows[0][0][3] == pytest.approx(0.0123)
    assert rows[0][1]["status"] in {"error", "empty"}


@pytest.mark.asyncio
async def test_observer_cost_is_logged_before_empty_output_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("biyu.setup_asset_versions.validate_characters_yaml_before_model", lambda _book: None)
    monkeypatch.setattr("biyu.observer.init_truth_files", lambda _book: None)
    monkeypatch.setattr("biyu.observer.read_all_truth_files", lambda _book: {})

    class Adapter:
        async def generate(self, _messages):
            return SimpleNamespace(text="", cost=0.0456)

    rows = []
    ok = await update_truth_files(
        tmp_path, 2, "正文", Adapter(),
        _log_cost_fn=lambda cost, latency, status="ok": rows.append((cost, latency, status)),
    )
    assert ok is False
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(0.0456)
    assert rows[0][2] == "empty"


def test_planning_confirmation_contains_readonly_outline_contract() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "biyu" / "ui" / "static"
    html = (root / "workbench.html").read_text(encoding="utf-8")
    script = (root / "workbench.js").read_text(encoding="utf-8")
    assert 'id="planning-compare"' in html
    assert 'id="planning-outline-read"' in html
    assert 'id="planning-read"' in html
    assert html.count('class="planning-compare-pane"') == 2
    assert 'class="readonly-label">只读</span>' in html
    assert "planning-outline-read" in script and "current.outline" in script
    assert 'textarea id="planning-outline-read"' not in html
