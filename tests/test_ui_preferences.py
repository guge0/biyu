"""T6 偏好沉淀单测 (P8-M3 T6)— preferences CRUD。

零烧钱,纯文件模拟。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from biyu.ui.preferences import (
    delete_preference,
    list_preferences,
    save_preference,
)


@pytest.fixture
def book_dir(tmp_path: Path) -> Path:
    """data/TestBook/ 目录。"""
    d = tmp_path / "TestBook"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """data/ 根目录。"""
    d = tmp_path
    return d


class TestSavePreference:
    def test_save_book_scope(self, book_dir: Path):
        """scope=book → 在本书 preferences.md 存储。"""
        result = save_preference(
            book_dir,
            content="建议增加女配林霜的戏份",
            source_session="session-001",
            scope="book",
        )
        assert result["scope"] == "book"
        assert result["source_session"] == "session-001"
        assert result["entry_id"] != ""
        # 文件已创建
        assert (book_dir / "preferences.md").exists()

    def test_save_global_scope(self, data_root: Path):
        """scope=global → 在 data/preferences_global.md 存储。"""
        result = save_preference(
            book_dir=None,
            content="减少战斗场景的描写比重",
            source_session="session-002",
            scope="global",
            data_root=data_root,
        )
        assert result["scope"] == "global"
        assert (data_root / "preferences_global.md").exists()


class TestListPreference:
    def test_list_book(self, book_dir: Path):
        """list_preferences 返回已存条目。"""
        save_preference(book_dir, content="女配加戏", source_session="s1", scope="book")
        save_preference(book_dir, content="节奏放缓", source_session="s2", scope="book")

        entries = list_preferences(book_dir, scope="book")
        assert len(entries) == 2
        assert entries[0]["entry_id"] != ""
        assert entries[0]["content"] in ("女配加戏", "节奏放缓")
        assert entries[1]["content"] in ("女配加戏", "节奏放缓")

    def test_list_global(self, data_root: Path):
        """list_preferences global 返回全局条目。"""
        save_preference(
            None, content="通用偏好1", source_session="s1",
            scope="global", data_root=data_root,
        )
        entries = list_preferences(scope="global", data_root=data_root)
        assert len(entries) == 1

    def test_list_empty(self, tmp_path: Path):
        """无可存储偏好的书 → 空列表。"""
        empty_dir = tmp_path / "EmptyBook"
        empty_dir.mkdir()
        entries = list_preferences(empty_dir, scope="book")
        assert entries == []


class TestDeletePreference:
    def test_delete_existing(self, book_dir: Path):
        """删除存在的条目 → True,且数量减 1。"""
        r1 = save_preference(book_dir, content="条目1", source_session="s1", scope="book")
        save_preference(book_dir, content="条目2", source_session="s2", scope="book")

        ok = delete_preference(r1["entry_id"], book_dir=book_dir, scope="book")
        assert ok

        entries = list_preferences(book_dir, scope="book")
        assert len(entries) == 1

    def test_delete_nonexistent(self, book_dir: Path):
        """删除不存在的条目 → False。"""
        ok = delete_preference("no-such-id", book_dir=book_dir, scope="book")
        assert not ok

    def test_delete_from_nonexistent_file(self, tmp_path: Path):
        """文件不存在的书 → False。"""
        empty_dir = tmp_path / "EmptyBook"
        empty_dir.mkdir()
        ok = delete_preference("some-id", book_dir=empty_dir, scope="book")
        assert not ok

    def test_delete_global(self, data_root: Path):
        """删除 global 偏好。"""
        r1 = save_preference(
            None, content="全局条目", source_session="s1",
            scope="global", data_root=data_root,
        )
        ok = delete_preference(r1["entry_id"], scope="global", data_root=data_root)
        assert ok
        entries = list_preferences(scope="global", data_root=data_root)
        assert len(entries) == 0
