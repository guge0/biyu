"""UI-owned SSE serialization; no business dependency."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator


async def sse_generator(events: asyncio.Queue) -> AsyncGenerator[str, None]:
    while True:
        event = await events.get()
        if event is None:
            yield "data: [DONE]\n\n"
            return
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
