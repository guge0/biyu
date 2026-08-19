"""Kimi K2.5 API adapter.

OpenAI-compatible API with strict parameter constraints:
- temperature: fixed 1.0 (thinking) or 0.6 (non-thinking), no other values allowed
- top_p: fixed 0.95
- n: fixed 1
- presence_penalty / frequency_penalty: fixed 0.0
- New param: thinking (default enabled, can be disabled)
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import LLMAdapter, LLMResponse
from .glm import LLMError


class KimiAdapter(LLMAdapter):
    """Kimi K2.5 API adapter."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = (self.base_url or "https://api.moonshot.cn/v1").rstrip("/")

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
            "model": self.model_name,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": False,
        }
        # K2.5: disable thinking for standard text generation
        thinking = kwargs.get("thinking", {"type": "disabled"})
        if thinking:
            payload["thinking"] = thinking
        # Do NOT pass temperature / top_p / n / presence_penalty / frequency_penalty
        # K2.5 uses fixed values and will error on any other values

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
        ) as client:
            resp = await client.post(self._chat_url(), headers=self._headers(), json=payload)
            self._handle_error(resp)
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]
        text = message.get("content", "")
        reasoning = message.get("reasoning_content")

        response = self._build_response(data, text)
        response.reasoning_content = reasoning
        return response

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }
        thinking = kwargs.get("thinking", {"type": "disabled"})
        if thinking:
            payload["thinking"] = thinking

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
