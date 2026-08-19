"""E-1 兜底机制埋雷测试(两态:注掉修复→红,装上→绿)。

覆盖:
- 空 content → EmptyContentError(empty)
- finish_reason=length → TruncatedError(truncated)
- 空→加长成功(不再原样重试)
- 空→加长仍空→降级成功(degraded=True)
- 全败 → 异常携带累计成本与尝试次数
"""
from __future__ import annotations

import asyncio

import pytest

from biyu.llm.base import (
    EmptyContentError,
    GenerationError,
    LLMAdapter,
    LLMResponse,
    TruncatedError,
)


class FakeAdapter(LLMAdapter):
    """按脚本返回响应或抛异常;记录每次调用的 max_tokens。"""

    def __init__(self, script, name="fake", max_tokens=16384):
        super().__init__(model_name=name, api_key="x", max_tokens=max_tokens)
        self.script = list(script)
        self.calls: list[dict] = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"max_tokens": kwargs.get("max_tokens"), "kwargs": kwargs})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        text, finish_reason, cost = item
        return LLMResponse(
            text=text,
            model=self.model_name,
            cost=cost,
            finish_reason=finish_reason,
        )

    async def stream(self, messages, **kwargs):
        raise NotImplementedError


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_ok_passthrough_no_retry():
    a = FakeAdapter([("正常戏核", None, 0.05)])
    resp = run(a.generate_guarded([{"role": "user", "content": "x"}]))
    assert resp.text == "正常戏核"
    assert resp.degraded is False
    assert len(a.calls) == 1


def test_empty_then_boosted_success():
    a = FakeAdapter([("", None, 0.28), ("长戏核", None, 0.30)])
    resp = run(a.generate_guarded([{"role": "user", "content": "x"}]))
    assert resp.text == "长戏核"
    assert len(a.calls) == 2
    # 第二次必须走加长档(去掉原样重试)
    assert a.calls[1]["max_tokens"] == int(16384 * 1.5)


def test_whitespace_only_is_empty():
    a = FakeAdapter([("   \n\t ", None, 0.10), ("   \n\t ", None, 0.10)])
    with pytest.raises(EmptyContentError) as ei:
        run(a.generate_guarded([{"role": "user", "content": "x"}]))
    assert ei.value.failure_type == "empty"


def test_truncated_finish_reason():
    a = FakeAdapter([("半截内容", "length", 0.28), ("半截内容", "length", 0.28)])
    with pytest.raises(TruncatedError) as ei:
        run(a.generate_guarded([{"role": "user", "content": "x"}]))
    assert ei.value.failure_type == "truncated"


def test_fallback_degraded_marked():
    a = FakeAdapter([("", None, 0.28), ("", None, 0.30)])
    fb = FakeAdapter([("降级戏核", None, 0.02)], name="v3")
    resp = run(a.generate_guarded([{"role": "user", "content": "x"}], fallback_adapter=fb))
    assert resp.text == "降级戏核"
    assert resp.degraded is True
    assert resp.model == "v3"
    assert len(a.calls) == 2
    assert len(fb.calls) == 1


def test_all_fail_carries_cost_and_attempts():
    a = FakeAdapter([("", None, 0.28), ("", None, 0.30)])
    with pytest.raises(EmptyContentError) as ei:
        run(a.generate_guarded([{"role": "user", "content": "x"}]))
    assert ei.value.attempts == 2
    assert abs(ei.value.total_cost - 0.58) < 1e-9
    assert ei.value.failure_type == "empty"


def test_fallback_also_empty_raises():
    a = FakeAdapter([("", None, 0.28), ("", None, 0.30)])
    fb = FakeAdapter([("", None, 0.01)], name="v3")
    with pytest.raises(GenerationError) as ei:
        run(a.generate_guarded([{"role": "user", "content": "x"}], fallback_adapter=fb))
    assert ei.value.attempts == 3


def test_transient_error_retried_then_success():
    a = FakeAdapter([RuntimeError("网络抖动"), ("重试成功", None, 0.05)])
    resp = run(a.generate_guarded([{"role": "user", "content": "x"}]))
    assert resp.text == "重试成功"
    assert len(a.calls) == 2


def test_detect_failure_classification():
    assert LLMAdapter.detect_failure(LLMResponse(text="正常", model="m")) is None
    assert LLMAdapter.detect_failure(LLMResponse(text="", model="m")) == "empty"
    assert LLMAdapter.detect_failure(LLMResponse(text="  ", model="m")) == "empty"
    assert LLMAdapter.detect_failure(LLMResponse(text="有内容", model="m", finish_reason="length")) == "truncated"
