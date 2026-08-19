from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


def _book(root: Path) -> Path:
    book = root / "Book"
    book.mkdir()
    (book / "book.json").write_text('{"id":"book-id","title":"测试书"}', encoding="utf-8")
    (book / "北极星.md").write_text("# 北极星\n\n## 故事\n旧内容。\n", encoding="utf-8")
    (book / "大纲.md").write_text("# 大纲\n\n## 第一幕\n旧内容。\n", encoding="utf-8")
    (book / "worldbook.yaml").write_text("facts: []\n", encoding="utf-8")
    (book / "characters.yaml").write_text(
        "characters:\n  - name: 林舟\n    tier: major_supporting\n    role: 旧定位\n", encoding="utf-8",
    )
    return book


@pytest.fixture
def editor_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    import biyu.ui.settings as settings
    import biyu.ui.workbench as workbench
    from biyu.ui.app import app

    book = _book(tmp_path)
    monkeypatch.setattr(workbench, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "feature_enabled", lambda _name: True)
    return TestClient(app), book


def test_editor_route_sets_server_actor_and_reports_data_root(
    editor_client: tuple[TestClient, Path],
) -> None:
    http, book = editor_client
    opened = http.get("/api/settings/editor/books/book-id")
    assert opened.status_code == 200
    assert opened.json()["data_root"] == str(book.parent)
    cell = next(item for item in opened.json()["cells"] if item["id"] == "north_star")

    saved = http.put(
        "/api/settings/editor/books/book-id/cells/north_star",
        json={"version": cell["version"], "content": "# 北极星\n\n## 一句话故事\n责编新稿。\n"},
    )
    assert saved.status_code == 200
    history = saved.json()["cell"]["history"]
    assert history[0]["actor"] == "责编"


def test_ordinary_route_sets_author_actor(editor_client: tuple[TestClient, Path]) -> None:
    http, _book_dir = editor_client
    opened = http.get("/api/settings/books/book-id").json()
    cell = next(item for item in opened["cells"] if item["id"] == "north_star")
    saved = http.put(
        "/api/settings/books/book-id/cells/north_star",
        json={"version": cell["version"], "content": "# 北极星\n\n## 一句话故事\n作者新稿。\n"},
    )
    assert saved.json()["cell"]["history"][0]["actor"] == "作者"


def test_editor_route_rejects_client_actor_and_never_retries_stale_write(
    editor_client: tuple[TestClient, Path],
) -> None:
    http, book = editor_client
    opened = http.get("/api/settings/editor/books/book-id").json()
    cell = next(item for item in opened["cells"] if item["id"] == "north_star")
    payload = {"version": cell["version"], "content": "# 北极星\n\n## 一句话故事\n一。\n"}
    assert http.put("/api/settings/editor/books/book-id/cells/north_star", json=payload).status_code == 200
    current = (book / "北极星.md").read_bytes()
    stale = http.put(
        "/api/settings/editor/books/book-id/cells/north_star",
        json={**payload, "actor": "author"},
    )
    assert stale.status_code == 422
    assert (book / "北极星.md").read_bytes() == current


def test_bridge_gets_before_put_and_exits_truthfully_on_409(tmp_path: Path) -> None:
    from biyu.cli.settings_bridge import write_cell

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data_root": "D:/BiyuData",
                    "cells": [{"id": "north_star", "label": "北极星", "length": 7, "version": "v1"}],
                },
            )
        assert json.loads(request.content)["version"] == "v1"
        return httpx.Response(409, json={"detail": "冲突"})

    result = write_cell(
        book="book-id",
        cell_id="north_star",
        content="# 北极星\n\n## 故事\n新。\n",
        base_url="http://127.0.0.1:8080/api/settings/editor",
        expected_data_root=Path("D:/BiyuData"),
        transport=httpx.MockTransport(handler),
    )
    assert calls == [
        ("GET", "/api/settings/editor/books/book-id"),
        ("PUT", "/api/settings/editor/books/book-id/cells/north_star"),
    ]
    assert result["status"] == "conflict"
    assert result["data_root"] == "D:/BiyuData"
    assert result["previous_length"] == 7
    assert "你刚在网页改过" in result["message"] and "没写进去" in result["message"]


def test_editor_character_route_can_update_and_archive_but_has_no_delete(
    editor_client: tuple[TestClient, Path],
) -> None:
    http, book = editor_client
    opened = http.get("/api/settings/editor/books/book-id").json()
    card = next(item for item in opened["characters"] if item["name"] == "林舟")
    changed = http.put(
        "/api/settings/editor/books/book-id/characters/%E6%9E%97%E8%88%9F",
        json={
            "version": card["version"],
            "content": "## 人物卡\nname: 林舟\ntier: major_supporting\nrole: 新定位\n",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["character"]["history"][0]["actor"] == "责编"
    archived = http.post(
        "/api/settings/editor/books/book-id/characters/%E6%9E%97%E8%88%9F/archive",
        json={"version": changed.json()["character"]["version"]},
    )
    assert archived.status_code == 200, archived.text
    assert "archived: true" in (book / "characters.yaml").read_text(encoding="utf-8")
    assert http.delete("/api/settings/editor/books/book-id/characters/%E6%9E%97%E8%88%9F").status_code == 405


def test_editor_character_route_can_create_missing_card_but_ordinary_route_cannot(
    editor_client: tuple[TestClient, Path],
) -> None:
    http, book = editor_client
    opened = http.get("/api/settings/editor/books/book-id").json()
    payload = {
        "version": opened["character_version"],
        "content": "## 人物卡\nname: 苏遥\ntier: major_supporting\nrole: 新人物\n",
    }
    ordinary = http.put("/api/settings/books/book-id/characters/%E8%8B%8F%E9%81%A5", json=payload)
    assert ordinary.status_code == 404
    created = http.put("/api/settings/editor/books/book-id/characters/%E8%8B%8F%E9%81%A5", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["character"]["history"][0]["actor"] == "责编"
    assert "name: 苏遥" in (book / "characters.yaml").read_text(encoding="utf-8")


def test_bridge_uses_collection_version_to_create_missing_character() -> None:
    from biyu.cli.settings_bridge import write_character

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data_root": "D:/BiyuData",
                    "characters": [],
                    "character_version": "cards-v1",
                },
            )
        assert json.loads(request.content)["version"] == "cards-v1"
        return httpx.Response(200, json={"character": {"name": "苏遥"}})

    result = write_character(
        book="book-id",
        name="苏遥",
        content="## 人物卡\nname: 苏遥\ntier: major_supporting\n",
        base_url="http://127.0.0.1:8080/api/settings/editor",
        expected_data_root=Path("D:/BiyuData"),
        transport=httpx.MockTransport(handler),
    )
    assert [request.method for request in requests] == ["GET", "PUT"]
    assert result["status"] == "ok" and "已创建" in result["message"]
