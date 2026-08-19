"""Doubao (ByteDance) API adapter via Volcengine Ark.

Key difference: the OpenAI ``model`` field uses the **endpoint ID** (ep-xxx)
created in the Volcengine Ark console, not a model name like ``doubao-1.6``.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import LLMAdapter, LLMResponse
from .glm import LLMError


class DoubaoAdapter(LLMAdapter):
    """Doubao API adapter via Volcengine Ark platform."""

    def __init__(self, endpoint_id: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.base_url = (self.base_url or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        self.endpoint_id = endpoint_id
        if not self.endpoint_id or "在此" in self.endpoint_id:
            raise ValueError(
                "Doubao endpoint_id is missing. "
                "Please create an inference endpoint at "
                "https://console.volcengine.com/ark "
                "(Online Inference -> Create Endpoint -> Select Doubao-1.6) "
                "and fill the ep-xxx ID in config/models.yaml"
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @staticmethod
    def _handle_error(response: httpx.Response) -> None:
        code = response.status_code
        if code == 200:
            return
        try:
            body = response.json()
            msg = body.get("error", {}).get("message", body.get("msg", response.text))
        except Exception:
            msg = response.text
        raise LLMError(code, msg)

    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse:
        payload = {
            "model": self.endpoint_id,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": False,
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
        ) as client:
            resp = await client.post(self._chat_url(), headers=self._headers(), json=payload)
            self._handle_error(resp)
            data = resp.json()

        text = data["choices"][0]["message"]["content"]
        return self._build_response(data, text)

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        payload = {
            "model": self.endpoint_id,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
        ) as client:
            async with client.stream("POST", self._chat_url(), headers=self._headers(), json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise LLMError(resp.status_code, body.decode(errors="replace"))
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
