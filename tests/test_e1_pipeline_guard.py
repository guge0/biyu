"""E-1 兜底 · pipeline 级埋雷:planning 空/失败时禁止继续走 Writer。

两态:装上修复(architect 段 generate_guarded + 失败拦截)→ 绿;
注掉拦截 → Writer 会被调用(红)。
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from biyu.llm.base import EmptyContentError, LLMResponse
import biyu.pipeline as pipeline


def _book(tmp_path: pytest.TempPathFactory):
    b = tmp_path / "book"
    b.mkdir()
    (b / "book.json").write_text(
        '{"title": "t", "genre": "xuanhuan", "chapter_target_words": 5000, '
        '"chapter_min_words": 4250, "context_mode": "long_context"}',
        encoding="utf-8",
    )
    (b / "outlines").mkdir()
    (b / "outlines/ch1.md").write_text("# 第一章\n测试细纲", encoding="utf-8")
    return b


def _setup(monkeypatch: pytest.MonkeyPatch, planner: MagicMock) -> MagicMock:
    registry = MagicMock()
    registry.get_pipeline_config.return_value = {"planner": "mock-planner"}
    registry.get_adapter_for_stage.return_value = planner
    registry.get_adapter.return_value = MagicMock()
    monkeypatch.setattr(pipeline, "get_registry", lambda: registry)
    monkeypatch.setattr(pipeline, "load_merged_voiceprint", lambda _: {"text": ""})
    monkeypatch.setattr(pipeline, "init_db", lambda _: None)
    monkeypatch.setattr(pipeline, "sync_characters_from_yaml", lambda _: (0, 0))
    monkeypatch.setattr(pipeline, "load_characters_yaml", lambda _: [])
    monkeypatch.setattr(pipeline, "_build_context_block", lambda *args: ("", None))
    monkeypatch.setattr(pipeline, "read_all_truth_files", lambda _: {})
    monkeypatch.setattr(pipeline, "build_planning_prompt", lambda **k: "planning prompt")
    return registry


@pytest.mark.asyncio
async def test_empty_planning_stops_before_writer(tmp_path, monkeypatch):
    """Architect 全败(empty)→ 管线停止:不写 planning.md、Writer 不被调用。"""
    planner = MagicMock()
    planner.generate_guarded = AsyncMock(
        side_effect=EmptyContentError(attempts=2, total_cost=0.58, total_latency=120.0)
    )
    writer = MagicMock()
    writer.generate = AsyncMock(return_value=LLMResponse(text="不应被生成", model="w"))
    registry = _setup(monkeypatch, planner)
    # writer adapter 也返回 mock(证明它不被调用)
    registry.get_adapter_for_stage.side_effect = lambda stage, override=None: (
        planner if stage == "planner" else writer
    )

    book = _book(tmp_path)
    result = await pipeline.generate_chapter(book, 1)

    assert result.final_text == ""
    assert result.planning_text == ""
    assert any("生成失败" in w and "empty" in w for w in result.warnings)
    assert not (book / "logs/ch1/planning.md").exists()  # 不写空文件
    writer.generate.assert_not_called()  # Writer 未被调用


@pytest.mark.asyncio
async def test_degraded_planning_stops_and_marks_file(tmp_path, monkeypatch):
    """降级成功 → 落盘带标记、管线停下、不进 Writer。"""
    planner = MagicMock()
    resp = LLMResponse(text="降级戏核内容", model="deepseek-chat", degraded=True, cost=0.02)
    planner.generate_guarded = AsyncMock(return_value=resp)
    writer = MagicMock()
    writer.generate = AsyncMock(return_value=LLMResponse(text="不应被生成", model="w"))
    registry = _setup(monkeypatch, planner)
    registry.get_adapter_for_stage.side_effect = lambda stage, override=None: (
        planner if stage == "planner" else writer
    )

    book = _tmp_book = _book(tmp_path)
    result = await pipeline.generate_chapter(book, 1)

    assert result.final_text == ""
    assert any("降级" in w for w in result.warnings)
    p = book / "logs/ch1/planning.md"
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "由降级模型" in content
    assert "生成" in content
    assert "deepseek-chat" in content
    writer.generate.assert_not_called()


@pytest.mark.asyncio
async def test_truncated_planning_stops(tmp_path, monkeypatch):
    from biyu.llm.base import TruncatedError

    planner = MagicMock()
    planner.generate_guarded = AsyncMock(
        side_effect=TruncatedError(attempts=1, total_cost=0.28, total_latency=90.0)
    )
    writer = MagicMock()
    writer.generate = AsyncMock(return_value=LLMResponse(text="不应被生成", model="w"))
    registry = _setup(monkeypatch, planner)
    registry.get_adapter_for_stage.side_effect = lambda stage, override=None: (
        planner if stage == "planner" else writer
    )

    book = _book(tmp_path)
    result = await pipeline.generate_chapter(book, 1)

    assert result.final_text == ""
    assert any("truncated" in w for w in result.warnings)
    assert not (book / "logs/ch1/planning.md").exists()
    writer.generate.assert_not_called()
