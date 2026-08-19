from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import EmbeddingResponse, LLMAdapter, LLMResponse


class LLMError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"[{status_code}] {message}")


class GLMAdapter(LLMAdapter):
    """智谱GLM API adapter."""

    EMBED_PATH = "/embeddings"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = (self.base_url or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _embed_url(self) -> str:
        return f"{self.base_url}{self.EMBED_PATH}"

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
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        # P8-M3R 白名单修复:Function calling — 透传 tools / tool_choice
        # (核查日志 2026-07-08 夜 §3 异常 4:GLM API 支持 function-calling,
        # 但 adapter 没打通;GLM 充值后跑 editor 多轮工具前必须先修此项)
        if "tools" in kwargs and kwargs["tools"]:
            payload["tools"] = kwargs["tools"]
            if "tool_choice" in kwargs:
                payload["tool_choice"] = kwargs["tool_choice"]

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        ) as client:
            resp = await client.post(self._chat_url(), headers=self._headers(), json=payload)
            self._handle_error(resp)
            data = resp.json()

        text = data["choices"][0]["message"]["content"]
        return self._build_response(data, text)

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
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

    async def embed(self, text: str, **kwargs) -> EmbeddingResponse:
        payload = {
            "model": self.model_name,
            "input": text,
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0),
        ) as client:
            resp = await client.post(self._embed_url(), headers=self._headers(), json=payload)
            self._handle_error(resp)
            data = resp.json()

        embedding = data["data"][0]["embedding"]
        usage = data.get("usage", {})
        return EmbeddingResponse(
            embedding=embedding,
            model=data.get("model", self.model_name),
            prompt_tokens=usage.get("prompt_tokens", 0),
            raw=data,
        )
