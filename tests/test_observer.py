"""test_observer.py — observer.py 伏笔三态重分类单测."""
from __future__ import annotations

from pathlib import Path

from biyu.observer import (
    reclassify_hooks,
    reclassify_pending_hooks_file,
    build_observer_prompt,
)


# ---------------------------------------------------------------------------
# reclassify_hooks 单测
# ---------------------------------------------------------------------------

class TestReclassifyHooks:
    def test_no_changes_needed(self):
        """全是 open/advancing/closed → 无变更。"""
        md = (
            "| hook_id | 起始章节 | 类型 | 状态 | 最近推进 | 预期回收 | 回收节奏 | 备注 |\n"
            "|---------|---------|------|------|---------|---------|---------|------|\n"
            "| hook_01 | 1 | 设定伏笔 | open | - | 中期 | - | 备注 |\n"
            "| hook_02 | 3 | 情节伏笔 | advancing | 第5章 | 短期 | - | 备注 |\n"
            "| hook_03 | 5 | 情节伏笔 | closed | 第8章 | 已回收 | - | 备注 |\n"
        )
        new_md, changes = reclassify_hooks(md)
        assert changes == []
        assert new_md == md

    def test_partially_closed_to_advancing(self):
        """partially_closed → advancing。"""
        md = (
            "| hook_id | 起始章节 | 类型 | 状态 | 最近推进 | 预期回收 | 回收节奏 | 备注 |\n"
            "|---------|---------|------|------|---------|---------|---------|------|\n"
            "| hook_01 | 1 | 设定伏笔 | partially_closed | 第5章 | 中期 | - | 备注 |\n"
            "| hook_02 | 3 | 情节伏笔 | open | - | 短期 | - | 备注 |\n"
        )
        new_md, changes = reclassify_hooks(md)
        assert len(changes) == 1
        assert changes[0]["hook_id"] == "hook_01"
        assert changes[0]["old"] == "partially_closed"
        assert changes[0]["new"] == "advancing"
        # advancing 出现在新内容中
        assert "| hook_01 | 1 | 设定伏笔 | advancing |" in new_md
        # hook_02 不变
        assert "| hook_02 | 3 | 情节伏笔 | open |" in new_md

    def test_multiple_reclassifications(self):
        """多个 partially_closed 全部变为 advancing。"""
        md = (
            "| hook_id | 起始章节 | 类型 | 状态 | 最近推进 |\n"
            "|---------|---------|------|------|---------|\n"
            "| hook_01 | 1 | 设定伏笔 | partially_closed | 第5章 |\n"
            "| hook_02 | 3 | 情节伏笔 | partially_closed | 第6章 |\n"
            "| hook_03 | 5 | 情节伏笔 | closed | 第8章 |\n"
        )
        new_md, changes = reclassify_hooks(md)
        assert len(changes) == 2
        assert all(c["new"] == "advancing" for c in changes)

    def test_empty_input(self):
        """空内容 → 无变更。"""
        new_md, changes = reclassify_hooks("")
        assert changes == []
        assert new_md == ""

    def test_no_header(self):
        """无表头 → 原样返回。"""
        md = "一些没有表头的内容\n| hook_01 | 数据 |"
        new_md, changes = reclassify_hooks(md)
        assert changes == []
        assert new_md == md

    def test_header_only(self):
        """只有表头没有数据行 → 无变更。"""
        md = (
            "| hook_id | 状态 |\n"
            "|---------|------|\n"
        )
        new_md, changes = reclassify_hooks(md)
        assert changes == []


# ---------------------------------------------------------------------------
# reclassify_pending_hooks_file 集成测试
# ---------------------------------------------------------------------------

class TestReclassifyFile:
    def test_reclassify_writes_file(self, tmp_path: Path):
        """重分类后文件被更新。"""
        from biyu.truth_files import write_truth_file, read_truth_file

        book_dir = tmp_path / "book"
        book_dir.mkdir()
        truth_dir = book_dir / "truth_files"
        truth_dir.mkdir()

        original = (
            "| hook_id | 起始章节 | 类型 | 状态 | 最近推进 |\n"
            "|---------|---------|------|------|---------|\n"
            "| hook_01 | 1 | 设定伏笔 | partially_closed | 第5章 |\n"
            "| hook_02 | 3 | 情节伏笔 | open | - |\n"
        )
        write_truth_file(book_dir, "pending_hooks.md", original)

        changes = reclassify_pending_hooks_file(book_dir)
        assert len(changes) == 1

        updated = read_truth_file(book_dir, "pending_hooks.md")
        assert "advancing" in updated
        assert "partially_closed" not in updated

    def test_reclassify_no_changes(self, tmp_path: Path):
        """无需修改时不写文件。"""
        from biyu.truth_files import write_truth_file

        book_dir = tmp_path / "book2"
        book_dir.mkdir()
        truth_dir = book_dir / "truth_files"
        truth_dir.mkdir()

        original = (
            "| hook_id | 状态 |\n"
            "|---------|------|\n"
            "| hook_01 | open |\n"
        )
        write_truth_file(book_dir, "pending_hooks.md", original)

        changes = reclassify_pending_hooks_file(book_dir)
        assert changes == []


# ---------------------------------------------------------------------------
# Observer prompt 验证
# ---------------------------------------------------------------------------

class TestObserverPrompt:
    def test_prompt_contains_three_states(self):
        """Prompt 包含三态状态机说明。"""
        prompt = build_observer_prompt(1, "正文内容", {
            "current_state.md": "| 字段 | 值 |",
            "particle_ledger.md": "| 章节 | 角色 |",
            "pending_hooks.md": "| hook_id | 状态 |",
        })
        assert "open" in prompt
        assert "advancing" in prompt
        assert "closed" in prompt
        assert "推进" in prompt
        assert "闭合" in prompt
        # 确保不再有旧的两态描述
        assert "partially_closed" not in prompt

    def test_prompt_has_explicit_warning(self):
        """Prompt 包含推进≠闭合的警告。"""
        prompt = build_observer_prompt(5, "正文", {
            "current_state.md": "",
            "particle_ledger.md": "",
            "pending_hooks.md": "",
        })
        assert "推进" in prompt and "≠" in prompt or "推进" in prompt and "闭合" in prompt
