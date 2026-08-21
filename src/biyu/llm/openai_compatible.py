from __future__ import annotations

import httpx
from typing import AsyncIterator

from .base import LLMAdapter, LLMResponse
from .glm import LLMError


class OpenAICompatibleAdapter(LLMAdapter):
    """Adapter for OpenAI-compatible chat completion endpoints."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        url = (self.base_url or "").strip().rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        if not url.endswith("/v1"):
            url += "/v1"
        self.base_url = url

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse:
        payload = {"model": self.model_name, "messages": messages, "max_tokens": kwargs.get("max_tokens", self.max_tokens), "stream": False}
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=60, write=20, pool=10)) as client:
                response = await client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(0, f"连接失败：{exc}") from exc
        if response.status_code >= 400:
            try:
                body = response.json(); message = body.get("error", {}).get("message", body.get("message", response.text))
            except Exception:
                message = response.text
            raise LLMError(response.status_code, str(message))
        try:
            data = response.json(); choice = data["choices"][0]; text = choice["message"].get("content", "")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(response.status_code, "响应不像 OpenAI 对话接口") from exc
        return self._build_response(data, text)

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        response = await self.generate(messages, **kwargs)
        yield response.text
