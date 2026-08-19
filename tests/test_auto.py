"""test_auto.py — auto.py 焰断保护单测."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

from biyu.auto import (
    CircuitBreakerTripped,
    _is_chapter_failed,
    _load_auto_config,
    auto_generate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeChapterResult:
    """Minimal ChapterResult stub."""
    chapter_num: int = 1
    final_text: str = "fake"
    word_count: int = 5000
    cost_cny: float = 1.0
    latency_seconds: float = 10.0
    stage_latencies: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    planning_text: str = ""
    skeleton_text: str = ""
    polished_text: str = ""
    audit_warnings: list = field(default_factory=list)


def _make_book_dir(tmp_path: Path) -> Path:
    """创建最简 book 目录(含大纲)。"""
    book_dir = tmp_path / "book"
    book_dir.mkdir()
    (book_dir / "book.json").write_text('{"title":"test"}', encoding="utf-8")
    outlines = book_dir / "outlines"
    outlines.mkdir()
    chapters = book_dir / "chapters"
    chapters.mkdir()
    for ch in range(1, 6):
        (outlines / f"ch{ch}.md").write_text(f"outline ch{ch}", encoding="utf-8")
    return book_dir


def _success_result(ch: int) -> FakeChapterResult:
    return FakeChapterResult(chapter_num=ch, word_count=5000, cost_cny=1.0)


def _block_result(ch: int) -> FakeChapterResult:
    return FakeChapterResult(
        chapter_num=ch,
        word_count=3000,
        cost_cny=1.0,
        warnings=["Auditor BLOCK: test_checker - test block"],
    )


def _quality_fail_result(ch: int) -> FakeChapterResult:
    return FakeChapterResult(
        chapter_num=ch,
        word_count=3000,
        cost_cny=1.0,
        warnings=["质量评分 2.0 低于阈值 3.5，已写入 _pending/，请老板确认"],
    )


def _write_pending(book_dir: Path, ch: int) -> None:
    pending_dir = book_dir / "chapters" / "_pending"
    pending_dir.mkdir(exist_ok=True)
    (pending_dir / f"ch{ch}.md").write_text("pending", encoding="utf-8")


def _write_success_chapter(book_dir: Path, ch: int) -> None:
    (book_dir / "chapters" / f"ch{ch}.md").write_text("good", encoding="utf-8")


# ---------------------------------------------------------------------------
# _is_chapter_failed
# ---------------------------------------------------------------------------

class TestIsChapterFailed:
    def test_not_failed(self, tmp_path: Path):
        from unittest.mock import MagicMock

        book_dir = _make_book_dir(tmp_path)
        book = MagicMock()
        book.chapters_dir = book_dir / "chapters"
        result = _success_result(1)
        failed, reason = _is_chapter_failed(result, book, 1)
        assert not failed
        assert reason == ""

    def test_failed_block(self, tmp_path: Path):
        from unittest.mock import MagicMock

        book_dir = _make_book_dir(tmp_path)
        book = MagicMock()
        book.chapters_dir = book_dir / "chapters"
        _write_pending(book_dir, 1)
        result = _block_result(1)
        failed, reason = _is_chapter_failed(result, book, 1)
        assert failed
        assert "BLOCK" in reason

    def test_failed_quality(self, tmp_path: Path):
        from unittest.mock import MagicMock

        book_dir = _make_book_dir(tmp_path)
        book = MagicMock()
        book.chapters_dir = book_dir / "chapters"
        _write_pending(book_dir, 1)
        result = _quality_fail_result(1)
        failed, reason = _is_chapter_failed(result, book, 1)
        assert failed
        assert "质量" in reason or "_pending" in reason


# ---------------------------------------------------------------------------
# _load_auto_config
# ---------------------------------------------------------------------------

class TestLoadAutoConfig:
    def test_returns_defaults_on_missing_file(self):
        with patch("biyu.config.get_config_path", side_effect=Exception("no file")):
            cfg = _load_auto_config()
            assert cfg["consecutive_fail_threshold"] == 3
            assert cfg["per_chapter_retry_max"] == 5
            assert cfg["budget_hard_stop"] == 50.0

    def test_fallback_to_defaults_logs_warning(self, caplog, monkeypatch):
        """config 加载失败 → fallback 时必须 log.warning 出声(P7-5)。

        背景:editor.py 的同类静默 except 让路径 bug 静默失效 6 个月。auto.py
        有同样 pattern(`except Exception: return dict(CIRCUIT_BREAKER_DEFAULTS)`),
        P7-5 一并改成出声,避免重蹈覆辙。
        """
        import logging as _logging
        from biyu import auto as auto_mod

        def _boom(*a, **kw):
            raise RuntimeError("simulated for P7-5 test")

        monkeypatch.setattr("biyu.config.get_config_path", _boom)

        with caplog.at_level(_logging.WARNING, logger="biyu.auto"):
            cfg = auto_mod._load_auto_config()

        # 安全网:fallback 默认值仍返回
        assert cfg["consecutive_fail_threshold"] == 3
        log_text = caplog.text
        # 出声:必须含 fallback/默认/default 任一关键词
        assert (
            "fallback" in log_text.lower()
            or "默认" in log_text
            or "default" in log_text.lower()
        ), "config 失败 fallback 必须在日志里出声(不许静默)"

    def test_merges_yaml_overrides(self, tmp_path: Path):
        import yaml

        cfg_file = tmp_path / "models.yaml"
        cfg_file.write_text(yaml.dump({
            "auto": {"consecutive_fail_threshold": 5, "budget_hard_stop": 100.0}
        }), encoding="utf-8")
        with patch("biyu.config.get_config_path", return_value=cfg_file):
            cfg = _load_auto_config()
            assert cfg["consecutive_fail_threshold"] == 5
            assert cfg["per_chapter_retry_max"] == 5  # default
            assert cfg["budget_hard_stop"] == 100.0


# ---------------------------------------------------------------------------
# Circuit breaker integration tests
# ---------------------------------------------------------------------------

_CFG_3_1 = {
    "consecutive_fail_threshold": 3,
    "per_chapter_retry_max": 1,
    "budget_hard_stop": 50.0,
}


def _run(coro):
    """同步运行异步协程(兼容无 pytest-asyncio 的环境)。

    P7-9 T2:加 RuntimeError 兜底。全套 pytest 时,前面某测试触发的事件循环
    操作让主线程 asyncio.get_event_loop() 在 Python 3.9 上抛
    'There is no current event loop in thread "MainThread"',
    导致 6 个 TestCircuitBreaker 全套失败。检测到该错误时自建新 loop 并设回主线程。

    [P8-M2.5 T7-1 已修污染源](2026-07-04,tests/conftest.py autouse fixture):
    上述污染在测试基础设施层兜住后,本兜底不再是 TestCircuitBreaker 走通的
    必要条件(实测验证:摘掉此 try/except,6 个 TestCircuitBreaker 仍全绿)。
    本兜底保留作 belt-and-suspenders(若 conftest 失效或单独 import _run 仍能工作)。
    TestRunHelper::test_run_handles_no_current_event_loop 仍依赖此兜底通过。
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # 主线程已无事件循环(被前面测试关闭),自建并设回
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class TestCircuitBreaker:
    def test_consecutive_3_block_triggers_breaker(self, tmp_path: Path):
        """连续 3 章 BLOCK → 焰断。"""
        book_dir = _make_book_dir(tmp_path)

        async def fake_gen(bd, ch):
            _write_pending(bd, ch)
            return _block_result(ch)

        with patch("biyu.pipeline.generate_chapter", side_effect=fake_gen):
            with patch("biyu.auto._load_auto_config", return_value=_CFG_3_1):
                with pytest.raises(CircuitBreakerTripped, match="连续"):
                    _run(auto_generate(book_dir, 1, 5))

    def test_single_chapter_retry_exceeded(self, tmp_path: Path):
        """单章 retry 超过上限 → 视为失败,累计到连续失败。"""
        book_dir = _make_book_dir(tmp_path)
        call_count = 0

        async def fake_gen(bd, ch):
            nonlocal call_count
            call_count += 1
            _write_pending(bd, ch)
            return _block_result(ch)

        cfg = dict(_CFG_3_1)
        cfg["per_chapter_retry_max"] = 2

        with patch("biyu.pipeline.generate_chapter", side_effect=fake_gen):
            with patch("biyu.auto._load_auto_config", return_value=cfg):
                with pytest.raises(CircuitBreakerTripped):
                    _run(auto_generate(book_dir, 1, 5))
                # 3 chapters × 2 retries each = 6 calls
                assert call_count == 6

    def test_normal_run_no_false_stop(self, tmp_path: Path):
        """0-2 章偶发失败但能恢复 → 不误停。"""
        book_dir = _make_book_dir(tmp_path)

        async def fake_gen(bd, ch):
            if ch == 2:
                _write_pending(bd, ch)
                return _block_result(ch)
            _write_success_chapter(bd, ch)
            return _success_result(ch)

        with patch("biyu.pipeline.generate_chapter", side_effect=fake_gen):
            with patch("biyu.auto._load_auto_config", return_value=_CFG_3_1):
                results = _run(auto_generate(book_dir, 1, 5))
                assert len(results) == 5

    def test_llm_exception_counted_as_failure(self, tmp_path: Path):
        """LLM 异常也算失败,计入连续失败。"""
        book_dir = _make_book_dir(tmp_path)

        async def fake_gen(bd, ch):
            raise RuntimeError("API timeout")

        with patch("biyu.pipeline.generate_chapter", side_effect=fake_gen):
            with patch("biyu.auto._load_auto_config", return_value=_CFG_3_1):
                with pytest.raises(CircuitBreakerTripped):
                    _run(auto_generate(book_dir, 1, 5))

    def test_budget_hard_stop(self, tmp_path: Path):
        """累计成本超硬停线 → 焰断。"""
        book_dir = _make_book_dir(tmp_path)

        async def fake_gen(bd, ch):
            _write_success_chapter(bd, ch)
            return FakeChapterResult(chapter_num=ch, cost_cny=20.0)

        cfg = dict(_CFG_3_1)
        cfg["budget_hard_stop"] = 30.0

        with patch("biyu.pipeline.generate_chapter", side_effect=fake_gen):
            with patch("biyu.auto._load_auto_config", return_value=cfg):
                with pytest.raises(CircuitBreakerTripped, match="预算"):
                    _run(auto_generate(book_dir, 1, 5))

    def test_recover_after_single_failure(self, tmp_path: Path):
        """单章失败后恢复 → 连续计数重置。"""
        book_dir = _make_book_dir(tmp_path)
        results_seq = []

        async def fake_gen(bd, ch):
            if ch == 2:
                _write_pending(bd, ch)
                return _block_result(ch)
            _write_success_chapter(bd, ch)
            r = _success_result(ch)
            results_seq.append(ch)
            return r

        with patch("biyu.pipeline.generate_chapter", side_effect=fake_gen):
            with patch("biyu.auto._load_auto_config", return_value=_CFG_3_1):
                results = _run(auto_generate(book_dir, 1, 4))
                assert len(results) == 4
                assert results_seq == [1, 3, 4]


# ---------------------------------------------------------------------------
# _run helper — Python 3.9 asyncio 兼容(P7-9 T2)
# ---------------------------------------------------------------------------

class TestRunHelper:
    """_run() helper 在主线程无事件循环时应自建 loop 兜底。

    背景(2026-07-03 一手核查):全套 pytest 时,前面某测试触发的事件循环
    操作让主线程 asyncio.get_event_loop() 抛 RuntimeError
    ('There is no current event loop in thread "MainThread"'),导致 6 个
    TestCircuitBreaker 全套失败、单跑能过。原 _run 直接调 get_event_loop 无兜底。
    P7-5/P7-7/P7-8 三轮核查均记此问题,P7-9 T2 治本。
    """

    def test_run_handles_no_current_event_loop(self, monkeypatch):
        """asyncio.get_event_loop() 抛 RuntimeError 时,_run 应自建 loop 兜底。"""
        import asyncio as _asyncio

        def _raise_no_loop():
            raise RuntimeError(
                "There is no current event loop in thread 'MainThread'."
            )

        # 模拟全套 pytest 中前面测试污染后的状态:get_event_loop 抛 RuntimeError
        monkeypatch.setattr(_asyncio, "get_event_loop", _raise_no_loop)

        async def simple():
            return 42

        # _run 应捕获 RuntimeError 并自建 loop,不抛给调用方
        assert _run(simple()) == 42

    def test_run_normal_path_still_works(self):
        """正常路径(有事件循环)时,_run 行为不变(回归保护)。"""
        # 不模拟任何异常,_run 走原 get_event_loop().run_until_complete 路径
        async def simple():
            return "ok"

        assert _run(simple()) == "ok"
