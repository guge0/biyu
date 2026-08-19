"""Observer 编码测试 — 验证 ¥ 等非 ASCII 字符在 Windows GBK 下不报错。"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from biyu.observer import update_truth_files, _ensure_utf8_stdout


class TestObserverEncoding:
    """测试 Observer 处理含特殊字符(¥)时不抛 UnicodeEncodeError。"""

    @pytest.fixture
    def mock_book_dir(self, tmp_path):
        """创建含 truth_files 初始化的最小书目录。"""
        truth_dir = tmp_path / "truth_files"
        truth_dir.mkdir()
        (truth_dir / "current_state.md").write_text(
            "| 字段 | 值 |\n|---|---|\n| 当前章 | 1 |\n", encoding="utf-8"
        )
        (truth_dir / "particle_ledger.md").write_text(
            "| 角色 | 属性 | 变化 |\n|---|---|---|\n", encoding="utf-8"
        )
        (truth_dir / "pending_hooks.md").write_text(
            "| hook_id | 内容 | 状态 |\n|---|---|---|\n", encoding="utf-8"
        )
        (tmp_path / "characters.yaml").write_text(
            "characters:\n  - name: 张今空\n    role: protagonist\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_ensure_utf8_stdout_does_not_crash(self):
        """_ensure_utf8_stdout 可安全调用。"""
        _ensure_utf8_stdout()  # 不应抛异常

    def test_yen_symbol_print(self, capsys):
        """¥ 符号通过 print 输出时不报错。"""
        _ensure_utf8_stdout()
        print("  [Observer] 真相文件已更新(3/3), ¥0.0123")
        captured = capsys.readouterr()
        assert "¥" in captured.out

    def test_update_truth_files_with_yen_cost(self, mock_book_dir):
        """update_truth_files 处理含 ¥ 的成本输出时不抛编码错误。"""
        mock_adapter = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = (
            "=== current_state ===\n"
            "| 字段 | 值 |\n|---|---|\n| 当前章 | 2 |\n"
            "=== particle_ledger ===\n"
            "| 角色 | 属性 | 变化 |\n|---|---|---|\n"
            "=== pending_hooks ===\n"
            "| hook_id | 内容 | 状态 |\n|---|---|---|\n"
        )
        mock_response.cost = 0.0123
        mock_adapter.generate.return_value = mock_response

        chapter_text = "张今空走进了房间。花费了¥100金币。"

        import asyncio
        result = asyncio.run(
            update_truth_files(mock_book_dir, 2, chapter_text, mock_adapter)
        )
        assert result is True

    def test_update_truth_files_failure_message_with_special_chars(self, mock_book_dir):
        """Observer 异常信息含特殊字符时不崩溃。"""
        mock_adapter = AsyncMock()
        mock_adapter.generate.side_effect = RuntimeError("成本超限: ¥5.00")

        import asyncio
        # 不应抛异常,应返回 False
        result = asyncio.run(
            update_truth_files(mock_book_dir, 1, "测试文本", mock_adapter)
        )
        assert result is False
