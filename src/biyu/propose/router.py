"""路径自动判断模块(P7-2 T1)。

根据作者 idea 的具体程度,自动选择 propose 流程的路径:
- SPECIFIC(具体想法)→ 底座 + 红蓝海对照
- DIRECTIONAL(半方向)→ 底座 + 该方向的套路归纳
- EMPTY(空)→ 纯市场归纳(底座)

实现:
- LLM 主路径:build_router_prompt → 调 adapter → 三选一解析
- 启发式降级:LLM 失败 / 非法值 / 无 adapter → 基于探索模态词的简单规则
- 空 idea:直接 EMPTY,不调 LLM(省一次调用)

启发式只是兜底,准确性靠 LLM 主路径;即便启发式误判,产出仍可用
(走错路径只是少/多一节红蓝海,不会崩)。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class PathDecision(str, Enum):
    """propose 流程路径决策。"""

    SPECIFIC = "specific"        # 具体想法 → 走红蓝海
    DIRECTIONAL = "directional"  # 半方向 → 走方向归纳
    EMPTY = "empty"              # 空 → 纯市场归纳


@dataclass
class RouterDecision:
    """路径判断产物(含成本信息,供 cost_log 用)。

    source:
    - 'empty_short_circuit':空 idea 直接 EMPTY,未调 LLM(cost=0)
    - 'heuristic_no_adapter':无 adapter,走启发式(cost=0)
    - 'llm':LLM 主路径成功
    - 'llm_heuristic_fallback':LLM 失败 / 非法值 → 启发式降级
    """

    decision: PathDecision
    source: str = "empty_short_circuit"
    cost_cny: float = 0.0
    latency_s: float = 0.0


class _LLMAdapterProto(Protocol):
    async def generate(self, messages: list, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_ROUTER_SYSTEM = """你是网文创作思路分类器。给定作者输入的一句话,判断它属于以下哪一类:

- specific:作者有具体的设定/想法(如"校车进秘境、轻喜剧爽文"、"系统流 + 都市修真"、"反派洗白")。特征:有具体题材、设定、人物、爽点等元素。
- directional:作者只有一个模糊的大方向(如"想写穿越的"、"想看修真"、"喜欢系统流")。特征:含"想写/想看/喜欢/有没有/推荐"等探索性模态词,但没有具体设定。
- empty:作者没说想法(空输入)。

红线:只返回三选一的小写英文标签(specific / directional / empty),不要解释、不要其他字符。"""


_ROUTER_USER_TEMPLATE = """作者输入:{idea}

请返回 specific / directional / empty 三选一(只返回标签,不要其他文字)。"""


def build_router_prompt(idea: str) -> list[dict]:
    """构造路径判断 LLM 调用的 messages。"""
    return [
        {"role": "system", "content": _ROUTER_SYSTEM},
        {"role": "user", "content": _ROUTER_USER_TEMPLATE.format(idea=idea)},
    ]


# ---------------------------------------------------------------------------
# LLM 输出解析
# ---------------------------------------------------------------------------


def _parse_llm_decision(text: str) -> PathDecision | None:
    """从 LLM 返回文本提取 specific/directional/empty 三选一。

    宽松:在文本里查三个标签之一(顺序 specific > directional > empty,
    保证含多个时取最具体的)。
    """
    if not text:
        return None
    text_lower = text.lower()
    for choice in (PathDecision.SPECIFIC, PathDecision.DIRECTIONAL, PathDecision.EMPTY):
        if choice.value in text_lower:
            return choice
    return None


# ---------------------------------------------------------------------------
# 启发式降级
# ---------------------------------------------------------------------------


# 探索性模态词:作者表达"想找/想写/想看"等大方向但没给具体设定
_DIRECTIONAL_HINTS = (
    "想写", "想看", "想找", "喜欢", "有没有", "推荐", "比较", "哪些",
    "打算写", "考虑写", "在选择", "在纠结",
)


def _heuristic_decide(idea: str) -> PathDecision:
    """启发式降级:基于探索模态词的简单规则。

    - 空 → EMPTY
    - 含探索模态词 → DIRECTIONAL
    - 其他 → SPECIFIC(保守判 SPECIFIC,避免丢红蓝海环节)
    """
    if not idea or not idea.strip():
        return PathDecision.EMPTY
    idea_str = idea.strip()
    if any(hint in idea_str for hint in _DIRECTIONAL_HINTS):
        return PathDecision.DIRECTIONAL
    return PathDecision.SPECIFIC


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def decide_path(idea: str, llm_adapter: _LLMAdapterProto | None) -> PathDecision:
    """根据 idea 自动选择 propose 路径(简单接口,只返决策)。

    Args:
        idea: 作者输入文本(可能为空)
        llm_adapter: 可选 LLM adapter;None / LLM 失败 / 返回非法值 → 走启发式

    Returns:
        PathDecision: SPECIFIC / DIRECTIONAL / EMPTY
    """
    return decide_path_with_cost(idea, llm_adapter).decision


def decide_path_with_cost(
    idea: str, llm_adapter: _LLMAdapterProto | None
) -> RouterDecision:
    """根据 idea 自动选择 propose 路径(完整接口,含成本信息供 cost_log 用)。

    Args:
        idea: 作者输入文本(可能为空)
        llm_adapter: 可选 LLM adapter;None / LLM 失败 / 返回非法值 → 走启发式

    Returns:
        RouterDecision:含 decision / source / cost_cny / latency_s
    """
    # 空 idea:直接 EMPTY,不调 LLM(省钱 + 启发式一致)
    if not idea or not idea.strip():
        return RouterDecision(decision=PathDecision.EMPTY, source="empty_short_circuit")

    # 无 adapter:启发式
    if llm_adapter is None:
        return RouterDecision(
            decision=_heuristic_decide(idea),
            source="heuristic_no_adapter",
        )

    # LLM 主路径
    started = time.time()
    try:
        messages = build_router_prompt(idea)
        resp = asyncio.run(llm_adapter.generate(messages))
        elapsed = time.time() - started
        cost = float(getattr(resp, "cost", 0.0) or 0.0)
        text = getattr(resp, "text", "") or ""
        decision = _parse_llm_decision(text)
        if decision is not None:
            return RouterDecision(
                decision=decision, source="llm",
                cost_cny=cost, latency_s=elapsed,
            )
        # 非法值 → 启发式降级(LLM 调用已发生,仍记成本)
        return RouterDecision(
            decision=_heuristic_decide(idea),
            source="llm_heuristic_fallback",
            cost_cny=cost, latency_s=elapsed,
        )
    except Exception:
        elapsed = time.time() - started
        # LLM 异常 → 启发式降级(无成本,调用未成功)
        return RouterDecision(
            decision=_heuristic_decide(idea),
            source="llm_heuristic_fallback",
            latency_s=elapsed,
        )
