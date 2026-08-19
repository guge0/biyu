from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import LLMAdapter, LLMResponse
from .glm import LLMError


class DeepSeekAdapter(LLMAdapter):
    """DeepSeek API适配器，支持V3（deepseek-chat）和R1（deepseek-reasoner）。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = (self.base_url or "https://api.deepseek.com/v1").rstrip("/")

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

    def _is_reasoner(self) -> bool:
        """判断当前模型是否为推理模型（R1）。"""
        return "reasoner" in self.model_name

    async def generate(
        self,
        messages: list[dict],
        cacheable_prefix: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate completion with optional prompt caching.

        Args:
            messages: 动态消息列表(每章变化的内容)。
            cacheable_prefix: 稳定不变的消息前缀(如 system + worldbook + characters)。
                DeepSeek 会对完全一致的 prefix 自动做 cache hit。
        """
        full_messages = (cacheable_prefix or []) + messages
        payload = {
            "model": self.model_name,
            "messages": full_messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": False,
        }
        # R1不支持temperature等采样参数，静默忽略
        if "temperature" in kwargs and not self._is_reasoner():
            payload["temperature"] = kwargs["temperature"]
        # Function calling: 传入 tools 参数
        if "tools" in kwargs and kwargs["tools"]:
            payload["tools"] = kwargs["tools"]

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
        if "temperature" in kwargs and not self._is_reasoner():
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
                    # R1流式先输出reasoning_content再输出content，只输出正式内容
                    content = delta.get("content", "")
                    if content:
                        yield content
