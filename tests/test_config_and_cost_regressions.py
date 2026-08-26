"""Config and cost accounting regression tests."""
import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from biyu.editor.multi_agent import load_editor_config, clear_config_cache
from biyu.editor.parser import EditorResult


# ---------------------------------------------------------------------------
# DEBT-Config-1: load_editor_config path + fallback warning
# ---------------------------------------------------------------------------

class TestConfigPath:
    def setup_method(self):
        clear_config_cache()

    def test_config_path_resolves_to_project_root(self):
        """config_path 应解析到项目根下的 config/editor.yaml。"""
        from biyu.editor import multi_agent
        module_file = Path(multi_agent.__file__)
        expected = module_file.parents[3] / "config" / "editor.yaml"
        # 验证路径确实存在
        assert expected.exists(), f"config 不存在于 {expected}"

        # 加载并验证
        config = load_editor_config()
        assert "mode" in config
        assert config["mode"] in ("single", "multi_agent")

    def test_config_path_parents_count(self):
        """验证 parents[3] 指向项目根（含 pyproject.toml）。"""
        from biyu.editor import multi_agent
        module_file = Path(multi_agent.__file__)
        project_root = module_file.parents[3]
        assert (project_root / "pyproject.toml").exists(), \
            f"parents[3]={project_root} 不是项目根（无 pyproject.toml）"
        assert (project_root / "config" / "editor.yaml").exists(), \
            f"config/editor.yaml 不存在于 {project_root}"

    def test_fallback_logs_warning_when_config_missing(self, caplog, tmp_path):
        """config 文件不存在时应显式记 warning 日志。"""
        clear_config_cache()
        # 临时把 config 文件移走来触发 fallback
        from biyu.editor import multi_agent
        module_file = Path(multi_agent.__file__)
        real_config = module_file.parents[3] / "config" / "editor.yaml"
        backup = tmp_path / "editor.yaml.bak"
        if real_config.exists():
            backup.write_text(real_config.read_text(encoding="utf-8"), encoding="utf-8")
            real_config.unlink()

        try:
            with caplog.at_level(logging.WARNING, logger="biyu.editor.multi_agent"):
                config = load_editor_config()

            assert config["mode"] == "single"
            assert any("falling back" in r.message.lower() or "editor.yaml not found" in r.message.lower()
                        for r in caplog.records), \
                "config 不存在时应记录 warning 日志"
        finally:
            # 恢复 config 文件
            if backup.exists():
                real_config.parent.mkdir(parents=True, exist_ok=True)
                real_config.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            clear_config_cache()


# ---------------------------------------------------------------------------
# DEBT-Config-1: _PHASE_TRACE_DIR no longer hardcoded
# ---------------------------------------------------------------------------

class TestPhaseTraceDir:
    def test_phase_trace_dir_follows_data_root(self, monkeypatch, tmp_path):
        """诊断轨迹属于作者数据根，不再落进源码仓。"""
        from biyu.editor import multi_agent

        monkeypatch.setattr("biyu.config.get_data_root", lambda: tmp_path)
        multi_agent._dump_phase_trace("phase1", {}, 1, book_dir=tmp_path / "book")

        traces = list((tmp_path / "book" / "phase_trace").glob("phase1_trace_*.json"))
        assert len(traces) == 1
        assert json.loads(traces[0].read_text(encoding="utf-8"))["chapter"] == 1

    def test_phase_trace_contract_has_no_source_data_root(self):
        """实现须在调用时解析 BIYU_DATA_ROOT，不能缓存源码仓路径。"""
        import inspect
        from biyu.editor import multi_agent

        source = inspect.getsource(multi_agent._dump_phase_trace)
        assert "book_dir" in source
        assert "parents[3] / \"data\"" not in source


# ---------------------------------------------------------------------------
# DEBT-COST-1: editor.py review_chapter cost accumulation
# ---------------------------------------------------------------------------

class TestEditorCostAccumulation:
    def test_single_review_chapter_accumulates_cost(self):
        """review_chapter (single mode) 应累计 cost 并返回。"""
        asyncio.run(self._test_cost())

    async def _test_cost(self):
        from biyu.editor.editor import review_chapter

        # 构造 mock adapter: 两次调用返回不同 cost
        resp1 = MagicMock()
        resp1.text = json.dumps({
            "issues": [],
            "queries_used": [],
            "confidence": "high",
        })
        resp1.cost = 0.0123
        resp1.reasoning_content = None
        resp1.raw = {"choices": [{"message": {"content": resp1.text}}]}

        adapter = AsyncMock()
        adapter.generate = AsyncMock(return_value=resp1)

        result = await review_chapter(
            chapter_num=1,
            chapter_text="测试正文测试正文",
            book_dir=Path("/tmp/test_book"),
            adapter=adapter,
        )

        assert isinstance(result.cost, float)
        assert result.cost > 0.0, \
            f"review_chapter 应累计 cost，实际 cost={result.cost}"

    def test_single_review_with_tool_calls_accumulates_all_costs(self):
        """含 tool call 的审稿应累计所有轮次 cost。"""
        asyncio.run(self._test_multi_round_cost())

    async def _test_multi_round_cost(self):
        from biyu.editor.editor import review_chapter

        # Round 1: tool call
        resp1 = MagicMock()
        resp1.text = "calling tool"
        resp1.cost = 0.0050
        resp1.reasoning_content = "Let me check..."
        resp1.raw = {
            "choices": [{
                "message": {
                    "content": "calling tool",
                    "tool_calls": [{
                        "id": "call_test",
                        "function": {"name": "look_up_character", "arguments": '{"char_name": "张今空"}'},
                        "type": "function",
                    }],
                }
            }]
        }

        # Round 2: final text
        resp2 = MagicMock()
        resp2.text = json.dumps({
            "issues": [],
            "queries_used": [],
            "confidence": "high",
        })
        resp2.cost = 0.0080
        resp2.reasoning_content = None
        resp2.raw = {"choices": [{"message": {"content": resp2.text}}]}

        adapter = AsyncMock()
        adapter.generate = AsyncMock(side_effect=[resp1, resp2])

        result = await review_chapter(
            chapter_num=1,
            chapter_text="测试正文",
            book_dir=Path("/tmp/test_book"),
            adapter=adapter,
        )

        # 两次调用 cost 都应累加
        assert abs(result.cost - 0.0130) < 0.0001, \
            f"两轮 cost 应合计 0.0130，实际 cost={result.cost}"

    def test_editor_result_has_cost_field(self):
        """EditorResult 应有 cost 字段。"""
        result = EditorResult()
        assert hasattr(result, 'cost')
        assert result.cost == 0.0

        result.cost = 0.025
        assert result.cost == 0.025
