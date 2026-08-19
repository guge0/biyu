"""R2 导入书无档案提示(P8-M3R T2.3b)— D-96 不静默降级。

Spec(specs/P8-M3R.md line 47):
   导入书无档案提示:编辑部顶部若检测当前书无 truth_files/ 或无 outlines/,
   显式提示"本书未建档,建议先倒灌(biyu refresh)再会诊"——不静默降级。

API: GET /api/books/{book_id}/archive-status → {has_truth_files, has_outlines, has_chapters}
前端: editor.js init 时调,任一为 false 显顶部提示 banner。

零烧钱,TestClient。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.web.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)

    # FullBook: 有 truth_files + outlines + chapters
    full = tmp_path / "FullBook"
    full.mkdir()
    (full / "book.json").write_text(json.dumps({"id": "full-1", "title": "F"}, ensure_ascii=False))
    (full / "truth_files").mkdir()
    (full / "truth_files" / "current_state.md").write_text("状态", encoding="utf-8")
    (full / "outlines").mkdir()
    (full / "outlines" / "ch1.md").write_text("细纲1", encoding="utf-8")
    (full / "chapters").mkdir()
    (full / "chapters" / "ch1.md").write_text("正文1", encoding="utf-8")

    # BareBook: 无 truth_files + 无 outlines(导入书未建档)
    bare = tmp_path / "BareBook"
    bare.mkdir()
    (bare / "book.json").write_text(json.dumps({"id": "bare-1", "title": "B"}, ensure_ascii=False))

    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def test_archive_status_full_book(tmp_data_root, client):
    """有 truth_files + outlines → has_truth_files=True, has_outlines=True。"""
    resp = client.get("/api/books/full-1/archive-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_truth_files"] is True
    assert data["has_outlines"] is True


def test_archive_status_bare_book(tmp_data_root, client):
    """无 truth_files + 无 outlines → 都 False(前端据此显提示)。"""
    resp = client.get("/api/books/bare-1/archive-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_truth_files"] is False
    assert data["has_outlines"] is False


def test_archive_status_by_dir_name(tmp_data_root, client):
    """用目录名也能访问(R1 兼容回退)。"""
    resp = client.get("/api/books/FullBook/archive-status")
    assert resp.status_code == 200
    assert resp.json()["has_truth_files"] is True


def test_archive_status_nonexistent_book_404(tmp_data_root, client):
    """不存在的书 → 404。"""
    resp = client.get("/api/books/nonexistent/archive-status")
    assert resp.status_code == 404
