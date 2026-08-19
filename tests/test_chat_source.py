"""T6.1(P8-M3R)— ChatManager source 字段 + API 过滤。

Spec(specs/P8-M3R.md R6 T6.1):
- ChatManager 创建会话支持 source 字段(默认 "production")
- /api/chat/sessions 列表默认隐 source=test(?include_test=true 才显)
- 自动化/联调脚本显式打 source=test
- UI 默认隐

零烧钱,纯逻辑测试 + TestClient。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app
from biyu.ui.chat import ChatManager


# ---------------------------------------------------------------------------
# ChatManager 单元测试
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_mgr(tmp_path: Path) -> ChatManager:
    data_root = tmp_path / "data"
    data_root.mkdir()
    return ChatManager(data_root=data_root)


def test_new_session_defaults_to_production_source(chat_mgr: ChatManager):
    """new_session 不传 source 时,默认 "production"。"""
    sid = chat_mgr.new_session("bookA", "editor")
    meta = chat_mgr.get_session(sid)
    assert meta is not None
    assert meta.get("source") == "production"


def test_new_session_with_test_source_stored_in_meta(chat_mgr: ChatManager):
    """new_session(source="test") 写到 meta.source。"""
    sid = chat_mgr.new_session("bookA", "editor", source="test")
    meta = chat_mgr.get_session(sid)
    assert meta is not None
    assert meta.get("source") == "test"


def test_list_sessions_excludes_test_by_default(chat_mgr: ChatManager):
    """list_sessions 默认 include_test=False,隐 source=test。"""
    chat_mgr.new_session("bookA", "editor", source="production")
    chat_mgr.new_session("bookA", "editor", source="test")
    chat_mgr.new_session("bookA", "editor", source="test")

    sessions = chat_mgr.list_sessions()
    sources = [s.get("source") for s in sessions]
    assert "test" not in sources, "默认不应包含 source=test"
    assert len(sessions) == 1


def test_list_sessions_include_test_true_shows_all(chat_mgr: ChatManager):
    """list_sessions(include_test=True) 显所有(含 test)。"""
    chat_mgr.new_session("bookA", "editor", source="production")
    chat_mgr.new_session("bookA", "editor", source="test")
    chat_mgr.new_session("bookA", "editor", source="test")

    sessions = chat_mgr.list_sessions(include_test=True)
    assert len(sessions) == 3


def test_list_sessions_old_sessions_without_source_treated_as_production(chat_mgr: ChatManager):
    """旧会话 meta 无 source 字段时,默认视为 production(不隐)。

    向后兼容:R6 之前创建的会话无 source 字段,UI 默认应仍能看到。
    """
    # 手动建一个无 source 字段的旧 meta
    import json
    consults = chat_mgr._data_root / "bookA" / "consults"
    consults.mkdir(parents=True)
    old_meta = {"id": "20260101-abcdef12", "book": "bookA", "role": "editor",
                "created_at": 1000000.0, "deleted": False}
    (consults / "20260101-abcdef12.json").write_text(json.dumps(old_meta), encoding="utf-8")

    sessions = chat_mgr.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "20260101-abcdef12"


def test_list_sessions_book_filter_with_include_test(chat_mgr: ChatManager):
    """book 过滤 + include_test 可叠加。"""
    chat_mgr.new_session("bookA", "editor", source="production")
    chat_mgr.new_session("bookA", "editor", source="test")
    chat_mgr.new_session("bookB", "editor", source="test")

    # bookA + 默认隐 test → 1
    assert len(chat_mgr.list_sessions(book="bookA")) == 1
    # bookA + include_test=True → 2
    assert len(chat_mgr.list_sessions(book="bookA", include_test=True)) == 2
    # bookB + 默认隐 test → 0
    assert len(chat_mgr.list_sessions(book="bookB")) == 0
    # bookB + include_test=True → 1
    assert len(chat_mgr.list_sessions(book="bookB", include_test=True)) == 1


# ---------------------------------------------------------------------------
# API 端点测试(TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def client(tmp_data_root: Path) -> TestClient:
    return TestClient(app)


def test_api_create_session_defaults_source_production(client: TestClient):
    """POST /api/chat/sessions 不传 source 时,默认 production。"""
    # 先建一本书(给 book.json)
    import json
    from biyu.config import get_data_root
    book_dir = get_data_root() / "testbook"
    book_dir.mkdir(parents=True)
    (book_dir / "book.json").write_text(json.dumps({"title": "testbook", "kind": "test"}), encoding="utf-8")

    resp = client.post("/api/chat/sessions", json={"book": "testbook", "role": "editor"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("source") == "production"


def test_api_create_session_accepts_source_test(client: TestClient):
    """POST 带 source=test 时,meta.source = test。"""
    import json
    from biyu.config import get_data_root
    book_dir = get_data_root() / "testbook2"
    book_dir.mkdir(parents=True)
    (book_dir / "book.json").write_text(json.dumps({"title": "testbook2", "kind": "test"}), encoding="utf-8")

    resp = client.post("/api/chat/sessions", json={"book": "testbook2", "role": "editor", "source": "test"})
    assert resp.status_code == 200
    assert resp.json().get("source") == "test"


def test_api_list_sessions_excludes_test_by_default(client: TestClient):
    """GET /api/chat/sessions 默认隐 source=test。"""
    import json
    from biyu.config import get_data_root
    book_dir = get_data_root() / "testbook3"
    book_dir.mkdir(parents=True)
    (book_dir / "book.json").write_text(json.dumps({"title": "testbook3", "kind": "test", "id": "tb3"}), encoding="utf-8")

    # 创建 1 production + 2 test
    client.post("/api/chat/sessions", json={"book": "tb3", "role": "editor"})
    client.post("/api/chat/sessions", json={"book": "tb3", "role": "editor", "source": "test"})
    client.post("/api/chat/sessions", json={"book": "tb3", "role": "editor", "source": "test"})

    resp = client.get("/api/chat/sessions")
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0].get("source") == "production"


def test_api_list_sessions_include_test_true(client: TestClient):
    """GET ?include_test=true 显所有。"""
    import json
    from biyu.config import get_data_root
    book_dir = get_data_root() / "testbook4"
    book_dir.mkdir(parents=True)
    (book_dir / "book.json").write_text(json.dumps({"title": "testbook4", "kind": "test", "id": "tb4"}), encoding="utf-8")

    client.post("/api/chat/sessions", json={"book": "tb4", "role": "editor"})
    client.post("/api/chat/sessions", json={"book": "tb4", "role": "editor", "source": "test"})

    resp = client.get("/api/chat/sessions?include_test=true")
    sessions = resp.json()["sessions"]
    # 全局可能有其他 test 会话,只验 source 类型齐
    sources = {s.get("source") for s in sessions}
    assert "production" in sources
    assert "test" in sources
