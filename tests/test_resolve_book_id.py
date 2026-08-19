"""R1 slug ID — resolve_book_dir 兼容回退(P8-M3R T1.2).

Spec(specs/P8-M3R.md line 28):
   路由 /api/books/{book_id}/... 兼容回退(先 id 匹配,再目录名)

resolve_book_dir 的契约扩展:
- 输入是 book_id(如 "dao-1")→ 扫所有 book.json,按 id 字段匹配 → 返该目录
- 输入是目录名(如 "大道行")→ 直接走 data_root/<book> 路径
- 两者都不命中 → FileNotFoundError
- book=None 时保留原 auto-detect 行为

零烧钱,纯逻辑测试。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from biyu.config import resolve_book_dir


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """tmp 数据根 + 3 本假书:
    - BookA: id="dao-1"
    - BookB: id="quanjue-1"
    - LegacyBook: 无 id(测目录名回退)
    """
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)

    a = tmp_path / "BookA"
    a.mkdir()
    (a / "book.json").write_text(
        json.dumps({"id": "dao-1", "title": "A"}, ensure_ascii=False),
        encoding="utf-8",
    )

    b = tmp_path / "BookB"
    b.mkdir()
    (b / "book.json").write_text(
        json.dumps({"id": "quanjue-1", "title": "B"}, ensure_ascii=False),
        encoding="utf-8",
    )

    leg = tmp_path / "LegacyBook"
    leg.mkdir()
    (leg / "book.json").write_text(
        json.dumps({"title": "Legacy"}, ensure_ascii=False),
        encoding="utf-8",
    )

    return tmp_path


def test_resolve_by_book_id(tmp_data_root):
    """输入 book_id,扫 book.json id 字段匹配,返对应目录。"""
    result = resolve_book_dir("dao-1")
    assert result.name == "BookA", f"id=dao-1 应返 BookA 目录,实际:{result}"


def test_resolve_by_book_id_another(tmp_data_root):
    """另一本 book_id 也能命中。"""
    result = resolve_book_dir("quanjue-1")
    assert result.name == "BookB"


def test_resolve_fallback_to_dir_name(tmp_data_root):
    """无 id 匹配时,回退目录名(旧契约兼容)。"""
    result = resolve_book_dir("LegacyBook")
    assert result.name == "LegacyBook"


def test_resolve_dir_name_with_id_book_also_works(tmp_data_root):
    """有 id 的书,用目录名访问也能命中(双路径都通)。"""
    result = resolve_book_dir("BookA")
    assert result.name == "BookA"


def test_resolve_unknown_id_raises(tmp_data_root):
    """不存在的 id → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        resolve_book_dir("nonexistent-id")


def test_resolve_unknown_dir_raises(tmp_data_root):
    """不存在的目录名 → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        resolve_book_dir("NonexistentBook")


def test_resolve_id_takes_priority_over_dir_name(tmp_path, monkeypatch):
    """边界:某书的 id 恰好等于另一书的目录名时,id 优先。

    场景:BookX 目录名 = "special",BookY 的 id = "special"。
    resolve("special") 应优先返 BookY(id 命中),而非 BookX(目录名命中)。
    """
    monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)

    x = tmp_path / "special"  # 目录名 = "special"
    x.mkdir()
    (x / "book.json").write_text(
        json.dumps({"id": "x-id", "title": "X"}, ensure_ascii=False),
        encoding="utf-8",
    )

    y = tmp_path / "BookY"
    y.mkdir()
    (y / "book.json").write_text(
        json.dumps({"id": "special", "title": "Y"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = resolve_book_dir("special")
    # id 优先 → 应返 BookY
    assert result.name == "BookY", f"id 应优先于目录名,实际:{result}"


def test_resolve_scans_secondary_data_root_and_lists_correct_choices(tmp_path, monkeypatch):
    """L-1 命门：网页建在副根的书，Claude Code 解析器也必须看得见。"""
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    external = secondary / "j1"
    external.mkdir()
    (external / "book.json").write_text(
        json.dumps({"id": "j1", "title": "阶段一测试书"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("biyu.config.get_data_root", lambda: primary)
    monkeypatch.setattr("biyu.config.get_data_root_2", lambda: secondary)

    assert resolve_book_dir("j1") == external
    with pytest.raises(FileNotFoundError, match="可选书目录.*j1"):
        resolve_book_dir("not-there")
