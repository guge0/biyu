"""T1 壳统一(P8-M2.5)— ui app 应能访问 M2 章节工作台的全部路由。

Spec 验收(specs/P8-M2.5.md line 25):
  `biyu ui` 单入口可完成:首页 → 立项 → 书架 → 审读 → 提示词页

本测试验证"T1 壳统一"的最小契约:经 `biyu.ui.app:app` 入口可访问 M2 加入的
章节工作台路由(books / chapters / characters / truth_files / cost / SSE generate /
SSE auto / standalone review / refresh-estimate)。零烧钱,全 mock。

T1 工程选择(D-83 工程细节):用 `include_router` 把 web router 挂到 ui app,
不物理搬代码。这样:
- 满足 spec 验收"`biyu ui` 单入口可完成"
- web/ 现有测试(test_web_review_routes.py 依赖 `biyu.web.app:app`)零回归
- 后续 T2-T5 在 ui/ 里加新路由,web/ 保留作 deprecated 旧入口
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


# ---------------------------------------------------------------------------
# T1.1 测试:ui app 能访问 M2 章节工作台路由
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把 data root 指到 tmp_path,建一本假书 TestBook(含 ch1.md)。

    Patch biyu.config.get_data_root 源头(因为 resolve_book_dir 内部调它)。
    """
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    # web/routes.py 重导出的引用也要 patch
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)

    book_dir = tmp_path / "TestBook"
    ch_dir = book_dir / "chapters"
    ch_dir.mkdir(parents=True)
    (ch_dir / "ch1.md").write_text("第1章 测试\n这是测试正文。" * 30, encoding="utf-8")

    import json
    (book_dir / "book.json").write_text(json.dumps({
        "title": "TestBook",
        "genre": "xuanhuan",
    }, ensure_ascii=False), encoding="utf-8")
    return book_dir


@pytest.fixture
def client():
    return TestClient(app)


def test_ui_app_can_list_books(tmp_book, client):
    """T1.1 RED:ui app 应能访问 GET /api/books(M2 章节工作台路由)。

    Spec 验收:`biyu ui` 单入口可完成"书架"。
    """
    resp = client.get("/api/books")
    assert resp.status_code == 200
    # F3 (P8-M3R-fix):响应从 list 改为 dict schema `{"books": [...], "count": N}`
    books = resp.json()["books"]
    # 应包含 tmp_book 建的 TestBook
    names = [b.get("name") for b in books]
    assert "TestBook" in names, f"TestBook 不在 ui app 的 /api/books 返回里: {books}"


def test_ui_app_can_list_chapters(tmp_book, client):
    """T1.1 RED:ui app 应能访问 GET /api/books/{book}/chapters。"""
    resp = client.get("/api/books/TestBook/chapters")
    assert resp.status_code == 200
    chapters = resp.json()
    assert isinstance(chapters, list)
    assert any(c["chapter"] == 1 and c["has_content"] for c in chapters)


def test_ui_app_can_get_chapter_content(tmp_book, client):
    """T1.1 RED:ui app 应能访问 GET /api/books/{book}/chapters/{n}/content。"""
    resp = client.get("/api/books/TestBook/chapters/1/content")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chapter"] == 1
    assert "测试正文" in body["content"]


def test_ui_app_can_get_refresh_estimate(tmp_book, client):
    """T1.1 RED:ui app 应能访问 GET /api/books/{book}/refresh-estimate。"""
    resp = client.get("/api/books/TestBook/refresh-estimate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chapter_count"] == 1
    assert body["per_chapter_low"] > 0


def test_ui_app_can_get_cost(tmp_book, client):
    """T1.1 RED:ui app 应能访问 GET /api/books/{book}/cost。"""
    resp = client.get("/api/books/TestBook/cost")
    assert resp.status_code == 200
    body = resp.json()
    # 没有成本日志时应返 total=0 + entries=[]
    assert body["total"] == 0
    assert body["entries"] == []


def test_ui_app_still_has_propose_routes(client):
    """T1.1 回归保护:ui app 原有的 M1 立项屏路由不丢失。

    GET /api/env / GET /api/session 是 M1 立项屏的路由,壳统一后必须仍可访问。
    """
    assert client.get("/api/env").status_code == 200
    assert client.get("/api/session").status_code == 200
