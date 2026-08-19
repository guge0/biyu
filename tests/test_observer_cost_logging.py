"""Observer 成本记账测试 — 验证 update_truth_files 拿到 _log_cost_fn 时把 cost/latency 传出去。

根因:pipeline.py 所有其他阶段都调 _log_cost,唯独 Observer 段漏了。
修复:update_truth_files 加 _log_cost_fn DI 参数(参照 _run_anchor_loop 模式)。
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from biyu.observer import update_truth_files


def _make_book_dir(tmp_path: Path) -> Path:
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
        "characters:\n  - name: 测试主角\n    role: protagonist\n",
        encoding="utf-8",
    )
    return tmp_path


class TestObserverCostLogging:
    """验证 Observer 拿到 _log_cost_fn 时把成本和延迟传出去。"""

    def test_log_cost_fn_called_with_resp_cost_and_latency(self, tmp_path):
        """update_truth_files 内部 LLM 调用后,_log_cost_fn 应被调一次,参数含 resp.cost。"""
        book_dir = _make_book_dir(tmp_path)

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
        mock_response.cost = 0.0200
        mock_adapter.generate.return_value = mock_response

        recorded_calls: list[tuple[float, float]] = []

        def fake_log_cost(cost: float, latency: float) -> None:
            recorded_calls.append((cost, latency))

        result = asyncio.run(
            update_truth_files(
                book_dir, 2, "测试章节正文", mock_adapter,
                _log_cost_fn=fake_log_cost,
            )
        )

        assert result is True, "Observer 应成功"
        assert len(recorded_calls) == 1, f"_log_cost_fn 应被调一次,实际 {len(recorded_calls)} 次"
        recorded_cost, recorded_latency = recorded_calls[0]
        assert recorded_cost == pytest.approx(0.0200, abs=1e-6), \
            f"记出的 cost 应等于 resp.cost=0.0200,实际 {recorded_cost}"
        assert recorded_latency > 0.0, f"latency 应大于 0,实际 {recorded_latency}"

    def test_log_cost_fn_none_when_not_passed(self, tmp_path):
        """不传 _log_cost_fn(默认 None)时,行为零回归 — 老调用方 refresh.py / 内部 rebuild 都走这条。"""
        book_dir = _make_book_dir(tmp_path)

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
        mock_response.cost = 0.0200
        mock_adapter.generate.return_value = mock_response

        # 默认不传 _log_cost_fn,不应抛异常
        result = asyncio.run(
            update_truth_files(book_dir, 2, "测试章节正文", mock_adapter)
        )
        assert result is True

    def test_log_cost_fn_not_called_on_failure(self, tmp_path):
        """Observer 内部异常时,_log_cost_fn 不应被调用(没成功调到 LLM,没成本可记)。"""
        book_dir = _make_book_dir(tmp_path)

        mock_adapter = AsyncMock()
        mock_adapter.generate.side_effect = RuntimeError("API 拒绝")

        recorded_calls: list[tuple[float, float]] = []

        def fake_log_cost(cost: float, latency: float) -> None:
            recorded_calls.append((cost, latency))

        result = asyncio.run(
            update_truth_files(
                book_dir, 1, "测试", mock_adapter,
                _log_cost_fn=fake_log_cost,
            )
        )

        assert result is False, "Observer 应失败"
        assert len(recorded_calls) == 0, "失败时不应记成本"
