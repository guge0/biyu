"""Tests for biyu.propose.redblue — P7-2 红蓝海对照.

覆盖 T5:
- LLM 合法 JSON → RedBlueResult(supply_crowding/demand_weak_signal/quadrant/honesty_note)
- quadrant 必须四选一(红海/蓝海/死海/荒漠);LLM 给非法值 → 降级
- honesty_note 必须 == _HONESTY_NOTE 常量(不可由 LLM 改)
- LLM 异常 / 无 adapter → 降级 source='failed'/'unavailable'
- 污染 JSON(包裹 / 前后缀)→ repair 成功
- schema 缺字段 → 重试 1 次

所有 LLM 调用 mock,零烧钱。
"""
from __future__ import annotations

from biyu.propose.prompts import _HONESTY_NOTE
from biyu.propose.redblue import (
    Quadrant,
    RedBlueResult,
    build_redblue,
)


class _FakeAdapter:
    """Mock LLM adapter,记录调用 + 返回预设响应。"""

    def __init__(self, response_text: str, cost: float = 0.001):
        self._response = response_text
        self._cost = cost
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)

        class _R:
            text = self._response
            cost = self._cost

        return _R()


class _SequentialAdapter:
    """Mock adapter 按顺序返回不同响应(用于重试测试)。"""

    def __init__(self, responses: list[str], cost: float = 0.001):
        self._responses = list(responses)
        self._cost = cost
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        text = self._responses.pop(0) if self._responses else ""

        class _R:
            pass

        r = _R()
        r.text = text
        r.cost = self._cost
        return r


class _FailingAdapter:
    """Mock adapter that raises."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def generate(self, messages, **kwargs):
        raise self._exc


# ---------------------------------------------------------------------------
# 合法路径
# ---------------------------------------------------------------------------


_VALID_REDBLUE = (
    '{"supply_crowding": "校车+秘境题材在起点都市榜前 20 占 4 本,'
    '番茄都市榜占 6 本,供给较拥挤。", '
    '"demand_weak_signal": "榜上同类作品位次靠前(前 5),'
    '在榜数量稳定但无爆款TOP1。", '
    '"quadrant": "红海"}'
)


def test_build_redblue_returns_result_when_llm_returns_valid_json():
    """LLM 返回合法 JSON → RedBlueResult,source='llm'。"""
    adapter = _FakeAdapter(_VALID_REDBLUE)

    result = build_redblue(
        idea="校车进秘境",
        rankings_text="## 起点\n1. 书A",
        llm_adapter=adapter,
    )

    assert isinstance(result, RedBlueResult)
    assert result.source == "llm"
    assert "供给" in result.supply_crowding or "拥挤" in result.supply_crowding
    assert "位次" in result.demand_weak_signal or "在榜" in result.demand_weak_signal
    assert result.quadrant == Quadrant.RED_SEA


def test_build_redblue_honesty_note_equals_constant_not_llm_generated():
    """honesty_note 必须 == _HONESTY_NOTE 常量。

    即使 LLM 输出里有自己的 honesty_note 字段,代码也忽略,只注入常量。
    """
    # LLM 假装自己产了 honesty_note(试图改写)
    payload_with_fake_note = (
        '{"supply_crowding": "x", "demand_weak_signal": "y", '
        '"quadrant": "蓝海", "honesty_note": "我瞎编的声明"}'
    )
    adapter = _FakeAdapter(payload_with_fake_note)

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"
    # 必须 == 常量,不 == LLM 的瞎编
    assert result.honesty_note == _HONESTY_NOTE
    assert "瞎编" not in result.honesty_note


# ---------------------------------------------------------------------------
# quadrant 四选一校验
# ---------------------------------------------------------------------------


def test_build_redblue_accepts_all_four_valid_quadrants():
    """quadrant 四个合法值都能解析。"""
    for q in ("红海", "蓝海", "死海", "荒漠"):
        payload = (
            f'{{"supply_crowding": "a", "demand_weak_signal": "b", "quadrant": "{q}"}}'
        )
        adapter = _FakeAdapter(payload)
        result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)
        assert result.source == "llm", f"合法 quadrant={q} 应该通过"
        assert result.quadrant.value == q


def test_build_redblue_falls_back_when_quadrant_is_invalid():
    """LLM 返回的 quadrant 不在四选一 → 视为 schema 错,重试 1 次仍错 → 降级。"""
    bad = (
        '{"supply_crowding": "x", "demand_weak_signal": "y", '
        '"quadrant": "珊瑚海"}'  # 非法
    )
    adapter = _SequentialAdapter([bad, bad])  # 两次都非法

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm_failed"
    assert len(adapter.calls) == 2  # 重试了


def test_build_redblue_falls_back_when_quadrant_missing():
    """LLM 返回的 JSON 缺 quadrant → 重试 1 次仍缺 → 降级。"""
    bad = '{"supply_crowding": "x", "demand_weak_signal": "y"}'
    adapter = _SequentialAdapter([bad, bad])

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm_failed"


# ---------------------------------------------------------------------------
# 污染 JSON / 重试
# ---------------------------------------------------------------------------


def test_build_redblue_repairs_json_wrapped_in_code_fence():
    """JSON 被 ```json ... ``` 包裹 → repair 成功。"""
    wrapped = f"```json\n{_VALID_REDBLUE}\n```"
    adapter = _FakeAdapter(wrapped)

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"
    assert result.quadrant == Quadrant.RED_SEA


def test_build_redblue_repairs_json_with_prefix_suffix():
    """JSON 前后含解说文本 → repair 成功。"""
    polluted = f"分析结果如下:\n{_VALID_REDBLUE}\n以上判断仅供参考。"
    adapter = _FakeAdapter(polluted)

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"


def test_build_redblue_retries_when_schema_incomplete_then_succeeds():
    """schema 缺字段 → 重试 1 次;第二次合法 → source='llm'。"""
    bad = '{"supply_crowding": "x", "quadrant": "红海"}'  # 缺 demand_weak_signal
    adapter = _SequentialAdapter([bad, _VALID_REDBLUE])

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm"
    assert len(adapter.calls) == 2


# ---------------------------------------------------------------------------
# 异常 / 无 adapter
# ---------------------------------------------------------------------------


def test_build_redblue_falls_back_when_llm_raises():
    """LLM 异常 → 直接降级,不重试。"""
    adapter = _FailingAdapter(RuntimeError("model offline"))

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm_failed"


def test_build_redblue_without_adapter_returns_unavailable():
    """没传 adapter → unavailable。"""
    result = build_redblue(idea="x", rankings_text="x", llm_adapter=None)

    assert result.source == "unavailable"


# ---------------------------------------------------------------------------
# 降级产物的 honesty_note 仍在(或显式不在,但不假)
# ---------------------------------------------------------------------------


def test_build_redblue_failed_result_does_not_fabricate_honesty_note():
    """降级产物 source='llm_failed' 时,honesty_note 仍 == 常量(不假造)。

    proposal 据此知道"红蓝海未生成",但诚实声明常量本身保持不变。
    """
    adapter = _FailingAdapter(RuntimeError("boom"))

    result = build_redblue(idea="x", rankings_text="x", llm_adapter=adapter)

    assert result.source == "llm_failed"
    # 即使失败,honesty_note 字段值仍是常量(不变成空串假造)
    assert result.honesty_note == _HONESTY_NOTE
