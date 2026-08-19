"""Q-1/Q-2 书架 GET /api/books 契约：只返现役 last_chapter。

Spec(specs/P8-M2.5.md line 10):
  顶部快捷「继续:<最近的书> · 上次审到第 N 章」

standalone Web 审读已摘除；书架不再扫描或暴露 last_reviewed。

每本书对象保留 last_chapter (int|None)：已签最高章节号。

零烧钱,纯逻辑测试。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """tmp 数据根 + 两本假书:
    - BookA:ch1-3 已签,ch1/ch3 已审读
    - BookB:仅 book.json,无章节(空态)
    """
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)

    # BookA
    a = tmp_path / "BookA"
    a.mkdir()
    (a / "book.json").write_text(json.dumps({
        "title": "Book A", "genre": "xuanhuan",
    }, ensure_ascii=False), encoding="utf-8")
    (a / "chapters").mkdir()
    for n in (1, 2, 3):
        (a / "chapters" / f"ch{n}.md").write_text(f"ch{n} body", encoding="utf-8")
    rev_dir = a / "reviews" / "standalone"
    rev_dir.mkdir(parents=True)
    (rev_dir / "ch1.md").write_text("rev ch1", encoding="utf-8")
    (rev_dir / "ch3.md").write_text("rev ch3", encoding="utf-8")

    # BookB(空态)
    b = tmp_path / "BookB"
    b.mkdir()
    (b / "book.json").write_text(json.dumps({
        "title": "Book B", "genre": "xuanhuan",
    }, ensure_ascii=False), encoding="utf-8")

    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def test_books_includes_last_chapter(tmp_data_root, client):
    """T2.1 RED:GET /api/books 返的书对象含 last_chapter 字段。"""
    resp = client.get("/api/books")
    assert resp.status_code == 200
    books = {b["name"]: b for b in resp.json()["books"]}
    assert books["BookA"]["last_chapter"] == 3, f"BookA last_chapter 应=3,实际:{books['BookA']}"
    assert books["BookA"]["last_written_chapter"] == 3
    assert books["BookA"]["finalized_count"] == 3


def test_books_counts_pending_body_as_written_but_not_finalized(tmp_data_root, client):
    """L-1：候选稿算已写，不能冒充已定稿。"""
    pending = tmp_data_root / "BookB" / "chapters" / "_pending"
    pending.mkdir(parents=True)
    (pending / "ch7.md").write_text("candidate", encoding="utf-8")

    books = {b["name"]: b for b in client.get("/api/books").json()["books"]}
    assert books["BookB"]["last_written_chapter"] == 7
    assert books["BookB"]["last_chapter"] == 7
    assert books["BookB"]["finalized_count"] == 0


def test_books_omits_removed_last_reviewed(tmp_data_root, client):
    """Q-2：已摘除的 standalone 审读不再残留在书架契约。"""
    resp = client.get("/api/books")
    books = {b["name"]: b for b in resp.json()["books"]}
    assert "last_reviewed" not in books["BookA"]


def test_books_empty_chapters_returns_none(tmp_data_root, client):
    """空书的 last_chapter 应为 None，不因历史审读目录崩溃。"""
    resp = client.get("/api/books")
    books = {b["name"]: b for b in resp.json()["books"]}
    # BookB 空态
    assert books["BookB"]["last_chapter"] is None


def test_books_without_review_dir_keeps_last_chapter(tmp_data_root, client):
    """有章节且无历史审读目录时，现役 last_chapter 契约不受影响。"""
    # 加一本只有章节没审读的书
    c = tmp_data_root / "BookC"
    c.mkdir()
    (c / "book.json").write_text(json.dumps({"title": "C"}), encoding="utf-8")
    (c / "chapters").mkdir()
    (c / "chapters" / "ch5.md").write_text("ch5", encoding="utf-8")

    resp = client.get("/api/books")
    books = {b["name"]: b for b in resp.json()["books"]}
    assert books["BookC"]["last_chapter"] == 5
    assert "last_reviewed" not in books["BookC"]


def test_books_still_returns_basic_meta(tmp_data_root, client):
    """T2.1 回归保护:原有字段(name / title / genre)不丢。"""
    resp = client.get("/api/books")
    books = {b["name"]: b for b in resp.json()["books"]}
    assert books["BookA"]["title"] == "Book A"
    assert books["BookA"]["genre"] == "xuanhuan"


def test_books_default_kind_is_test(tmp_data_root, client):
    """B 事实表:book.json 无 kind 字段时默认 'test'(非 real 书收折叠区)。"""
    resp = client.get("/api/books")
    books = {b["name"]: b for b in resp.json()["books"]}
    assert books["BookA"]["kind"] == "test"
    assert books["BookB"]["kind"] == "test"


def test_books_with_explicit_kind(tmp_data_root, client):
    """T0.1 RED:book.json 显式 kind='test' 时按值返回。"""
    c = tmp_data_root / "BookC"
    c.mkdir()
    (c / "book.json").write_text(json.dumps({
        "title": "Book C", "kind": "test",
    }, ensure_ascii=False), encoding="utf-8")

    resp = client.get("/api/books")
    books = {b["name"]: b for b in resp.json()["books"]}
    assert books["BookC"]["kind"] == "test"


# ── F3 (P8-M3R-fix):/api/books list→dict schema ────────────────────────────


class TestBooksDictSchema:
    """F3:/api/books 返回从 list 改为 dict schema。

    B3 transcript §Step 1 traceback: `'list' object has no attribute 'get'` —
    外部按 REST 约定 `{books: [...]}` 解析会炸。

    Schema: `{"books": [...], "count": N}`(count 冗余但便于外部快速核验)。
    """

    def test_response_is_dict_not_list(self, tmp_data_root, client):
        """响应根是 dict,不是 list(B3 §72 修复)。"""
        resp = client.get("/api/books")
        data = resp.json()
        assert isinstance(data, dict), (
            f"F3:响应应为 dict(含 books 字段),实为 {type(data).__name__}"
        )
        assert not isinstance(data, list), "F3:不应再返 list"

    def test_books_field_is_list(self, tmp_data_root, client):
        """响应含 'books' 键且值为 list。"""
        resp = client.get("/api/books")
        data = resp.json()
        assert "books" in data, "F3:响应应含 'books' 键"
        assert isinstance(data["books"], list), (
            f"F3:'books' 应是 list,实为 {type(data['books']).__name__}"
        )

    def test_count_field_matches_books_length(self, tmp_data_root, client):
        """响应含 'count' 键,等于 len(books)。"""
        resp = client.get("/api/books")
        data = resp.json()
        assert "count" in data, "F3:响应应含 'count' 键(冗余,便于外部核验)"
        assert data["count"] == len(data["books"]), (
            f"F3:count({data['count']}) 应等于 len(books)({len(data['books'])})"
        )

    def test_books_objects_have_required_fields(self, tmp_data_root, client):
        """每条 book 对象含必需字段: name / id / kind。"""
        resp = client.get("/api/books")
        books = resp.json()["books"]
        assert len(books) > 0, "测试预设了 BookA/BookB"
        for b in books:
            assert "name" in b, f"每书必有 name: {b}"
            assert "id" in b, f"R1 slug ID:每书必有 id: {b}"
            assert "kind" in b, f"每书必有 kind(默认 test): {b}"
