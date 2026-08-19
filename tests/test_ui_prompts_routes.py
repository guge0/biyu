"""Tests for biyu.ui.routes GET /api/prompts/{inventory,texts,source} — T5 spec line 13。

页面主体渲染 .anchor/state/prompt_texts_<date>.md 最新导出件(中枢裁定);
inventory 索引与 source 视图保留为辅。严格只读(无写入口)。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from biyu.ui.app import app


@pytest.fixture
def client(monkeypatch):
    return TestClient(app)


def test_get_prompts_inventory_returns_markdown(tmp_path, monkeypatch, client):
    """GET /api/prompts/inventory 应返 200 + markdown 文本。"""
    from biyu.ui import routes as ui_routes

    state_dir = tmp_path / ".anchor" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "prompt_inventory.md").write_text("# Architect\n# Writer\n# Editor\n", encoding="utf-8")
    monkeypatch.setattr(ui_routes, "get_project_root", lambda: tmp_path)
    resp = client.get("/api/prompts/inventory")
    assert resp.status_code == 200
    body = resp.json()
    assert "markdown" in body
    md = body["markdown"]
    assert "Architect" in md or "architect" in md.lower()
    assert "Writer" in md or "writer" in md.lower()
    assert "Editor" in md or "editor" in md.lower()


def test_get_prompts_inventory_includes_file_paths(tmp_path, monkeypatch, client):
    """inventory 应含文件位置(src/biyu/prompts/...)。"""
    from biyu.ui import routes as ui_routes

    state_dir = tmp_path / ".anchor" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "prompt_inventory.md").write_text("src/biyu/prompts/chapter_writer.py\n", encoding="utf-8")
    monkeypatch.setattr(ui_routes, "get_project_root", lambda: tmp_path)
    resp = client.get("/api/prompts/inventory")
    body = resp.json()
    md = body["markdown"]
    assert "src/biyu/prompts/" in md or "src/biyu/editor/" in md


def test_get_prompts_inventory_no_write_method(client):
    """严禁 POST/PUT/DELETE /api/prompts/* —— 页面无写入口。"""
    assert client.post("/api/prompts/inventory", json={}).status_code == 405
    assert client.put("/api/prompts/inventory", json={}).status_code == 405
    assert client.delete("/api/prompts/inventory").status_code == 405


def test_get_prompts_inventory_returns_source(client):
    """GET /api/prompts/source?file=...&start=...&end=... → 返源码片段。"""
    resp = client.get("/api/prompts/source", params={
        "file": "src/biyu/prompts/chapter_writer.py",
        "start": 1, "end": 10,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "text" in body
    assert body["file"] == "src/biyu/prompts/chapter_writer.py"


def test_get_prompts_source_rejects_paths_outside_src(client):
    """安全:路径白名单只允许 src/biyu/prompts/ 和 src/biyu/editor/。"""
    # config/models.yaml 含 Key,应拒绝
    resp = client.get("/api/prompts/source", params={
        "file": "config/models.yaml", "start": 1, "end": 5,
    })
    assert resp.status_code == 400
    # ../ 路径也应拒绝
    resp2 = client.get("/api/prompts/source", params={
        "file": "../etc/passwd", "start": 1, "end": 5,
    })
    assert resp2.status_code == 400


# ---------------------------------------------------------------------------
# T5 改造:GET /api/prompts/texts(中枢裁定——主体改读 prompt_texts_<date>.md)
# ---------------------------------------------------------------------------


def test_get_prompts_texts_returns_latest(tmp_path, monkeypatch, client):
    """/api/prompts/texts 应返最新的 prompt_texts_<date>.md 全文。"""
    from biyu.ui import routes as ui_routes
    from biyu.config import get_data_root

    state_dir = tmp_path / ".anchor" / "state"
    state_dir.mkdir(parents=True)
    # 三份不同日期的 prompt_texts
    (state_dir / "prompt_texts_2026-06-15.md").write_text("# 旧\n## 6-15\n", encoding="utf-8")
    (state_dir / "prompt_texts_2026-07-01.md").write_text("# 中\n## 7-01\n", encoding="utf-8")
    (state_dir / "prompt_texts_2026-07-03.md").write_text("# 新\n## 7-03\n", encoding="utf-8")
    # 让 routes 模块把仓库根指向 tmp_path
    monkeypatch.setattr(ui_routes, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr("biyu.ui.routes.get_data_root", lambda: tmp_path)
    monkeypatch.setattr(ui_routes, "get_project_root", lambda: tmp_path)

    resp = client.get("/api/prompts/texts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["markdown"] == "# 新\n## 7-03\n"
    assert body["date"] == "2026-07-03"


def test_get_prompts_texts_returns_empty_when_no_file(tmp_path, monkeypatch, client):
    """无 prompt_texts_*.md 文件时,返 200 + 空 markdown + null date(不报错)。"""
    from biyu.ui import routes as ui_routes

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    monkeypatch.setattr(ui_routes, "get_data_root", lambda: empty_root)
    monkeypatch.setattr(ui_routes, "get_project_root", lambda: empty_root)

    resp = client.get("/api/prompts/texts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["markdown"] == ""
    assert body["date"] is None


def test_get_prompts_texts_no_write_method(client):
    """严禁 POST/PUT/DELETE /api/prompts/texts —— 页面无写入口。"""
    assert client.post("/api/prompts/texts", json={}).status_code == 405
    assert client.put("/api/prompts/texts", json={}).status_code == 405
    assert client.delete("/api/prompts/texts").status_code == 405


def test_get_prompts_texts_picks_latest_by_date_in_filename(tmp_path, monkeypatch, client):
    """按文件名内嵌日期选最新,不看 mtime(避免文件系统时间漂移影响)。"""
    from biyu.ui import routes as ui_routes

    state_dir = tmp_path / ".anchor" / "state"
    state_dir.mkdir(parents=True)
    # 旧文件 mtime 较新(故意写反),新日期文件 mtime 较旧
    # 文件名日期才是权威依据
    (state_dir / "prompt_texts_2026-07-10.md").write_text("# 真·新\n", encoding="utf-8")
    (state_dir / "prompt_texts_2026-06-01.md").write_text("# 真·旧\n", encoding="utf-8")
    monkeypatch.setattr(ui_routes, "get_data_root", lambda: tmp_path)

    resp = client.get("/api/prompts/texts")
    body = resp.json()
    assert body["date"] == "2026-07-10"
    assert "真·新" in body["markdown"]
