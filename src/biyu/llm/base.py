from __future__ import annotations

import asyncio
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    finish_reason: str | None = None
    raw: dict | None = None
    reasoning_content: str | None = None  # R1等推理模型的思维链
    degraded: bool = False  # True=本次响应由降级模型(非主模型)生成


class GenerationError(Exception):
    """LLM 生成失败(空内容或截断),带失败类型与累计尝试信息。

    failure_type: "empty"(空/纯空白)或 "truncated"(finish_reason=length)。
    """

    def __init__(self, failure_type: str, attempts: int, total_cost: float = 0.0, total_latency: float = 0.0):
        self.failure_type = failure_type
        self.attempts = attempts
        self.total_cost = total_cost
        self.total_latency = total_latency
        super().__init__(f"LLM 生成失败({failure_type}),已重试 {attempts} 次")


class EmptyContentError(GenerationError):
    """模型返回空/纯空白内容。"""

    def __init__(self, attempts: int, total_cost: float = 0.0, total_latency: float = 0.0):
        super().__init__("empty", attempts, total_cost, total_latency)


class TruncatedError(GenerationError):
    """模型输出被 max_tokens 截断(finish_reason=length)。"""

    def __init__(self, attempts: int, total_cost: float = 0.0, total_latency: float = 0.0):
        super().__init__("truncated", attempts, total_cost, total_latency)


@dataclass
class EmbeddingResponse:
    embedding: list[float]
    model: str
    prompt_tokens: int = 0
    raw: dict | None = None


def resolve_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} patterns with environment variable values."""
    def _replacer(m: re.Match) -> str:
        return os.environ.get(m.group(1), m.group(0))
    return re.sub(r"\$\{(\w+)\}", _replacer, value)


class LLMAdapter(ABC):
    """Abstract base class for LLM providers."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        max_tokens: int = 8000,
        cost_per_1k_input: float = 0.0,
        cost_per_1k_output: float = 0.0,
        **kwargs,
    ):
        self.model_name = model_name
        self.api_key = resolve_env_vars(api_key)
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.cost_per_1k_input + completion_tokens * self.cost_per_1k_output) / 1000.0

    @abstractmethod
    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse:
        ...

    @abstractmethod
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        ...

    async def embed(self, text: str, **kwargs) -> EmbeddingResponse:
        raise NotImplementedError(f"{self.__class__.__name__} does not support embeddings")

    def _build_response(self, data: dict, text: str) -> LLMResponse:
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        cost = self.estimate_cost(prompt_tokens, completion_tokens)
        choices = data.get("choices", [{}])
        finish_reason = choices[0].get("finish_reason") if choices else None
        return LLMResponse(
            text=text,
            model=data.get("model", self.model_name),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            finish_reason=finish_reason,
            raw=data,
        )

    @staticmethod
    def detect_failure(resp: LLMResponse) -> str | None:
        """检测响应是否失败:None=正常;"empty"=空/纯空白;"truncated"=被截断。"""
        if not resp.text or not resp.text.strip():
            return "empty"
        if resp.finish_reason == "length":
            return "truncated"
        return None

    async def generate_guarded(
        self,
        messages: list[dict],
        fallback_adapter: "LLMAdapter | None" = None,
        max_tokens: int | None = None,
        boost_factor: float = 1.5,
        **kwargs,
    ) -> LLMResponse:
        """带失败检测、加长重试与降级的生成。

        重试梯(E-1 决定:max_tokens 天花板问题已由步骤 1 证实,去掉原样重试档):
        1. 正常档:max_tokens(或 self.max_tokens)
        2. 加长档:max_tokens × boost_factor(默认 1.5)
        3. 降级档:fallback_adapter(仅当提供;成功则 resp.degraded=True)
        全部失败:抛 EmptyContentError / TruncatedError(带累计成本与耗时)。
        """
        base_mt = max_tokens or self.max_tokens
        attempts = 0
        total_cost = 0.0
        total_latency = 0.0
        failure_type: str | None = None

        async def _try_once(adapter: "LLMAdapter", mt: int | None) -> LLMResponse | None:
            nonlocal attempts, total_cost, total_latency, failure_type
            call_kwargs = {**kwargs, "max_tokens": mt} if mt else kwargs
            last_exc: Exception | None = None
            for attempt in range(3):  # 传输级异常重试 2 次(与原 _call_with_retry 语义一致)
                t0 = time.monotonic()
                try:
                    resp = await adapter.generate(messages, **call_kwargs)
                except Exception as exc:
                    total_latency += time.monotonic() - t0
                    attempts += 1
                    last_exc = exc
                    if attempt < 2:
                        await asyncio.sleep(5.0)
                    continue
                total_cost += resp.cost
                total_latency += time.monotonic() - t0
                attempts += 1
                ft = self.detect_failure(resp)
                if ft:
                    failure_type = ft
                    return None
                return resp
            # 传输级异常最终失败:透传(非 empty/truncated 语义)
            assert last_exc is not None
            raise last_exc

        # 档 1:正常
        resp = await _try_once(self, base_mt)
        if resp is not None:
            return resp
        # 档 2:加长(天花板问题→直接进加长档,原样重试是纯烧钱)
        resp = await _try_once(self, int(base_mt * boost_factor))
        if resp is not None:
            return resp
        # 档 3:降级
        if fallback_adapter is not None:
            resp = await _try_once(fallback_adapter, None)
            if resp is not None:
                resp.degraded = True
                return resp
        # 全败
        cls = TruncatedError if failure_type == "truncated" else EmptyContentError
        raise cls(attempts, total_cost, total_latency)
