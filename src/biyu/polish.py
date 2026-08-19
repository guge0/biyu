"""Kimi external polish — graceful degradation on failure.

权限: 前500字开篇重写 + 章末200字钩子强化 + 3-5处关键对话优化
禁区: 不改情节/设定/字数(±200字以内)/人物关系

失败降级: 返回原文 + warning,绝不阻塞 pipeline。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from biyu.llm import ModelRegistry
from biyu.prompts.v3_opening import build_polish_prompt


@dataclass
class PolishResult:
    """Result of the polish stage."""
    polished_text: str
    success: bool
    error: str = ""
    cost: float = 0.0
    latency_seconds: float = 0.0


async def polish_chapter(
    text: str,
    registry: ModelRegistry,
    model_key: str = "kimi-k2.5",
    max_retries: int = 2,
    retry_delay: float = 5.0,
) -> PolishResult:
    """Polish a chapter using Kimi. Returns original text on any failure.

    Args:
        text: The chapter text to polish.
        registry: ModelRegistry for getting the Kimi adapter.
        model_key: Model key in models.yaml (default: kimi-k2.5).
        max_retries: Max retry attempts (default 2).
        retry_delay: Seconds between retries.

    Returns:
        PolishResult with polished text or original text on failure.
    """
    import time

    prompt = build_polish_prompt(text)
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, max_retries + 1):
        try:
            adapter = registry.get_adapter(model_key)
            t0 = time.time()
            resp = await asyncio.wait_for(adapter.generate(messages), timeout=180.0)
            latency = time.time() - t0

            if not resp.text or not resp.text.strip():
                return PolishResult(
                    polished_text=text,
                    success=False,
                    error="Kimi 返回空文本",
                    cost=resp.cost,
                    latency_seconds=latency,
                )

            return PolishResult(
                polished_text=resp.text,
                success=True,
                cost=resp.cost,
                latency_seconds=latency,
            )
        except asyncio.TimeoutError:
            return PolishResult(
                polished_text=text,
                success=False,
                error=f"Kimi 润色超时(180s),降级使用原文",
                latency_seconds=90.0,
            )
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
                continue
            return PolishResult(
                polished_text=text,
                success=False,
                error=f"Kimi 润色失败(重试{attempt}次): {e}",
            )

    return PolishResult(
        polished_text=text,
        success=False,
        error="Kimi 润色失败: 未预期的退出",
    )
