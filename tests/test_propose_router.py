"""Tests for biyu.propose.router — 路径自动判断(P7-2 T1).

覆盖:
- 空 idea → EMPTY(不调 LLM,省钱)
- LLM 主路径:具体想法 → SPECIFIC;半方向 → DIRECTIONAL
- prompt 含 specific/directional/empty 三选一约束
- LLM 异常 / 返回非法值 / 无 adapter → 启发式降级,不崩
"""
from __future__ import annotations

from biyu.propose.router import PathDecision, decide_path


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


class _FailingAdapter:
    """Mock adapter that raises to trigger heuristic fallback."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def generate(self, messages, **kwargs):
        raise self._exc


# ---------------------------------------------------------------------------
# 空 idea → EMPTY(不调 LLM)
# ---------------------------------------------------------------------------


def test_decide_path_empty_idea_returns_empty_without_llm_call():
    """空 idea → 直接 EMPTY,不调 LLM(省一次调用)。"""
    adapter = _FakeAdapter("specific")

    result = decide_path(idea="", llm_adapter=adapter)

    assert result == PathDecision.EMPTY
    assert not adapter.calls  # 没调 LLM


def test_decide_path_whitespace_only_idea_returns_empty():
    """仅空白的 idea → EMPTY,不调 LLM。"""
    adapter = _FakeAdapter("specific")

    result = decide_path(idea="   \n  ", llm_adapter=adapter)

    assert result == PathDecision.EMPTY
    assert not adapter.calls


# ---------------------------------------------------------------------------
# LLM 主路径
# ---------------------------------------------------------------------------


def test_decide_path_specific_idea_via_llm():
    """LLM 判断"校车进秘境、轻喜剧爽文"为 specific → SPECIFIC。"""
    adapter = _FakeAdapter("specific")

    result = decide_path(idea="校车进秘境、轻喜剧爽文", llm_adapter=adapter)

    assert result == PathDecision.SPECIFIC


def test_decide_path_directional_idea_via_llm():
    """LLM 判断"想写穿越的"为 directional → DIRECTIONAL。"""
    adapter = _FakeAdapter("directional")

    result = decide_path(idea="想写穿越的", llm_adapter=adapter)

    assert result == PathDecision.DIRECTIONAL


def test_decide_path_prompt_constrains_to_three_choices():
    """prompt 必须含 specific/directional/empty 三个标签 + 三选一约束。

    通过检查发给 LLM 的 messages 内容验证。
    """
    adapter = _FakeAdapter("specific")

    decide_path(idea="某设想", llm_adapter=adapter)

    sent_text = "".join(m.get("content", "") for m in adapter.calls[0])
    assert "specific" in sent_text
    assert "directional" in sent_text
    assert "empty" in sent_text


# ---------------------------------------------------------------------------
# LLM 失败 / 非法值 / 无 adapter → 启发式降级
# ---------------------------------------------------------------------------


def test_decide_path_falls_back_to_directional_when_llm_raises_on_directional_text():
    """LLM 异常 + idea 含探索模态词("想写")→ 启发式判 DIRECTIONAL,不崩。"""
    adapter = _FailingAdapter(RuntimeError("model offline"))

    result = decide_path(idea="想写穿越的", llm_adapter=adapter)

    assert result == PathDecision.DIRECTIONAL


def test_decide_path_falls_back_to_specific_for_concrete_text():
    """LLM 异常 + 具体设定文本(无探索模态词)→ 启发式判 SPECIFIC,不崩。"""
    adapter = _FailingAdapter(RuntimeError("model offline"))

    result = decide_path(idea="校车进秘境、轻喜剧爽文", llm_adapter=adapter)

    assert result == PathDecision.SPECIFIC


def test_decide_path_falls_back_when_llm_returns_invalid_value():
    """LLM 返回非三选一(如自由发挥)→ 启发式降级,不抛错。"""
    adapter = _FakeAdapter("我觉得这是个好想法")  # 非 specific/directional/empty

    result = decide_path(idea="校车进秘境", llm_adapter=adapter)

    assert result == PathDecision.SPECIFIC  # 启发式:具体文本


def test_decide_path_falls_back_when_llm_returns_empty_string():
    """LLM 返回空串 → 启发式降级。"""
    adapter = _FakeAdapter("")

    result = decide_path(idea="想写穿越的", llm_adapter=adapter)

    assert result == PathDecision.DIRECTIONAL  # 启发式


def test_decide_path_without_adapter_goes_heuristic_and_does_not_crash():
    """没传 adapter(离线模式)→ 走启发式,不崩,返回合法 PathDecision。"""
    result = decide_path(idea="某设想", llm_adapter=None)

    assert result in (PathDecision.SPECIFIC, PathDecision.DIRECTIONAL, PathDecision.EMPTY)
