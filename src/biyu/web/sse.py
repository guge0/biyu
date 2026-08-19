"""SSE 封装 — 用于生成进度推送。"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator


async def sse_generator(events: asyncio.Queue) -> AsyncGenerator[str, None]:
    """从 asyncio.Queue 消费事件并生成 SSE 格式输出。"""
    while True:
        try:
            event = await asyncio.wait_for(events.get(), timeout=300.0)
        except asyncio.TimeoutError:
            # 心跳
            yield ": heartbeat\n\n"
            continue

        if event is None:
            yield "data: [DONE]\n\n"
            break

        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def make_event(event_type: str, **kwargs) -> dict:
    """构造标准 SSE 事件。"""
    return {"type": event_type, **kwargs}
