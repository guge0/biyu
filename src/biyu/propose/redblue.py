"""红蓝海对照模块(P7-2 T5)。

给作者的具体想法做"红蓝海对照",产出四象限归类 + 供给侧拥挤度 + 同类在榜弱信号。
诚实声明(_HONESTY_NOTE)是代码常量,不靠 LLM 产 —— 保证不可省、不被改写。

1 次 LLM 调用(主路径);schema 不全或 quadrant 非法 → 重试 1 次;LLM 异常直接降级。
红线:LLM 不得编造需求侧数字(详见 prompts._REDBLUE_SYSTEM)。

实现:
- LLM 主路径:build_redblue_prompt → 调 adapter → 解析 JSON → 校验 quadrant 四选一 → RedBlueResult。
- 降级:重试仍失败 / LLM 异常 → source='llm_failed',proposal 据此不显示红蓝海节。
- 无 adapter:source='unavailable'。
- honesty_note 永远 == _HONESTY_NOTE 常量(无论 source)。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from biyu.fingerprint.adapter import _extract_json_object
from biyu.propose.prompts import _HONESTY_NOTE, build_redblue_prompt


class Quadrant(str, Enum):
    """红蓝海四象限。"""

    RED_SEA = "红海"      # 多人写多人看
    BLUE_SEA = "蓝海"     # 少人写多人看
    DEAD_SEA = "死海"     # 多人写少人看
    WASTELAND = "荒漠"    # 少人写少人看


_VALID_QUADRANT_VALUES = {q.value for q in Quadrant}


@dataclass
class RedBlueResult:
    """红蓝海对照产物。

    source: 'llm' / 'llm_failed' / 'unavailable'
    honesty_note: 永远 == _HONESTY_NOTE 常量(无论 source,保证"不可省")
    quadrant: 仅 source='llm' 时有意义;其他 source 为 None
    """

    supply_crowding: str = ""
    demand_weak_signal: str = ""
    quadrant: Quadrant | None = None
    honesty_note: str = _HONESTY_NOTE  # 直接默认值绑定常量
    source: str = "unavailable"
    cost_cny: float = 0.0
    latency_s: float = 0.0


class _LLMAdapterProto(Protocol):
    async def generate(self, messages: list, **kwargs: Any) -> Any: ...


_MAX_RETRIES = 1


def build_redblue(
    idea: str,
    rankings_text: str,
    llm_adapter: _LLMAdapterProto | None,
) -> RedBlueResult:
    """合成红蓝海对照。

    Args:
        idea: 作者设想文本(应为具体想法,非空)
        rankings_text: 已格式化的榜单 Markdown 文本(真实数据)
        llm_adapter: LLM adapter;None → 直接返回 unavailable

    Returns:
        RedBlueResult(honesty_note 永远 == _HONESTY_NOTE 常量)
    """
    if llm_adapter is None:
        return RedBlueResult(source="unavailable")

    started = time.time()
    total_cost = 0.0
    last_text = ""

    for attempt in range(_MAX_RETRIES + 1):
        try:
            messages = build_redblue_prompt(idea, rankings_text)
            resp = asyncio.run(llm_adapter.generate(messages))
            cost = float(getattr(resp, "cost", 0.0) or 0.0)
            total_cost += cost
            last_text = getattr(resp, "text", "") or ""
        except Exception:
            elapsed = time.time() - started
            return RedBlueResult(source="llm_failed", cost_cny=total_cost, latency_s=elapsed)

        parsed = _parse_and_validate_redblue(last_text)
        if parsed is not None:
            elapsed = time.time() - started
            return _build_result_from_parsed(parsed, total_cost, elapsed)

    elapsed = time.time() - started
    return RedBlueResult(source="llm_failed", cost_cny=total_cost, latency_s=elapsed)


def _parse_and_validate_redblue(text: str) -> dict | None:
    """解析 + schema 校验。

    必填:supply_crowding(str 非空)、demand_weak_signal(str 非空)、
         quadrant(str 且 ∈ {红海/蓝海/死海/荒漠})
    """
    try:
        obj = _extract_json_object(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    supply = obj.get("supply_crowding")
    if not (isinstance(supply, str) and supply.strip()):
        return None
    demand = obj.get("demand_weak_signal")
    if not (isinstance(demand, str) and demand.strip()):
        return None
    quadrant = obj.get("quadrant")
    if not isinstance(quadrant, str):
        return None
    if quadrant.strip() not in _VALID_QUADRANT_VALUES:
        return None
    return obj


def _build_result_from_parsed(
    parsed: dict, cost_cny: float, latency_s: float
) -> RedBlueResult:
    """从合法 dict 构造 RedBlueResult。honesty_note 强制 == 常量。"""
    quadrant_str = str(parsed.get("quadrant", "")).strip()
    quadrant = next(
        (q for q in Quadrant if q.value == quadrant_str),
        None,
    )
    return RedBlueResult(
        supply_crowding=str(parsed.get("supply_crowding", "")).strip(),
        demand_weak_signal=str(parsed.get("demand_weak_signal", "")).strip(),
        quadrant=quadrant,
        honesty_note=_HONESTY_NOTE,  # 显式绑定常量,忽略 LLM 的 honesty_note 字段
        source="llm",
        cost_cny=cost_cny,
        latency_s=latency_s,
    )
