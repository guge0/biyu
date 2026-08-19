"""R1 slug ID — /api/chat/sessions API 端点 book_id 集成(P8-M3R T1.2).

Spec(specs/P8-M3R.md line 28):
   /api/chat/sessions body 的 book 字段语义改 book_id;前端全用 id。

契约扩展:
- POST body.book 可以是 id 或目录名,服务端解析后存 meta.book=dir_name, meta.book_id=id
- GET ?book= 同样接受 id 或目录名,内部按 book_id 过滤
- 响应含 book_id 字段(供前端用)

零烧钱,TestClient 纯逻辑。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """tmp 数据根 + 2 本书:
    - BookA: id="dao-1"
    - BookB: 无 id(测回退)
    """
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)

    a = tmp_path / "BookA"
    a.mkdir()
    (a / "book.json").write_text(json.dumps({
        "id": "dao-1", "title": "Book A", "genre": "xuanhuan",
    }, ensure_ascii=False), encoding="utf-8")

    b = tmp_path / "BookB"
    b.mkdir()
    (b / "book.json").write_text(json.dumps({
        "title": "Book B",
    }, ensure_ascii=False), encoding="utf-8")

    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/chat/sessions
# ---------------------------------------------------------------------------


def test_create_session_by_book_id(tmp_data_root, client):
    """POST 用 book_id(slug)创建会话 → 响应含 book_id 字段,book 字段为目录名。"""
    resp = client.post("/api/chat/sessions", json={"book": "dao-1", "role": "editor"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["book_id"] == "dao-1", f"book_id 应=dao-1,实际:{data}"
    assert data["book"] == "BookA", f"book 应=目录名 BookA,实际:{data}"


def test_create_session_by_dir_name_still_works(tmp_data_root, client):
    """POST 用目录名仍可工作(兼容回退);响应 book_id 回退目录名。"""
    resp = client.post("/api/chat/sessions", json={"book": "BookA", "role": "editor"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["book"] == "BookA"
    assert data["book_id"] == "dao-1"  # 解析目录名后仍能拿到 id


def test_create_session_no_id_book_falls_back(tmp_data_root, client):
    """无 id 的书(BookB),book_id 字段回退目录名。"""
    resp = client.post("/api/chat/sessions", json={"book": "BookB", "role": "editor"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["book"] == "BookB"
    assert data["book_id"] == "BookB"  # 回退


# ---------------------------------------------------------------------------
# GET /api/chat/sessions?book=
# ---------------------------------------------------------------------------


def test_list_sessions_by_book_id(tmp_data_root, client):
    """GET ?book=<book_id> 能过滤出新创建的会话。"""
    client.post("/api/chat/sessions", json={"book": "dao-1", "role": "editor"})
    client.post("/api/chat/sessions", json={"book": "BookB", "role": "editor"})

    resp = client.get("/api/chat/sessions?book=dao-1")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["book_id"] == "dao-1"


def test_list_sessions_by_dir_name_still_works(tmp_data_root, client):
    """GET ?book=<dir_name> 仍可工作(兼容回退)。"""
    client.post("/api/chat/sessions", json={"book": "dao-1", "role": "editor"})

    resp = client.get("/api/chat/sessions?book=BookA")
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
