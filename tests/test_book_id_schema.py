"""R1 slug ID — BookConfig.id + /api/books 返回 id(P8-M3R T1.1b/T1.2).

Spec(specs/P8-M3R.md line 28):
   book.json 加 id 字段(稳定 slug,如 dao-1、quanjue-1);
   /api/books 返回带 id;路由 /api/books/{book_id}/... 兼容回退。

本文件测:
- BookConfig.id 读 book.json id 字段;无则回退目录名(过渡不断)
- /api/books 返回的书对象含 id 字段
- id 缺失时 /api/books 用目录名作 id 回退(避免旧数据立刻红)

零烧钱,纯逻辑测试。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.config import BookConfig
from biyu.ui.app import app


# ---------------------------------------------------------------------------
# BookConfig.id
# ---------------------------------------------------------------------------


def test_book_config_id_reads_from_meta(tmp_path: Path):
    """BookConfig.id 读 book.json 的 id 字段。"""
    book_dir = tmp_path / "BookA"
    book_dir.mkdir()
    (book_dir / "book.json").write_text(
        json.dumps({"title": "Book A", "id": "dao-1"}, ensure_ascii=False),
        encoding="utf-8",
    )

    cfg = BookConfig(book_dir)
    assert cfg.id == "dao-1", "BookConfig.id 应读 book.json 的 id 字段"


def test_book_config_id_falls_back_to_dir_name(tmp_path: Path):
    """无 id 字段时,BookConfig.id 回退为目录名(过渡期兼容)。"""
    book_dir = tmp_path / "LegacyBook"
    book_dir.mkdir()
    (book_dir / "book.json").write_text(
        json.dumps({"title": "Legacy"}, ensure_ascii=False),
        encoding="utf-8",
    )

    cfg = BookConfig(book_dir)
    assert cfg.id == "LegacyBook", "无 id 字段时应回退目录名"


# ---------------------------------------------------------------------------
# /api/books 返回 id
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """tmp 数据根 + 两本假书:
    - BookA:有 id 字段
    - BookB:无 id 字段(测回退)
    """
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)

    a = tmp_path / "BookA"
    a.mkdir()
    (a / "book.json").write_text(json.dumps({
        "title": "Book A", "genre": "xuanhuan", "id": "dao-1",
    }, ensure_ascii=False), encoding="utf-8")

    b = tmp_path / "BookB"
    b.mkdir()
    (b / "book.json").write_text(json.dumps({
        "title": "Book B", "genre": "xuanhuan",
    }, ensure_ascii=False), encoding="utf-8")

    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def test_api_books_returns_id_field(tmp_data_root, client):
    """/api/books 返的书对象含 id 字段。"""
    resp = client.get("/api/books")
    assert resp.status_code == 200
    # F3 (P8-M3R-fix):/api/books 返 dict schema {books, count}
    books = {b["name"]: b for b in resp.json()["books"]}
    assert books["BookA"]["id"] == "dao-1", f"BookA id 应=dao-1,实际:{books['BookA']}"


def test_api_books_id_falls_back_to_dir_name(tmp_data_root, client):
    """book.json 无 id 时,/api/books 用目录名作 id 回退。"""
    resp = client.get("/api/books")
    # F3 (P8-M3R-fix):/api/books 返 dict schema {books, count}
    books = {b["name"]: b for b in resp.json()["books"]}
    assert books["BookB"]["id"] == "BookB", f"BookB 无 id 时应用目录名,实际:{books['BookB']}"
