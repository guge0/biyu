"""I-1 双根扫描测试:书架双根+根标注、重名区分、读放行、写拦截、单根回退。"""
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biyu.config import get_data_root_2, get_data_roots  # noqa: E402


@pytest.fixture()
def dual_roots(tmp_path, monkeypatch):
    """两个数据根,各放一本书;其中 dev 根放一本与 prod 同 id 的重名书。"""
    prod = tmp_path / "prod_root"
    dev = tmp_path / "dev_root"
    prod.mkdir()
    dev.mkdir()
    for root, bid, title in [
        (prod, "bookA", "生产书A"),
        (dev, "bookA", "开发书A同名"),
        (dev, "bookB", "开发书B"),
    ]:
        d = root / bid
        d.mkdir()
        (d / "book.json").write_text(
            json.dumps({"id": bid, "title": title, "display_name": title}), encoding="utf-8"
        )
        (d / "outlines").mkdir()
        (d / "chapters").mkdir()
        (d / "logs").mkdir()
        (d / "outlines" / "ch1.md").write_text("第1章细纲\n", encoding="utf-8")
    monkeypatch.setenv("BIYU_DATA_ROOT", str(prod))
    monkeypatch.setenv("BIYU_DATA_ROOT_2", str(dev))
    return prod, dev


def test_get_data_roots_order(dual_roots):
    prod, dev = dual_roots
    roots = get_data_roots()
    assert roots[0] == prod.resolve()
    assert roots[1] == dev.resolve()
    assert get_data_root_2() == dev.resolve()


def test_single_root_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("BIYU_DATA_ROOT_2", raising=False)
    monkeypatch.setenv("BIYU_DATA_ROOT", str(tmp_path / "only"))
    assert get_data_root_2() is None
    assert len(get_data_roots()) == 1


def test_bookshelf_lists_both_roots_with_labels(dual_roots):
    from biyu.ui.app import app

    client = TestClient(app)
    resp = client.get("/api/books")
    assert resp.status_code == 200
    books = resp.json()["books"]
    by_id = {b["id"]: b for b in books}
    # 重名 bookA 两条,标注区分,不合并
    a_same = [b for b in books if b["id"] == "bookA"]
    assert len(a_same) == 2, "重名书不许静默合并"
    labels = {b["root"] for b in a_same}
    assert "生产根" in labels
    assert any("开发根" in l for l in labels)
    assert by_id["bookB"]["root"].startswith("开发根")


def test_read_chapter_from_dev_root_ok(dual_roots):
    from biyu.ui.app import app

    client = TestClient(app)
    resp = client.get("/api/workbench/books/bookB/chapters/1")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, dict)


def test_write_to_dev_root_blocked_403(dual_roots):
    from biyu.ui.app import app

    client = TestClient(app)
    resp = client.put(
        "/api/workbench/books/bookB/chapters/1/outline",
        json={"outline": "改细纲"},
    )
    assert resp.status_code == 403, resp.text
    assert "只读" in resp.json()["detail"]


def test_write_to_prod_root_allowed(dual_roots):
    from biyu.ui.app import app

    client = TestClient(app)
    resp = client.put(
        "/api/workbench/books/bookA/chapters/1/outline",
        json={"outline": "改细纲"},
    )
    # 书解析成功(生产根)后,是否 200 取决于该路由实现;403 只应来自写保护
    assert resp.status_code != 403, resp.text


def test_single_root_write_unchanged(tmp_path, monkeypatch):
    """未设第二根时,写路径保持历史行为(不被中间件误拦)。"""
    root = tmp_path / "only"
    root.mkdir()
    d = root / "bookC"
    d.mkdir()
    (d / "book.json").write_text(json.dumps({"id": "bookC"}), encoding="utf-8")
    (d / "outlines").mkdir()
    monkeypatch.setenv("BIYU_DATA_ROOT", str(root))
    monkeypatch.delenv("BIYU_DATA_ROOT_2", raising=False)
    from biyu.ui.app import app

    client = TestClient(app)
    resp = client.put(
        "/api/workbench/books/bookC/chapters/1/outline",
        json={"outline": "改"},
    )
    assert resp.status_code != 403
